"""Geometry-explicit multi-image packets for controlled lumbar experiments.

No credentials, patient identifiers, DICOM I/O, inference or production defaults.
The caller supplies identity-verified planes and complete immutable memberships.
Coordinates describe displayed pixel centers after any crop/flip/resize; they
must not be copied unchanged from an original image after a display transform.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont

VERSION = '1.0.0'
MAX_IMAGES = 64
MAX_PIXELS = 16_000_000


@dataclass(frozen=True)
class SlicePlane:
    image_id: str
    block_id: str
    member: int
    origin: tuple[float, float, float]
    orientation: tuple[float, float, float, float, float, float]
    spacing: tuple[float, float]  # row, column millimeters
    size: tuple[int, int]  # displayed width, height
    reference_key: str = field(repr=False)

    def __post_init__(self):
        if not self.image_id or not self.block_id or self.member < 1:
            raise ValueError('invalid_plane_identity')
        if len(self.origin) != 3 or len(self.orientation) != 6 or len(self.spacing) != 2:
            raise ValueError('invalid_plane_geometry')
        if not np.isfinite([*self.origin,*self.orientation,*self.spacing]).all():
            raise ValueError('nonfinite_plane_geometry')
        if min(self.spacing) <= 0 or len(self.size) != 2 or min(self.size) < 2:
            raise ValueError('invalid_plane_size_or_spacing')
        row, col = self.axes
        if not np.allclose([row@row,col@col,row@col],[1.,1.,0.],atol=1e-3):
            raise ValueError('invalid_plane_orientation')

    @property
    def axes(self):
        return np.array(self.orientation[:3]), np.array(self.orientation[3:])

    @property
    def normal(self):
        row,col = self.axes
        n = np.cross(row,col)
        return n/np.linalg.norm(n)

    def point(self, x, y):
        row,col = self.axes
        return np.array(self.origin)+row*self.spacing[1]*x+col*self.spacing[0]*y

    def public(self):
        return {'image_id':self.image_id,'block_id':self.block_id,'member':self.member,
                'display_origin_lps_mm':list(self.origin),
                'display_orientation_lps':list(self.orientation),
                'display_pixel_spacing_row_column_mm':list(self.spacing),
                'display_size_width_height':list(self.size)}


def _reference(planes):
    keys={p.reference_key for p in planes}
    if len(keys)!=1 or not next(iter(keys),''):
        raise ValueError('frame_of_reference_unverified')


def build_manifest(planes: Sequence[SlicePlane], expected_members: Mapping[str,Sequence[int]]):
    """Sort inside each parent group by a common physical normal, never merge."""
    if not planes or len(planes)>MAX_IMAGES:
        raise ValueError('spatial_image_budget_exceeded')
    if sum(p.size[0]*p.size[1] for p in planes)>MAX_PIXELS:
        raise ValueError('spatial_pixel_budget_exceeded')
    _reference(planes)
    if len({p.image_id for p in planes})!=len(planes):
        raise ValueError('duplicate_image_identity')
    if {p.block_id for p in planes} != set(expected_members):
        raise ValueError('group_membership_mismatch')
    blocks=[]
    for block, members in expected_members.items():
        rows=[p for p in planes if p.block_id==block]
        if len(set(members))!=len(members) or sorted(p.member for p in rows)!=sorted(members):
            raise ValueError('group_membership_mismatch')
        normal=rows[0].normal
        axis=int(np.argmax(np.abs(normal)))
        desired=-1 if axis==2 else 1
        normal=normal if normal[axis]*desired>0 else -normal
        if any(float(p.normal@normal)<0.999 and float(p.normal@normal)>-0.999 for p in rows):
            raise ValueError('incompatible_planes_in_group')
        ordered=sorted(rows,key=lambda p:float(np.array(p.origin)@normal))
        distances=np.diff([np.array(p.origin)@normal for p in ordered])
        if len(distances) and min(distances)<0.01:
            raise ValueError('duplicate_or_temporal_planes')
        regular=len(distances)<2 or np.allclose(distances,np.median(distances),rtol=.05,atol=.1)
        blocks.append({'block_id':block,'complete_membership':True,
            'original_members':list(members),'ordered_members':[p.member for p in ordered],
            'ordered_image_ids':[p.image_id for p in ordered],
            'order_direction':{0:'patient_right_to_left',1:'patient_anterior_to_posterior',2:'patient_cranial_to_caudal'}[axis],
            'order_normal_lps':normal.round(8).tolist(),
            'adjacent_plane_distances_mm':np.round(distances,5).tolist(),
            'sampling_status':'regular' if regular else 'irregular_or_gapped'})
    return {'schema_version':VERSION,'coordinate_system':'patient_LPS_mm',
        'coordinate_definition':'X increases left, Y posterior, Z superior; origins are displayed pixel centers',
        'sequence_kind':'spatial_not_temporal','shared_frame_of_reference':True,
        'cross_acquisition_registration':'shared_coordinate_frame_only; motion not independently measured',
        'group_boundaries':'Never interpolate or assume continuity across different blocks',
        'anatomical_numbering_verified_by_geometry':False,
        'blocks':blocks,'planes':[p.public() for p in planes]}


def intersection(reference: SlicePlane, other: SlicePlane):
    """Plane intersection in reference display pixels, clipped to both FOVs."""
    _reference([reference,other])
    row,col=reference.axes
    n=other.normal
    a=float(n@row)*reference.spacing[1]
    b=float(n@col)*reference.spacing[0]
    c=float(n@(np.array(reference.origin)-np.array(other.origin)))
    if np.hypot(a/reference.spacing[1],b/reference.spacing[0])<1e-5:
        raise ValueError('parallel_planes')
    w,h=reference.size
    points=[]
    if abs(b)>1e-9:
        for x in (0.,w-1.):
            y=-(a*x+c)/b
            if -1e-7<=y<=h-1+1e-7:points.append(np.array([x,np.clip(y,0,h-1)]))
    if abs(a)>1e-9:
        for y in (0.,h-1.):
            x=-(b*y+c)/a
            if -1e-7<=x<=w-1+1e-7:points.append(np.array([np.clip(x,0,w-1),y]))
    if len(points)<2:raise ValueError('plane_outside_reference_fov')
    first,last=max(((p,q) for p in points for q in points),key=lambda x:np.linalg.norm(x[1]-x[0]))
    other_row,other_col=other.axes
    coords=[]
    for x,y in (first,last):
        delta=reference.point(x,y)-np.array(other.origin)
        coords.append(np.array([delta@other_row/other.spacing[1],delta@other_col/other.spacing[0]]))
    low,high=0.,1.
    for axis,bound in enumerate((other.size[0]-1,other.size[1]-1)):
        start=float(coords[0][axis]); change=float(coords[1][axis]-coords[0][axis])
        if abs(change)<1e-9:
            if not -1e-7<=start<=bound+1e-7:raise ValueError('plane_outside_other_fov')
        else:
            lo,hi=sorted((-start/change,(bound-start)/change))
            low,high=max(low,lo),min(high,hi)
    if high<=low or np.linalg.norm(last-first)<1e-6:
        raise ValueError('plane_outside_other_fov')
    delta=last-first
    return tuple(tuple(float(v) for v in point) for point in (first+low*delta,first+high*delta))


def render_locator(reference, planes, pixels: Image.Image, path: Path):
    """Create an auxiliary plane map; leave original diagnostic pixels intact."""
    if pixels.size!=reference.size:raise ValueError('display_geometry_size_mismatch')
    w,h=pixels.size
    top=70
    canvas=Image.new('RGB',(max(w,360)+340,max(h,110+len(planes)*24)+top),'black')
    canvas.paste(pixels.convert('RGB'),(0,top))
    draw=ImageDraw.Draw(canvas)
    try:font=ImageFont.truetype('arial.ttf',14)
    except OSError:font=ImageFont.load_default()
    draw.text((8,8),'PLANE LOCATOR ONLY | NOT LESION OUTLINES',font=font,fill='white')
    draw.text((8,30),'Reference: '+reference.image_id,font=font,fill='white')
    colors=['#22d3ee','#eab308','#f472b6','#4ade80','#c4b5fd']
    groups=list(dict.fromkeys(p.block_id for p in planes))
    audits=[]; omitted=[]
    for i,p in enumerate(planes,1):
        color=colors[groups.index(p.block_id)%len(colors)]
        try:segment=intersection(reference,p)
        except ValueError as exc:
            omitted.append({'image_id':p.image_id,'reason':str(exc)})
            continue
        draw.line([(x,y+top) for x,y in segment],fill=color,width=2)
        x,y=segment[0]
        draw.text((max(1,min(x,w-22)),max(top,min(y+top,h+top-18))),str(i),font=font,fill=color)
        draw.text((max(w,360)+8,top+i*24),f'{i}: {p.image_id}',font=font,fill=color)
        audits.append({'image_id':p.image_id,'reference_image_id':reference.image_id,
            'segment_reference_display_xy':[list(pt) for pt in segment],
            'segment_patient_lps_mm':[reference.point(*pt).round(5).tolist() for pt in segment]})
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    canvas.save(path,format='PNG')
    return {'status':'complete' if not omitted else 'partial','diagnostic_pixels_modified':False,
        'locator_pixels_annotated':True,
        'reference_image_id':reference.image_id,'intersections':audits,'omitted_intersections':omitted}


def render_correspondence_cards(reference, axial_planes, pixels, directory, *, expected_members):
    """Pair every physical axial plane with one locator and clean enlarged views.

    The sagittal crop covers all intersections in the slab with context padding;
    it is not a lesion ROI. Only the separate locator receives a reference line.
    Original native images must still accompany these auxiliary cards at dispatch.
    """
    axial_planes = list(axial_planes)
    _reference([reference, *axial_planes])
    groups = {p.block_id for p in axial_planes}
    if len(groups) != 1:
        raise ValueError('one_complete_axial_group_required')
    manifest = build_manifest(axial_planes, {next(iter(groups)):list(expected_members)})
    block = manifest['blocks'][0]
    by_id = {p.image_id:p for p in axial_planes}
    ordered = [by_id[i] for i in block['ordered_image_ids']]
    for plane in [reference, *ordered]:
        if plane.image_id not in pixels or pixels[plane.image_id].size != plane.size:
            raise ValueError('display_geometry_size_mismatch')
    segments = [intersection(reference,p) for p in ordered]
    sw,sh = reference.size
    if sw*sh > MAX_PIXELS:
        raise ValueError('spatial_pixel_budget_exceeded')
    ys = [pt[1] for segment in segments for pt in segment]
    pad = max(20,sh*.06)
    crop = (0,max(0,int(np.floor(min(ys)-pad))),sw,min(sh,int(np.ceil(max(ys)+pad))+1))
    if crop[3]-crop[1] < 2:
        raise ValueError('insufficient_sagittal_context')
    try:
        font = ImageFont.truetype('arial.ttf',23)
        small = ImageFont.truetype('arial.ttf',19)
    except OSError:
        font = small = ImageFont.load_default()
    directory = Path(directory)
    filenames = [f'pair_{i:02d}.png' for i in range(1,len(ordered)+1)]
    if any((directory/name).exists() for name in filenames):
        raise FileExistsError('correspondence_card_exists')
    cards = []
    for index,(plane,segment,filename) in enumerate(zip(ordered,segments,filenames),1):
        tag = f'A{index}'
        locator_scale = 300/sw
        locator_size = (300,max(2,round(sh*locator_scale)))
        sag_source = pixels[reference.image_id].convert('RGB').crop(crop)
        sag_size = (600,max(2,round(sag_source.height*600/sag_source.width)))
        aw,ah = plane.size
        axial_size = (600,max(2,round(ah*600/aw)))
        top = 130
        height = top+max(locator_size[1],sag_size[1],axial_size[1])+75
        if height*1580 > MAX_PIXELS:
            raise ValueError('correspondence_canvas_budget_exceeded')
        canvas = Image.new('RGB',(1580,height),'#0b111b')
        draw = ImageDraw.Draw(canvas)
        distance = None if index==1 else block['adjacent_plane_distances_mm'][index-2]
        distance_text = 'First acquired plane in this group' if distance is None else f'{distance:g} mm from previous plane'
        draw.text((20,14),f'{tag} / {len(ordered)} | {plane.image_id} | {distance_text}',font=font,fill='white')
        draw.text((20,50),f'Order: {block["order_direction"]} | Sagittal reference: {reference.image_id}',font=small,fill='#d4dce7')
        draw.text((20,91),f'{tag}: LOCATOR ONLY',font=small,fill='#ffbf47')
        draw.text((350,91),'SAGITTAL SLAB CONTEXT | CLEAN',font=small,fill='white')
        draw.text((980,91),f'{tag}: MATCHING AXIAL | CLEAN',font=small,fill='white')
        canvas.paste(pixels[reference.image_id].convert('RGB').resize(locator_size,Image.Resampling.LANCZOS),(20,top))
        # The line is confined to the locator; labels never enter clean panels.
        draw.line([(20+x*locator_scale,top+y*locator_size[1]/sh) for x,y in segment],fill='#ffbf47',width=2)
        sag_box = (350,top,350+sag_size[0],top+sag_size[1])
        axial_box = (980,top,980+axial_size[0],top+axial_size[1])
        canvas.paste(sag_source.resize(sag_size,Image.Resampling.LANCZOS),sag_box[:2])
        canvas.paste(pixels[plane.image_id].convert('RGB').resize(axial_size,Image.Resampling.LANCZOS),axial_box[:2])
        draw.text((20,height-54),'Orange line = acquired axial plane, not a lesion. Clean panels contain no overlays.',font=small,fill='#d4dce7')
        draw.text((20,height-29),'Enlargement adds no acquired detail. Read the accompanying native slices for diagnosis.',font=small,fill='#d4dce7')
        directory.mkdir(parents=True,exist_ok=True)
        canvas.save(directory/filename,format='PNG')
        cards.append({'pair_id':tag,'file':filename,'axial_image_id':plane.image_id,
            'sagittal_image_id':reference.image_id,'distance_from_previous_mm':distance,
            'locator_line_count':1,'locator_canvas_xyxy':[20,top,320,top+locator_size[1]],
            'segment_reference_display_xy':[list(p) for p in segment],
            'clean_sagittal_panel':{'source_crop_xyxy':list(crop),'display_size':list(sag_size),'canvas_xyxy':list(sag_box)},
            'clean_axial_panel':{'source_crop_xyxy':[0,0,aw,ah],'display_size':list(axial_size),'canvas_xyxy':list(axial_box)}})
    return {'schema_version':'paired-locator-1.0.0','complete_membership':True,
        'block_id':block['block_id'],'order_direction':block['order_direction'],
        'ordered_members':block['ordered_members'],'original_source_pixels_modified':False,
        'clean_panels_annotated':False,'crop_basis':'full slab intersections with sagittal context padding; not lesion selection',
        'native_images_required_at_dispatch':True,'cards':cards}
