import requests
import re
from PacsClient.utils.config import SEGMENTS_PATH
from PacsClient.utils.utils import client_desktop_path


def post_json(self, url: str, payload: dict, timeout: int = 180):
    """POST a JSON payload to the given URL.

    Args:
        url (str): Destination URL.
        payload (dict): JSON-serializable dictionary.
        timeout (int, optional): Request timeout in seconds. Defaults to 180.

    Returns:
        requests.Response: The response object (caller may call raise_for_status()).
    """
    return requests.post(url, json=payload, timeout=timeout)


def download_file(url: str, payload: dict, *, kind: str = "nifti", timeout: int = 300):
    """POST to the server with `?download=<kind>` and save the file to Desktop.

    The server is expected to stream a file (e.g., NIfTI or SEG NRRD) and
    set a `Content-Disposition` header with a filename. The file is saved
    to the user's Desktop (or Home fallback).

    Args:
        url (str): Destination URL (e.g., http://IP:PORT/dicom-info/).
        payload (dict): JSON-serializable payload to include in POST body.
        kind (str, optional): Download kind: "nifti" or "seg". Defaults to "nifti".
        timeout (int, optional): Request timeout in seconds. Defaults to 300.

    Returns:
        pathlib.Path: Path to the saved file.

    Raises:
        requests.HTTPError: If the server returns an error status.
        requests.RequestException: For other network errors.
    """
    with requests.post(url, params={"download": kind}, json=payload, timeout=timeout, stream=True) as r:
        r.raise_for_status()
        cd = r.headers.get("content-disposition", "")
        m = re.search(r'filename="?([^"]+)"?', cd)
        filename = m.group(
            1) if m else f"{payload['params'].get('name', 'poly_seg')}.{('nii.gz' if kind == 'nifti' else 'seg.nrrd')}"
        # filename = "SEG_From_Client_1200.nii.gz"
        # out_path = client_desktop_path() / filename
        out_path = SEGMENTS_PATH / filename
        print(f'output path in server_connection: {out_path}\n')
        with open(out_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
    return out_path