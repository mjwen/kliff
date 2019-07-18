import os
import numpy as np
import torch
import kliff
from .model_torch import ModelTorch
from ..log import log_entry

logger = kliff.logger.get_logger(__name__)


class NeuralNetwork(ModelTorch):
    """Neural Network model.

    A feed-forward neural network model.

    Parameters
    ----------
    descriptor: object
        A descriptor that transforms atomic environment information to the fingerprints,
        which are used as the input for the neural network.

    seed: int (optional)
        Global seed for random numbers.
    """

    def __init__(self, descriptor, seed=35):
        super(NeuralNetwork, self).__init__(descriptor, seed)

        self.layers = None

        logger.info('"{}" instantiated.'.format(self.__class__.__name__))

    def add_layers(self, *layers):
        """Add layers to the sequential model.

        Parameters
        ----------
        layers: torch.nn layers
            ``torch.nn`` layers that are used to build a sequential model.  Available ones
            including: torch.nn.Linear, torch.nn.Dropout, and torch.nn.Sigmoid among
            others. See https://pytorch.org/docs/stable/nn.html for a full list of
            torch.nn layers.
        """
        if self.layers is not None:
            report_error(
                '"add_layers" called multiple times. It should be called only once.'
            )
        else:
            self.layers = []

        for la in layers:
            self.layers.append(la)
            # set it as attr so that parameters are automatically registered
            setattr(self, 'layer_{}'.format(len(self.layers)), la)

        # check shape of first layer and last layer
        first = self.layers[0]
        if first.in_features != len(self.descriptor):
            report_error(
                '"in_features" of first layer should be equal to descriptor size.'
            )
        last = self.layers[-1]
        if last.out_features != 1:
            report_error('"out_features" of last layer should be 1.')

        # cast types
        self.type(self.dtype)

    def forward(self, x):
        for j, layer in enumerate(self.layers):
            x = layer(x)
        return x

    def write_kim_model(self, path=None):

        if path is None:
            modelname = 'NeuralNetwork_KLIFF__MO_000000111111_000'
            path = os.path.join(os.getcwd(), modelname)
        else:
            path = os.path.abspath(path)
            modelname = os.path.basename(path)
        if not os.path.exists(path):
            os.makedirs(path)

        desc_name = 'descriptor.params'
        nn_name = 'NN.params'
        dropout_name = 'dropout_binary.params'

        paramfiles = [desc_name, nn_name, dropout_name]
        self.write_kim_cmakelists(
            path, modelname=modelname, paramfiles=paramfiles, version='2.0.2'
        )
        self.write_kim_params(path, nn_name)
        self.descriptor.write_kim_params(path, desc_name)
        self.write_kim_dropout_binary(path, dropout_name)

        msg = 'KLIFF trained model write to "{}"'.format(path)
        log_entry(logger, msg, level='info')

    def write_kim_params(self, path, fname='NN.params'):

        weights, biases = self._get_weights_and_biases()
        activations = self._get_activations()
        drop_ratios = self._get_drop_ratios()

        # PyTorch uses x*W^T + b, so we need to transpose it.
        # see https://pytorch.org/docs/stable/nn.html#linear
        weights = [torch.t(w) for w in weights]

        with open(os.path.join(path, fname), 'w') as fout:
            # header
            fout.write('#' + '=' * 80 + '\n')
            fout.write(
                '# NN structure and parameters file generated by KLIFF\n'
                '# \n'
                '# Note that the NN assumes each row of the input "X" is an \n'
                '# observation, i.e. the layer is implemented as\n'
                '# Y = activation(XW + b).\n'
                '# You need to transpose your weight matrix if each column of "X" is \n'
                '# an observation.\n'
            )
            fout.write('#' + '=' * 80 + '\n\n')

            # number of layers
            num_layers = len(weights)
            fout.write(
                '{}    # number of layers (excluding input layer,including output '
                'layer)\n'.format(num_layers)
            )

            # size of layers
            for b in biases:
                fout.write('{}  '.format(len(b)))
            fout.write('  # size of each layer (last must be 1)\n')

            # activation function
            # TODO enable writing different activations for each layer
            activation = activations[0]
            fout.write('{}    # activation function\n'.format(activation))

            # keep probability
            for i in drop_ratios:
                fout.write('{:.15g}  '.format(1.0 - i))
            fout.write('  # keep probability of input for each layer\n\n')

            # weights and biases
            for i, (w, b) in enumerate(zip(weights, biases)):

                # weight
                rows, cols = w.shape
                if i != num_layers - 1:
                    fout.write(
                        '# weight of hidden layer {},  shape({}, {})\n'.format(
                            i + 1, rows, cols
                        )
                    )
                else:
                    fout.write(
                        '# weight of output layer, shape({}, {})\n'.format(rows, cols)
                    )
                for line in w:
                    for item in line:
                        if self.dtype == torch.float64:
                            fout.write('{:23.15e}'.format(item))
                        else:
                            fout.write('{:15.7e}'.format(item))
                    fout.write('\n')

                # bias
                if i != num_layers - 1:
                    fout.write(
                        '# bias of hidden layer {}, shape({}, )\n'.format(i + 1, cols)
                    )
                else:
                    fout.write('# bias of output layer, shape({}, )\n'.format(cols))
                for item in b:
                    if self.dtype == torch.float64:
                        fout.write('{:23.15e}'.format(item))
                    else:
                        fout.write('{:15.7e}'.format(item))
                fout.write('\n\n')

    def write_kim_dropout_binary(self, path, fname='dropout_binary.params', repeat=None):

        drop_ratios = self._get_drop_ratios()
        keep_prob = [1.0 - i for i in drop_ratios]
        _, biases = self._get_weights_and_biases()
        num_units = [self.descriptor.get_size()] + [len(i) for i in biases]

        # TODO change repeat 50 to the below code once the KIM driver is updated
        repeat = 50
        # no_drop = np.all(np.asarray(drop_ratios) < 1e-6)
        # if no_drop:
        #    repeat = 0
        # else:
        #    if repeat is None:
        #        repeat = 50

        with open(os.path.join(path, fname), 'w') as fout:
            fout.write('#' + '=' * 80 + '\n')
            fout.write(
                '# Dropout binary parameters file generated by KLIFF.\n'
                '#\n'
                '# Note, if number of repeat is 0, it means that no dropout needs to \n'
                '# be applied at all.\n'
            )
            fout.write('#' + '=' * 80 + '\n\n')

            fout.write('{}  # number of repeat\n'.format(repeat))
            for rep in range(repeat):
                fout.write('#' + '=' * 80 + '\n')
                fout.write('# instance {}\n'.format(rep))
                for i in range(len(keep_prob)):
                    fout.write('# layer {}\n'.format(i))
                    n = num_units[i]
                    k = keep_prob[i]
                    rnd = np.floor(np.random.uniform(k, k + 1, n))
                    rnd = np.asarray(rnd, dtype=np.intc)
                    for d in rnd:
                        d = 1 if d > 1 else d
                        d = 0 if d < 0 else d
                        fout.write('{} '.format(d))
                    fout.write('\n')

    @staticmethod
    def write_kim_cmakelists(
        path,
        modelname='NeuralNetwork_KLIFF__MO_000000111111',
        drivername='dNN_WT__MD_000000111111_000',
        paramfiles=["descriptor.params", "NN.params", "dropout_binary.params"],
        version='2.0.2',
    ):
        with open(os.path.join(path, 'CMakeLists.txt'), 'w') as fout:
            fout.write('#\n')
            fout.write('# Contributors:\n')
            fout.write('#    KLIFF (https://kliff.readthedocs.io)\n')
            fout.write('#\n\n')
            fout.write('cmake_minimum_required(VERSION 3.4)\n\n')
            fout.write('list(APPEND CMAKE_PREFIX_PATH $ENV{KIM_API_CMAKE_PREFIX_DIR})\n')
            fout.write('find_package(KIM-API 2.0 REQUIRED CONFIG)\n')
            fout.write('if(NOT TARGET kim-api)\n')
            fout.write('  enable_testing()\n')
            fout.write(
                '  project("${KIM_API_PROJECT_NAME}" VERSION "${KIM_API_VERSION}"\n'
            )
            fout.write('    LANGUAGES CXX C Fortran)\n')
            fout.write('endif()\n\n')
            fout.write('add_kim_api_model_library(\n')
            fout.write('  NAME            "{}"\n'.format(modelname))
            fout.write('  DRIVER_NAME     "{}"\n'.format(drivername))
            fout.write('  PARAMETER_FILES')
            for s in paramfiles:
                fout.write(' "{}"'.format(s))
            fout.write('\n')
            fout.write('  )\n')

    def _group_layers(
        self,
        param_layer=['Linear'],
        activ_layer=['Sigmoid', 'Tanh', 'ReLU', 'ELU'],
        dropout_layer=['Dropout'],
    ):
        """Divide all the layers into groups.

        The first group is either an empty list or a `Dropout` layer for the input layer.
        The last group typically contains only a `Linear` layer.  For other groups, each
        group contains two, or three layers. `Linear` layer and an activation layer are
        mandatory, and a third `Dropout` layer is optional.

        Return
        ------
        groups: list of list of layers
        """

        groups = []
        new_group = []

        supported = param_layer + activ_layer + dropout_layer
        for i, layer in enumerate(self.layers):
            name = layer.__class__.__name__
            if name not in supported:
                report_error(
                    'Layer "{}" not supported by KIM model. Cannot proceed '
                    'to write.'.format(name)
                )

            if name in activ_layer:
                if i == 0:
                    report_error('First layer cannot be a "{}" layer'.format(name))
                if self.layers[i - 1].__class__.__name__ not in param_layer:
                    report_error(
                        'Cannot convert to KIM model. a "{}" layer must follow '
                        'a "Linear" layer.'.format(name)
                    )
            if name[:7] in dropout_layer:
                if self.layers[i - 1].__class__.__name__ not in activ_layer:
                    report_error(
                        'Cannot convert to KIM model. a "{}" layer must follow '
                        'an activation layer.'.format(name)
                    )
            if name in param_layer:
                groups.append(new_group)
                new_group = []
            new_group.append(layer)
        groups.append(new_group)

        return groups, param_layer, activ_layer, dropout_layer

    def _get_weights_and_biases(self):
        """Get weights and biases of all layers that have weights and biases."""

        groups, supported, _, _ = self._group_layers()

        weights = []
        biases = []
        for i, g in enumerate(groups):
            if i != 0:
                layer = g[0]
                name = layer.__class__.__name__
                if name in supported:
                    weight = layer.weight
                    bias = layer.bias
                    weights.append(weight)
                    biases.append(bias)
        return weights, biases

    def _get_activations(self):
        """Get the activation of all layers."""

        groups, _, supported, _ = self._group_layers()

        activations = []
        for i, g in enumerate(groups):
            if i != 0 and i != (len(groups) - 1):
                layer = g[1]
                name = layer.__class__.__name__
                if name in supported:
                    activations.append(name.lower())
        return activations

    def _get_drop_ratios(self):
        """Get the dropout ratio of all layers."""

        groups, _, _, supported = self._group_layers()

        drop_ratios = []
        for i, g in enumerate(groups):
            if i == 0:
                if len(g) != 0:
                    layer = g[0]
                    name = layer.__class__.__name__
                    if name in supported:
                        drop_ratios.append(layer.p)
                else:
                    drop_ratios.append(0.0)
            elif i == len(groups) - 1:
                pass
            else:
                if len(g) == 3:
                    layer = g[2]
                    name = layer.__class__.__name__
                    if name in supported:
                        drop_ratios.append(layer.p)
                else:
                    drop_ratios.append(0.0)

        return drop_ratios


class NeuralNetworkError(Exception):
    def __init__(self, msg):
        super(NeuralNetworkError, self).__init__(msg)
        self.msg = msg

    def __expr__(self):
        return self.msg


def report_error(msg):
    log_entry(logger, msg, level='error')
    raise NeuralNetworkError(msg)
