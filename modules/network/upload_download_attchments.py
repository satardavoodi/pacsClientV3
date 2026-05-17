import os
import json
import base64
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Union
from .socket_config import get_socket_config
from .socket_token_manager import get_socket_token_manager
# اگر SocketClient را قبلاً داری، این import/کلاس را حذف کن
import socket
from PacsClient.utils.config import ATTACHMENT_PATH
from typing import List, Union, Iterable, Optional
from PacsClient.utils import list_files_in_folder, append_attachments_uploaded
from .attachment_pending_sync import mark_pending, mark_synced, record_attempt

logger = logging.getLogger(__name__)

_UPLOAD_REQUEST_MAX_ATTEMPTS = 2


class SocketClient:
    def __init__(self):
        config = get_socket_config()
        self.host = config.get_socket_host()
        self.port = config.get_socket_port()
        self.socket = None

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))

    def send_request(self, endpoint: str, params: Dict[str, Any]) -> Dict[str, Any]:
        # Create request with token
        request = {"endpoint": endpoint, "params": params}
        token_manager = get_socket_token_manager()
        request = token_manager.add_token_to_request(request)
        
        payload = json.dumps(request, ensure_ascii=False).encode("utf-8")
        self.socket.sendall(len(payload).to_bytes(4, byteorder="big"))
        self.socket.sendall(payload)
        
        # Read response - skip broadcast messages and get actual response
        max_attempts = 10  # Maximum attempts to get a non-broadcast response
        for attempt in range(max_attempts):
            length_buf = self._recvall(4)
            if not length_buf:
                raise RuntimeError("No response length")
            resp_len = int.from_bytes(length_buf, "big")
            data = self._recvall(resp_len)
            if not data:
                raise RuntimeError("No response data")
            
            response = json.loads(data.decode("utf-8"))
            
            # Check if this is a broadcast message (not the actual response)
            if response.get("type") == "broadcast":
                # Skip broadcast messages and read next message
                continue
            
            # This is the actual response
            return response
        
        # If we got here, all messages were broadcasts - return the last one as fallback
        raise RuntimeError("Only broadcast messages received, no actual response")

    def _recvall(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.socket.recv(min(8192, n - len(buf)))
            if not chunk:
                break
            buf += chunk
        return buf

    def disconnect(self):
        if self.socket:
            try:
                self.socket.close()
            finally:
                self.socket = None


# upload attachments

# --- نگاشت پسوند به نوع اتچمنت ---
_EXT2TYPE = {
    # image
    "jpg": "image", "jpeg": "image", "png": "image", "bmp": "image", "gif": "image",
    "webp": "image", "tif": "image", "tiff": "image",
    # audio
    "mp3": "audio", "wav": "audio", "m4a": "audio", "ogg": "audio", "webm": "audio",
    # video
    "mp4": "video", "mkv": "video", "mov": "video", "avi": "video", "webm_vid": "video",
    # document
    "pdf": "document", "doc": "document", "docx": "document",
    "xls": "document", "xlsx": "document", "ppt": "document", "pptx": "document",
    "txt": "document", "csv": "document", "json": "document"
}


def _guess_attachment_type(file_path: str) -> str:
    ext = Path(file_path).suffix.lower().lstrip(".")
    if ext == "webm":
        # webm می‌تواند هم audio باشد هم video؛ پیش‌فرض را audio می‌گذاریم
        return "audio"
    return _EXT2TYPE.get(ext, "document")


def _file_format(file_path: str) -> str:
    return Path(file_path).suffix.lower().lstrip(".") or "bin"


def upload_attachments_for_study(
        study_uid: str,
        attachments_uploaded: str,
        *,
        client: Optional[SocketClient] = None,
        attachment_type: Optional[str] = None,  # اگر None باشد از پسوند حدس می‌زنیم
        description: Optional[str] = None,
        uploaded_by: Optional[str] = None,
        max_size_mb: Optional[int] = None,  # اگر مقدار بدهی، فایل‌های بزرگ‌تر را رد می‌کند
        stop_on_error: bool = False,
        verbose: bool = True,
        # attachments_uploaded: str = None
) -> Dict[str, Any]:
    """
    ارسال یک یا چند فایل به اندپوینت UploadAttachment.

    Parameters
    ----------
    study_uid : str
        UID مطالعه مقصد.
    files : str | List[str]
        مسیر فایل یا لیستی از مسیرها.
    client : SocketClient | None
        اگر از قبل سِشن باز داری بده؛ وگرنه به host/port وصل می‌شود.
    host, port : اتصال به سرور (اگر client ندهی).
    attachment_type : Optional[str]
        'image' | 'audio' | 'video' | 'document' ؛ اگر None باشد از پسوند تشخیص می‌دهیم.
    description : Optional[str]
        توضیح مشترک برای همه فایل‌ها (می‌توانی خالی بگذاری).
    uploaded_by : Optional[str]
        نام کاربر آپلودکننده.
    max_size_mb : Optional[int]
        حداکثر حجم مجاز به مگابایت (None یعنی بدون محدودیت).
    stop_on_error : bool
        اگر True باشد با اولین خطا متوقف می‌شود.
    verbose : bool
        چاپ لاگ ساده.

    Returns
    -------
    Dict[str, Any]
        خلاصه‌ی نتایج شامل موفق‌ها، خطاها و پاسخ سرور برای هر فایل.
    """
    # ✅ دریافت لیست فایل‌های آپلود‌شده از دیتابیس
    attachments_uploaded = attachments_uploaded if attachments_uploaded is not None else ''
    lst_uploaded_raw = attachments_uploaded.split(',') if attachments_uploaded else []
    
    # ✅ نرمال‌سازی مسیرها برای مقایسه درست (از Path استفاده کنیم)
    # تبدیل به absolute path و normalize کردن (حذف / یا \ اضافی)
    uploaded_paths_normalized = set()
    for p in lst_uploaded_raw:
        if p.strip():
            try:
                normalized = str(Path(p).resolve())
                uploaded_paths_normalized.add(normalized)
            except Exception:
                # اگر مسیر نامعتبر بود، نادیده بگیر
                pass
    
    # ✅ پیدا کردن همه فایل‌های موجود در پوشه
    path_study_attachments = ATTACHMENT_PATH / study_uid
    files = list_files_in_folder(path_study_attachments)
    
    # ✅ فیلتر کردن فایل‌های آپلود‌شده (با مقایسه absolute path نرمال‌شده)
    files_to_upload = []
    for file in files:
        try:
            file_normalized = str(Path(file).resolve())
            if file_normalized not in uploaded_paths_normalized:
                files_to_upload.append(file)
        except Exception:
            # اگر مسیر نامعتبر بود، نادیده بگیر
            pass
    
    files = files_to_upload
    
    # 📊 لاگ برای دیباگ (فقط اگر verbose=True)
    if verbose:
        logger.info("%s", "=" * 60)
        logger.info("UPLOAD ATTACHMENTS FOR STUDY: %s", study_uid)
        logger.info("%s", "=" * 60)
        logger.info("Attachment folder: %s", path_study_attachments)
        logger.info("Total files found: %d", len(files) + len(uploaded_paths_normalized))
        logger.info("Already uploaded: %d", len(uploaded_paths_normalized))
        logger.info("New files to upload: %d", len(files))
        if files:
            logger.info("Files to upload:")
            for idx, f in enumerate(files, 1):
                logger.info("%d. %s", idx, Path(f).name)
        logger.info("%s", "=" * 60)

    paths = [files] if isinstance(files, str) else list(files)
    results: List[Dict[str, Any]] = []
    created_client = False

    if not paths:
        return {
            "study_uid": study_uid,
            "total": 0,
            "success": 0,
            "failed": 0,
            "results": [],
        }

    # اتصال
    if client is None:
        client = SocketClient()
        client.connect()
        created_client = True

    try:
        for p in paths:
            p = str(p)
            entry: Dict[str, Any] = {"file": p, "status": "pending"}
            try:
                if not os.path.isfile(p):
                    raise FileNotFoundError("file does not exist")

                size_bytes = os.path.getsize(p)
                if max_size_mb is not None and size_bytes > max_size_mb * 1024 * 1024:
                    raise ValueError(f"file exceeds {max_size_mb} MB")

                with open(p, "rb") as f:
                    raw = f.read()

                b64 = base64.b64encode(raw).decode("utf-8")
                fformat = _file_format(p)
                atype = attachment_type or _guess_attachment_type(p)

                params = {
                    "study_uid": study_uid,
                    "attachment_data": b64,
                    "attachment_type": atype,
                    "file_format": fformat,
                    "file_name": Path(p).name,  # اختیاری؛ سرور اگر لازم بداند خودش نام یونیک می‌سازد
                }
                if description:
                    params["description"] = description
                if uploaded_by:
                    params["uploaded_by"] = uploaded_by

                file_name = Path(p).name
                mark_pending(study_uid, file_name)
                last_exc: Optional[Exception] = None
                resp: Optional[Dict[str, Any]] = None
                for _attempt in range(_UPLOAD_REQUEST_MAX_ATTEMPTS):
                    record_attempt(study_uid, file_name)
                    try:
                        resp = client.send_request("UploadAttachment", params)
                        break
                    except Exception as req_exc:
                        last_exc = req_exc

                if resp is None:
                    raise RuntimeError(str(last_exc) if last_exc else "UploadAttachment request failed")

                entry["response"] = resp

                # Check if response is a broadcast message (should not happen, but handle it)
                if resp.get("type") == "broadcast":
                    # This is a broadcast, not the actual response - treat as error
                    entry["status"] = "error"
                    entry["error"] = "Received broadcast message instead of response"
                    if verbose:
                        logger.warning(
                            "Warning: Received broadcast for %s, treating as error",
                            Path(p).name,
                        )
                elif resp.get("status") == "success":
                    entry["status"] = "success"
                    append_attachments_uploaded(study_uid=study_uid, value=p)  # add path file to db
                    mark_synced(study_uid, file_name)
                else:
                    entry["status"] = "error"
                    entry["error"] = resp.get("error", "unknown server error")
                    mark_pending(study_uid, file_name)
                    if stop_on_error:
                        results.append(entry)
                        break

            except Exception as e:
                entry["status"] = "error"
                entry["error"] = str(e)
                try:
                    mark_pending(study_uid, Path(p).name)
                except Exception:
                    pass
                if stop_on_error:
                    results.append(entry)
                    break
            results.append(entry)

    finally:
        if created_client:
            client.disconnect()

    summary = {
        "study_uid": study_uid,
        "total": len(paths),
        "success": sum(1 for r in results if r.get("status") == "success"),
        "failed": sum(1 for r in results if r.get("status") == "error"),
        "results": results
    }

    return summary

# --- نمونه‌های استفاده ---

# 1) یک فایل
# upload_attachments_for_study(
#     study_uid="1.2.840.113619.2.55.3.12345678.123",
#     files="D:/notes/xray_annotation.png",
#     host="localhost", port=50052,
#     description="یادداشت روی عکس رادیولوژی",
#     uploaded_by="dr_ahmadi"
# )

# 2) چند فایل با تشخیص خودکار نوع از پسوند
# upload_attachments_for_study(
#     study_uid="1.2.840.113619.2.55.3.12345678.123",
#     files=[
#         "D:/voice/voice_note.webm",     # به طور پیش‌فرض audio در نظر گرفته می‌شود
#         "D:/docs/report.pdf",           # document
#         "D:/images/markups.jpg"         # image
#     ],
#     uploaded_by="technician1",
#     max_size_mb=200
# )

# 3) اگر بخواهی نوع را خودت تحمیل کنی (مثلاً webm را به عنوان video بفرستی)
# upload_attachments_for_study(
#     study_uid="1.2.840.113619.2.55.3.12345678.123",
#     files="D:/captures/screen.webm",
#     attachment_type="video"
# )


################################################################################################
# Download attachments

def _ensure_dir(p: Union[str, Path]) -> Path:
    p = Path(p)
    p.mkdir(parents=True, exist_ok=True)
    return p


def download_attachments_for_study(
    study_uid: str,
    *,
    client: Optional[SocketClient] = None,
    attachment_type: str = "",             # "", "image", "audio", "video", "document"
    names: Optional[Iterable[str]] = None, # اگر مقدار بدهید، فقط همان نام‌ها دانلود می‌شوند
    out_dir: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    دانلود اتچمنت‌های یک Study از سرور و ذخیره روی دیسک.

    Parameters
    ----------
    study_uid : str
        UID مطالعه.
    client : SocketClient | None
        اگر از قبل کانکشن باز دارید بدهید؛ در غیر این صورت خودم وصل/قطع می‌شوم.
    attachment_type : str
        فیلتر نوع اتچمنت ("image" | "audio" | "video" | "document" | ""=همه).
    names : Iterable[str] | None
        لیست نام فایل‌هایی که می‌خواهید (Optional). اگر None باشد همه دانلود می‌شوند.
    out_dir : str | Path | None
        مسیر ذخیره‌سازی. پیش‌فرض: ./downloaded_attachments/{study_uid}
    overwrite : bool
        اگر False باشد و فایل وجود داشته باشد، از دانلودِ مجدد صرف‌نظر می‌شود.
    verbose : bool
        چاپ لاگ ساده.

    Returns
    -------
    Dict[str, Any]:
        خلاصه‌ی عملیات شامل مسیر خروجی، تعداد کل/دانلودشده/خطا و جزئیات هر فایل.
    """
    created_client = False
    if client is None:
        client = SocketClient()
        client.connect()
        created_client = True

    try:
        # درخواست لیست به همراه داده‌ها
        resp = client.send_request("GetStudyAttachments", {
            "study_uid": study_uid,
            "attachment_type": attachment_type or "",
            "include_data": True
        })

        if resp.get("status") != "success":
            raise RuntimeError(resp.get("error", "GetStudyAttachments failed"))

        data = resp.get("data", {})
        items: List[Dict[str, Any]] = data.get("attachments", [])

        # فیلتر بر اساس names (در صورت نیاز)
        name_set = set(n.strip() for n in names) if names else None
        if name_set:
            items = [it for it in items if it.get("file_name") in name_set]

        # تعیین پوشه خروجی
        if out_dir is None:
            out_dir = ATTACHMENT_PATH / study_uid
        out_dir = _ensure_dir(out_dir)

        results: List[Dict[str, Any]] = []
        saved_count = 0
        error_count = 0

        for it in items:
            entry = {
                "file_name": it.get("file_name"),
                "attachment_type": it.get("attachment_type"),
                "file_format": it.get("file_format"),
                "file_size": it.get("file_size"),
                "file_exists_on_server": bool(it.get("file_exists", False)),
                "status": "pending",
                "saved_path": None,
                "error": None
            }

            try:
                if not it.get("file_exists", False):
                    raise FileNotFoundError("file not found on server storage")

                b64 = it.get("attachment_data")
                if not b64:
                    raise ValueError("attachment_data is missing (include_data may be False on server)")

                raw = base64.b64decode(b64)
                target_path = out_dir / it["file_name"]

                if target_path.exists() and not overwrite:
                    entry["status"] = "skipped"
                    entry["saved_path"] = str(target_path)
                else:
                    with open(target_path, "wb") as f:
                        f.write(raw)
                    entry["status"] = "saved"
                    entry["saved_path"] = str(target_path)
                    saved_count += 1

                append_attachments_uploaded(study_uid=study_uid, value=entry["saved_path"])  # add path file to db

            except Exception as e:
                entry["status"] = "error"
                entry["error"] = str(e)
                error_count += 1

            results.append(entry)

        summary = {
            "study_uid": study_uid,
            "out_dir": str(out_dir),
            "total": len(items),
            "saved": saved_count,
            "skipped": sum(1 for r in results if r["status"] == "skipped"),
            "failed": error_count,
            "results": results
        }

        return summary

    finally:
        if created_client:
            client.disconnect()


def download_single_attachment(
    study_uid: str,
    file_name: str,
    *,
    client: Optional[SocketClient] = None,
    out_path: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    verbose: bool = True
) -> Path:
    """
    دانلود یک اتچمنت مشخص (با نام فایل) از یک Study.

    - برای یافتن فایل، لیست کامل را از سرور می‌گیریم و در کلاینت فیلتر می‌کنیم.
    """
    res = download_attachments_for_study(
        study_uid,
        client=client,
        attachment_type="",      # همه انواع
        names=[file_name],
        out_dir=(Path(out_path).parent if out_path else None),
        overwrite=overwrite,
        verbose=verbose
    )
    # پیدا کردن رکورد همین فایل
    for r in res["results"]:
        if r["file_name"] == file_name and r["status"] in ("saved", "skipped"):
            # اگر کاربر مسیر خاص داده بود، در صورت نیاز جابه‌جا کنیم
            if out_path:
                src = Path(r["saved_path"])
                dst = Path(out_path)
                if src.resolve() != dst.resolve():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    if not dst.exists() or overwrite:
                        src.replace(dst)
                    return dst
            return Path(r["saved_path"])
    raise FileNotFoundError(f"attachment '{file_name}' not found or failed to download")


######################### async ##########################
# --- Async wrapper (non-blocking for Qt/asyncio) ---
import asyncio
from functools import partial


async def download_attachments_for_study_async(
    study_uid: str,
    *,
    client: Optional[SocketClient] = None,
    attachment_type: str = "",
    names: Optional[Iterable[str]] = None,
    out_dir: Optional[Union[str, Path]] = None,
    overwrite: bool = False,
    verbose: bool = True,
) -> Dict[str, Any]:
    fn = partial(
        download_attachments_for_study,
        study_uid,
        client=client,
        attachment_type=attachment_type,
        names=names,
        out_dir=out_dir,
        overwrite=overwrite,
        verbose=verbose,
    )
    return await asyncio.to_thread(fn)


