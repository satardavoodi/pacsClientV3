# corner_labels.py
import vtk
from typing import Literal

HJust = Literal["left", "center", "right"]
VJust = Literal["bottom", "middle", "top"]


# class CornerActor:
#     def __init__(self, text: str, norm_x: float, norm_y: float):
#         self.text = text
#         self.norm_x = norm_x
#         self.norm_y = norm_y


class CustomTextActor(vtk.vtkTextActor):
    def __init__(self):
        super().__init__()
        self.default_normx = None
        self.default_normy = None

    def set_default_norms(self, norm_x, norm_y):
        self.default_normx = norm_x
        self.default_normy = norm_y


def make_corner_actor(text: str,
                      norm_x: float,
                      norm_y: float,
                      h_just: HJust = "left",
                      v_just: VJust = "bottom",
                      font_size: int = 14) -> vtk.vtkTextActor:
    """
    Parameters
    ----------

    norm_x, norm_y : float
        مختصات نرمال‌شده (۰..۱) روی ویوپورت.
    h_just : {"left", "center", "right"}
        چسباندن لبهٔ افقی متن به نقطهٔ لنگر.
    v_just : {"bottom", "middle", "top"}
        چسباندن لبهٔ عمودی متن به نقطهٔ لنگر.
    """
    # actor = vtk.vtkTextActor()
    actor = CustomTextActor()
    actor.SetInput(text)

    tp = actor.GetTextProperty()
    tp.SetFontFamilyToArial()
    tp.SetFontSize(font_size)
    tp.SetBold(True)
    tp.SetColor(1, 1, 1)
    tp.SetBackgroundColor(0, 0, 0)
    tp.SetBackgroundOpacity(0.35)

    # توجیه افقی
    if h_just == "left":
        tp.SetJustificationToLeft()
    elif h_just == "center":
        tp.SetJustificationToCentered()
    else:  # "right"
        tp.SetJustificationToRight()

    # توجیه عمودی
    if v_just == "bottom":
        tp.SetVerticalJustificationToBottom()
    elif v_just == "middle":
        tp.SetVerticalJustificationToCentered()
    else:  # "top"
        tp.SetVerticalJustificationToTop()

    actor.GetPositionCoordinate().SetCoordinateSystemToNormalizedViewport()
    actor.SetPosition(norm_x, norm_y)

    actor.set_default_norms(norm_x, norm_y)
    return actor

# # شُرت‌کات برای چهار گوشه
# def bl(text, x=0.02, y=0.02, **kw):
#     return make_corner_actor(text, x, y, "left",  "bottom", **kw)
#
# def tl(text, x=0.02, y=0.98, **kw):
#     return make_corner_actor(text, x, y, "left",  "top",    **kw)
#
# def br(text, x=0.98, y=0.02, **kw):
#     return make_corner_actor(text, x, y, "right", "bottom", **kw)
#
# def tr(text, x=0.98, y=0.98, **kw):
#     return make_corner_actor(text, x, y, "right", "top",    **kw)
