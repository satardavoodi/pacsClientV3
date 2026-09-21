# Adapted from ETRO-MIT/LowerLimbMalalignment-SGR at 64b292e6398803082e0bd7535774efa2792c6a4b.
# Apache-2.0. Changes: offline initialization; no TLS override. See LICENSE and NOTICE.
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# # # # # # # # # # # Functions adapted from: https://github.com/ternaus/robot-surgery-segmentation # # # # # # # # # #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Python packages
import torch
from torch import nn
from torch.nn import functional as F
import torchvision

# Avoid error when downloading for the first time weights from TorchVision. Only run it the first time, you can delete
# the next two lines of code once the weights have been downloaded from the Torchvision servers.


# 3x3 convolution layer
def conv3x3(in_, out):
    return nn.Conv2d(in_, out, 3, padding=1)


# Convolution layer with subsequent ReLU activation
class ConvRelu(nn.Module):
    def __init__(self, in_: int, out: int):
        super(ConvRelu, self).__init__()
        self.conv = conv3x3(in_, out)
        self.activation = nn.ReLU(inplace=True)

    def forward(self, x):
        x = self.conv(x)
        x = self.activation(x)
        return x


# Decoder block
class DecoderBlock(nn.Module):
    """
    Paramaters for Deconvolution were chosen to avoid artifacts, following
    link https://distill.pub/2016/deconv-checkerboard/
    """

    def __init__(self, in_channels, middle_channels, out_channels, is_deconv=True):
        super(DecoderBlock, self).__init__()
        self.in_channels = in_channels

        if is_deconv:
            self.block = nn.Sequential(
                ConvRelu(in_channels, middle_channels),
                nn.ConvTranspose2d(middle_channels, out_channels, kernel_size=4, stride=2,
                                   padding=1),
                nn.ReLU(inplace=True)
            )
        else:
            self.block = nn.Sequential(
                nn.Upsample(scale_factor=2, mode='bilinear'),
                ConvRelu(in_channels, middle_channels),
                ConvRelu(middle_channels, out_channels),
            )

    def forward(self, x):
        return self.block(x)


# U-Net network where the encoder is initialized by extracting the weights from the VGG-16 encoder.
class UNet16(nn.Module):
    def __init__(self, num_classes=1, num_filters=32):
        super().__init__()
        # Set parameters
        self.num_classes = num_classes

        # Set network layers
        self.pool = nn.MaxPool2d(2, 2)
        relu = nn.ReLU(inplace=True)

        # Download VGG-16 and its weights from torchvision repository
        vgg16_weights = torchvision.models.VGG16_Weights
        encoder = torchvision.models.vgg16(weights=None).features

        # Set convolution layers -> Get the weights from the VGG-16 encoder
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

        # Set bottleneck
        self.center = DecoderBlock(512, num_filters * 8 * 2, num_filters * 8)

        # Set decoder branch
        self.dec5 = DecoderBlock(512 + num_filters * 8, num_filters * 8 * 2, num_filters * 8)
        self.dec4 = DecoderBlock(512 + num_filters * 8, num_filters * 8 * 2, num_filters * 8)
        self.dec3 = DecoderBlock(256 + num_filters * 8, num_filters * 4 * 2, num_filters * 2)
        self.dec2 = DecoderBlock(128 + num_filters * 2, num_filters * 2 * 2, num_filters)
        self.dec1 = ConvRelu(64 + num_filters, num_filters)
        self.final = nn.Conv2d(num_filters, num_classes, kernel_size=1)

    def forward(self, x):
        conv1 = self.conv1(x)
        conv2 = self.conv2(self.pool(conv1))
        conv3 = self.conv3(self.pool(conv2))
        conv4 = self.conv4(self.pool(conv3))
        conv5 = self.conv5(self.pool(conv4))

        center = self.center(self.pool(conv5))

        dec5 = self.dec5(torch.cat([center, conv5], 1))

        dec4 = self.dec4(torch.cat([dec5, conv4], 1))
        dec3 = self.dec3(torch.cat([dec4, conv3], 1))
        dec2 = self.dec2(torch.cat([dec3, conv2], 1))
        dec1 = self.dec1(torch.cat([dec2, conv1], 1))

        if self.num_classes > 1:
            x_out = F.log_softmax(self.final(dec1), dim=1)
        else:
            x_out = self.final(dec1)

        return x_out


# U-Net similar to the one above, the only difference is that the "relu" and the "encoder" include the "self." term.
class UNet16V2(nn.Module):
    def __init__(self, num_classes=1, num_filters=32):
        super().__init__()
        # Set parameters
        self.num_classes = num_classes

        # Set network layers
        self.pool = nn.MaxPool2d(2, 2)
        self.relu = nn.ReLU(inplace=True)

        # Get the encoder weights
        vgg16_weights = torchvision.models.VGG16_Weights
        self.encoder = torchvision.models.vgg16(weights=None).features

        # Transfer weights from the VGG-16 to the U-Net
        self.conv1 = nn.Sequential(self.encoder[0],
                                   self.relu,
                                   self.encoder[2],
                                   self.relu)

        self.conv2 = nn.Sequential(self.encoder[5],
                                   self.relu,
                                   self.encoder[7],
                                   self.relu)

        self.conv3 = nn.Sequential(self.encoder[10],
                                   self.relu,
                                   self.encoder[12],
                                   self.relu,
                                   self.encoder[14],
                                   self.relu)

        self.conv4 = nn.Sequential(self.encoder[17],
                                   self.relu,
                                   self.encoder[19],
                                   self.relu,
                                   self.encoder[21],
                                   self.relu)

        self.conv5 = nn.Sequential(self.encoder[24],
                                   self.relu,
                                   self.encoder[26],
                                   self.relu,
                                   self.encoder[28],
                                   self.relu)

        self.center = DecoderBlock(512, num_filters * 8 * 2, num_filters * 8)

        self.dec5 = DecoderBlock(512 + num_filters * 8, num_filters * 8 * 2, num_filters * 8)
        self.dec4 = DecoderBlock(512 + num_filters * 8, num_filters * 8 * 2, num_filters * 8)
        self.dec3 = DecoderBlock(256 + num_filters * 8, num_filters * 4 * 2, num_filters * 2)
        self.dec2 = DecoderBlock(128 + num_filters * 2, num_filters * 2 * 2, num_filters)
        self.dec1 = ConvRelu(64 + num_filters, num_filters)
        self.final = nn.Conv2d(num_filters, num_classes, kernel_size=1)

    def forward(self, x):
        conv1 = self.conv1(x)
        conv2 = self.conv2(self.pool(conv1))
        conv3 = self.conv3(self.pool(conv2))
        conv4 = self.conv4(self.pool(conv3))
        conv5 = self.conv5(self.pool(conv4))

        center = self.center(self.pool(conv5))

        dec5 = self.dec5(torch.cat([center, conv5], 1))

        dec4 = self.dec4(torch.cat([dec5, conv4], 1))
        dec3 = self.dec3(torch.cat([dec4, conv3], 1))
        dec2 = self.dec2(torch.cat([dec3, conv2], 1))
        dec1 = self.dec1(torch.cat([dec2, conv1], 1))

        if self.num_classes > 1:
            x_out = F.log_softmax(self.final(dec1), dim=1)
        else:
            x_out = self.final(dec1)

        return x_out
