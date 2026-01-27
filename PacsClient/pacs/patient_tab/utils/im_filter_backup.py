import SimpleITK as sitk
import numpy as np


def apply_filters(itk_image: sitk.Image):
    # itk_image = sitk.SmoothingRecursiveGaussian(itk_image, sigma=1)
    # اعمال فیلتر Bilateral
    # image_bilateral = sitk.Bilateral(itk_image, domainSigma=2.0, rangeSigma=50.0)
    #
    # # Gaussian
    # image_gaussian = sitk.SmoothingRecursiveGaussian(image_bilateral, sigma=1.0)
    #
    # # CLAHE - به ازای هر اسلایس
    # filtered_slices = []
    # for z in range(image_gaussian.GetSize()[2]):
    #     slice_2d = image_gaussian[:, :, z]
    #
    #     # نرمال‌سازی شدت‌ها و تبدیل به ۸ بیت
    #     slice_8bit = sitk.Cast(sitk.RescaleIntensity(slice_2d, outputMinimum=0, outputMaximum=255), sitk.sitkUInt8)
    #
    #     # یکسان‌سازی origin، spacing و direction برای همه اسلایس‌ها
    #     slice_8bit.SetOrigin((0.0, 0.0))
    #     slice_8bit.SetSpacing((1.0, 1.0))
    #     slice_8bit.SetDirection((1.0, 0.0, 0.0, 1.0))  # برای 2D
    #
    #     # CLAHE
    #     clahe_slice = sitk.AdaptiveHistogramEqualization(slice_8bit, alpha=0.3, beta=0.3, radius=[8, 8])
    #     filtered_slices.append(clahe_slice)
    #
    # # Join to form a 3D volume again
    # image_final = sitk.JoinSeries(filtered_slices)
    #
    # # تنظیم جهت محور برای سازگاری با VTK (اختیاری، بسته به نیاز)
    # image_final.SetSpacing((1.0, 1.0, 1.0))
    # image_final.SetOrigin((0.0, 0.0, 0.0))
    # image_final.SetDirection(np.identity(3).flatten())  # برای volume
    #
    # return image_final
    ##############################################################################################
    pass
    # bilateral_image = apply_filter_denoise(itk_image)
    # itk_image = bilateral_image

    # up_scale_image = apply_filter_upscale_image(itk_image)
    # itk_image = up_scale_image

    # unsharp = apply_unsharp_mask(itk_image)
    # itk_image = unsharp

    # itk_image = contrast_compression(itk_image)

    return itk_image




def contrast_compression(itk_image: sitk.Image, contrast=5.0) -> sitk.Image:
    """
    کاهش شدت سفید و سیاه با تونینگ غیرخطی sigmoid-like
    contrast: پارامتر کنترل شدت فشرده سازی (بیشتر = فشرده سازی بیشتر)
    """
    np_img = sitk.GetArrayFromImage(itk_image).astype(np.float32)

    # نرمال‌سازی اولیه به بازه 0-1
    np_img = (np_img - np.min(np_img)) / (np.max(np_img) - np.min(np_img) + 1e-8)

    # تابع sigmoid-like
    compressed = 1 / (1 + np.exp(-contrast * (np_img - 0.5)))

    # بازگشت به بازه اولیه شدت‌ها
    compressed = compressed * 255.0
    compressed_uint8 = compressed.astype(np.uint8)

    # تبدیل به sitk.Image و حفظ مشخصات
    new_img = sitk.GetImageFromArray(compressed_uint8)
    new_img.SetSpacing(itk_image.GetSpacing())
    new_img.SetOrigin(itk_image.GetOrigin())
    new_img.SetDirection(itk_image.GetDirection())

    return new_img






def apply_filter_denoise(itk_image: sitk.Image) -> sitk.Image:
    return sitk.Bilateral(
        itk_image,
        domainSigma=1.0,
        rangeSigma=5.0
    )


def apply_filter_upscale_image(itk_image: sitk.Image, scale_factor=2) -> sitk.Image:
    original_spacing = itk_image.GetSpacing()
    original_size = itk_image.GetSize()

    # calculate new spacing and size
    new_spacing = [sp/scale_factor if i<2 else sp for i,sp in enumerate(original_spacing)]
    new_size = [original_size[0] * scale_factor, original_size[1] * scale_factor, original_size[2]]

    # set Resampler
    resampler = sitk.ResampleImageFilter()
    resampler.SetOutputSpacing(new_spacing)
    resampler.SetSize(new_size)
    resampler.SetOutputDirection(itk_image.GetDirection())
    resampler.SetOutputOrigin(itk_image.GetOrigin())
    resampler.SetInterpolator(sitk.sitkBSpline)  # یا sitk.sitkLinear برای سرعت بالاتر

    upsampled = resampler.Execute(itk_image)
    return upsampled



def apply_unsharp_mask(image, sigma=0.5, amount=1.0):
    # Step 1: Apply Gaussian blur
    # Cast input to float32 for safe arithmetic
    image_float = sitk.Cast(image, sitk.sitkFloat32)

    # Step 1: Gaussian Blur
    blurred = sitk.SmoothingRecursiveGaussian(image_float, sigma)

    # Step 2: Compute high-frequency details
    mask = sitk.Subtract(image_float, blurred)

    # Step 3: Add scaled details back
    sharpened = sitk.Add(image_float, amount * mask)
    # sharpened = sitk.Cast(sharpened, image.GetPixelID())

    return sharpened