import SimpleITK as sitk
from pathlib import Path
import utils
from natsort import natsorted
from image_filters import apply_filters


def read_dicom_folder(folder):
    metadata = {}
    reader = sitk.ImageSeriesReader()
    dicom_names = reader.GetGDCMSeriesFileNames(folder)
    reader.SetFileNames(dicom_names)
    itk_image: sitk.Image = reader.Execute()

    # get window width and window center for all slice image
    lst_windows_levels = []
    lst_meta_changeable = []
    # load metadata that are changeable base on slice
    print('itk_image:', itk_image)
    for file in dicom_names:
        window_level, meta = utils.get_meta_changeable(file)
        lst_windows_levels.append(window_level)
        lst_meta_changeable.append(meta)

    metadata['windows_levels'] = lst_windows_levels
    metadata['meta_changed'] = lst_meta_changeable
    metadata['meta_fixed'] = utils.get_meta_fixed(dicom_names[0])  # we can set any number of dicom_names


    itk_image = apply_filters(itk_image, metadata)
    vtk_image_data, metadata['orientation'] = utils.convert_itk2vtk(itk_image)

    # print(vtk_image_data.GetScalarRange())
    # arr = sitk.GetArrayFromImage(itk_image)
    # print('mmmmmmmmmmmmm::', arr.min(), arr.max())
    return vtk_image_data, metadata


def read_dicom_folder_with_files(dicom_names):
    metadata = {}
    reader = sitk.ImageSeriesReader()
    reader.SetFileNames(dicom_names)

    lst_windows_levels = []
    lst_meta_changeable = []
    print(type(dicom_names), 'd:', dicom_names)
    for file in dicom_names:
        print('file:', file)
        window_level, meta = utils.get_meta_changeable(file)
        lst_windows_levels.append(window_level)
        lst_meta_changeable.append(meta)

    metadata['windows_levels'] = lst_windows_levels
    metadata['meta_changed'] = lst_meta_changeable
    metadata['meta_fixed'] = utils.get_meta_fixed(dicom_names[0])  # we can set any number of dicom_names

    itk_image: sitk.Image = reader.Execute()

    # if not metadata['meta_fixed']['is_rgb']:
    if not metadata['meta_changed'][0]['is_rgb']:  # for check the series has rgb image
        itk_image = apply_filters(itk_image, metadata)

    vtk_image_data, metadata['orientation'] = utils.convert_itk2vtk(itk_image)
    return vtk_image_data, metadata


def load_images(folder_path):
    lst_series = []  # vtk_image_data, metadata

    if folder_path:  # Import dicom
        folder_path = Path(folder_path)
        # else:  # the root folder is parent dicom folder and subs folder aren't valid

        print('enter to read root.')
        # vtk_image_data, metadata = read_dicom_folder(str(folder_path))
        # metadata['path'] = folder_path
        # lst_series.append((vtk_image_data, metadata))

        size_dict: dict = utils.group_images_base_on_size(folder_path)
        print('size_dict 2:', size_dict)

        for size, files in size_dict.items():
            # vtk_image_data, metadata = read_dicom_folder_with_files(str(files))
            vtk_image_data, metadata = read_dicom_folder_with_files(files)
            metadata['path'] = folder_path
            lst_series.append((vtk_image_data, metadata))



    return lst_series


# path_image_sample = r'/Users/euleday/mostafa/Telegram Downloads/1.2.840.1.99.1.47.1.1676784562068.62543'
#   RTTI typeinfo:   itk::Image<int, 3u>
#       RTTI typeinfo:   itk::ImportImageContainer<unsigned long, int>


# path_image_sample = r'/Users/euleday/mostafa/Telegram Downloads/t correct'
path_image_sample = r'M:\mostafa\codes\PacsClient\source\1.2.840.1.99.1.47.1.1672817802285.61624\Series_112122768'
load_images(path_image_sample)
