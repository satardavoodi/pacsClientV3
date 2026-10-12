"""Explicit elevated provisioning of one approved Eagle login operator SID."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main(argv=None):
    import argparse
    from modules.ai_imaging.eagle_eye_remote.service_admin import provision_login_operator
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--operator-sid", required=True)
    args = parser.parse_args(argv)
    if not Path(args.config).is_absolute():
        parser.error("Use the absolute reviewed Server configuration path.")
    result = provision_login_operator(args.config, args.operator_sid)
    print("Provisioned fixed Eagle service operator rights: 0x%02x" % result["operator_rights"])


if __name__ == "__main__":
    main()
