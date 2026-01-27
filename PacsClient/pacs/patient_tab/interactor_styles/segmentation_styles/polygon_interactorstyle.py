"""
Polygon segmentation interactor style for VTK-based medical image viewers.

This module provides a custom interactor style that lets users draw a polygon
(contour) on the displayed slice, converts the drawn points from the display
world space back to the original input image IJK space, performs necessary
axis flips to match server-side conventions, and then posts a segmentation
request to a FastAPI endpoint. Optionally, it can download the resulting NIfTI
file to the client's Desktop.

Notes:
    - The server address and default case parameters are configurable via
      `set_server()` and `set_case()`. The constructor also initializes them
      using the DEFAULT_* constants below.
    - `_display_world_to_input_ijk_many()` computes the mapping between the
      resliced display image and the original input image using direction,
      spacing, and origin matrices.
    - The current implementation flips j/k indices after mapping to match a
      180° rotation around X in IJK space (common for some viewer/server
      conventions).
"""
import numpy as np
import vtkmodules.all as vtk
from typing import List, Tuple
from . import AbstractInteractorStyle
from ..tools_object_manager import PolygonSegmentationObject
from ..interactor_utils.server_connection import download_file, post_json
from ..interactor_utils.convertors import (get_world_points, world_to_ijk_vtk,
                                           build_payload_ijk, rect_from_quad_by_longest_diagonal)
from PacsClient.utils.config import server_config, SEGMENTS_PATH
from PacsClient.utils.utils import get_server_url


class ContourWidget(vtk.vtkContourWidget):
    """Customized vtkContourWidget with streamlined polygon drawing behavior.

    This widget:
      - Uses an oriented glyph contour representation with a custom line width
        and color for better visibility.
      - Is set to polygon mode with linear interpolation by default.
      - Restricts point placement to the active image actor to avoid off-slice
        node placement.
      - Emits a custom "ClosedForFirstTimeEvent" once the loop is closed.

    Args:
        image_viewer: An image viewer object that exposes an interactor and an
            image actor (used by the point placer).
    """

    def __init__(self, image_viewer):
        super(ContourWidget, self).__init__()
        self.repr: vtk.vtkOrientedGlyphContourRepresentation = vtk.vtkOrientedGlyphContourRepresentation()
        self.repr.GetLinesProperty().SetLineWidth(2)
        self.repr.GetLinesProperty().SetColor(1.0, 0.1, 0.0)  # polygon line color

        self.SetRepresentation(self.repr)
        self.SetInteractor(image_viewer.image_interactor)
        self.SetModeToPolygon()

        interpolator = vtk.vtkLinearContourLineInterpolator()
        self.repr.SetLineInterpolator(interpolator)

        placer = vtk.vtkImageActorPointPlacer()
        placer.SetImageActor(image_viewer.GetImageActor())
        self.repr.SetPointPlacer(placer)

        self.closed = False
        self.ClosedForFirstTimeEvent = vtk.vtkCommand.UserEvent + 1
        self.AddObserver(vtk.vtkCommand.EndInteractionEvent, self.OnEndInteraction)

    def OnEndInteraction(self, obj, event, calldata=None):
        """Event hook: called when interaction ends.

        Once the loop is detected as closed for the first time, mark as closed
        and invoke a custom event to let listeners proceed.

        Args:
            obj: The widget instance (VTK callback signature).
            event: VTK event name/id.
            calldata: Optional event data (unused).
        """
        if obj.repr.GetClosedLoop() and not self.closed:
            self.closed = True
            self.InvokeEvent(self.ClosedForFirstTimeEvent)

    def set_polygon_color_red(self, R: float, G: float, B: float):
        """Set polygon polyline color.

        Args:
            R (float): Red component in [0, 1].
            G (float): Green component in [0, 1].
            B (float): Blue component in [0, 1].
        """
        self.repr.GetLinesProperty().SetColor(R, G, B)

    def SetModeToPolygon(self):
        """Configure the widget for polygon drawing.

        Behavior:
            - FollowCursorOn()
            - ContinuousDrawOff()
            - Node picking disabled to avoid accidental edits while drawing
        """
        self.FollowCursorOn()
        self.ContinuousDrawOff()
        self.SetAllowNodePicking(False)


class PolygonSegmentationInteractorStyle(AbstractInteractorStyle):
    def __init__(self, image_viewer, on_polygon_finished=None):
        super().__init__(image_viewer)
        self.active_widget = self.create_contour_widget()
        self.active_widget.Off()
        self.active_contours = []

        self.server_config = server_config
        self.set_server(self.server_config["SERVER_IP"],
                        self.server_config["SERVER_PORT"])

        # --- این قسمت را اصلاح کن ---

        series_meta = self.image_viewer.metadata.get('series', {})

        # UID واقعی دایکام (همونی که تو متادیتا داری)
        series_uid = series_meta.get('series_uid')   # ← این رشته‌ی بلند

        # اگر هر دلیلی UID نبود، می‌تونی به عنوان fallback از سری ایندکس استفاده کنی
        series_index = None
        if series_uid is None:
            series_index = series_meta.get('series_number')
        dicom_folder = get_server_url('segmentation')
        print(f'dicom_folder: {dicom_folder}\n')
        print(f'series config from config file: {self.server_config["DICOM_FOLDER"]}\n')
        self.set_case(
            dicom_folder=self.server_config["DICOM_FOLDER"],
            out_dir=SEGMENTS_PATH,
            series_rule=self.server_config["DEFAULT_SERIES_RULE"],
            seg_name=self.server_config["DEFAULT_SEG_NAME"],
            download_to_client=self.server_config["DOWNLOAD_TO_CLIENT"],
            debug_seg=self.server_config["DEBUG_SEG"],
            series_uid=str(series_uid) if series_uid else None,
            series_index=series_index,
        )

        print(f'\nmetadata: {self.image_viewer.metadata}')
        print(f'\nmetadata fixed: {self.image_viewer.metadata_fixed}')
        print(f'\n[poly] using series_uid={series_uid}, series_index={series_index}\n')


    def _get_server_config_keys(self):
        return self.server_config.keys()

    def _get_server_config_values(self):
        return self.server_config.values()

    def On(self):
        """Enable the active contour widget."""
        self.active_widget.On()

    def Off(self):
        """Disable the active contour widget."""
        self.active_widget.Off()

    def get_server_config(self):
        return self.server_config

    def set_server(self, ip: str, port: int = 9000):
        """Configure the target FastAPI server.
        Args:
            ip (str): Server IP or hostname.
            port (int, optional): Server port. Defaults to 9000.
        """
        self.server_ip = ip
        self.server_port = int(port)

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
        self.server_config['STUDY_UID'] = self.image_viewer.metadata_fixed['study_uid']
        # self.server_config["DICOM_FOLDER"] = r'D:\Sources\{}'.format(
        #     self.image_viewer.metadata_fixed['study_uid'] # set payload's dicom folder with study uid.
        # )

    def create_contour_widget(self):
        """Create and initialize a new ContourWidget bound to the viewer.

        Returns:
            ContourWidget: The configured, active contour widget instance.
        """
        widget = ContourWidget(self.image_viewer)
        widget.AddObserver(widget.ClosedForFirstTimeEvent, self.on_contour_closed)
        widget.AddObserver(vtk.vtkCommand.StartInteractionEvent, self.on_interaction_start)
        widget.On()
        return widget

    def on_interaction_start(self, obj: ContourWidget, event, calldata=None):
        """Event hook: called when polygon interaction starts.

        Emits the interactor's "interaction" signal and registers the widget
        in any measurement/annotation list the viewer maintains.
        """
        self.emit_interaction()
        self.image_viewer.GetMeasurements().AddItem(obj)

    def on_right_button_press(self, obj, event):
        """Optional right-mouse-press hook (currently unused)."""
        pass

    def on_right_button_release(self, obj, event):
        """Reset the active contour widget on right-mouse-button release.

        This toggles the widget Off->On to start a fresh polygon interaction,
        then triggers a render to update the viewer.
        """
        self.Off()
        self.active_widget = self.create_contour_widget()
        self.On()
        self.image_viewer.Render()

    def on_contour_closed(self, obj: ContourWidget, event, calldata=None):
        """Main handler: send 3D IJK vertices to server (no 'slice' field)."""

        # sanity checks
        if not (self.server_config.get("STUDY_UID") or self.server_config.get("DICOM_FOLDER")):
            print("[poly] neither study_uid nor dicom_folder set; abort.")
            return

        rep = getattr(obj, "repr", None)
        if not (rep and hasattr(rep, "GetClosedLoop") and rep.GetClosedLoop()):
            print("[poly] contour not closed; skip send")
            return

        num_nodes = int(rep.GetNumberOfNodes() or 0)
        if num_nodes < 3:
            print("[poly] need at least 3 points; abort.")
            return

        # read polygon nodes (DISPLAY world)
        pts_world_out = get_world_points(points=num_nodes, rep=rep)

        # drop duplicated last point if loop auto-closes
        if len(pts_world_out) >= 2 and all(abs(pts_world_out[-1][d] - pts_world_out[0][d]) < 1e-6 for d in range(3)):
            pts_world_out.pop()
        if len(pts_world_out) < 3:
            print("[poly] need at least 3 unique points; abort.")
            return

        # map to input IJK (3D)
        try:
            ijk_list_3d = [
                # world_to_ijk_vtk(self.image_viewer.image_reslice.GetOutput(), w_pt)
                self.image_viewer.world_to_ijk(xw=w_pt[0], yw=w_pt[1], zw=w_pt[2], y_flip=True)
                for w_pt in pts_world_out
            ]
        except Exception as e:
            print(f"[poly] ERROR: cannot map display-world to input-ijk: {e}")
            return
        try:
            url = get_server_url('segmentation')

        except Exception as e:
            print(f"[poly] ERROR: cannot connect to server: {e}")
            return
        # send to server
        payload = build_payload_ijk(self.server_config, ijk_list_3d)
        url = f"{url}/dicom-info/"
        print(f'\nfinal url: {url}\n')

        out_path = None  # ensure defined
        try:
            if self.server_config.get("DOWNLOAD_TO_CLIENT"):
                out_path = download_file(url, payload, kind="nifti")
            else:
                r = post_json(url, payload, timeout=180)
                r.raise_for_status()
                resp = r.json() or {}
                out_path = resp.get("nifti_path") or resp.get("out_path") or resp.get("path")
        except Exception as e:
            print("[poly] send/download failed:", e)

        polygon_segmentation_object = PolygonSegmentationObject(obj)
        self.add_object_to_store_widgets(polygon_segmentation_object, self.tool_access.POLYGON_SEGMENTATION)

        try:
            obj.ProcessEventsOff()
        except Exception:
            pass

        self.active_widget = self.create_contour_widget()
        self.active_contours.append(obj)
        self.get_information()

        if out_path:
            self.image_viewer.overlay(out_path, pts_world_out=pts_world_out, pts_ijk=ijk_list_3d)
        else:
            print("[poly] no overlay path returned; skip overlay.")

    def get_information(self):
        """Hook for updating any UI/labels after actions.

        Currently a placeholder. Override as needed in your application to
        surface state (e.g., last response, slice index, etc.).
        """
        pass

    def draw_segmentation_with_ijk_point(self, pts_world_out: list):
        if not (self.server_config.get("STUDY_UID") or self.server_config.get("DICOM_FOLDER")):
            print("[poly] neither study_uid nor dicom_folder set; abort.")
            return

        # drop duplicated last point if loop auto-closes
        if len(pts_world_out) >= 2 and all(abs(pts_world_out[-1][d] - pts_world_out[0][d]) < 1e-6 for d in range(3)):
            pts_world_out.pop()
        if len(pts_world_out) < 3:
            print("[poly] need at least 3 unique points; abort.")
            return

        # map to input IJK (3D)
        try:
            ijk_list_3d = [
                # world_to_ijk_vtk(self.image_viewer.image_reslice.GetOutput(), w_pt)
                self.image_viewer.world_to_ijk(xw=w_pt[0], yw=w_pt[1], zw=w_pt[2], y_flip=True)
                for w_pt in pts_world_out
            ]
        except Exception as e:
            print(f"[poly] ERROR: cannot map display-world to input-ijk: {e}")
            return

        payload = build_payload_ijk(self.server_config, ijk_list_3d)
        url = f"http://{self.server_ip}:{self.server_port}/dicom-info/"

        try:
            print(f'\npayload: {payload}\n')
            print(f'ijk points on countor closed: {payload["params"]["points"]}')

            if self.server_config.get("DOWNLOAD_TO_CLIENT"):
                out_path = download_file(url, payload, kind="nifti")
                # print(f'in if on counter closed out_path: {out_path}')
            else:
                r = post_json(url, payload, timeout=180)
                r.raise_for_status()
                resp = r.json()
                print("[poly] server response:", resp)
        except Exception as e:
            print("[poly] send/download failed:", e)

        points = payload["params"]["points"]

        corners = rect_from_quad_by_longest_diagonal(points=points, image_size=None, margin=0.0, keep_z="first", round_to_int=False)
        print(f'\n\n\npoints: {points}\n\ncorners: {corners}\n')



        # UI bookkeeping
        # polygon_segmentation_object = PolygonSegmentationObject(self.active_widget)
        # self.add_object_to_store_widgets(polygon_segmentation_object, self.tool_access.POLYGON_SEGMENTATION)
        # self.active_widget = self.create_contour_widget()
        # self.active_contours.append(obj)
        self.get_information()
        self.image_viewer.overlay(out_path)
