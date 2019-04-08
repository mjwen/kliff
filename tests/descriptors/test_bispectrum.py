from kliff.dataset import Configuration
from kliff.descriptors.bispectrum import Bispectrum


fname = '../configs_extxyz/Si.xyz'
conf = Configuration(format='extxyz', identifier=fname)
conf.read(fname)

cutoff = {'Si-Si': 4}
jmax = 3
desc = Bispectrum(jmax)
