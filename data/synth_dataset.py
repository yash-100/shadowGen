import copy
from pathlib import Path
import torchvision.transforms as transforms
import numpy as np
from PIL import Image,ImageFilter


from data.base_dataset import get_params, get_transform
from data.image_folder import make_dataset
from data.base_dataset import BaseDataset
from data.util import InfiniteSampler
from util.illum_affine_model import darken


class SynthDataset(BaseDataset):
    def __init__(self):
        self.i=100001
    @staticmethod
    def modify_commandline_options(parser, is_train):
        parser.add_argument('--xmin_at_y_0', type=float, default=0.0)
        parser.add_argument('--xmax_at_y_0', type=float, default=0.25)
        parser.add_argument('--ymax_at_x_255', type=float, default=0.9)
        parser.add_argument('--ymin_at_x_255', type=float, default=0.1)
        parser.add_argument('--x_turb_mu', type=float, default=0.05)
        parser.add_argument('--x_turb_sigma', type=float, default=0.025)
        parser.add_argument('--slope_max', type=float, default=1.0)
        parser.add_argument(
            '--intercepts_mode', type=str, default='affine',
            choices=['affine', 'affine_unsync', 'random_jitter',
            'gamma_correction'])
        return parser

    def initialize(self, opt):
        super().initialize(opt)
        self.mask_iter = InfiniteSampler(len(self.mask_paths))

    def get_paths(self, opt):
        our_root = self.root.parent  # remove train/test
        target_paths = make_dataset(our_root / 'shadow_free', read_cache=True)
        mask_paths = make_dataset(our_root / 'matte', read_cache=True)
        # note that last element is used to define self.dataset_size
        return {'mask': mask_paths, 'target': target_paths}

    def __getitem__(self, index):
        target_pil = Image.open(self.target_paths[index]).convert('RGB')
        print(self.target_paths[index])
        mask_index = next(self.mask_iter)
        mask_pil = Image.open(self.mask_paths[1]).convert('L').filter(ImageFilter.GaussianBlur(radius=5))

        image_params = get_params(self.opt, target_pil.size)
        transform_image = get_transform(self.opt, image_params)

        if self.opt.mask_preprocess_mode == "scale_width":
            mask_opt = copy.deepcopy(self.opt)
            mask_opt.preprocess_mode = 'scale_width'
            mask_params = get_params(mask_opt, mask_pil.size)
        elif self.opt.mask_preprocess_mode == "dhan":
            mask_params = image_params  # For feeding batch to DHAN
        else:
            raise NotImplementedError
        transform_mask = get_transform(self.opt, mask_params, n_ch=1)

        target = transform_image(target_pil)
        mask = transform_mask(mask_pil)

        target_dark = darken(target, self.opt)  # this is proposed
        input_tensor = mask * target_dark
        input_tensor += (1 - mask) * target
        # print(type(input_tensor))
        # transform = transforms.Compose([transforms.PILToTensor()])

        s=Path("/content/SynShadow/datasets/SynShadow/input")
        # def tensorToImageConversion(Tensor):
        # # Convert the tensor to numpy array of type uint8
        #     Tensor = Tensor.detach().cpu().numpy().astype('uint8')
        # # Transpose the array to (height, width, channels) format
        #     Tensor = np.transpose(Tensor, (1, 2, 0))
        # # Create an image from the array
        #     return Image.fromarray(Tensor)
        transform = transforms. ToPILImage()
        img = transform(input_tensor)

        # b=tensorToImageConversion(input_tensor)
        img.save(f"{s}/{self.target_paths[index][34:49]}.jpeg",format="jpeg")
        self.i+=1
        input_dict = {
            'input': input_tensor, 'target': target,
            'mask': mask, 'path': self.target_paths[index],
        }
        # print(type(input_dict))
        # print(target)
        # print(self.target_paths[index])

        if self.opt.mask_to_G is not None:
            assert self.opt.mask_to_G == 'gt'
            # Since the mask annotation in ISTD/SRD is a bit noisy,
            # we randomize mask to simulate such noisyness
            thresh = np.random.uniform(0.1, 0.9)
            input_dict['precomp_mask'] = (mask > thresh).float()
        # print(self.postprocess(input_dict))
        return self.postprocess(input_dict)

    def __len__(self):
        return self.dataset_size
