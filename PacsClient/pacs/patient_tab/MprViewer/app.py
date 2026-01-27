# PyQt5
from PyQt5 import QtCore, QtWidgets, QtGui
from PyQt5.QtWidgets import QFileDialog, QProgressDialog

# VTK
from QtOrthoViewer import *
from QtSegmentationViewer import QtSegmentationViewer
from VtkBase import VtkBase
from ViewersConnection import ViewersConnection

# DICOM to MHD conversion
import SimpleITK as sitk
import pydicom
import os
import tempfile
import numpy as np

# Main Window
class MainWindow(QtWidgets.QMainWindow):
    
    # Constructor
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MPR Viewer")
        self.setWindowIcon(QtGui.QIcon("icon.ico"))
        
        # Create a central widget and set the layout
        central_widget = QtWidgets.QWidget()
        central_layout = QtWidgets.QHBoxLayout()
        
        # Create the viewers
        self.vtkBaseClass = VtkBase()
        self.QtSagittalOrthoViewer = QtOrthoViewer(self.vtkBaseClass, SLICE_ORIENTATION_YZ, "Sagittal Plane - YZ")
        self.QtCoronalOrthoViewer = QtOrthoViewer(self.vtkBaseClass, SLICE_ORIENTATION_XZ, "Coronal Plane - XZ")
        self.QtAxialOrthoViewer = QtOrthoViewer(self.vtkBaseClass, SLICE_ORIENTATION_XY, "Axial Plane - XY")
        self.QtSegmentationViewer = QtSegmentationViewer(self.vtkBaseClass, label="3D Viewer")
        
        self.ViewersConnection = ViewersConnection(self.vtkBaseClass)
        self.ViewersConnection.add_orthogonal_viewer(self.QtSagittalOrthoViewer.get_viewer())
        self.ViewersConnection.add_orthogonal_viewer(self.QtCoronalOrthoViewer.get_viewer())
        self.ViewersConnection.add_orthogonal_viewer(self.QtAxialOrthoViewer.get_viewer())
        self.ViewersConnection.add_segmentation_viewer(self.QtSegmentationViewer.get_viewer())

        # Set up the main layout
        main_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        
        left_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        left_splitter.addWidget(self.QtAxialOrthoViewer)
        left_splitter.addWidget(self.QtSegmentationViewer)
        
        right_splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        right_splitter.addWidget(self.QtCoronalOrthoViewer)
        right_splitter.addWidget(self.QtSagittalOrthoViewer)

        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(right_splitter)

        # Set the central widget
        central_layout.addWidget(main_splitter)
        central_widget.setLayout(central_layout)
        self.setCentralWidget(central_widget)
                        
        # Add menu bar
        self.create_menu()

        # Connect signals and slots
        self.connect()
    
    # Connect signals and slots         
    def connect(self):
        pass
    
    # Create the menu bar
    def create_menu(self):
        menu_bar = self.menuBar()

        file_menu = menu_bar.addMenu("File")

        # Open MHD Image
        open_action = QtWidgets.QAction("Open Image (MHD)", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_data)
        file_menu.addAction(open_action)

        # Open DICOM Folder
        open_dicom_action = QtWidgets.QAction("Open DICOM Folder", self)
        open_dicom_action.setShortcut("Ctrl+D")
        open_dicom_action.triggered.connect(self.open_dicom_folder)
        file_menu.addAction(open_dicom_action)

        file_menu.addSeparator()

        # Exit
        exit_action = QtWidgets.QAction("Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.exit)
        file_menu.addAction(exit_action)

    # Open data
    def open_data(self):
        file_dialog = QFileDialog()
        file_dialog.setFileMode(QFileDialog.ExistingFile)
        file_dialog.setNameFilter("Image Files (*.mhd)")
        if file_dialog.exec_():
            filenames = file_dialog.selectedFiles()
            if len(filenames) > 0:
                filename = filenames[0]
                try:
                    self.load_data(filename)
                    self.render_data()
                except Exception as e:
                    print(e)
                    QtWidgets.QMessageBox.critical(self, "خطا", "امکان باز کردن فایل تصویر وجود ندارد.")

    # Open DICOM folder and convert to MHD
    def open_dicom_folder(self):
        """انتخاب پوشه DICOM، تبدیل به MHD و نمایش"""
        folder_dialog = QFileDialog()
        folder_dialog.setFileMode(QFileDialog.Directory)
        folder_dialog.setOption(QFileDialog.ShowDirsOnly, True)
        
        dicom_folder = folder_dialog.getExistingDirectory(
            self, 
            "انتخاب پوشه حاوی فایل‌های DICOM",
            "",
            QFileDialog.ShowDirsOnly
        )
        
        if dicom_folder:
            progress = None
            try:
                # نمایش Progress Dialog
                progress = QProgressDialog("در حال تبدیل فایل‌های DICOM...", "لغو", 0, 100, self)
                progress.setWindowModality(QtCore.Qt.WindowModal)
                progress.setMinimumDuration(0)
                progress.setValue(10)
                
                # ایجاد نام فایل منحصر به فرد با timestamp
                import time
                timestamp = int(time.time())
                temp_dir = tempfile.gettempdir()
                output_filename = os.path.join(temp_dir, f"temp_dicom_{timestamp}")
                
                progress.setValue(20)
                progress.setLabelText("در حال خواندن فایل‌های DICOM...")
                QtWidgets.QApplication.processEvents()
                
                # تبدیل DICOM به MHD با حفظ orientation
                reader = sitk.ImageSeriesReader()
                dicom_names = reader.GetGDCMSeriesFileNames(dicom_folder)
                
                if len(dicom_names) == 0:
                    progress.close()
                    QtWidgets.QMessageBox.warning(
                        self, 
                        "هشدار", 
                        "هیچ فایل DICOM در پوشه انتخابی پیدا نشد!"
                    )
                    return
                
                progress.setValue(30)
                progress.setLabelText(f"در حال پردازش {len(dicom_names)} فایل...")
                QtWidgets.QApplication.processEvents()
                
                # استخراج Window/Level و orientation از فایل DICOM اول
                window_level_info = self.extract_window_level_from_dicom(dicom_names[0])
                
                progress.setValue(40)
                QtWidgets.QApplication.processEvents()
                
                # خواندن سری DICOM با حفظ metadata
                reader.SetFileNames(dicom_names)
                reader.MetaDataDictionaryArrayUpdateOn()
                reader.LoadPrivateTagsOn()
                
                progress.setValue(50)
                QtWidgets.QApplication.processEvents()
                
                image = reader.Execute()
                
                # حفظ spacing اصلی
                original_spacing = image.GetSpacing()
                
                # بررسی نیاز به interpolation (اگر spacing ها یکسان نیستند)
                spacing_diff = max(original_spacing) / min(original_spacing)
                needs_interpolation = spacing_diff > 1.5  # اگر اختلاف بیشتر از 50% باشد
                
                if needs_interpolation:
                    progress.setValue(55)
                    progress.setLabelText("در حال انجام interpolation برای spacing یکنواخت...")
                    QtWidgets.QApplication.processEvents()
                    
                    # Resample به isotropic spacing
                    image = self.resample_to_isotropic(image)
                    
                    progress.setValue(60)
                    QtWidgets.QApplication.processEvents()
                
                # حفظ orientation اصلی DICOM
                # DICOM به صورت پیش‌فرض LPS orientation دارد
                # SimpleITK به صورت پیش‌فرض orientation را حفظ می‌کند
                original_direction = image.GetDirection()
                original_origin = image.GetOrigin()
                final_spacing = image.GetSpacing()
                
                progress.setValue(65)
                progress.setLabelText("در حال ذخیره فایل...")
                QtWidgets.QApplication.processEvents()
                
                # ذخیره به فرمت MHD با حفظ تمام metadata
                output_path = f"{output_filename}.mhd"
                sitk.WriteImage(image, output_path, True)  # True = useCompression
                
                progress.setValue(80)
                progress.setLabelText("در حال بارگذاری تصویر...")
                QtWidgets.QApplication.processEvents()
                
                # بارگذاری و نمایش
                self.load_data(output_path)
                
                progress.setValue(90)
                QtWidgets.QApplication.processEvents()
                
                # اعمال Window/Level استخراج شده
                if window_level_info['window'] and window_level_info['level']:
                    self.apply_window_level(
                        window_level_info['window'], 
                        window_level_info['level'],
                        window_level_info['rescale_slope'],
                        window_level_info['rescale_intercept']
                    )
                else:
                    # اگر Window/Level در DICOM نبود، محاسبه خودکار
                    self.auto_adjust_window_level(image)
                
                progress.setValue(95)
                progress.setLabelText("در حال رندر تصویر...")
                QtWidgets.QApplication.processEvents()
                
                # رندر با تاخیر کوچک برای اطمینان از بارگذاری کامل
                QtWidgets.QApplication.processEvents()
                self.render_data()
                
                progress.setValue(100)
                progress.close()
                
                # نمایش پیام موفقیت
                info_msg = f"✅ تبدیل و نمایش با موفقیت انجام شد!\n\n"
                info_msg += f"📁 تعداد فایل‌های DICOM: {len(dicom_names)}\n"
                info_msg += f"📐 اندازه تصویر: {image.GetSize()}\n"
                
                # نمایش spacing با جزئیات
                if needs_interpolation:
                    info_msg += f"📏 Spacing اصلی: ({original_spacing[0]:.2f}, {original_spacing[1]:.2f}, {original_spacing[2]:.2f})\n"
                    info_msg += f"📏 Spacing نهایی (isotropic): ({final_spacing[0]:.2f}, {final_spacing[1]:.2f}, {final_spacing[2]:.2f}) ✅\n"
                else:
                    info_msg += f"📏 Spacing: ({final_spacing[0]:.2f}, {final_spacing[1]:.2f}, {final_spacing[2]:.2f})\n"
                
                info_msg += f"🧭 Origin: {original_origin}\n"
                info_msg += f"📊 Pixel Range: {self.vtkBaseClass.scalerRange}\n"
                
                if window_level_info['window'] and window_level_info['level']:
                    info_msg += f"🎨 DICOM W/L: {window_level_info['window']:.0f}/{window_level_info['level']:.0f}\n"
                    if window_level_info['rescale_slope'] != 1.0 or window_level_info['rescale_intercept'] != 0.0:
                        info_msg += f"📐 Rescale: slope={window_level_info['rescale_slope']}, intercept={window_level_info['rescale_intercept']}"
                else:
                    info_msg += f"🎨 Window/Level: تنظیم خودکار"
                
                QtWidgets.QMessageBox.information(self, "موفقیت", info_msg)
                
            except Exception as e:
                if progress:
                    progress.close()
                error_msg = f"خطا در تبدیل یا نمایش فایل‌های DICOM:\n\n{str(e)}"
                print(f"Error: {e}")
                import traceback
                traceback.print_exc()
                QtWidgets.QMessageBox.critical(self, "خطا", error_msg)
    
    # Extract Window/Level from DICOM file
    def extract_window_level_from_dicom(self, dicom_file_path):
        """استخراج Window و Level از فایل DICOM با در نظر گرفتن Rescale"""
        try:
            ds = pydicom.dcmread(dicom_file_path)
            
            # تلاش برای خواندن Window Center و Window Width
            window = None
            level = None
            
            # خواندن Rescale Slope و Intercept (برای CT اهمیت دارد)
            rescale_slope = float(ds.RescaleSlope) if hasattr(ds, 'RescaleSlope') else 1.0
            rescale_intercept = float(ds.RescaleIntercept) if hasattr(ds, 'RescaleIntercept') else 0.0
            
            if hasattr(ds, 'WindowWidth') and hasattr(ds, 'WindowCenter'):
                # اگر چند مقدار وجود دارد، اولی را بگیر
                if isinstance(ds.WindowWidth, pydicom.multival.MultiValue):
                    window = float(ds.WindowWidth[0])
                else:
                    window = float(ds.WindowWidth)
                
                if isinstance(ds.WindowCenter, pydicom.multival.MultiValue):
                    level = float(ds.WindowCenter[0])
                else:
                    level = float(ds.WindowCenter)
            
            return {
                'window': window,
                'level': level,
                'rescale_slope': rescale_slope,
                'rescale_intercept': rescale_intercept,
                'modality': ds.Modality if hasattr(ds, 'Modality') else 'Unknown'
            }
            
        except Exception as e:
            print(f"Warning: Could not extract Window/Level from DICOM: {e}")
            return {
                'window': None, 
                'level': None, 
                'rescale_slope': 1.0,
                'rescale_intercept': 0.0,
                'modality': 'Unknown'
            }
    
    # Apply Window/Level to viewers
    def apply_window_level(self, window, level, rescale_slope=1.0, rescale_intercept=0.0):
        """اعمال Window و Level به تمام viewer ها با در نظر گرفتن Rescale"""
        try:
            # در DICOM: مقادیر Window/Level در واحد Hounsfield (برای CT) یا مقادیر واقعی پیکسل هستند
            # در VTK: بعد از ImageShiftScale، مقادیر بین 0-255 هستند
            
            # دریافت scaler range واقعی از VTK
            scaler_range = self.vtkBaseClass.scalerRange
            scaler_min = float(scaler_range[0])
            scaler_max = float(scaler_range[1])
            
            # محاسبه Window/Level در فضای 0-255
            # فرمول نگاشت: vtk_value = (dicom_value - scaler_min) * 255 / (scaler_max - scaler_min)
            
            if scaler_max != scaler_min:
                # تبدیل level از DICOM space به VTK space (0-255)
                vtk_level = (level - scaler_min) * 255.0 / (scaler_max - scaler_min)
                
                # window در DICOM نسبت به range کل است
                # باید آن را به نسبت 0-255 تبدیل کنیم
                vtk_window = window * 255.0 / (scaler_max - scaler_min)
                
                # محدود کردن به محدوده معقول
                vtk_level = max(0, min(255, vtk_level))
                vtk_window = max(1, min(255, vtk_window))
            else:
                # اگر range صفر بود، از مقادیر پیش‌فرض استفاده کن
                vtk_window = 255
                vtk_level = 127
            
            # اعمال به VtkBase
            self.vtkBaseClass.imageWindowLevel.SetWindow(float(vtk_window))
            self.vtkBaseClass.imageWindowLevel.SetLevel(float(vtk_level))
            self.vtkBaseClass.imageWindowLevel.Update()
            self.vtkBaseClass.imageWindowLevel.UpdateWholeExtent()
            
            # به‌روزرسانی imageMapToColors
            self.vtkBaseClass.imageMapToColors.Update()
            self.vtkBaseClass.imageMapToColors.UpdateWholeExtent()
            
            # به‌روزرسانی imageBlend
            self.vtkBaseClass.imageBlend.Update()
            self.vtkBaseClass.imageBlend.UpdateWholeExtent()
            
            print(f"DICOM Window/Level: W={window}, L={level}")
            print(f"Scaler Range: {scaler_min} to {scaler_max}")
            print(f"VTK Window/Level: W={vtk_window:.1f}, L={vtk_level:.1f}")
            
        except Exception as e:
            print(f"Error applying Window/Level: {e}")
            import traceback
            traceback.print_exc()
    
    # Auto adjust Window/Level based on image statistics
    def auto_adjust_window_level(self, sitk_image):
        """تنظیم خودکار Window/Level بر اساس آمار تصویر"""
        try:
            # تبدیل به numpy array برای محاسبه آمار
            np_array = sitk.GetArrayFromImage(sitk_image)
            
            # محاسبه percentile ها برای جلوگیری از تاثیر outlier ها
            p2 = np.percentile(np_array, 2)
            p98 = np.percentile(np_array, 98)
            
            # محاسبه Window و Level
            window = p98 - p2
            level = (p98 + p2) / 2
            
            # اعمال
            self.apply_window_level(window, level)
            
            print(f"Auto-adjusted Window/Level: Window={window:.1f}, Level={level:.1f}")
            
        except Exception as e:
            print(f"Error in auto-adjusting Window/Level: {e}")
            # اگر خطا داشت، مقادیر پیش‌فرض
            self.apply_window_level(255, 127)
    
    # Resample image to isotropic spacing
    def resample_to_isotropic(self, image, interpolator=sitk.sitkLinear):
        """
        Resample تصویر به spacing یکنواخت (isotropic) برای MPR بهتر
        
        Parameters:
        -----------
        image : SimpleITK.Image
            تصویر ورودی
        interpolator : SimpleITK interpolator
            نوع interpolation (پیش‌فرض: Linear)
        
        Returns:
        --------
        SimpleITK.Image
            تصویر resampled شده با spacing یکنواخت
        """
        try:
            # دریافت spacing اصلی
            original_spacing = image.GetSpacing()
            original_size = image.GetSize()
            
            # انتخاب کوچکترین spacing به عنوان target (بهترین کیفیت)
            new_spacing = [min(original_spacing)] * 3
            
            # محاسبه اندازه جدید برای حفظ ابعاد فیزیکی
            new_size = [
                int(round(original_size[0] * (original_spacing[0] / new_spacing[0]))),
                int(round(original_size[1] * (original_spacing[1] / new_spacing[1]))),
                int(round(original_size[2] * (original_spacing[2] / new_spacing[2])))
            ]
            
            # تنظیم resampler
            resample = sitk.ResampleImageFilter()
            resample.SetOutputSpacing(new_spacing)
            resample.SetSize(new_size)
            resample.SetOutputDirection(image.GetDirection())
            resample.SetOutputOrigin(image.GetOrigin())
            resample.SetTransform(sitk.Transform())
            resample.SetDefaultPixelValue(image.GetPixelIDValue())
            resample.SetInterpolator(interpolator)
            
            # اجرای resampling
            resampled_image = resample.Execute(image)
            
            print(f"Resampling completed:")
            print(f"  Original spacing: {original_spacing}")
            print(f"  Original size: {original_size}")
            print(f"  New spacing: {new_spacing}")
            print(f"  New size: {new_size}")
            
            return resampled_image
            
        except Exception as e:
            print(f"Error in resampling: {e}")
            print("Returning original image without resampling")
            return image                    

    # Load the data
    def load_data(self, filename):
        self.vtkBaseClass.connect_on_data(filename)
        self.QtAxialOrthoViewer.connect_on_data(filename)
        self.QtCoronalOrthoViewer.connect_on_data(filename)
        self.QtSagittalOrthoViewer.connect_on_data(filename)
        self.QtSegmentationViewer.connect_on_data(filename)
        self.ViewersConnection.connect_on_data()
    
    # Render the data   
    def render_data(self):
        self.QtAxialOrthoViewer.render()
        self.QtCoronalOrthoViewer.render()
        self.QtSagittalOrthoViewer.render()
        self.QtSegmentationViewer.render()

    # Close the application
    def closeEvent(self, QCloseEvent):
        super().closeEvent(QCloseEvent)
        self.QtAxialOrthoViewer.close()
        self.QtCoronalOrthoViewer.close()
        self.QtSagittalOrthoViewer.close()
        self.QtSegmentationViewer.close()
    
    # Exit the application  
    def exit(self):
        self.close()
