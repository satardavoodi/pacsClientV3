import re
import os
from PySide6.QtGui import QPixmap

from .abstract_interactorstyle import AbstractInteractorStyle
import vtkmodules.all as vtk
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QDialogButtonBox,
    QMessageBox,
    QProgressDialog,
    QAbstractItemView
)
from PySide6.QtCore import Qt, Signal, QThread
import requests
import json
from PacsClient.pacs.patient_tab.utils import show_message
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QSlider, QDialogButtonBox, QFrame
from pathlib import Path
from urllib.parse import urljoin
from PacsClient.utils.config import SOURCE_PATH, ATTACHMENT_PATH, IMAGES_LOGIN_PATH
from PacsClient.utils.utils import SERVERS_FILE, get_server_url
# write_bone_age_feedback_csv is imported LAZILY inside _save_feedback_csv (below).
# A module-level import pulls in modules.ai_imaging.ai_module_ui.__init__, which
# eagerly loads ai_mainwindow -> service_tab -> overrides -> AIPatientWidget, and
# AIPatientWidget subclasses PacsClient...PatientWidget. When this style module is
# reached DURING PatientWidget's own import (patient_toolbar -> this module), that
# closes an import cycle ("cannot import name 'PatientWidget' from a partially
# initialized module") whenever the import order isn't primed by another test.
from modules.viewer.advanced.viewer_2d import create_text_actor


#base_url = 'http://81.16.117.196:5173'
breast_url = get_server_url("breast") if SERVERS_FILE.exists() else None
boneage_url = get_server_url("boneage") if SERVERS_FILE.exists() else None


def _eagle_worker_lifecycle_enabled() -> bool:
    """AIPACS_EAGLE_WORKER_LIFECYCLE (default ON; =0 = legacy single-ref behaviour).

    Guards the crash-hardening for the Eagle Eye MG/DX server workers:
      * a re-entrancy guard (no duplicate concurrent run for the same study), and
      * keeping every started QThread strongly referenced until it ACTUALLY
        finishes, so it can never be garbage-collected — or deleted with its
        parent — while still running (that is a Qt `qFatal`/abort =
        "the Python process crashes").
    """
    raw = os.environ.get("AIPACS_EAGLE_WORKER_LIFECYCLE")
    if raw is None:
        return True
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


# THE CRASH THIS PREVENTS
# -----------------------
# `AIChatInteractorStyle._current_worker` used to be the ONLY strong reference to
# the running `MamoWorker` / `BoneAgeWorker` QThread, and it was never cleared and
# never `deleteLater()`-d. Two consequences, both of which abort the interpreter
# with "QThread: Destroyed while thread is still running":
#   1. A SECOND Eagle Eye run overwrote `_current_worker = worker` while the first
#      thread was still talking to the server → the first thread's refcount hit 0
#      → Python GC finalized a *running* QThread → Qt calls abort().
#   2. Closing the patient / tab mid-request deleted the style object, dropping the
#      only ref to the running thread — same abort.
# The set below keeps a process-level strong ref to every started worker until it
# emits finished/error, so neither can happen. Same proven idiom as EchoMind's
# `_ORPHANED_WORKERS` (ai_chat_pages.py) and the documented curved-MPR
# deleted-object teardown fix.
_LIVE_AI_WORKERS: set = set()


def _retire_ai_worker(worker) -> None:
    """A worker finished on its own — drop the process-level ref and let Qt free it."""
    try:
        _LIVE_AI_WORKERS.discard(worker)
    except Exception:
        pass
    try:
        worker.deleteLater()
    except Exception:
        pass



class MGCSVSelectionDialog(QDialog):
    """
    Dialog to select existing MG AI analysis CSVs
    """

    def __init__(self, parent, study_uid: str):
        super().__init__(parent)
        self.setWindowTitle("Select AI Analysis Result")
        self.setMinimumSize(720, 420)

        self.study_uid = study_uid
        self.selected_pair = None  # (detection_csv, classification_csv)

        # Dark theme styling
        self.setStyleSheet("""
            QDialog {
                background-color: #1a202c;
            }
            QLabel {
                color: #e2e8f0;
                font-size: 13px;
            }
            QTableWidget {
                background-color: #2d3748;
                color: #e2e8f0;
                border: 1px solid #4a5568;
                border-radius: 6px;
                gridline-color: #4a5568;
            }
            QTableWidget::item {
                padding: 8px;
            }
            QTableWidget::item:selected {
                background-color: #3182ce;
                color: #ffffff;
            }
            QHeaderView::section {
                background-color: #2d3748;
                color: #a0aec0;
                padding: 8px;
                border: none;
                border-bottom: 1px solid #4a5568;
                font-weight: bold;
            }
            QPushButton {
                background-color: #3182ce;
                color: #ffffff;
                border: none;
                border-radius: 6px;
                padding: 8px 20px;
                font-size: 13px;
                min-width: 80px;
            }
            QPushButton:hover {
                background-color: #2c5aa0;
            }
            QPushButton:pressed {
                background-color: #1e4a8a;
            }
            QDialogButtonBox {
                button-layout: 3;
            }
        """)

        root = QVBoxLayout(self)

        info = QLabel("Select an existing AI analysis result to load:")
        root.addWidget(info)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels([
            "Detection CSV",
            "Classification CSV",
            "Threshold"
        ])

        # ✅ درستِ enumها
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.verticalHeader().setVisible(False)

        root.addWidget(self.table)

        btns = QDialogButtonBox(QDialogButtonBox.Open | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        root.addWidget(btns)

        self._populate()

    def _populate(self):
        base_dir = ATTACHMENT_PATH / self.study_uid
        if not base_dir.exists():
            return

        det_files = sorted(base_dir.glob("updated_csv_with_boxes_*.csv"))

        def find_classification(det_name: str) -> str | None:
            suffix = det_name.replace("updated_csv_with_boxes_", "")
            cls = base_dir / f"classification_{suffix}"
            return cls.name if cls.exists() else None

        # regex: threshold + optional version
        pattern = re.compile(r"_(\d+\.\d+)(?:_(\d+))?$")

        for det in det_files:
            cls = find_classification(det.name)
            if cls is None:
                continue

            threshold = ""
            m = pattern.search(det.stem)
            if m:
                thr = m.group(1)
                ver = m.group(2)
                threshold = f"{thr} ({ver})" if ver else thr

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(det.name))
            self.table.setItem(row, 1, QTableWidgetItem(cls))
            self.table.setItem(row, 2, QTableWidgetItem(threshold))

        if self.table.rowCount() > 0:
            self.table.selectRow(0)

    def accept(self):
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "No Selection", "Please select a result first.")
            return

        det = self.table.item(row, 0).text()
        cls = self.table.item(row, 1).text()
        self.selected_pair = (det, cls)
        super().accept()


class AISettingsDialog(QDialog):
    def __init__(self, parent=None, initial: float = 0.45):
        super().__init__(parent)
        self.setWindowTitle("EAGLE EYE Settings")
        self.setModal(True)
        # self.setMinimumWidth(480)
        self.setMinimumSize(720, 480)

        # ---- UI
        root = QVBoxLayout(self)

        # icon_lbl = QLabel(header_row)
        # 1) اگر آیکون داخل qrc است (طبق پروژه‌ات که /icons داری):
        # pix = QPixmap(":/icons/ai_settings.png")  # ← مسیر آیکون خودت
        # 2) یا اگر فایل است:
        # pix = QPixmap(f"{IMAGES_LOGIN_PATH}/icon.jpg")  # ← مسیر آیکون خودت
        #
        # if not pix.isNull():
        #     # DPI-friendly scaling
        #     icon_lbl.setPixmap(pix.scaled(28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        # else:
        #     # fallback اگر پیدا نشد
        #     icon_lbl.setText("🟦")
        #     icon_lbl.setStyleSheet("font-size:22px;")

        # title_lbl = QLabel("AI Analysis Settings", header_row)
        # title_lbl.setStyleSheet("font-size:20px; font-weight:700; color:white;")

        # header_layout.addWidget(icon_lbl, 0, Qt.AlignVCenter)
        # header_layout.addWidget(title_lbl, 0, Qt.AlignVCenter)
        # header_layout.addStretch(1)

        # sub = QLabel("Configure Detection and Classification Parameters")
        # sub.setStyleSheet("color:#d0d7e1; margin-top:2px;")
        # bar = QFrame()
        # bar.setFrameShape(QFrame.HLine)
        # bar.setStyleSheet("color:#235bc0;")

        # Section title
        # sec = QLabel("🔎  Detection Parameters")
        # sec.setStyleSheet("font-weight:600; margin-top:8px;")

        # Slider row
        row = QHBoxLayout()
        label = QLabel("Detection Evaluation Threshold")
        label.setStyleSheet("margin-right:8px;")
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)            # 0.00 ... 1.00
        self.slider.setValue(int(initial * 100))
        self.slider.setTickInterval(5)
        self.slider.setSingleStep(1)
        self.slider.setStyleSheet('''
        background-color: rgba(255, 255, 255, 0.04);
        ''')

        self.val = QLabel(f"{initial:.2f}")
        self.val.setFixedWidth(48)
        self.val.setAlignment(Qt.AlignCenter)

        # row.addWidget(label, 1)
        row.addWidget(self.slider)
        row.addWidget(self.val)

        # Range hint
        hint = QLabel("Range: 0.0 – 1.0  |  Recommended: 0.45")
        hint.setStyleSheet("color:#8aa0bd; font-size:12px;")

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.setStyleSheet('''
        background-color: rgba(255, 255, 255, 0.4);
        ''')
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)

        # Layout build
        # root.addWidget(header_row)
        # root.addWidget(sub)
        # root.addWidget(bar)
        # root.addWidget(sec)

        root.addWidget(label)
        root.addLayout(row)
        # root.addWidget(hint)
        root.addWidget(btns)

        # live update
        self.slider.valueChanged.connect(lambda v: self.val.setText(f"{v/100:.2f}"))

        # پس از:
        eagle_path = str(IMAGES_LOGIN_PATH / 'Eagle-eye2.png')

        # برای QSS بهتر است مسیر اسلش رو به جلو باشد
        _eagle = eagle_path.replace("\\", "/")
        
        # Debug: print path to verify
        print(f"Eagle Eye image path: {_eagle}")

        # [جایگزین کاملِ استایل قبلی]
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            /* بک‌گراند با تصویر عقاب + رنگ پشتیبان */
            QDialog {{
                border-image: url("{_eagle}") 0 0 0 0 stretch stretch;
                background-color: #0f172a;  /* fallback در صورت نبود تصویر */
            }}

            /* متن‌ها شفاف بمانند تا بک‌گراند دیده شود */
            QLabel {{
                color:#e6edf3;
                background: transparent;
            }}

            /* استایل‌های قبلی‌ات (بدون پس‌زمینه‌ی مات) */
            QSlider::groove:horizontal {{
                height:6px; background:#334155; border-radius:4px;
            }}
            QSlider::handle:horizontal {{
                width:18px; height:18px; border-radius:9px; background:#3b82f6; margin:-7px 0;
            }}
            QSlider::sub-page:horizontal {{
                background:#3b82f6; height:6px; border-radius:4px;
            }}
            QDialogButtonBox QPushButton {{
                padding:6px 14px; border-radius:8px;
            }}
        """)

    def value(self) -> float:
        return round(self.slider.value() / 100.0, 2)


class MamoWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, study_uid: str, breast_url: str, headers: dict | None = None,
                 det_eval_thr: float = 0.45, aux_eval_thr: float = 0.75):
        super().__init__()
        self.study_uid = study_uid
        self.breast_url = breast_url
        self.headers = headers
        self.canceled = False
        self.det_eval_thr = float(det_eval_thr)
        self.aux_eval_thr = float(aux_eval_thr)

    def run(self):
        try:
            # URL = f"{self.base_url}/api/v1/run_by_study"
            URL = f"{self.breast_url}/api/v1/run_full_analysis"

            payload = {
                "study_id": self.study_uid,
                "output_name": self.study_uid,
                "det_eval_thr": self.det_eval_thr,   # ← مقدار از دیالوگ
                "aux_eval_thr": self.aux_eval_thr,
                "run_classification": True,
                # "save_npy": True,
                # "save_png16": True

            }
            # (connect, read) — a DEAD host now fails in ~10 s instead of blocking
            # this worker thread for the full 240 s (a "stuck request"). The server
            # analysis itself is allowed the full 240 s read budget.
            resp = requests.post(URL, json=payload, timeout=(10, 240))

            print("============================")
            print(f"[MG][REQ] url={URL}")
            print(f"[MG][REQ] payload={payload}")
            print(f"[MG][RESP] status={resp.status_code} ok={resp.ok}")
            try:
                print(f"[MG][RESP] headers={dict(resp.headers)}")
            except Exception:
                pass
            print("============================")

            if self.canceled:
                raise Exception("Process canceled by user")

            # NOTE: do NOT use resp.raise_for_status() here.
            #
            # raise_for_status() builds its HTTPError from the status LINE only and
            # discards the response BODY — but the body is where the AI server puts
            # the actual cause. A 502 therefore surfaced to the user as a bare
            # "Bad Gateway" while the discarded body said, e.g.:
            #     "PACS request failed: 127.0.0.1:8000 ... actively refused"
            # i.e. the AI server's own PACS backend was down. The user (and we) had
            # no way to see that. Read the body, then raise.
            if not resp.ok:
                detail = ""
                try:
                    detail = (resp.text or "").strip()
                except Exception:
                    pass
                if len(detail) > 600:
                    detail = detail[:600] + "…"
                print(f"[MG][RESP] error body={detail!r}")
                raise Exception(
                    f"AI server returned {resp.status_code} {resp.reason or ''}".strip()
                    + (f" — {detail}" if detail else "")
                )

            try:
                data = resp.json()
                if isinstance(data, dict):
                    print(f"[MG][RESP] json keys={list(data.keys())}")
                else:
                    print(f"[MG][RESP] json type={type(data)}")
                print(f"[MG][RESP] json={data}")
            except ValueError:
                raw = (resp.text or "")
                snippet = raw[:1000]
                raise Exception(f"Invalid JSON response: {snippet}")

            # 2) دانلود فایل‌ها با چک cancel
            out = self.download_updated_csv_and_overlays(self.study_uid, data, self.breast_url, headers=self.headers)

            if self.canceled:
                raise Exception("Process canceled by user")

            self.finished.emit(out)  # خروجی دانلود را emit می‌کند (اختیاری)

        except Exception as e:
            self.error.emit(f"Error during AI process: {str(e)}")

    def _with_threshold_and_no_overwrite(
            self,
            directory: Path,
            filename: str,
            threshold: float
    ) -> Path:
        """
        Add threshold to filename and avoid overwrite by appending _2, _3, ...
        Example:
          classification.csv -> classification_0.45.csv
          classification_0.45.csv (exists) -> classification_0.45_2.csv
        """
        stem = Path(filename).stem
        suffix = Path(filename).suffix

        base_name = f"{stem}_{threshold:.2f}"
        candidate = directory / f"{base_name}{suffix}"

        counter = 2
        while candidate.exists():
            candidate = directory / f"{base_name}_{counter}{suffix}"
            counter += 1

        return candidate

    def download_updated_csv_and_overlays(
            self,
            study_uid,
            resp: dict,
            breast_url: str,
            *,
            headers: dict | None = None
    ) -> dict:
        """
        Download CSV outputs and rename them based on detection threshold
        without overwriting existing files.
        """
        csv_dir = ATTACHMENT_PATH / study_uid
        csv_dir.mkdir(parents=True, exist_ok=True)

        results = {"csv": None, "csv_classification": None, "images": []}

        # -------------------------
        # 1) Detection CSV
        # -------------------------
        detection_resp = resp.get("detection", {})
        if "updated_csv" in detection_resp and "url" in detection_resp["updated_csv"]:
            csv_rel_url = detection_resp["updated_csv"]["url"]
            original_name = detection_resp["updated_csv"].get("path") or "updated_csv_with_boxes.csv"

            csv_url = urljoin(breast_url.rstrip("/") + "/", csv_rel_url.lstrip("/"))

            out_path = self._with_threshold_and_no_overwrite(
                csv_dir,
                original_name,
                self.det_eval_thr
            )

            results["csv"] = str(
                self._save_binary(csv_url, out_path, headers=headers)
            )

        # -------------------------
        # 2) Classification CSV
        # -------------------------
        classification_resp = resp.get("classification")
        if classification_resp and "outputs" in classification_resp:
            outputs = classification_resp.get("outputs", {})
            inference_csv = outputs.get("inference_csv", {})

            csv_rel_url = inference_csv.get("url")
            original_name = inference_csv.get("path") or "classification.csv"

            if csv_rel_url:
                csv_url = urljoin(breast_url.rstrip("/") + "/", csv_rel_url.lstrip("/"))

                out_path = self._with_threshold_and_no_overwrite(
                    csv_dir,
                    original_name,
                    self.det_eval_thr
                )

                results["csv_classification"] = str(
                    self._save_binary(csv_url, out_path, headers=headers)
                )

        return results

    def _save_binary(self, url: str, out_path: Path, headers: dict | None = None, timeout: int = 60):
        """
        نسخه modify‌شده برای چک cancel در حلقه دانلود.
        """
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with requests.get(url, headers=headers, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            with open(out_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 64):
                    if self.canceled:
                        raise Exception("Process canceled by user")
                    if chunk:
                        f.write(chunk)
        return out_path

class BoneAgeWorker(QThread):
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, study_uid: str, sex: str | None, boneage_url: str,
                 headers: dict | None = None, metadata_context: dict | None = None):
        super().__init__()
        self.study_uid = study_uid
        self.sex = sex
        self.boneage = boneage_url
        self.headers = headers or {}
        self.metadata_context = metadata_context or {}
        self.canceled = False
        self.data = None

    def run(self):
        try:

            # endpoint سرویس سن استخوان
            url = f"{self.boneage}/predict"
            payload = {
                "study_id": self.study_uid,
            }
            if self.sex:
                if self.sex in ["m", "M", "male", "Male", "0", 0]:
                    payload["sex"] = "male"
                elif self.sex in ["female", "F", "Female", "1", 1]:
                    payload["sex"] = "female"

            print(f"payload in bone worker {payload}\n")
            print("==========================")
            print(f"bone age url is : {url}")
            print(f"Bone age payload is : {payload}")
            print("==========================")

            # (connect, read) — a dead host fails in ~10 s instead of hanging the
            # worker thread for the full budget (a "stuck request").
            resp = requests.post(
                url,
                json=payload,
                headers=self.headers,
                timeout=(10, 360)
            )
            print("[DX] resp:", resp)

            if self.canceled:
                raise Exception("Process canceled by user")

            resp.raise_for_status()

            try:
                data = resp.json()
                # فقط برای اطمینان که keyها هستن (اگر نباشه KeyError می‌گیری)
                _months = data["predicted_bone_age_months"]
                _years = data["predicted_bone_age_years"]

                self.data = data
                print(f"self.data: {self.data}")
            except ValueError:
                raise Exception(f"Invalid JSON response: {resp.text}")
            except KeyError as e:
                raise Exception(f"Missing expected field in response: {e}")

            if self.canceled:
                raise Exception("Process canceled by user")

            # ✅ ذخیره‌ی نتیجه DX به‌صورت JSON در دیسک (برای کش مثل MG)
            json_path = self._save_result_json(data)
            if json_path is not None:
                data["_json_path"] = str(json_path)

            feedback_csv_path = self._save_feedback_csv(data)
            if feedback_csv_path is not None:
                data["_feedback_csv_path"] = str(feedback_csv_path)

            self.finished.emit(data)

        except Exception as e:
            self.error.emit(f"Error during bone-age AI process: {str(e)}")

    def _save_result_json(self, data: dict):
        """
        ذخیره نتیجه‌ی bone age در یک JSON:
        Canonical keys + legacy compatibility keys.
        مسیر: ATTACHMENT_PATH / <study_uid> / bone_age.json
        """
        try:
            # Canonical, stable schema for DX bone-age results.
            canonical_years = data.get("predicted_bone_age_years")
            canonical_months = data.get("predicted_bone_age_months")
            canonical_sex = data.get("sex")
            if isinstance(canonical_sex, str):
                _sx = canonical_sex.strip().lower()
                if _sx in ("m", "male", "0"):
                    canonical_sex = "male"
                elif _sx in ("f", "female", "1"):
                    canonical_sex = "female"
                else:
                    canonical_sex = _sx or None

            payload = {
                "schema": "bone_age_v1",
                "schema_version": 1,
                # Canonical keys (new)
                "bone_age_years": canonical_years,
                "bone_age_months": canonical_months,
                "sex": canonical_sex,
                # Legacy keys (kept for backward compatibility)
                "predicted_bone_age_months": canonical_months,
                "predicted_bone_age_years": canonical_years,
                # چون این Worker فقط برای DX استفاده می‌شود، مودالیتی را ثابت DX می‌گذاریم
                "modality": "DX",
            }

            out_dir = ATTACHMENT_PATH / self.study_uid
            out_dir.mkdir(parents=True, exist_ok=True)

            out_path = out_dir / "bone_age.json"

            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            print(f"[DX] bone age JSON saved at: {out_path}")
            return out_path

        except Exception as e:
            print(f"[DX] failed to save bone age JSON: {e}")
            return None

    def _save_feedback_csv(self, data: dict):
        try:
            from modules.ai_imaging.ai_module_ui.feedback_schema import (
                write_bone_age_feedback_csv,
            )
            out_dir = ATTACHMENT_PATH / self.study_uid
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = write_bone_age_feedback_csv(
                self.study_uid,
                out_dir,
                self.metadata_context,
                data,
            )
            print(f"[DX] bone age feedback CSV saved at: {out_path}")
            return out_path
        except Exception as e:
            print(f"[DX] failed to save bone age feedback CSV: {e}")
            return None

class AIChatInteractorStyle(AbstractInteractorStyle):
    """
    InteractorStyle for AI tools (MG detection, DX bone age, ...)
    """

    def __init__(self, image_viewer):
        super().__init__(image_viewer)
        self.image_viewer = image_viewer
        self.patient_widget = None
        # نگه داشتن رفرنس به worker ها برای جلوگیری از gc
        self._current_worker = None

    # ------------------------------------------------------------------
    # Eagle Eye worker lifecycle (crash-hardening — see _LIVE_AI_WORKERS)
    # ------------------------------------------------------------------
    def _ai_worker_busy(self) -> bool:
        """True while an Eagle Eye MG/DX worker for this style is still running."""
        w = getattr(self, "_current_worker", None)
        if w is None:
            return False
        try:
            return bool(w.isRunning())
        except RuntimeError:
            # underlying C++ QThread already gone → treat as not busy
            self._current_worker = None
            return False

    def _register_ai_worker(self, worker) -> None:
        """Track a worker so it is never GC'd/deleted while running, and is cleaned
        up exactly once when it finishes.

        Keeps `self._current_worker` (the re-entrancy sentinel) AND a process-level
        strong ref in `_LIVE_AI_WORKERS`. Both are released on finished/error.
        """
        if not _eagle_worker_lifecycle_enabled():
            self._current_worker = worker
            return

        self._current_worker = worker
        _LIVE_AI_WORKERS.add(worker)

        def _cleanup(*_args, _w=worker):
            # runs on the GUI thread (queued from the worker's finished/error)
            if getattr(self, "_current_worker", None) is _w:
                self._current_worker = None
            _retire_ai_worker(_w)

        # connect AFTER the caller's own on_finished/error so the worker object
        # outlives those slots; cleanup only drops references.
        try:
            worker.finished.connect(_cleanup)
            worker.error.connect(_cleanup)
        except Exception as e:
            print(f"[EAGLE] worker cleanup wiring failed (non-fatal): {e}")

    def _save_mg_manifest(self, study_uid: str, det_csv: str, cls_csv: str):
        """
        Save / update MG AI manifest.
        - Keeps history of all runs
        - Updates active pointer
        - Never overwrites previous runs (preserves 'available')
        """
        try:
            out_dir = ATTACHMENT_PATH / study_uid
            out_dir.mkdir(parents=True, exist_ok=True)

            manifest_path = out_dir / "mg_ai_manifest.json"

            # ---- load existing manifest if exists
            if manifest_path.exists():
                try:
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        manifest = json.load(f)
                except Exception:
                    manifest = {}
            else:
                manifest = {}

            available = manifest.get("available", [])

            # ---- extract threshold from filename robustly
            thr = None
            try:
                m = re.search(r"_(\d+\.\d+)(?:_\d+)?\.csv$", det_csv)
                if m:
                    thr = float(m.group(1))
            except Exception:
                thr = None

            new_entry = {
                "detection": det_csv,
                "classification": cls_csv,
                "threshold": thr
            }

            # ---- check if already exists
            exists = any(
                e.get("detection") == det_csv and e.get("classification") == cls_csv
                for e in available
            )

            if not exists:
                available.append(new_entry)

            # ---- update manifest
            manifest["available"] = available
            manifest["active"] = {
                "detection": det_csv,
                "classification": cls_csv
            }

            # ---- atomic write
            tmp_path = manifest_path.with_suffix(".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, ensure_ascii=False, indent=2)
            os.replace(tmp_path, manifest_path)

            print(f"[MG] manifest updated: {manifest_path}")

        except Exception as e:
            print(f"[MG] failed to save manifest: {e}")

    def _live_dialog_parent(self):
        """Return image_viewer.vtk_widget as a dialog parent ONLY if its C++ object
        is still alive, else None (a safe top-level parent).

        The FAST viewer (QtFastContainer) can be deleted between the user triggering
        Eagle Eye and a dialog being shown (a patient switch / viewer rebuild in
        between). Parenting a QMessageBox/dialog to the freed widget raised
        ``RuntimeError: Internal C++ object (QtFastContainer) already deleted`` (seen
        caught in the live logs) — that is the catchable form of the PySide6
        use-after-free that hard-crashed the installed build with an access violation
        (0xc0000005 in pyside6.abi3.dll; other-PC WER, 2026-06-17). Same shiboken6
        liveness idiom as PacsClient/.../_hp_layout.py::_hide_loading_overlay."""
        try:
            vw = getattr(self.image_viewer, 'vtk_widget', None)
            if vw is None:
                return None
            try:
                import shiboken6
                if not shiboken6.isValid(vw):
                    return None
            except ImportError:
                pass
            return vw
        except Exception:
            return None

    def check_status(self, patient_widget):
        """
        Select behavior based on modality
        """
        self.patient_widget = patient_widget

        modality_raw: str = self.image_viewer.metadata_fixed.get("modality", "").upper()

        # ---- MR: lumbar spine visual session (stage 1 - capture only)
        # Handled entirely on the workstation: no server request, no upload, no
        # model. Eagle Eye opens its own 3x1 layout and captures the study; the
        # MG/DX server pipeline below is not involved.
        if modality_raw == "MR":
            if self._open_lumbar_eagle_eye(patient_widget):
                return
            # Only reached when the lumbar path itself could not run (module
            # import or panel switch failed) — the "wrong region" and "user
            # declined" cases are reported inside _open_lumbar_eagle_eye.
            show_message(
                "Eagle Eye could not open the lumbar spine layout for this study.\n"
                "See the log for details."
            )
            return

        if modality_raw not in ["MG", "DX"]:
            show_message("This tool is only available for MG, DX and lumbar MR images.")
            return

        study_uid = self.image_viewer.metadata_fixed["study_uid"]

        # ---- MG: Mammography analysis
        if modality_raw == "MG":
            csv_dir = ATTACHMENT_PATH / study_uid
            existing_csvs = list(csv_dir.glob("updated_csv_with_boxes_*.csv"))

            if existing_csvs:
                msg_box = QMessageBox(self._live_dialog_parent())
                msg_box.setIcon(QMessageBox.Question)
                msg_box.setWindowTitle("MG Analysis")
                msg_box.setText("AI analysis already exists for this study.")
                msg_box.setInformativeText(
                    "Existing analysis results were found.\nWhat would you like to do?"
                )

                btn_rerun = msg_box.addButton("Re-run", QMessageBox.AcceptRole)
                btn_open = msg_box.addButton("Open Results", QMessageBox.ActionRole)
                btn_cancel = msg_box.addButton("Cancel", QMessageBox.RejectRole)

                msg_box.exec()
                clicked = msg_box.clickedButton()

                if clicked == btn_rerun:
                    self.start_mg_process(study_uid)
                    return

                elif clicked == btn_open:
                    dlg = MGCSVSelectionDialog(self._live_dialog_parent(), study_uid)
                    if dlg.exec() == QDialog.Accepted:
                        det_csv, cls_csv = dlg.selected_pair

                        # ✅ ذخیره انتخاب کاربر در manifest
                        self._save_mg_manifest(study_uid, det_csv, cls_csv)

                        self.open_ai_module()
                    return

                return

            # First-time analysis
            self.start_mg_process(study_uid)
            return

        # ---- DX (بدون تغییر)
        elif modality_raw == "DX":
            bone_json = ATTACHMENT_PATH / study_uid / "bone_age.json"
            if bone_json.exists():
                show_message("Bone age analysis already exists.")
                self.open_ai_module()
                return

            self.start_dx_process(study_uid)

    def _open_lumbar_eagle_eye(self, patient_widget) -> bool:
        """Resolve study -> protocol -> series, then open Eagle Eye.

        NOTHING opens until every required viewport has a validated series behind
        it. A sweep started against a half-filled layout produces a session that
        looks complete and is wrong, so the whole pre-flight happens here, before
        the tab exists.

        Facts come from the study's DICOM headers on disk, never from what the
        GUI happens to hold in memory. A real Siemens lumbar study (2026-08-26)
        was refused by an earlier text-only gate because the local DB had an
        empty StudyDescription and NULL series body parts, while every header on
        disk said ``BodyPartExamined = 'LSPINE'``.

        Returns True when the click was handled — including "the user cancelled"
        and "this region is not supported", both of which are reported by the
        resolver itself.
        """
        try:
            from modules.ai_imaging.eagle_eye_lumbar import resolver as ee_resolver
            from modules.ai_imaging.eagle_eye_lumbar import session_request
            from modules.ai_imaging.eagle_eye_lumbar.selection_dialogs import QtPrompts
            from modules.ai_imaging.eagle_eye_modes import normalize_eagle_eye_mode
        except Exception as exc:
            print(f"[EAGLE-EYE] resolver unavailable: {exc}")
            return False

        try:
            context = ee_resolver.ResolveContext.for_widget(patient_widget)
            prompts = QtPrompts(self._live_dialog_parent())
            resolution = ee_resolver.resolve(context, prompts)
        except Exception as exc:
            print(f"[EAGLE-EYE] resolution failed: {exc}")
            import traceback
            traceback.print_exc()
            return False

        if resolution is None:
            print("[EAGLE-EYE] resolution produced no runnable mapping; nothing opened")
            return True  # handled — the resolver already told the user why

        self._log_resolution(resolution)

        mode = normalize_eagle_eye_mode(resolution.protocol.id)
        if mode is None:
            print(f"[EAGLE-EYE] no Eagle Eye mode for protocol {resolution.protocol.id}")
            return False

        try:
            payload = session_request.with_study_context(
                resolution.as_dict(),
                patient_widget,
                resolution.selection,
                candidates=resolution.candidates,
            )
            session_request.stash(resolution.study.study_uid, payload)
            patient_widget._preferred_eagle_eye_mode = mode
            # The chosen study is not necessarily the tab's primary one.
            patient_widget._preferred_eagle_eye_study_uid = resolution.study.study_uid
            patient_widget.switch_right_panel('ai_module')
            return True
        except Exception as exc:
            print(f"[EAGLE-EYE] failed to open the Eagle Eye tab: {exc}")
            return False

    @staticmethod
    def _log_resolution(resolution) -> None:
        """One readable block per run — the first thing to read when a run looks wrong."""
        try:
            print(f"[EAGLE-EYE] study    : {resolution.study.label} "
                  f"({resolution.study.study_uid})")
            print(f"[EAGLE-EYE] protocol : {resolution.protocol.name} "
                  f"[{resolution.detection.confidence}] {resolution.detection.reason}")
            for slot_key in resolution.protocol.slot_keys:
                slot = resolution.selection[slot_key]
                spec = resolution.protocol.slot(slot_key)
                chosen = slot.chosen
                print(f"[EAGLE-EYE]   {spec.label:<14} -> "
                      f"series {chosen.series_number} {chosen.series_description!r} "
                      f"score={slot.score:.1f} confidence={slot.confidence} "
                      f"by={'user' if slot.manual else 'auto'}")
        except Exception as exc:
            print(f"[EAGLE-EYE] could not log the resolution: {exc}")

    def open_ai_module(self):
        if self.patient_widget is not None:
            try:
                metadata_fixed = getattr(self.image_viewer, 'metadata_fixed', {}) or {}
                metadata = getattr(self.image_viewer, 'metadata', {}) or {}
                modality = str(
                    metadata_fixed.get('modality')
                    or metadata.get('series', {}).get('modality', '')
                    or ''
                ).upper()
                if modality == "DX":
                    self.patient_widget._preferred_eagle_eye_mode = "bone_age"
                elif modality == "MG":
                    self.patient_widget._preferred_eagle_eye_mode = "mammography"
            except Exception:
                pass
            self.patient_widget.switch_right_panel('ai_module')  # open AI module

    # --------- MG (Mammography) pipeline  ---------
    def start_mg_process(self, study_uid: str):
        print(f'[MG] start processing on the server for {study_uid}')

        # Re-entrancy guard: never start a second server job while one is still
        # running. Without this, a second run overwrote the ONLY reference to the
        # first (still-running) QThread → GC → "Destroyed while thread is still
        # running" → the Python process aborts. It also prevents duplicate uploads
        # / duplicate server jobs for the same study.
        if _eagle_worker_lifecycle_enabled() and self._ai_worker_busy():
            show_message(
                "An Eagle Eye analysis is already running for this study.\n"
                "Please wait for it to finish before starting another."
            )
            return

        # 1) Threshold dialog
        dlg = AISettingsDialog(self._live_dialog_parent(), initial=0.45)
        if dlg.exec() != QDialog.Accepted:
            return
        det_thr = dlg.value()

        # 2) Loading overlay (consistent with Eagle Eye tab)
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        from PySide6.QtCore import Qt as QtCore_Qt, QTimer
        
        main_window = self.image_viewer.vtk_widget.window()
        loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=main_window,
            title="EAGLE EYE AI Analysis",
            status="Processing Mammography Analysis",
            subtitle="Please wait while the AI analyzes the images"
        )
        loading_overlay.setWindowModality(QtCore_Qt.ApplicationModal)
        
        # Store reference to overlay for cleanup
        overlay_ref = {'overlay': loading_overlay, 'timer': None}

        # 3) Worker
        breast_url = get_server_url('breast')
        if not breast_url:
            show_message(
                "Breast AI service URL is not configured. "
                "Go to Settings > Server Settings > AI Service URL, approve, then save URLs."
            )
            return
        worker = MamoWorker(study_uid, breast_url, det_eval_thr=det_thr)

        def on_finished(out: dict):
            # Cancel safety timeout
            if overlay_ref['timer']:
                overlay_ref['timer'].stop()
            
            # Hide loading overlay safely
            if overlay_ref['overlay']:
                try:
                    AiPacsLoadingOverlay.hide_overlay(overlay_ref['overlay'], fade_ms=0, delay_ms=0)
                except RuntimeError:
                    pass  # Already deleted
                overlay_ref['overlay'] = None

            det_path = out.get("csv")
            cls_path = out.get("csv_classification")

            if not det_path:
                show_message("AI process finished, but no detection output was generated.")
                return

            det_name = Path(det_path).name
            cls_name = Path(cls_path).name if cls_path else None

            # ✅ همیشه run را ثبت کن (حتی بدون classification)
            self._save_mg_manifest(study_uid, det_name, cls_name)

            # ✅ اگر classification نیامده → یعنی هیچ چیزی detect نشده
            if cls_path is None:
                show_message(
                    "AI analysis completed.\n"
                    "ُThis case is normal with the selected threshold."
                )
            else:
                show_message("EAGLE EYE (MG) completed successfully!")

            self.open_ai_module()

        worker.finished.connect(on_finished)
        worker.error.connect(lambda msg: (
            overlay_ref['timer'].stop() if overlay_ref.get('timer') else None,
            AiPacsLoadingOverlay.hide_overlay(overlay_ref['overlay'], fade_ms=0, delay_ms=0) if overlay_ref.get('overlay') else None,
            overlay_ref.update({'overlay': None}),
            show_message(msg)
        ))

        # Safety timeout: force-remove the overlay only AFTER the worker's own read
        # budget (240 s) has elapsed — not before. The old 120 s value hid the modal
        # overlay while the request was STILL running for up to another 120 s, so the
        # UI looked idle and the user re-clicked Eagle Eye → a duplicate run that
        # overwrote the still-running worker → the abort described above. Keep the
        # safety net well beyond the request timeout.
        def force_hide_overlay():
            if overlay_ref.get('overlay'):
                try:
                    print("⚠️ [MG Analysis] Force removing loading after safety timeout")
                    AiPacsLoadingOverlay.hide_overlay(overlay_ref['overlay'], fade_ms=0, delay_ms=0)
                except RuntimeError:
                    pass
                overlay_ref['overlay'] = None

        safety_timer = QTimer()
        safety_timer.setSingleShot(True)
        safety_timer.timeout.connect(force_hide_overlay)
        safety_timer.start(260000)  # 260 s > the worker's 240 s read timeout
        overlay_ref['timer'] = safety_timer

        # Track the worker so it can never be GC'd/deleted while running, and is
        # cleaned up exactly once when it finishes (sets self._current_worker).
        self._register_ai_worker(worker)
        worker.start()

    # --------- DX (Bone Age) pipeline  ---------
    def start_dx_process(self, study_uid: str):
        print(f'[DX] start bone-age processing for {study_uid}')

        # Same re-entrancy guard as MG — a second run must not overwrite the only
        # reference to a still-running worker (→ GC of a live QThread → abort).
        if _eagle_worker_lifecycle_enabled() and self._ai_worker_busy():
            show_message(
                "An Eagle Eye analysis is already running for this study.\n"
                "Please wait for it to finish before starting another."
            )
            return

        # اگر در متادیتا جنسیت لازم است، اینجا بخوان:
        patient_sex = self.image_viewer.metadata_fixed.get('patient_sex', None)
        print(f'patient sex : {patient_sex}\n')
        # اگر key واقعی چیز دیگری است، فقط همین خط را عوض کن.

        metadata_fixed = getattr(self.image_viewer, 'metadata_fixed', None)
        if not isinstance(metadata_fixed, dict):
            metadata_fixed = {}
        metadata = getattr(self.image_viewer, 'metadata', None)
        if not isinstance(metadata, dict):
            metadata = {}
        series_meta = metadata.get('series', {}) if isinstance(metadata.get('series', {}), dict) else {}
        instances = metadata.get('instances') if isinstance(metadata.get('instances'), list) else []
        first_instance = instances[0] if instances and isinstance(instances[0], dict) else {}

        metadata_context = {
            'patient_id': metadata_fixed.get('patient_id') or metadata_fixed.get('patient_code') or metadata.get('patient_id') or metadata.get('PatientID'),
            'patient_code': metadata_fixed.get('patient_code'),
            'series_instance_uid': series_meta.get('series_uid') or series_meta.get('SeriesInstanceUID') or metadata_fixed.get('series_uid') or metadata_fixed.get('series_instance_uid'),
            'sop_instance_uid': first_instance.get('sop_instance_uid') or first_instance.get('SOPInstanceUID'),
        }

        # 1) Loading overlay (consistent with Eagle Eye tab)
        from PacsClient.components.loading_overlay import AiPacsLoadingOverlay
        from PySide6.QtCore import Qt as QtCore_Qt, QTimer
        
        main_window = self.image_viewer.vtk_widget.window()
        loading_overlay = AiPacsLoadingOverlay.show_overlay(
            parent=main_window,
            title="EAGLE EYE AI Analysis",
            status="Estimating Bone Age",
            subtitle="Please wait while the AI analyzes the bone structure"
        )
        loading_overlay.setWindowModality(QtCore_Qt.ApplicationModal)
        
        # Store reference to overlay for cleanup
        overlay_ref = {'overlay': loading_overlay, 'timer': None}
        boneage_url = get_server_url('boneage')
        if not boneage_url:
            try:
                AiPacsLoadingOverlay.hide_overlay(loading_overlay, fade_ms=0, delay_ms=0)
            except RuntimeError:
                pass
            show_message(
                "Bone age AI service URL is not configured. "
                "Go to Settings > Server Settings > AI Service URL, approve, then save URLs."
            )
            return

        worker = BoneAgeWorker(
            study_uid=study_uid,
            sex=patient_sex,
            boneage_url=boneage_url,
            metadata_context=metadata_context,
        )

        def on_finished(data: dict):
            # Cancel safety timeout
            if overlay_ref['timer']:
                overlay_ref['timer'].stop()
            
            # Hide loading overlay safely
            if overlay_ref['overlay']:
                try:
                    AiPacsLoadingOverlay.hide_overlay(overlay_ref['overlay'], fade_ms=0, delay_ms=0)
                except RuntimeError:
                    pass  # Already deleted
                overlay_ref['overlay'] = None

            # بر اساس خروجی واقعی سرور:
            # {'predicted_bone_age_months': 157.56, 'predicted_bone_age_years': 13.13, ...}
            age_months = data.get("predicted_bone_age_months")
            age_years = data.get("predicted_bone_age_years")
            model_used = data.get("model_used")

            if age_years is not None or age_months is not None:
                msg_lines = ["Bone age analysis completed."]

                if age_years is not None:
                    msg_lines.append(f"Estimated age: {age_years:.2f} years")
                if age_months is not None:
                    msg_lines.append(f"({age_months:.1f} months)")
                if model_used:
                    msg_lines.append(f"Model: {model_used}")

                show_message("\n".join(msg_lines))
            else:
                show_message("Bone age analysis completed.")

            # دقیقا مثل منطق MG → بعد از موفقیت، AI module رو باز کن
            self.open_ai_module()

        worker.finished.connect(on_finished)
        worker.error.connect(lambda msg: (
            overlay_ref['timer'].stop() if overlay_ref.get('timer') else None,
            AiPacsLoadingOverlay.hide_overlay(overlay_ref['overlay'], fade_ms=0, delay_ms=0) if overlay_ref.get('overlay') else None,
            overlay_ref.update({'overlay': None}),
            show_message(msg)
        ))
        
        # Safety timeout: Force remove loading after 60 seconds (bone age analysis can take time)
        def force_hide_overlay():
            if overlay_ref.get('overlay'):
                try:
                    print("⚠️ [Bone Age Analysis] Force removing loading after 60s timeout")
                    AiPacsLoadingOverlay.hide_overlay(overlay_ref['overlay'], fade_ms=0, delay_ms=0)
                except RuntimeError:
                    pass
                overlay_ref['overlay'] = None
        
        safety_timer = QTimer()
        safety_timer.setSingleShot(True)
        safety_timer.timeout.connect(force_hide_overlay)
        safety_timer.start(60000)  # 60 seconds for bone age analysis
        overlay_ref['timer'] = safety_timer

        # Track the worker so it can never be GC'd/deleted while running.
        self._register_ai_worker(worker)
        worker.start()



# TODO: new class
