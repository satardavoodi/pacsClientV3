# Adapted from ETRO-MIT/LowerLimbMalalignment-SGR at 64b292e6398803082e0bd7535774efa2792c6a4b.
# Apache-2.0. Changes: offline initialization; no TLS override. See LICENSE and NOTICE.
# Python packages
import torch
import torch.nn as nn
import torchvision


# SGR network that combines a U-Net (to generate probability maps) and a VGG-16 encoder (to yield the final estimation
# of the landmarks coordinates).
class SGRNetwork16(nn.Module):
    def __init__(self, unet16, num_coordinates: int, net_pretrained: bool = False):
        super(SGRNetwork16, self).__init__()
        # Set parameters
        self.net_pretrained = net_pretrained
        self.num_coordinates = num_coordinates

        # Set unet model
        self.unet = unet16

        # Set layers
        relu = nn.ReLU(inplace=True)
        self.pool = nn.MaxPool2d(2, 2)

        # Download VGG-16 model from torchvision repository
        vgg16_weights = torchvision.models.VGG16_Weights
        encoder = torchvision.models.vgg16(weights=None).features

        # Modify input layer according to type of input
        # Ankle image: 3-channels xray image + 2-channels landmark mask = 5 input features
        # Femur image: 3-channels xray image + 1-channel landmark mask = 4 input features
        # Knee image: 3-channels xray image + 5-channels landmark mask = 8 input features
        if self.num_coordinates == 4:
            encoder[0] = torch.nn.Conv2d(5, 64, kernel_size=(1, 1), stride=(1, 1))
        elif self.num_coordinates == 2:
            encoder[0] = torch.nn.Conv2d(4, 64, kernel_size=(1, 1), stride=(1, 1))
        elif self.num_coordinates == 10:
            encoder[0] = torch.nn.Conv2d(8, 64, kernel_size=(1, 1), stride=(1, 1))

        # Set layers for the encoder section
        self.conv1 = nn.Sequential(encoder[0],
                                   relu,
                                   encoder[2],
                                   relu)
        self.conv2 = nn.Sequential(encoder[5],
                                   relu,
                                   encoder[7],
                                   relu)
        self.conv3 = nn.Sequential(encoder[10],
                                   relu,
                                   encoder[12],
                                   relu,
                                   encoder[14],
                                   relu)
        self.conv4 = nn.Sequential(encoder[17],
                                   relu,
                                   encoder[19],
                                   relu,
                                   encoder[21],
                                   relu)
        self.conv5 = nn.Sequential(encoder[24],
                                   relu,
                                   encoder[26],
                                   relu,
                                   encoder[28],
                                   relu)
        self.fc1 = nn.Sequential(nn.Flatten(),
                                 nn.Linear(131072, self.num_coordinates))

    def forward(self, x):
        out1 = self.unet(x)
        cat = torch.cat((x, out1), dim=1)
        conv1 = self.conv1(cat)
        conv2 = self.conv2(self.pool(conv1))
        conv3 = self.conv3(self.pool(conv2))
        conv4 = self.conv4(self.pool(conv3))
        conv5 = self.conv5(self.pool(conv4))
        out2 = self.fc1(self.pool(conv5))

        return out1, out2
