"""AI-PACS licensing fingerprint probe.

Captures every RAW input that feeds Key 1 (the machine fingerprint) plus the
derived IDs and current license state, appends a timestamped record to a JSONL
file, and — from the second run onward — reports exactly which raw input changed
since the previous run.

Intended use for the "license lost after reboot" investigation:

    1. Run BEFORE reboot:   python tools\\diagnostics\\license_fingerprint_probe.py
    2. Reboot the machine.
    3. Run AFTER reboot:    python tools\\diagnostics\\license_fingerprint_probe.py

The second run prints a CHANGED / STABLE line for each identifier, pinpointing
the root cause instead of guessing. No secret key or full license hash is
recorded.
"""
import os
import sys
import json
import uuid
from datetime import datetime
from pathlib import Path

# Make the LicenseGenerator package importable regardless of CWD.
_HERE = Path(__file__).resolve()
_ROOT = _HERE.parents[2]
sys.path.insert(0, str(_ROOT / "modules" / "LicenseGenerator"))

import license_manager as lm  # noqa: E402
from license_manager import LicenseManager  # noqa: E402


def _mask(v, keep=6):
    if not v:
        return "<none>"
    s = str(v)
    return s if len(s) <= keep else f"{s[:keep]}…({len(s)} chars)"


def collect() -> dict:
    node = uuid.getnode()
    mac = ":".join(("%012X" % node)[i:i + 2] for i in range(0, 12, 2))
    comps = lm.collect_fingerprint_components()
    mgr = LicenseManager()

    lic_exists = mgr.license_path.exists()
    lic_valid = None
    lic_msg = None
    if lic_exists:
        try:
            lic_valid, lic_msg = mgr.check_license()
        except Exception as exc:
            lic_valid, lic_msg = False, f"error: {exc}"

    return {
        "timestamp": datetime.now().isoformat(),
        # raw stable inputs
        "machine_guid": comps.get("machine_guid"),
        "system_volume_serial": comps.get("system_volume_serial"),
        # raw legacy inputs (the suspected unstable ones)
        "uuid_getnode_int": node,
        "uuid_getnode_mac": mac,
        "computername": os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME")),
        "getnode_is_multicast": bool(node & (1 << 40)),  # locally-administered/random bit
        # derived IDs
        "stable_id": lm._hash_id(lm._derive_stable_raw(comps)) if lm._derive_stable_raw(comps) else None,
        "legacy_id": lm._hash_id(lm._read_legacy_node_raw()),
        "cached_id": lm._read_cached_machine_id(),
        "effective_key1": mgr.get_hardware_id(log=False),
        # license state
        "license_path": str(mgr.license_path),
        "license_file_exists": lic_exists,
        "license_valid": lic_valid,
        "license_message": lic_msg,
    }


def main() -> int:
    record = collect()

    out_dir = _ROOT / "user_data" / "logs"
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        out_dir = Path(lm._compute_app_data_dir())
    out_path = out_dir / "license_fingerprint_probe.jsonl"

    previous = None
    try:
        if out_path.exists():
            lines = [l for l in out_path.read_text(encoding="utf-8").splitlines() if l.strip()]
            if lines:
                previous = json.loads(lines[-1])
    except Exception:
        previous = None

    with out_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    print("=" * 70)
    print("AI-PACS LICENSE FINGERPRINT PROBE")
    print(f"time            : {record['timestamp']}")
    print(f"record appended : {out_path}")
    print("-" * 70)
    print("RAW INPUTS")
    print(f"  machine_guid          : {record['machine_guid']}")
    print(f"  system_volume_serial  : {record['system_volume_serial']}")
    print(f"  uuid.getnode() MAC    : {record['uuid_getnode_mac']}  "
          f"(random/multicast bit set: {record['getnode_is_multicast']})")
    print(f"  COMPUTERNAME          : {record['computername']}")
    print("DERIVED IDs")
    print(f"  stable_id (v2)        : {record['stable_id']}")
    print(f"  legacy_id (v1)        : {record['legacy_id']}")
    print(f"  cached_id             : {record['cached_id']}")
    print(f"  EFFECTIVE Key 1       : {record['effective_key1']}")
    print("LICENSE STATE")
    print(f"  file                  : {record['license_path']}")
    print(f"  exists                : {record['license_file_exists']}")
    print(f"  valid                 : {record['license_valid']}  ({record['license_message']})")

    if previous:
        print("-" * 70)
        print(f"COMPARISON vs previous run ({previous.get('timestamp')})")
        watch = [
            "machine_guid", "system_volume_serial", "uuid_getnode_mac",
            "computername", "stable_id", "legacy_id", "effective_key1",
        ]
        for key in watch:
            before, after = previous.get(key), record.get(key)
            state = "STABLE " if before == after else "CHANGED"
            print(f"  [{state}] {key}: {_mask(before)} -> {_mask(after)}")
        if previous.get("effective_key1") != record.get("effective_key1"):
            print("\n  >>> Key 1 CHANGED across runs. The CHANGED raw input(s) above "
                  "are the root cause.")
        else:
            print("\n  >>> Key 1 is STABLE across runs. Licensing identity preserved.")
    else:
        print("-" * 70)
        print("First run recorded. Reboot, then run this probe again to compare.")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
