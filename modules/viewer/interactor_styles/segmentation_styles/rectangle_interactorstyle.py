import vtkmodules.all as vtk
from typing import List, Tuple
from . import AbstractInteractorStyle
from ..interactor_utils.server_connection import download_file, post_json
from ..interactor_utils.convertors import (world_to_ijk_vtk, build_payload_ijk)
from PacsClient.utils.config import server_config, SEGMENTS_PATH

class RectangleSegmentationInteractorStyle(AbstractInteractorStyle):
    """
    رسم مستطیل با rubber-band روی اسلایسِ نمایش داده‌شده و ارسال ۴ رأس به سرور.
    پایپ‌لاین دقیقاً مثل پلیگان:
        Display (px) → World → IJK  (با همان ورودی map: image_reslice.GetOutput())
        سپس build_payload_ijk → POST → (اختیاری) دانلود و overlay
    """

    def __init__(self, image_viewer):
        super().__init__(image_viewer)

        # ---- تنظیمات سرور/کیس مثل پلیگان ----
        self.server_config = server_config
        self.set_server(self.server_config["SERVER_IP"], self.server_config["SERVER_PORT"])
        self.set_case(
            dicom_folder=self.server_config["DICOM_FOLDER"],
            out_dir=SEGMENTS_PATH,
            series_rule=self.server_config["DEFAULT_SERIES_RULE"],
            seg_name=self.server_config["DEFAULT_SEG_NAME"],
            download_to_client=self.server_config["DOWNLOAD_TO_CLIENT"],
            debug_seg=self.server_config["DEBUG_SEG"],
        )

        # ---- وضعیت رسم ----
        self._drawing = False
        self._p0_disp: Tuple[int, int] | None = None
        self._p1_disp: Tuple[int, int] | None = None

        # ---- actor2D برای نمایش کادر ----
        self._rect_actor = None
        self._rect_pts = None
        self._rect_poly = None
        self._ensure_rubberband_actor()

        self.interactor_name = "RECTANGLE_SEGMENTATION"


    def set_case(self, dicom_folder: str, *, out_dir: str | None = None,
                 series_uid: str | None = None, series_index: int | None = None,
                 series_rule: str = "largest", seg_name: str = "poly_seg",
                 download_to_client: bool = False, debug_seg: bool = False):
        """Set current case parameters (DICOM series and output options).

        Args:
            dicom_folder (str): Absolute path to the DICOM series on the server.
            out_dir (str | None, optional): Output directory on the server. If
                None, the server may choose a default location (e.g., Desktop).
            series_uid (str | None, optional): Explicit SeriesInstanceUID to
                select. If provided, it takes precedence over index/rule.
            series_index (int | None, optional): Series index to select if UID
                is not given.
            series_rule (str, optional): Series selection rule (e.g., "largest",
                "first"). Used if neither UID nor index is set. Defaults to "largest".
            seg_name (str, optional): Name for the output segmentation. Defaults
                to "poly_seg".
            download_to_client (bool, optional): If True, download NIfTI to
                client's Desktop. Otherwise the server just processes it.
            debug_seg (bool, optional): If True, include extra debug data/prints.

        Notes:
            This method only sets parameters on the client side; server-side
            behavior depends on the API implementation.
        """
        self.server_config["DICOM_FOLDER"] = dicom_folder
        self.server_config["OUT_DIR"] = out_dir
        self.server_config["SERIES_NAME"] = seg_name
        self.server_config["DOWNLOAD_TO_CLIENT"] = download_to_client
        self.server_config["SERIES_UID"] = series_uid
        self.server_config["SERIES_RULE"] = series_rule
        self.server_config["SERIES_INDEX"] = series_index
        self.server_config["DEBUG_SEG"] = debug_seg


    def set_server(self, ip: str, port: int = 9000):
        """Configure the target FastAPI server.
        Args:
            ip (str): Server IP or hostname.
            port (int, optional): Server port. Defaults to 9000.
        """
        self.server_ip = ip
        self.server_port = int(port)


    # ================== رویدادها (هم‌راستا با AbstractInteractorStyle) ==================

    def on_left_button_press(self, obj, event):
        # شروع درگ: مختصات شروع را بگیر و rubber-band را نشان بده
        super().on_left_button_press(obj, event)
        self._drawing = True
        self._p0_disp = self.GetInteractor().GetEventPosition()
        self._p1_disp = self._p0_disp
        self._update_rubberband()


    def on_mouse_move(self, obj, event):
        # هنگام رسم، فقط rubber-band را آپدیت کن (وگرنه رفتار والد حفظ)
        if self._drawing:
            self._p1_disp = self.GetInteractor().GetEventPosition()
            self._update_rubberband()
            return True
        return super().on_mouse_move(obj, event)


    def on_left_button_release(self, obj, event):
        # پایان درگ: اگر مستطیل معتبر است، مثل on_contour_closed در پلیگان finalize کن
        if self._drawing:
            self._drawing = False
            self._p1_disp = self.GetInteractor().GetEventPosition()
            if self._has_valid_rect():
                self.on_rectangle_closed()
        super().on_left_button_release(obj, event)


    # ================== هستهٔ کار (آینهٔ on_contour_closed در پلیگان) ==================

    def on_rectangle_closed(self):
        """
        ۱) گوشه‌ها در Display (پیکسل) → ۲) World → ۳) IJK با ورودی map = image_reslice.GetOutput()
        ۴) payload → ۵) ارسال → ۶) overlay (اگر دانلود شد)
        """

        # --- 0) sanity checks مثل پلیگان ---
        if not self.server_config.get("DICOM_FOLDER"):
            print("[rect] dicom_folder is not set on client; abort.")
            return

        # --- 1) گرفتن 4 گوشه در Display ---
        corners_disp = self._get_corners_disp()
        if len(corners_disp) != 4:
            print("[rect] invalid rectangle; need 4 corners.")
            return

        # --- 2) Display → World (با متد کلاسِ انتزاعی) ---
        corners_world = [self.display_to_world(x, y) for (x, y) in corners_disp]

        # --- 3) World → IJK  (دقیقاً همان ورودی که در پلیگان استفاده می‌کنی) ---
        # Polygon does: world_to_ijk_vtk(self.image_viewer.image_reslice.GetOutput(), w_pt)
        # تا شیفت اسلایس رخ ندهد، عیناً همان ورودی را استفاده می‌کنیم.
        try:
            in_img = self.image_viewer.image_reslice.GetOutput()  # مثل پلیگان
            ijk_list_3d = [world_to_ijk_vtk(in_img, w_pt) for w_pt in corners_world]
        except Exception as e:
            print(f"[rect] ERROR: cannot map display-world to input-ijk: {e}")
            return

        # --- 4) ساخت payload و 5) ارسال ---
        payload = build_payload_ijk(self.server_config, ijk_list_3d)
        url = f"http://{self.server_ip}:{self.server_port}/dicom-info/"

        out_path = None
        try:
            print(f'[rect] payload: {payload}')
            if self.server_config.get("DOWNLOAD_TO_CLIENT"):
                out_path = download_file(url, payload, kind="nifti")
                print(f"[rect] downloaded to: {out_path}")
            else:
                r = post_json(url, payload, timeout=180)
                r.raise_for_status()
                print("[rect] server response:", r.json())
        except Exception as e:
            print("[rect] send/download failed:", e)

        # --- 6) overlay فقط اگر مسیر محلی داریم ---
        if out_path:
            self.image_viewer.overlay(out_path)

        # ثبتِ actor روی اسلایس فعلی (سازگار با سیستم ذخیرهٔ ویجت‌ها)
        self.add_object_to_store_widgets(self._rect_actor, "rect_actor")
        self.get_information()
        self.image_viewer.Render()


    # ================== Rubber-band UI ==================

    def _ensure_rubberband_actor(self):
        if self._rect_actor is not None:
            return
        self._rect_pts = vtk.vtkPoints()
        self._rect_pts.SetNumberOfPoints(5)  # LL, LR, UR, UL, LL
        lines = vtk.vtkCellArray()
        lines.InsertNextCell(5)
        for i in range(5):
            lines.InsertCellPoint(i)
        self._rect_poly = vtk.vtkPolyData()
        self._rect_poly.SetPoints(self._rect_pts)
        self._rect_poly.SetLines(lines)

        mapper = vtk.vtkPolyDataMapper2D()
        mapper.SetInputData(self._rect_poly)

        self._rect_actor = vtk.vtkActor2D()
        self._rect_actor.SetMapper(mapper)
        self._rect_actor.GetProperty().SetLineWidth(2.0)
        self._rect_actor.GetProperty().SetOpacity(1.0)
        self._rect_actor.GetProperty().SetColor(*self.color)

        self.image_viewer.renderer.AddViewProp(self._rect_actor)
        self._rect_actor.VisibilityOff()


    def _update_rubberband(self):
        if not (self._p0_disp and self._p1_disp):
            self._rect_actor.VisibilityOff()
            return
        x0, y0 = self._p0_disp
        x1, y1 = self._p1_disp
        x_min, x_max = (x0, x1) if x0 <= x1 else (x1, x0)
        y_min, y_max = (y0, y1) if y0 <= y1 else (y1, y0)

        self._rect_pts.SetPoint(0, x_min, y_min, 0)
        self._rect_pts.SetPoint(1, x_max, y_min, 0)
        self._rect_pts.SetPoint(2, x_max, y_max, 0)
        self._rect_pts.SetPoint(3, x_min, y_max, 0)
        self._rect_pts.SetPoint(4, x_min, y_min, 0)
        self._rect_pts.Modified()
        self._rect_poly.Modified()
        self._rect_actor.VisibilityOn()
        self.image_viewer.Render()


    def _has_valid_rect(self) -> bool:
        return bool(self._p0_disp and self._p1_disp and self._p0_disp != self._p1_disp)


    def _get_corners_disp(self) -> List[Tuple[int, int]]:
        if not self._has_valid_rect():
            return []
        x0, y0 = self._p0_disp
        x1, y1 = self._p1_disp
        x_min, x_max = (x0, x1) if x0 <= x1 else (x1, x0)
        y_min, y_max = (y0, y1) if y0 <= y1 else (y1, y0)
        # ترتیب ساعتگرد از پایین-چپ (LL, LR, UR, UL)
        return [(x_min, y_min), (x_max, y_min), (x_max, y_max), (x_min, y_max)]

