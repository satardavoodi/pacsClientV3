"""
License Manager Module
License and authentication management.

Machine fingerprint (Key 1) is derived from STABLE Windows identifiers
(registry MachineGuid + system-volume serial) so it does NOT change across
reboots, network changes, VPN / virtual (Hyper-V, VMware) adapters, docking,
or temporary loss of internet.

Backward compatibility: the previous scheme derived the fingerprint from
uuid.getnode() (a MAC address, which is unstable across reboots). Licenses
activated under that legacy scheme are still accepted during validation, so
existing working machines do NOT need to re-activate. Only machines whose
legacy fingerprint was drifting need to activate once onto the stable ID.

Diagnostics: dedicated licensing logging is written to <appdata>/AIPacs/
license.log (and mirrored to the standard 'aipacs.license' logger). No secret
key or full license hash is ever logged.
"""
import os
import sys
import json
import hashlib
import uuid
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

# Fingerprint scheme version:
#   v1 = legacy  : SHA256(uuid.getnode()-MAC + COMPUTERNAME)   [UNSTABLE]
#   v2 = stable  : SHA256(MachineGuid | system-volume-serial)  [STABLE]
FINGERPRINT_SCHEME_VERSION = 2

# Shared HMAC-style secret. Centralised here (was duplicated across methods).
# NOTE: this is a symmetric secret shipped in the client; replacing it with an
# asymmetric signature is tracked separately in the licensing security review.
# It is intentionally UNCHANGED so all previously issued Key 2 values stay valid.
SECRET_KEY = "AIPACS-SECRET-KEY-2026-V1"

_LICENSE_LOGGER_NAME = "aipacs.license"
_LICENSE_LOG_FILENAME = "license.log"
_MACHINE_ID_CACHE_FILENAME = "machine_id.dat"
_FINGERPRINT_STATE_FILENAME = "fingerprint_state.json"


# --------------------------------------------------------------------------- #
# App-data location (shared by class + module-level logger)
# --------------------------------------------------------------------------- #

def _compute_app_data_dir() -> Path:
    """Persistent per-user data dir for AIPacs (same location as license.dat)."""
    if os.name == "nt":
        base = os.getenv("APPDATA") or os.path.expanduser("~")
        base_dir = Path(base) / "AIPacs"
    else:
        base_dir = Path.home() / ".aipacs"
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return base_dir


# --------------------------------------------------------------------------- #
# Dedicated licensing logger (never logs secrets / full hashes)
# --------------------------------------------------------------------------- #

_license_logger: Optional[logging.Logger] = None


def _mask(value: Optional[str], keep: int = 4) -> str:
    """Mask an identifier for logging: show a short prefix only."""
    if not value:
        return "<none>"
    s = str(value)
    if len(s) <= keep:
        return s[0] + "***"
    return f"{s[:keep]}…({len(s)} chars)"


def get_license_logger() -> logging.Logger:
    """Lazily configure a rotating file logger under <appdata>/AIPacs/license.log.

    Also propagates to the standard logging tree so that, when running inside
    the main application, licensing events land in the app's normal handlers.
    """
    global _license_logger
    if _license_logger is not None:
        return _license_logger

    logger = logging.getLogger(_LICENSE_LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = True  # also flow into the app's root/handlers

    already = any(
        isinstance(h, RotatingFileHandler)
        and getattr(h, "_aipacs_license_handler", False)
        for h in logger.handlers
    )
    if not already:
        try:
            log_path = _compute_app_data_dir() / _LICENSE_LOG_FILENAME
            handler = RotatingFileHandler(
                log_path, maxBytes=512 * 1024, backupCount=3, encoding="utf-8"
            )
            handler._aipacs_license_handler = True  # type: ignore[attr-defined]
            handler.setFormatter(
                logging.Formatter(
                    "%(asctime)s %(levelname)s [license] %(message)s"
                )
            )
            logger.addHandler(handler)
        except Exception:
            # Logging must never break licensing.
            pass

    _license_logger = logger
    return logger


def _log() -> logging.Logger:
    return get_license_logger()


# --------------------------------------------------------------------------- #
# Stable hardware-identifier readers
# --------------------------------------------------------------------------- #

def _read_machine_guid() -> Optional[str]:
    """Windows registry MachineGuid — stable across reboots, unique per OS
    install. Changes only on OS reinstall / clone. On non-Windows, fall back to
    /etc/machine-id."""
    if os.name != "nt":
        for p in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
            try:
                val = Path(p).read_text(encoding="utf-8").strip()
                if val:
                    return val
            except Exception:
                continue
        return None
    try:
        import winreg  # local import: Windows only
        # KEY_WOW64_64KEY so a 32-bit frozen build reads the 64-bit registry view.
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        )
        try:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
        finally:
            winreg.CloseKey(key)
        val = str(val).strip()
        return val or None
    except Exception as exc:
        _log().warning("MachineGuid read failed: %s", exc)
        return None


def _read_system_volume_serial() -> Optional[str]:
    """Serial number of the system volume (e.g. C:). Stable across reboots;
    changes only if the volume is reformatted."""
    if os.name != "nt":
        return None
    try:
        import ctypes  # local import: Windows only
        system_drive = (os.environ.get("SystemDrive", "C:") + "\\")
        serial = ctypes.c_uint(0)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(system_drive),
            None, 0,
            ctypes.byref(serial),
            None, None, None, 0,
        )
        if ok:
            return f"{serial.value:08X}"
        _log().warning("GetVolumeInformationW returned 0 for %s", system_drive)
    except Exception as exc:
        _log().warning("volume serial read failed: %s", exc)
    return None


def _read_legacy_node_raw() -> str:
    """Legacy (v1) raw fingerprint input: MAC via uuid.getnode() + COMPUTERNAME.
    UNSTABLE — kept ONLY so legacy activations still validate."""
    mac = uuid.getnode()
    mac_str = ":".join(("%012X" % mac)[i:i + 2] for i in range(0, 12, 2))
    computer_name = os.environ.get(
        "COMPUTERNAME", os.environ.get("HOSTNAME", "unknown")
    )
    return f"{mac_str}-{computer_name}"


def _hash_id(raw: str) -> str:
    """Derive the 32-char hardware ID from a raw fingerprint string."""
    return hashlib.sha256(raw.encode()).hexdigest()[:32].upper()


# --------------------------------------------------------------------------- #
# Fingerprint composition + diagnostics
# --------------------------------------------------------------------------- #

def collect_fingerprint_components() -> Dict[str, Optional[str]]:
    """Return the raw stable identifiers used to build Key 1 (for diagnostics
    and change-detection). Values here are machine identifiers, NOT secrets."""
    return {
        "machine_guid": _read_machine_guid(),
        "system_volume_serial": _read_system_volume_serial(),
    }


def _derive_stable_raw(components: Dict[str, Optional[str]]) -> Optional[str]:
    """Compose the stable raw fingerprint string from available components.
    Requires at least one stable component to succeed."""
    parts: List[str] = []
    if components.get("machine_guid"):
        parts.append("MG:" + str(components["machine_guid"]))
    if components.get("system_volume_serial"):
        parts.append("VS:" + str(components["system_volume_serial"]))
    if not parts:
        return None
    return "|".join(parts)


def _machine_id_cache_path() -> Path:
    return _compute_app_data_dir() / _MACHINE_ID_CACHE_FILENAME


def _read_cached_machine_id() -> Optional[str]:
    try:
        p = _machine_id_cache_path()
        if p.exists():
            val = p.read_text(encoding="utf-8").strip()
            if len(val) == 32:
                return val.upper()
    except Exception:
        pass
    return None


def _write_cached_machine_id(machine_id: str) -> None:
    try:
        _machine_id_cache_path().write_text(machine_id, encoding="utf-8")
    except Exception:
        pass


def _fingerprint_state_path() -> Path:
    return _compute_app_data_dir() / _FINGERPRINT_STATE_FILENAME


def record_and_diff_components(components: Dict[str, Optional[str]]) -> List[str]:
    """Compare current fingerprint components against the last recorded set and
    log which component(s) changed. Returns the list of changed component names.

    Only short hashes of each component are persisted (never the raw values), so
    the state file itself leaks nothing useful. This is what lets a future
    licensing failure be traced to the *specific* input that changed."""
    changed: List[str] = []
    current = {
        k: (hashlib.sha256(v.encode()).hexdigest()[:12] if v else None)
        for k, v in components.items()
    }
    previous: Dict[str, Optional[str]] = {}
    try:
        p = _fingerprint_state_path()
        if p.exists():
            previous = json.loads(p.read_text(encoding="utf-8")) or {}
    except Exception:
        previous = {}

    if previous:
        for key, cur in current.items():
            prev = previous.get(key)
            if prev != cur:
                changed.append(key)
                _log().warning(
                    "fingerprint component changed: %s prev=%s now=%s",
                    key, _mask(prev, 6), _mask(cur, 6),
                )
    try:
        _fingerprint_state_path().write_text(
            json.dumps(current), encoding="utf-8"
        )
    except Exception:
        pass
    return changed


# --------------------------------------------------------------------------- #
# License manager
# --------------------------------------------------------------------------- #

class LicenseManager:
    """Application license manager."""

    LICENSE_FILE = "license.dat"

    def __init__(self):
        self.app_data_dir = _compute_app_data_dir()
        self.license_path = self.app_data_dir / self.LICENSE_FILE

    def _get_app_data_dir(self) -> Path:
        """Retained for backward compatibility with older callers."""
        return _compute_app_data_dir()

    # ----- machine fingerprint (Key 1) ------------------------------------- #

    def get_hardware_id(self, *, log: bool = True) -> str:
        """Return the STABLE 32-char machine ID used to build Key 1.

        Order of preference:
          1. Stable composite (MachineGuid + system-volume serial)  [v2]
          2. Previously cached stable ID (if hardware reads fail transiently)
          3. Legacy uuid.getnode()+COMPUTERNAME fingerprint          [v1, unstable]
        """
        components = collect_fingerprint_components()
        if log:
            record_and_diff_components(components)

        stable_raw = _derive_stable_raw(components)
        if stable_raw:
            machine_id = _hash_id(stable_raw)
            _write_cached_machine_id(machine_id)
            if log:
                _log().info(
                    "hardware_id derived scheme=v2-stable id=%s "
                    "machine_guid=%s volume_serial=%s",
                    _mask(machine_id), _mask(components.get("machine_guid")),
                    _mask(components.get("system_volume_serial")),
                )
            return machine_id

        cached = _read_cached_machine_id()
        if cached:
            if log:
                _log().warning(
                    "stable identifiers unavailable; using cached machine_id "
                    "id=%s (reboot stability preserved via cache)",
                    _mask(cached),
                )
            return cached

        legacy_id = _hash_id(_read_legacy_node_raw())
        if log:
            _log().warning(
                "no stable identifiers and no cache; falling back to LEGACY "
                "MAC-based fingerprint id=%s — this value can change across "
                "reboots and may require re-activation",
                _mask(legacy_id),
            )
        return legacy_id


    def _current_candidate_ids(self) -> List[Tuple[str, str]]:
        """Ordered (machine_id, scheme_label) candidates accepted for THIS
        machine during validation. Enables legacy licenses to keep working
        without re-activation."""
        candidates: List[Tuple[str, str]] = []
        seen = set()

        def _add(mid: Optional[str], label: str) -> None:
            if mid and mid not in seen:
                seen.add(mid)
                candidates.append((mid, label))

        components = collect_fingerprint_components()
        stable_raw = _derive_stable_raw(components)
        if stable_raw:
            _add(_hash_id(stable_raw), "v2-stable")
        _add(_read_cached_machine_id(), "v2-cached")
        _add(_hash_id(_read_legacy_node_raw()), "v1-legacy")
        return candidates

    def format_hardware_id(self, hardware_id: str) -> str:
        """Format hardware ID as ABCD-EFGH-... (4-char groups)."""
        parts = [hardware_id[i:i + 4] for i in range(0, len(hardware_id), 4)]
        return "-".join(parts)

    # ----- key generation (company/manager side) --------------------------- #

    def generate_license_key(self, hardware_id: str, days: int = 365) -> str:
        """Generate Key 2 for a given Key 1 (hardware_id) and duration.

        The generator hashes exactly the hardware_id string it is given; it does
        NOT recompute the fingerprint. Deterministic for a fixed
        (hardware_id, expiry_date)."""
        expiry_date = (datetime.now() + timedelta(days=days)).strftime("%Y%m%d")
        data = f"{hardware_id}|{expiry_date}|{SECRET_KEY}"
        license_hash = hashlib.sha256(data.encode()).hexdigest()[:24].upper()
        return f"{expiry_date}-{license_hash}"

    def format_license_key(self, license_key: str) -> str:
        """Format Key 2 as EXPIRY-ABCD-EFGH-... for readability."""
        if "-" not in license_key:
            return license_key
        parts = license_key.split("-", 1)
        if len(parts) != 2:
            return license_key
        date_part, hash_part = parts[0], parts[1]
        hash_parts = [hash_part[i:i + 4] for i in range(0, len(hash_part), 4)]
        return f"{date_part}-{'-'.join(hash_parts)}"


    # ----- validation ------------------------------------------------------ #

    def validate_license(
        self, license_key: str, hardware_id: Optional[str] = None
    ) -> Tuple[bool, str]:
        """Validate Key 2.

        If ``hardware_id`` is given (e.g. the generator verifying its own
        output), validation is against exactly that ID. Otherwise every accepted
        candidate for the current machine is tried (stable, cached, legacy), so
        licenses issued under the old scheme keep working."""
        try:
            raw = license_key.replace(" ", "").replace("-", "")
            if len(raw) < 32:
                _log().warning("validation failed: malformed key len=%d", len(raw))
                return False, "Invalid license key format"

            expiry_str = raw[:8]
            provided_hash = raw[8:].upper()

            try:
                expiry_date = datetime.strptime(expiry_str, "%Y%m%d")
            except ValueError:
                _log().warning("validation failed: bad expiry '%s'", expiry_str)
                return False, "Invalid license expiry date"

            if datetime.now() > expiry_date:
                _log().warning("validation failed: expired on %s", expiry_str)
                return False, "License has expired"

            if hardware_id is not None:
                norm = hardware_id.replace(" ", "").replace("-", "").upper()
                candidates = [(norm, "explicit")]
            else:
                candidates = self._current_candidate_ids()

            for mid, label in candidates:
                data = f"{mid}|{expiry_str}|{SECRET_KEY}"
                expected = hashlib.sha256(data.encode()).hexdigest()[:24].upper()
                if provided_hash == expected:
                    days_remaining = (expiry_date - datetime.now()).days
                    _log().info(
                        "validation OK scheme=%s id=%s days_remaining=%d",
                        label, _mask(mid), days_remaining,
                    )
                    return True, f"License is valid. {days_remaining} days remaining"

            _log().warning(
                "validation failed: key does not match this machine "
                "(tried %d candidate ID(s): %s)",
                len(candidates),
                ", ".join(f"{lbl}:{_mask(mid)}" for mid, lbl in candidates),
            )
            return False, "License key is not valid for this system"
        except Exception as exc:
            _log().error("validation error: %s", exc)
            return False, f"Error validating license: {str(exc)}"


    # ----- persistence ----------------------------------------------------- #

    def save_license(self, license_key: str) -> Tuple[bool, str]:
        """Validate and persist Key 2 to <appdata>/AIPacs/license.dat."""
        is_valid, message = self.validate_license(license_key)
        if not is_valid:
            _log().warning("save_license refused: %s", message)
            return False, message

        try:
            machine_id = self.get_hardware_id(log=False)
            data = {
                "license_key": license_key.replace(" ", "").replace("-", ""),
                "hardware_id": machine_id,
                "fingerprint_scheme": FINGERPRINT_SCHEME_VERSION,
                "activated_at": datetime.now().isoformat(),
            }
            self.license_path.write_text(json.dumps(data), encoding="utf-8")
            _log().info(
                "license saved path=%s id=%s scheme=v%d",
                self.license_path, _mask(machine_id), FINGERPRINT_SCHEME_VERSION,
            )
            return True, message
        except Exception as exc:
            _log().error("save_license write failed: %s", exc)
            return False, f"Error saving license: {str(exc)}"

    def check_license(self) -> Tuple[bool, str]:
        """Load the stored license and validate it against this machine."""
        if not self.license_path.exists():
            _log().info("check_license: no license file at %s", self.license_path)
            return False, "No license found. Please activate."

        try:
            data = json.loads(self.license_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, KeyError) as exc:
            _log().error("check_license: corrupt license file: %s", exc)
            return False, "Corrupt license file"
        except Exception as exc:
            _log().error("check_license: cannot read license file: %s", exc)
            return False, f"Error checking license: {str(exc)}"

        license_key = data.get("license_key", "")
        if not license_key:
            _log().warning("check_license: license file has no key")
            return False, "Invalid license file"

        stored_id = data.get("hardware_id")
        _log().info(
            "check_license: stored license found scheme=v%s stored_id=%s",
            data.get("fingerprint_scheme", "1"), _mask(stored_id),
        )
        return self.validate_license(license_key)
