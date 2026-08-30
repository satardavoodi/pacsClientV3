r"""Generate the encrypted EchoMind center registry without printing secrets.

Normal use reads a JSON file kept OUTSIDE the repository:

    python tools/security/generate_echomind_center_registry.py --input D:\secure\centers.json

Input schema::

    {"centers": [{"center_code": "CENTER", "center_display": "Center",
                  "provider_key": "...", "access_codes": ["..."]}]}

``--legacy-source`` exists only to migrate the former plaintext ``CENTERS`` declaration in
place. It should not be needed after the first protected registry is generated.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = REPO_ROOT / "modules" / "EchoMind" / "center_registry.py"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from modules.EchoMind.credential_envelope import seal_provider_key  # noqa: E402


def _load_json(path: Path) -> list[dict[str, Any]]:
    resolved = path.resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise ValueError("Secret registry input must be stored outside the repository.")
    data = json.loads(resolved.read_text(encoding="utf-8"))
    centers = data.get("centers") if isinstance(data, dict) else None
    if not isinstance(centers, list):
        raise ValueError("Input must contain a centers list.")
    return centers


def _keyword(call: ast.Call, name: str) -> Any:
    for item in call.keywords:
        if item.arg == name:
            return ast.literal_eval(item.value)
    raise ValueError(f"Legacy center record is missing {name}.")


def _load_legacy_source(path: Path) -> list[dict[str, Any]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    value: ast.AST | None = None
    for node in tree.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "CENTERS":
                value = node.value
                break
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "CENTERS" for target in node.targets
        ):
            value = node.value
            break
    if not isinstance(value, (ast.List, ast.Tuple)):
        raise ValueError("Legacy CENTERS declaration was not found.")
    centers: list[dict[str, Any]] = []
    for item in value.elts:
        if not isinstance(item, ast.Call):
            raise ValueError("Legacy CENTERS contains an unsupported entry.")
        centers.append(
            {
                "center_code": _keyword(item, "center_code"),
                "center_display": _keyword(item, "center_display"),
                "provider_key": _keyword(item, "gapgpt_key"),
                "access_codes": _keyword(item, "irannobat_keys"),
            }
        )
    return centers


def _normalize(centers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    seen_access_codes: set[str] = set()
    for raw in centers:
        code = str(raw.get("center_code") or "").strip().upper()
        display = str(raw.get("center_display") or code).strip()
        provider = str(raw.get("provider_key") or raw.get("gapgpt_key") or "").strip()
        access_codes = [str(value or "").strip() for value in raw.get("access_codes", [])]
        access_codes = [value for value in access_codes if value]
        if not code or not display or not provider or not access_codes:
            raise ValueError("Every center needs code, display, provider_key, and access_codes.")
        if code in seen_codes:
            raise ValueError(f"Duplicate center code: {code}")
        duplicates = seen_access_codes.intersection(access_codes)
        if duplicates:
            raise ValueError(f"Duplicate access code detected for center {code}.")
        seen_codes.add(code)
        seen_access_codes.update(access_codes)
        credentials = []
        for access_code in access_codes:
            envelope = seal_provider_key(access_code, provider, code)
            credentials.append(
                {
                    "lookup_digest": envelope.lookup_digest,
                    "kdf_salt_b64": envelope.kdf_salt_b64,
                    "nonce_b64": envelope.nonce_b64,
                    "ciphertext_b64": envelope.ciphertext_b64,
                }
            )
        output.append(
            {
                "center_code": code,
                "center_display": display,
                "credentials": credentials,
            }
        )
    return output


def _render(centers: list[dict[str, Any]]) -> str:
    lines = [
        '"""Generated encrypted EchoMind center registry. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
        "# Plaintext access codes and provider credentials are intentionally absent.",
        "ENCRYPTED_CENTERS = (",
    ]
    for center in centers:
        lines.extend(
            [
                "    {",
                f"        'center_code': {center['center_code']!r},",
                f"        'center_display': {center['center_display']!r},",
                "        'credentials': (",
            ]
        )
        for credential in center["credentials"]:
            lines.extend(
                [
                    "            {",
                    f"                'lookup_digest': {credential['lookup_digest']!r},",
                    f"                'kdf_salt_b64': {credential['kdf_salt_b64']!r},",
                    f"                'nonce_b64': {credential['nonce_b64']!r},",
                    f"                'ciphertext_b64': {credential['ciphertext_b64']!r},",
                    "            },",
                ]
            )
        lines.extend(["        ),", "    },"])
    lines.extend([")", ""])
    return "\n".join(lines)


def _assert_plaintext_absent(text: str, source: list[dict[str, Any]]) -> None:
    for center in source:
        sensitive = [
            str(center.get("provider_key") or center.get("gapgpt_key") or "").strip(),
            *[str(value or "").strip() for value in center.get("access_codes", [])],
        ]
        if any(value and value in text for value in sensitive):
            raise ValueError("Generated registry still contains plaintext credential material.")


def main() -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path)
    source.add_argument("--legacy-source", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    raw = _load_json(args.input) if args.input else _load_legacy_source(args.legacy_source)
    protected = _normalize(raw)
    rendered = _render(protected)
    _assert_plaintext_absent(rendered, raw)

    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp = output.with_suffix(output.suffix + ".tmp")
    tmp.write_text(rendered, encoding="utf-8", newline="\n")
    os.replace(tmp, output)
    print(f"Generated protected registry: {output} ({len(protected)} centers)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
