"""Exercise research review UI state transitions with synthetic browser state."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def run_script(fragment, setup, assertion):
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for review UI behavior checks')
    source = (Path(__file__).resolve().parents[3] /
              'tools/eagle_eye/enhance_calcification_review.py').read_text()
    if fragment == 'persist':
        code = source.split('function persist()', 1)[1].split('function select(', 1)[0]
        code = 'function persist()' + code
    else:
        code = source.split("document.getElementById('save').onclick=", 1)[1].split(';persist();', 1)[0]
        code = 'const exportReview=' + code + ';'
    result = subprocess.run([node, '-e', setup + code + assertion], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_notes_only_review_counts_as_assessed():
    item = dict(id='synthetic', proposal_label='unreviewed', whole_crop='unreviewed',
                calcification_subtype='unreviewed', image_quality='unreviewed',
                point_annotations=[], review_notes='Image is too bright')
    setup = "const queue={items:" + json.dumps([item]) + "};const cacheKey='test';const fields=[];"
    setup += "const progress={};const localStorage={setItem(){}};const document={getElementById(id){return id==='progress'?progress:null}};"
    run_script('persist', setup, "persist();if(progress.textContent!=='1 / 1 assessed')throw Error('Lost notes-only progress');")


def test_unassessable_crop_cannot_export_as_negative():
    item = dict(proposal_label='not_calcification', whole_crop='reviewed_no_calcification',
                image_quality='unassessable', point_annotations=[])
    setup = 'const queue={items:' + json.dumps([item]) + '};let message="";'
    setup += "const alert=s=>message=s;const document={getElementById(){return {value:'synthetic-reviewer'}},createElement(){throw Error('Unsafe export')}};"
    run_script('export', setup, "exportReview();if(!message.includes('assessable'))throw Error('Missing quality gate');")


def test_rectangle_reverse_drag_maps_native_source_coordinates():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js required')
    source = (Path(__file__).resolve().parents[3] /
              'tools/eagle_eye/enhance_calcification_review.py').read_text()
    function = 'function makeReviewBox' + source.split('function makeReviewBox', 1)[1].split('\nfunction select(', 1)[0]
    code = function + "\nconst b=makeReviewBox([100,200],[20,30],[500,600]);if(JSON.stringify(b.crop_box)!=='[20,30,100,200]'||JSON.stringify(b.image_box)!=='[520,630,600,800]')throw Error('Wrong coordinates');if(makeReviewBox([5,5],[5,5],[0,0])!==null)throw Error('Click became region');const c=makeReviewBox([-5,-9],[1200,1400],[0,0]);if(JSON.stringify(c.crop_box)!=='[0,0,1024,1024]')throw Error('Out of bounds');"
    result = subprocess.run([node, '-e', code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
