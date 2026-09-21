"""Import allowlisted inference sources from a private, read-only server snapshot.

Preserve computation while removing executable demos, comments/docstrings and
machine-specific paths. Never import API servers, training code or patient files.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[2]
FILES = {
    'breast': ['FCOS_INFERENCE.py', 'CASE_DICOM_TO_PNG.py',
               'XGBoost_AR/CREATE_LESION.py', 'XGBoost_AR/SINGLEVIEW_FEATURES.py',
               'XGBoost_AR/TWO_VIEW_FEATURES.py', 'XGBoost_AR/XGBOOST_INFERENCE.py'],
    'bone-age': ['bone_age_inference.py', 'dicom_utils.py'],
}


class Clean(ast.NodeTransformer):
    def visit_Expr(self, node):
        if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return None
        return self.generic_visit(node)

    def visit_If(self, node):
        if '__name__' in ast.unparse(node.test):
            return None
        return self.generic_visit(node)

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            if re.search(r'[A-Za-z]:[\\/]', node.value):
                node.value = ''
            elif re.search(r'[\u0600-\u06ff]', node.value):
                node.value = 'Ambiguous image association; review the source identity.'
        return node


def main(snapshot):
    target = REPO / 'modules/ai_imaging/eagle_eye_engines/vendor'
    hashes = {}
    for engine, names in FILES.items():
        dest = target / engine.replace('-', '_')
        dest.mkdir(parents=True, exist_ok=True)
        for name in names:
            source = snapshot / engine / name
            hashes[f'{engine}/{name}'] = hashlib.sha256(source.read_bytes()).hexdigest()
            tree = Clean().visit(ast.parse(source.read_text(encoding='utf-8-sig')))
            if name == 'FCOS_INFERENCE.py':
                for index, node in enumerate(tree.body):
                    if isinstance(node, ast.FunctionDef) and node.name == 'load_model':
                        tree.body[index] = ast.parse("def load_model():\n    raise RuntimeError('Configure the verified state-dict loader before inference.')").body[0]
                for node in ast.walk(tree):
                    if isinstance(node, ast.keyword) and node.arg == 'weights_backbone':
                        node.value = ast.Constant(None)
            ast.fix_missing_locations(tree)
            text = '# Imported inference implementation; provenance in ../provenance.json.\n' + ast.unparse(tree) + '\n'
            compile(text, name, 'exec')
            (dest / Path(name).name).write_text(text, encoding='utf-8')
    (target / 'provenance.json').write_text(json.dumps({
        'date': '2026-09-21', 'original_sha256': hashes,
        'sources': {'breast': 'pacs:D:/FCOS_AR', 'bone-age': 'wina100:D:/Bone/BoneInference'},
        'transformation': 'AST-normalized; comments/docstrings, main demos and absolute machine paths removed; diagnostic translation; FCOS loader requires a verified adapter and disables backbone downloads.',
        'distribution_rights': 'Owner-supplied project; redistribution review remains pending.'
    }, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('snapshot', type=Path)
    main(parser.parse_args().snapshot)
