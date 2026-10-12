"""Explicit private console provisioning; never embeds or prints a password."""
import argparse
import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.ai_imaging.eagle_eye_remote.admin_auth import provision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--stdin', action='store_true', help='Read one password line from a private pipe.')
    args = parser.parse_args()
    password = sys.stdin.readline().rstrip('\r\n') if args.stdin else getpass.getpass('Server administrator password: ')
    provision(args.store, args.username, password)
    password = None
    print('Server console identity provisioned; existing accounts are never replaced.')


if __name__ == '__main__':
    main()
