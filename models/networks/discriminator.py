import numpy as np
import torch.nn as nn
import torch.nn.functional as F

import util.util as util
from models.networks.base.base_network import BaseNetwork
from models.networks.base.normalization import get_nonspade_norm_layer


class MultiscaleDiscriminator(BaseNetwork):
    @staticmethod
    def modify_commandline_options(parser, is_train):
        parser.add_argument('--netD_subarch', type=str, default='n_layer',
                            help='architecture of each discriminator')
        parser.add_argument('--num_D', type=int, default=2,
                            help='number of discriminators in multiscale')
        opt, _ = parser.parse_known_args()

        # define properties of each discriminator
        subnetD = util.find_class_in_module(opt.netD_subarch + 'discriminator',
                                            'models.networks.discriminator')
        subnetD.modify_commandline_options(parser, is_train)

        return parser

    def __init__(self, opt):
        super().__init__()
        self.opt = opt

        for i in range(opt.num_D):
            subnetD = self.create_single_discriminator(opt)
            self.add_module('discriminator_%d' % i, subnetD)

    def create_single_discriminator(self, opt):
        subarch = opt.netD_subarch
        if subarch == 'n_layer':
            netD = NLayerDiscriminator(opt)
        else:
            raise ValueError(
                'unrecognized discriminator subarchitecture %s' % subarch)
        return netD

    def downsample(self, input):
        return F.avg_pool2d(input, kernel_size=3,
                            stride=2, padding=[1, 1],
                            count_include_pad=False)

    # Returns list of lists of discriminator outputs.
    # The final result is of size opt.num_D x opt.n_layers_D
    def forward(self, input):
        result = []
        get_intermediate_features = not self.opt.no_ganFeat_loss
        for name, D in self.named_children():
            out = D(input)
            if not get_intermediate_features:
                out = [out]
            result.append(out)
            input = self.downsample(input)

        return result


# Defines the PatchGAN discriminator with the specified arguments.
class NLayerDiscriminator(BaseNetwork):
    @staticmethod
    def modify_commandline_options(parser, is_train):
        parser.add_argument('--n_layers_D', type=int, default=4,
                            help='# layers in each discriminator')
        return parser

    def __init__(self, opt):
        super().__init__()
        self.opt = opt

        kw = 4
        padw = int(np.ceil((kw - 1.0) / 2))
        nf = opt.ndf
        input_nc = self.compute_D_input_nc(opt)

        norm_layer = get_nonspade_norm_layer(opt, opt.norm_D)
        sequence = [[
            nn.Conv2d(input_nc, nf, kernel_size=kw, stride=2, padding=padw),
            nn.LeakyReLU(0.2, False)
        ]]

        for n in range(1, opt.n_layers_D):
            nf_prev = nf
            nf = min(nf * 2, 512)
            stride = 1 if n == opt.n_layers_D - 1 else 2
            sequence += [[norm_layer(nn.Conv2d(nf_prev, nf, kernel_size=kw,
                                               stride=stride, padding=padw)),
                          nn.LeakyReLU(0.2, False)
                          ]]

        sequence += [[nn.Conv2d(nf, 1, kernel_size=kw,
                                stride=1, padding=padw)]]

        # We divide the layers into groups to extract intermediate outputs
        for n in range(len(sequence)):
            self.add_module('model' + str(n), nn.Sequential(*sequence[n]))

    def compute_D_input_nc(self, opt):
        if opt.model in ['pix2pix', 'dhan']:
            input_nc = opt.input_nc + opt.output_nc
        elif opt.model in ['our']:
            if opt.model == 'our' and self.opt.use_precomp_mask_to_D:
                input_nc += 1
            input_nc = opt.output_nc
        else:
            raise NotImplementedError
        return input_nc

    def forward(self, input):
        results = [input]
        for submodel in self.children():
            intermediate_output = submodel(results[-1])
            results.append(intermediate_output)

        get_intermediate_features = not self.opt.no_ganFeat_loss
        if get_intermediate_features:
            return results[1:]
        else:
            return results[-1]


# global discriminator
class GlobalDiscriminator(BaseNetwork):
    def __init__(self, opt):
        super().__init__()
        self.opt = opt

        kw = 4
        padw = int(np.ceil((kw - 1.0) / 2))
        nf = opt.ndf
        input_nc = self.compute_D_input_nc(opt)

        norm_layer = get_nonspade_norm_layer(opt, opt.norm_D)
        sequence = [
            nn.Conv2d(input_nc, nf, kernel_size=kw, stride=2, padding=padw),
            nn.LeakyReLU(0.2, False)
        ]

        for n in range(4):
            nf_prev = nf
            nf = min(nf * 2, 512)
            sequence.extend([
                norm_layer(nn.Conv2d(nf_prev, nf, kernel_size=kw,
                                     stride=2, padding=padw)),
                nn.LeakyReLU(0.2, False)
            ])

        self.extractor = nn.Sequential(*sequence)
        self.classifier = nn.Linear(9 * 9 * 512, 1)

    def compute_D_input_nc(self, opt):
        if opt.model == 'pix2pix':
            input_nc = opt.input_nc + opt.output_nc
        elif opt.model in ['argan', 'our']:
            input_nc = opt.output_nc
        else:
            raise NotImplementedError
        return input_nc

    def forward(self, input):
        h = self.extractor(input)
        h = self.classifier(h.view(input.size(0), -1))
        return h
