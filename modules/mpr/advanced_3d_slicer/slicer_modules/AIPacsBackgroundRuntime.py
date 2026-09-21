"""Private, authenticated resident runtime. Loaded before Slicer creates its window."""
import importlib.util
import json
import math
import os
from pathlib import Path
import queue
import secrets
import socket
import threading
import time

import qt
import slicer
from slicer.ScriptedLoadableModule import ScriptedLoadableModule


class WindowGuard(qt.QObject):
    def __init__(self):
        super().__init__()
        self.promoted = False
        self.protected = 0

    def eventFilter(self, obj, event):
        if not self.promoted and event.type() in (qt.QEvent.Polish, qt.QEvent.Show):
            if obj.isWidgetType() and obj.isWindow():
                if not obj.testAttribute(qt.Qt.WA_DontShowOnScreen):
                    obj.setProperty("_aipacsResidentHidden", True)
                    obj.setAttribute(qt.Qt.WA_DontShowOnScreen, True)
                    self.protected += 1
        return False

    def promote(self):
        """Restore every window suppressed by this guard, including modal dialogs."""
        self.promoted = True
        slicer.app.removeEventFilter(self)
        # Query live widgets instead of retaining wrappers across startup teardown.
        for widget in slicer.app.topLevelWidgets():
            if not widget.property("_aipacsResidentHidden"):
                continue
            widget.setProperty("_aipacsResidentHidden", False)
            widget.setAttribute(qt.Qt.WA_DontShowOnScreen, False)
            if widget.isVisible():
                # Clearing the attribute alone does not map an already-visible
                # QWidget. Do not hide/re-show QDialogs: hiding ends dialog.exec().
                handle = widget.windowHandle()
                if handle:
                    handle.setVisible(True)


class AIPacsBackgroundRuntime(ScriptedLoadableModule):
    def __init__(self, parent):
        super().__init__(parent)
        parent.title = "AI-PACS Background Runtime"
        parent.hidden = True
        if not os.environ.get("AIPACS_RESIDENT_ROOT"):
            return
        # Module constructors run before the custom main-window constructor.
        self.guard = WindowGuard()
        slicer.app.installEventFilter(self.guard)
        self.runtime = Runtime(self.guard)
        slicer.app.connect("startupCompleted()", self.runtime.initialize)


class Runtime:
    def __init__(self, guard):
        self.guard = guard
        self.role = os.environ["AIPACS_RESIDENT_ROLE"]
        self.root = Path(os.environ["AIPACS_RESIDENT_ROOT"])
        self.token = os.environ.pop("AIPACS_RESIDENT_TOKEN")
        self.commands = queue.Queue(maxsize=4)
        self.completed = queue.Queue()
        self.results = {}
        self.lock = threading.Lock()
        self.active = False
        self.ready = False
        self.timer = qt.QTimer()
        self.timer.setInterval(25)
        self.timer.connect("timeout()", self.poll)
        self.startup = None

    def initialize(self):
        if self.ready:
            return
        window = slicer.util.mainWindow()
        if self.role == "viewer":
            if not window or not window.testAttribute(qt.Qt.WA_DontShowOnScreen):
                slicer.app.exit(1)
                return
            window.hide()
            spec = importlib.util.spec_from_file_location("aipacs_resident_startup", os.environ["AIPACS_RESIDENT_STARTUP"])
            self.startup = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.startup)
            self.startup.install_presentation()
        elif window:
            slicer.app.exit(1)
            return
        self.ready = True
        self.timer.start()
        threading.Thread(target=self.serve, name="Slicer-private-command-server", daemon=True).start()

    def serve(self):
        # Socket/file operations live outside the Slicer event loop.
        try:
            with socket.socket() as server:
                server.bind(("127.0.0.1", 0))
                server.listen(4)
                server.settimeout(1)
                descriptor = {"protocol": 1, "role": self.role, "port": server.getsockname()[1], "pid": os.getpid()}
                temp = self.root / "ready.partial"
                temp.write_text(json.dumps(descriptor), encoding="utf-8")
                temp.replace(self.root / "ready.json")
                while self.ready:
                    try:
                        connection, _ = server.accept()
                    except socket.timeout:
                        continue
                    with connection:
                        connection.settimeout(2)
                        data = bytearray()
                        try:
                            while b"\n" not in data:
                                chunk = connection.recv(min(4096, 65537 - len(data)))
                                if not chunk or len(data) + len(chunk) > 65536:
                                    raise ValueError("Invalid message size")
                                data.extend(chunk)
                            request = json.loads(data.split(b"\n", 1)[0])
                            response = self.accept(request)
                        except Exception:
                            response = {"ok": False, "error": "Invalid or unauthorized runtime request"}
                        try:
                            connection.sendall((json.dumps(response) + "\n").encode())
                        except OSError:
                            continue
        except Exception as exc:
            self.completed.put((None, None, type(exc).__name__))

    def accept(self, request):
        if not isinstance(request, dict) or not secrets.compare_digest(str(request.get("token", "")), self.token):
            raise ValueError("Unauthorized")
        operation = request.get("operation")
        if operation == "ping":
            return {"ok": True, "ready": self.ready, "role": self.role}
        request_id = request.get("id", "")
        if len(request_id) != 32 or any(c not in "0123456789abcdef" for c in request_id):
            raise ValueError("Invalid job ID")
        with self.lock:
            if operation == "result":
                return dict(self.results[request_id], ok=True)
            if operation != "submit":
                raise ValueError("Unsupported operation")
            if request_id in self.results:
                return {"ok": True, "accepted": True}
            command = request.get("command")
            allowed = {"status", "show", "hide", "load_dicom"} if self.role == "viewer" else {"status", "analyze"}
            if command not in allowed or not isinstance(request.get("parameters"), dict):
                raise ValueError("Unsupported command")
            if self.active or not self.commands.empty():
                raise ValueError("Runtime is busy")
            if len(self.results) >= 32:
                self.results.pop(next(iter(self.results)))
            self.results[request_id] = {"state": "running"}
            self.commands.put_nowait((request_id, command, request["parameters"]))
        return {"ok": True, "accepted": True}

    def finish(self, request_id, result=None, error=None):
        with self.lock:
            self.results[request_id] = ({"state": "failed", "error": "Runtime operation failed: " + error}
                                        if error else {"state": "succeeded", "result": result})
            self.active = False

    def poll(self):
        time.sleep(0.001)  # Yield PythonQt's GIL; never pump nested Qt events.
        try:
            request_id, result, error = self.completed.get_nowait()
        except queue.Empty:
            pass
        else:
            if request_id is None:
                slicer.app.exit(1)
                return
            self.finish(request_id, result, error)
        if self.active:
            return
        try:
            request_id, command, parameters = self.commands.get_nowait()
        except queue.Empty:
            return
        self.active = True
        if command == "analyze":
            threading.Thread(target=self.analyze, args=(request_id, parameters), daemon=True).start()
            return
        try:
            result = self.viewer_command(command, parameters)
            self.finish(request_id, result)
        except Exception as exc:
            self.finish(request_id, error=type(exc).__name__)

    def viewer_command(self, command, parameters):
        window = slicer.util.mainWindow()
        if command == "status":
            return {"role": self.role, "pid": os.getpid(), "window_exists": bool(window),
                    "window_visible": bool(window and window.visible), "hidden_before_show": self.guard.protected > 0,
                    "volume_nodes": slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode")}
        if command == "hide":
            window.hide()
            return {"visible": False}
        if command not in {"show", "load_dicom"}:
            raise ValueError("Unsupported viewer command")
        if command == "load_dicom":
            allowed = {"command", "dicom_dir", "layout", "patient_id", "study_id", "series_uid", "window_width",
                       "window_level", "viewport_x", "viewport_y", "viewport_width", "viewport_height"}
            if set(parameters) - allowed or not parameters.get("dicom_dir"):
                raise ValueError("A source directory is required")
            if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode"):
                raise RuntimeError("Close the current Advanced Analysis session before changing its source")
            geometry = [parameters.get("viewport_" + key) for key in ("x", "y", "width", "height")]
            if all(value is not None for value in geometry):
                geometry = [int(value) for value in geometry]
                if any(abs(value) > 32768 for value in geometry) or min(geometry[2:]) < 100:
                    raise ValueError("Invalid viewport geometry")
                self.startup.prepare_window_geometry(geometry)
            elif not self.guard.promoted:
                self.startup.prepare_window_geometry()
        self.guard.promote()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        modal = slicer.app.activeModalWidget()
        if modal and modal.isVisible():
            modal.raise_()
            modal.activateWindow()
        if command == "show":
            return {"visible": True, "pid": os.getpid()}
        from DICOMLib import DICOMUtils
        with DICOMUtils.TemporaryDICOMDatabase() as database:
            DICOMUtils.importDicom(parameters["dicom_dir"], database)
            available = [series for patient in database.patients()
                         for study in database.studiesForPatient(patient) for series in database.seriesForStudy(study)]
            series_uid = parameters.get("series_uid")
            if not series_uid and len(available) == 1:
                series_uid = available[0]
            if not series_uid or series_uid not in available:
                raise ValueError("Select an exact available series; ambiguous folders are not loaded")
            nodes = DICOMUtils.loadSeriesByUID([series_uid])
        volumes = [slicer.mrmlScene.GetNodeByID(node) for node in nodes]
        volumes = [node for node in volumes if node and node.IsA("vtkMRMLScalarVolumeNode")]
        if len(volumes) != 1:
            raise RuntimeError("Requested series did not resolve to one scalar volume")
        volume = volumes[0]
        self.startup.configure_views(parameters.get("layout", "mpr"), volume, parameters)
        self.startup.apply_window_level_if_present(volume, parameters)
        self.startup.store_patient_info(parameters.get("patient_id"), parameters.get("study_id"),
                                        parameters.get("window_width"), parameters.get("window_level"), series_uid)
        self.startup.set_window_title(parameters.get("patient_id"), parameters.get("study_id"))
        return {"loaded": True, "pid": os.getpid(), "volume_node_id": volume.GetID(),
                "dimensions_ijk": list(volume.GetImageData().GetDimensions())}

    def analyze(self, request_id, parameters):
        try:
            import numpy as np
            job_id = parameters.get("job_id", "")
            if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
                raise ValueError("Invalid analysis job")
            directory = (self.root / "jobs" / job_id).resolve()
            if not directory.is_relative_to(self.root.resolve()):
                raise ValueError("Invalid analysis directory")
            array = np.load(directory / "input.npy", allow_pickle=False)
            affine = np.asarray(json.loads((directory / "input.json").read_text())["affine_ras"], dtype=float)
            if (array.ndim != 3 or array.dtype.kind not in "iuf" or array.size > 256 * 1024 * 1024
                    or not np.isfinite(array).all() or affine.shape != (4, 4) or not np.isfinite(affine).all()
                    or not np.allclose(affine[3], [0, 0, 0, 1]) or abs(np.linalg.det(affine[:3, :3])) < 1e-8):
                raise ValueError("Invalid analysis snapshot")
            algorithm = parameters.get("algorithm")
            if algorithm == "threshold":
                import vtk
                from vtk.util.numpy_support import numpy_to_vtk, vtk_to_numpy
                lower, upper = float(parameters["lower"]), float(parameters["upper"])
                if not math.isfinite(lower) or not math.isfinite(upper) or lower > upper:
                    raise ValueError("Invalid threshold bounds")
                image = vtk.vtkImageData()
                image.SetDimensions(*array.shape[::-1])
                image.GetPointData().SetScalars(numpy_to_vtk(np.ascontiguousarray(array).ravel(), deep=True))
                effect = vtk.vtkImageThreshold()
                effect.SetInputData(image)
                effect.ThresholdBetween(lower, upper)
                effect.SetInValue(1)
                effect.SetOutValue(0)
                effect.SetOutputScalarTypeToUnsignedChar()
                effect.Update()
                labels = vtk_to_numpy(effect.GetOutput().GetPointData().GetScalars()).reshape(array.shape).copy()
                result = {"algorithm": algorithm, "voxels": int(np.count_nonzero(labels)),
                          "volume_mm3": float(np.count_nonzero(labels) * abs(np.linalg.det(affine[:3, :3])))}
            elif algorithm == "vertebrae_mr":
                import sys
                bundle = Path(os.environ["AIPACS_OFFLINE_LUMBAR_ROOT"])
                app = str(bundle / "app")
                if app not in sys.path:
                    sys.path.append(app)
                from offline_lumbar.service import run_snapshot
                result, labels = run_snapshot(bundle, directory / "engine", array, affine)
            else:
                raise ValueError("Unsupported analysis algorithm")
            np.save(directory / "labels.npy", labels, allow_pickle=False)
            result.update(job_id=job_id, labels_file=str(directory / "labels.npy"),
                          shape_kji=list(array.shape), affine_ras=affine.tolist(),
                          role="analysis", pid=os.getpid(), clinical_validation="not_established")
            (directory / "result.json").write_text(json.dumps(result), encoding="utf-8")
            self.completed.put((request_id, result, None))
        except Exception as exc:
            self.completed.put((request_id, None, type(exc).__name__))
