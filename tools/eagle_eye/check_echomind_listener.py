"""Check the owned service through its existing private TLS client identity."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server-config', type=Path, required=True)
    args = parser.parse_args()
    from modules.ai_imaging.eagle_eye_remote.client import Client
    config = json.loads(args.server_config.read_text(encoding='utf-8-sig'))
    client = Client({'url': f"https://127.0.0.1:{config['port']}",
        'token_file': config['clients']['development-control'],
        'ca_file': config['certificate'], **config['local_client_tls']})
    capabilities = client.json('/v1/capabilities')
    echo = capabilities.get('echomind') or {}
    passed = (capabilities.get('protocol') == 1
        and len(capabilities.get('modules', [])) == 7
        and echo.get('server_owned_prompts') is True
        and len(echo.get('workflows', [])) == 14)
    print(json.dumps({'passed': passed, 'model_count': len(capabilities.get('modules', [])),
                      'echomind_workflow_count': len(echo.get('workflows', []))}))
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
