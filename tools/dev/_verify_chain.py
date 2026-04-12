"""Verify the forwarding chain at runtime."""
import sys, os, inspect
sys.path.insert(0, r"c:\AI-Pacs codes\aipacs-pydicom2d")

from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget.widget import VTKWidget
from PacsClient.pacs.patient_tab.ui.patient_ui.vtk_widget._vw_scroll import _VWScrollMixin

# 1. widget.py wheelEvent source
src = inspect.getsource(VTKWidget.wheelEvent)
print("=== widget.py wheelEvent source ===")
print(src)

# 2. MRO super() resolution
print("\n=== super() from VTKWidget resolves wheelEvent to ===")
for cls in VTKWidget.__mro__[1:]:
    if "wheelEvent" in cls.__dict__:
        print(f"  -> {cls.__module__}.{cls.__qualname__}.wheelEvent")
        break

# 3. Check mixin wheelEvent properties
mixin_src = inspect.getsource(_VWScrollMixin.wheelEvent)
mixin_lines = mixin_src.split('\n')
print(f"\n=== _VWScrollMixin.wheelEvent ({len(mixin_lines)} lines) ===")
print(f"  calls super().wheelEvent(): {'super().wheelEvent' in mixin_src}")
print(f"  calls event.accept():       {'event.accept()' in mixin_src}")
print(f"  has queue_interactive:       {'queue_interactive_slice_target' in mixin_src}")

# 4. Check keyPressEvent
kp_src = inspect.getsource(_VWScrollMixin.keyPressEvent)
print(f"\n=== _VWScrollMixin.keyPressEvent ===")
print(f"  calls super().keyPressEvent(): {'super().keyPressEvent' in kp_src}")

# 5. Check the widget.py event() override (diagnostic)
if hasattr(VTKWidget, 'event') and 'event' in VTKWidget.__dict__:
    event_src = inspect.getsource(VTKWidget.event)
    print(f"\n=== widget.py event() override ===")
    print(event_src)
else:
    print("\n=== NO event() override in widget.py ===")

# 6. Check that VTKWidget is the same class imported everywhere
from PacsClient.pacs.patient_tab.ui.patient_ui.widget_viewer import VTKWidget as VTK2
from PacsClient.pacs.patient_tab.ui.patient_ui import VTKWidget as VTK3
print(f"\n=== Identity check ===")
print(f"  vtk_widget.widget.VTKWidget is widget_viewer.VTKWidget: {VTKWidget is VTK2}")
print(f"  vtk_widget.widget.VTKWidget is patient_ui.VTKWidget:    {VTKWidget is VTK3}")
print(f"  All same id: {id(VTKWidget)} == {id(VTK2)} == {id(VTK3)}")

# 7. Verify ALL forwarding methods exist in __dict__
print(f"\n=== VTKWidget.__dict__ event methods ===")
for m in ['event', 'wheelEvent', 'keyPressEvent', 'mouseMoveEvent', 'mouseReleaseEvent', 'leaveEvent', 'resizeEvent']:
    present = m in VTKWidget.__dict__
    print(f"  {m}: {'YES' if present else 'NO'}")
