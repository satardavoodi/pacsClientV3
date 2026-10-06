"""Render a private physician review UI with native point corrections, not masks."""
import argparse
import json
from pathlib import Path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    payload=json.loads((args.root/'private-queue.json').read_text())
    for item in payload['items']:
        item.update(calcification_subtype='unreviewed',point_annotations=[],review_notes='',image_quality='unreviewed',box_annotations=[],review_complete=False,microcalcification_assessment='unreviewed')
    payload['box_annotation_semantics']='Physician-confirmed calcification region extents in native crop and source image coordinates, half-open xyxy; not dense masks. Subtype requires explicit review.'
    payload['point_annotation_semantics']='Physician-marked native crop centers; not segmentation masks or bounding boxes.'
    document='''<!doctype html><html lang="en"><meta charset="utf-8"><title>Breast model physician review</title>
<style>body{background:#181818;color:#eee;font:16px system-ui;margin:24px}article{border:1px solid #666;margin:24px 0;padding:16px}
canvas{display:block;width:512px;max-width:none;cursor:crosshair;background:black}.viewport{overflow:auto;max-height:850px;margin:12px 0}
label{display:block;margin:12px 0}select,input,textarea,button{font:inherit;padding:8px}textarea{width:min(700px,90%)}button{margin:4px}
.toolbar{position:sticky;top:0;background:#222;padding:12px;z-index:2}a{color:lightblue}</style>
<h1>Breast model physician review</h1><p>Predictions are unverified. Assess the marked proposal separately from the entire crop.
Benign calcifications also count. Review original morphology at native size. Do not enter patient identifiers in notes.</p>
<p>Drag a rectangle around each true calcification or cluster. Green numbered rectangles are your corrections; red is the model proposal. Draw as many regions as needed. Use the region list to remove an incorrect rectangle.
Optional point mode: click to mark a missed calcification center; click a nearby point again to remove it. Cyan points are your corrections.
Points are not pixel masks. Rejecting the red proposal does not prove the whole crop contains no calcifications.
These are development samples, not an independent test.</p>
<div class="toolbar"><label>Reviewer identifier <input id="reviewer" autocomplete="off"></label>
<button id="save">Export reviewed JSON</button><span id="progress"></span></div><main id="cards"></main><script>const queue='''
    document+=json.dumps(payload).replace('<','\\u003c')+''';
const cacheKey='breast-review-fields-'+queue.checkpoint_sha256;
let saved={};try{saved=JSON.parse(localStorage.getItem(cacheKey)||'{}')}catch(e){}
const fields=['proposal_label','whole_crop','calcification_subtype','point_annotations','review_notes','image_quality','box_annotations','review_complete','microcalcification_assessment','display_window'];
queue.items.forEach(item=>{const prior=saved[item.id];if(prior)fields.forEach(k=>{if(prior[k]!==undefined)item[k]=prior[k]})});
function persist(){const data={};queue.items.forEach(i=>{data[i.id]={};fields.forEach(k=>data[i.id][k]=i[k])});
localStorage.setItem(cacheKey,JSON.stringify(data));
document.getElementById('progress').textContent=queue.items.filter(i=>i.proposal_label!=='unreviewed'||i.whole_crop!=='unreviewed'||i.calcification_subtype!=='unreviewed'||i.image_quality!=='unreviewed'||i.review_notes.trim()||i.point_annotations.length||i.box_annotations?.length).length+' / '+queue.items.length+' assessed';
queue.items.forEach(i=>{const c=document.getElementById('conflict-'+i.id);if(c)c.textContent=i.whole_crop==='reviewed_no_calcification'&&(i.proposal_label==='calcification'||i.point_annotations.length||i.box_annotations?.length)?'Conflicting labels: positive annotations cannot coexist with a calcification-free entire crop.':''});}
function makeReviewBox(start,end,window){const x1=Math.max(0,Math.floor(Math.min(start[0],end[0]))),y1=Math.max(0,Math.floor(Math.min(start[1],end[1]))),x2=Math.min(1024,Math.ceil(Math.max(start[0],end[0]))),y2=Math.min(1024,Math.ceil(Math.max(start[1],end[1])));if(x2-x1<2||y2-y1<2)return null;return {crop_box:[x1,y1,x2,y2],image_box:[x1+window[0],y1+window[1],x2+window[0],y2+window[1]],label:'calcification',subtype:'microcalcification'};}
function select(item,key,label,choices){const l=document.createElement('label');l.textContent=label+' ';
const s=document.createElement('select');choices.forEach(([value,text])=>{const o=document.createElement('option');o.value=value;o.textContent=text;s.append(o)});
s.value=item[key];s.onchange=()=>{item[key]=s.value;persist()};l.append(s);return l;}
queue.items.forEach(item=>{const card=document.createElement('article');const title=document.createElement('h2');title.textContent=item.id;card.append(title);
const a=document.createElement('a');a.href=item.id+'.png';a.target='_blank';a.textContent='Open original crop';card.append(a);
const viewport=document.createElement('div');viewport.className='viewport';const canvas=document.createElement('canvas');canvas.width=1024;canvas.height=1024;
viewport.append(canvas);card.append(viewport);canvas.style.touchAction='none';const image=new Image();const ctx=canvas.getContext('2d');let showBox=true,original=null,low=item.display_window?.low??0,high=item.display_window?.high??255,dragStart=null,dragEnd=null,mode='rectangle';
function draw(){if(!original)return;const output=new ImageData(new Uint8ClampedArray(original.data),1024,1024);for(let n=0;n<output.data.length;n+=4){const v=Math.max(0,Math.min(255,(original.data[n]-low)*255/(high-low)));output.data[n]=output.data[n+1]=output.data[n+2]=v;}ctx.putImageData(output,0,0);if(showBox){const b=item.proposal_box,w=item.crop_window;ctx.strokeStyle='red';ctx.lineWidth=2;ctx.strokeRect(b[0]-w[0],b[1]-w[1],b[2]-b[0],b[3]-b[1])}
ctx.strokeStyle='cyan';ctx.lineWidth=1;item.point_annotations.forEach(p=>{ctx.beginPath();ctx.arc(p.crop_x,p.crop_y,5,0,Math.PI*2);ctx.stroke()});ctx.strokeStyle='#00ff80';ctx.fillStyle='#00ff80';ctx.font='22px system-ui';ctx.lineWidth=2;item.box_annotations.forEach((p,n)=>{const b=p.crop_box;ctx.strokeRect(b[0],b[1],b[2]-b[0],b[3]-b[1]);ctx.fillText(String(n+1),b[0]+3,Math.max(22,b[1]-4))});if(dragStart&&dragEnd){const b=makeReviewBox(dragStart,dragEnd,item.crop_window);if(b)ctx.strokeRect(b.crop_box[0],b.crop_box[1],b.crop_box[2]-b.crop_box[0],b.crop_box[3]-b.crop_box[1]);}}
image.onload=()=>{ctx.drawImage(image,0,0);original=ctx.getImageData(0,0,1024,1024);draw()};image.src=item.id+'.png';
const windowInfo=document.createElement('p');windowInfo.textContent='Display window: '+low+'–'+high+'. Display adjustments do not change source pixels or annotation coordinates.';card.append(windowInfo);
function updateWindow(){item.display_window={low,high};windowInfo.textContent='Display window: '+low+'–'+high+'. Source pixels and annotation coordinates are unchanged.';draw();persist();}
[['Window low',0,254,()=>low,v=>low=Math.min(v,high-1)],['Window high',1,255,()=>high,v=>high=Math.max(v,low+1)]].forEach(([label,min,max,get,set])=>{const l=document.createElement('label');l.textContent=label+' ';const s=document.createElement('input');s.type='range';s.min=min;s.max=max;s.value=get();s.oninput=()=>{set(Number(s.value));updateWindow()};l.append(s);card.append(l)});
const reset=document.createElement('button');reset.textContent='Reset original display';reset.onclick=()=>{low=0;high=255;const sliders=card.querySelectorAll('input[type=range]');sliders[0].value=0;sliders[1].value=255;updateWindow()};card.append(reset);
const modes=document.createElement('label');modes.textContent='Annotation tool ';const modeSelect=document.createElement('select');[['rectangle','Draw numbered rectangles'],['point','Mark individual points']].forEach(([v,t])=>{const o=document.createElement('option');o.value=v;o.textContent=t;modeSelect.append(o)});modeSelect.onchange=()=>mode=modeSelect.value;modes.append(modeSelect);card.append(modes);
const regionList=document.createElement('div');card.append(regionList);
function refreshRegions(){regionList.replaceChildren();item.box_annotations.forEach((box,n)=>{const row=document.createElement('div');row.textContent='Region '+(n+1)+' — '+box.subtype+' ';const remove=document.createElement('button');remove.textContent='Remove region '+(n+1);remove.onclick=()=>{item.box_annotations.splice(n,1);item.review_complete=false;item.microcalcification_assessment='unreviewed';completion.textContent='Finish reviewing this image';refreshRegions();draw();persist()};row.append(remove);regionList.append(row)});}refreshRegions();
function position(e){const b=canvas.getBoundingClientRect();return [Math.max(0,Math.min(1024,(e.clientX-b.left)*1024/b.width)),Math.max(0,Math.min(1024,(e.clientY-b.top)*1024/b.height))];}
canvas.onpointerdown=e=>{if(mode!=='rectangle'||e.button!==0)return;dragStart=position(e);dragEnd=dragStart;canvas.setPointerCapture(e.pointerId);e.preventDefault()};
canvas.onpointermove=e=>{if(dragStart){dragEnd=position(e);draw()}};
canvas.onpointerup=e=>{if(!dragStart)return;const box=makeReviewBox(dragStart,position(e),item.crop_window);dragStart=dragEnd=null;if(box){item.box_annotations.push(box);item.whole_crop='contains_calcification';item.review_complete=false;item.microcalcification_assessment='unreviewed';completion.textContent='Finish reviewing this image';refreshRegions();persist()}draw();};
canvas.onpointercancel=()=>{dragStart=dragEnd=null;draw()};
canvas.onclick=e=>{if(mode!=='point')return;const bounds=canvas.getBoundingClientRect();const x=Math.floor((e.clientX-bounds.left)*1024/bounds.width),y=Math.floor((e.clientY-bounds.top)*1024/bounds.height);
if(x<0||y<0||x>=1024||y>=1024)return;const n=item.point_annotations.findIndex(p=>Math.hypot(p.crop_x-x,p.crop_y-y)<=7);
if(n>=0)item.point_annotations.splice(n,1);else item.point_annotations.push({crop_x:x,crop_y:y,image_x:x+item.crop_window[0],image_y:y+item.crop_window[1]});draw();persist()};
[['Native size',()=>canvas.style.width='1024px'],['Fit preview',()=>canvas.style.width='512px'],['Toggle proposal box',()=>{showBox=!showBox;draw()}],['Clear points',()=>{if(confirm('Clear your marked points for this crop?')){item.point_annotations=[];draw();persist()}}]].forEach(([text,action])=>{const b=document.createElement('button');b.textContent=text;b.onclick=action;card.append(b)});
const completion=document.createElement('button');completion.textContent=item.review_complete?'Review complete':'Finish reviewing this image';completion.onclick=()=>{if(item.image_quality==='unreviewed'){alert('Rate image quality first.');return;}item.review_complete=true;item.microcalcification_assessment=item.image_quality!=='adequate'?'uncertain':item.box_annotations.length||item.point_annotations.length?'present':'absent';item.whole_crop=item.box_annotations.length||item.point_annotations.length?'contains_calcification':'uncertain';item.proposal_label='unreviewed';completion.textContent='Review complete';persist()};card.append(completion);
const qualityChoices=[['unreviewed','Not rated yet'],['adequate','Good / excellent'],['moderate','Moderate'],['unassessable','Not assessable']];
const legacyQuality={too_bright:'Previously rated: too bright',too_dark:'Previously rated: too dark',uncertain:'Previously rated: uncertain'};
if(legacyQuality[item.image_quality])qualityChoices.push([item.image_quality,legacyQuality[item.image_quality]]);
card.append(select(item,'image_quality','Image quality',qualityChoices));
const conflict=document.createElement('p');conflict.id='conflict-'+item.id;conflict.style.color='#ffb080';card.append(conflict);
const l=document.createElement('label');l.textContent='Correction notes';const t=document.createElement('textarea');t.value=item.review_notes;t.oninput=()=>{item.review_notes=t.value;persist()};l.append(t);card.append(l);document.getElementById('cards').append(card)});
document.getElementById('save').onclick=()=>{const reviewer=document.getElementById('reviewer').value.trim();if(!reviewer){alert('Enter a reviewer identifier.');return;}
if(queue.items.some(i=>i.whole_crop==='reviewed_no_calcification'&&(i.proposal_label==='calcification'||i.point_annotations.length||i.box_annotations?.length))){alert('Resolve contradictory no-calcification crop labels and positive proposals/points/rectangles.');return;}
if(queue.items.some(i=>i.whole_crop==='reviewed_no_calcification'&&i.image_quality!=='adequate')){alert('A calcification-free training crop requires an assessable image. Review image quality first.');return;}
queue.items.forEach(i=>i.reviewer=reviewer);queue.status='human_review_export_requires_validation';queue.reviewed_at=new Date().toISOString();
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(queue,null,2)],{type:'application/json'}));a.download='reviewed-deepmica-proposals.json';a.click();URL.revokeObjectURL(a.href)};persist();
</script></html>'''
    (args.root/'review-with-corrections.html').write_text(document,encoding='utf-8')
    print(json.dumps({'status':'private_correction_ui_ready','cards':len(payload['items']),
                      'automatic_training_labels':0,'point_masks_created':0}))


if __name__=='__main__':main()
