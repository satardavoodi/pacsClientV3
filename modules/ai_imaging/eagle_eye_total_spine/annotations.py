"""Shared source-coordinate measurement overlays and aspect-correct export."""
import math
import numpy as np
from .geometry import endplate_points
from .assessment import body_centers

BLUE = '#38bdf8'
YELLOW = '#fbbf24'
GREEN = '#4ade80'
PINK = '#f472b6'


def perpendicular_construction(upper, lower, shape, spacing, slot=0, count=1, lower_color=YELLOW):
    """Extend actual endplates to feet of perpendiculars meeting inside the film.

    Choose the intersection first, then project it onto both infinite endplate
    lines. This changes only construction placement, never source landmarks or
    measured tilt. All feasibility checks and right angles use physical spacing.
    """
    h, w = shape
    scale = np.array([spacing[1], spacing[0]], dtype=float)
    extent = np.array([w-1, h-1])*scale
    pairs = [np.asarray(p, dtype=float)*scale for p in (upper, lower)]
    directions = [(p[1]-p[0])/np.linalg.norm(p[1]-p[0]) for p in pairs]
    normals = [np.array([-d[1], d[0]]) for d in directions]
    center = np.mean(pairs, axis=(0, 1))
    radius = min(min(extent)*.06, extent[1]/(max(1,count)*5))
    preferred_y = center[1] if count==1 else extent[1]*(slot+.5)/count-radius*.5
    preferred_x = extent[0]*(.78 if center[0]<extent[0]/2 else .22)
    targets = [np.array([x,y]) for x in np.linspace(.12*extent[0],.88*extent[0],13)
               for y in [np.clip(preferred_y,2*radius,extent[1]-2*radius), *np.linspace(.12*extent[1],.88*extent[1],11)]]
    targets.sort(key=lambda p: abs(p[0]-preferred_x)/extent[0]+2*abs(p[1]-preferred_y)/extent[1])
    def inside(p): return bool((p>=0).all() and (p<=extent).all())
    for origin in targets:
        feet = [p[0]+d*np.dot(origin-p[0],d) for p,d in zip(pairs,directions)]
        if any(not inside(f) or np.linalg.norm(origin-f)<radius*.4 for f in feet): continue
        tips = [origin+n*radius*1.5 for n in normals]
        if not all(inside(t) for t in tips): continue
        lines=[]; squares=[]
        def add(a,b,color,role):
            lines.append(dict(points=[(a/scale).tolist(),(b/scale).tolist()],color=color,
                              dashed=False,handles=False,role=role))
        feasible=True
        for pair,d,n,foot,tip,color in zip(pairs,directions,normals,feet,tips,(BLUE,lower_color)):
            # Extend from the real endplate through the perpendicular foot.
            t=np.dot(foot-pair[0],d); length=np.linalg.norm(pair[1]-pair[0])
            add(pair[0]+min(0,t)*d,pair[0]+max(length,t)*d,color,'endplate_extension')
            add(foot,origin,color,'perpendicular'); add(origin,tip,color,'angle_ray')
            toward=n*(1 if np.dot(origin-foot,n)>=0 else -1)
            tangent=d*(1 if np.dot(pair.mean(0)-foot,d)>=0 else -1)
            size=min(radius*.22,np.linalg.norm(origin-foot)*.2,length*.2)
            a=foot+toward*size; b=a+tangent*size; c=foot+tangent*size
            if not all(inside(p) for p in (a,b,c)): feasible=False; break
            add(a,b,color,'right_angle'); add(b,c,color,'right_angle')
            squares.append([(v/scale).tolist() for v in (a,b,c)])
        if not feasible: continue
        lo,hi=sorted(math.atan2(n[1],n[0]) for n in normals)
        arc=[origin+radius*np.array([math.cos(t),math.sin(t)]) for t in np.linspace(lo,hi,41)]
        if not all(inside(p) for p in arc): continue
        for a,b in zip(arc,arc[1:]): add(a,b,'#ffffff','angle_arc')
        return dict(lines=lines,normals=[[(origin/scale).tolist(),(t/scale).tolist()] for t in tips],
                    angle_deg=math.degrees(hi-lo),label_at=(origin/scale).tolist(),
                    feet=[(f/scale).tolist() for f in feet],intersection=(origin/scale).tolist(),
                    mode='source endplate perpendiculars',right_angles=squares)
    # Rare cropped/extreme geometry may not admit an in-film construction.
    # Keep that exceptional diagram explicitly distinguished from source lines.
    result=_translated_perpendicular_construction(upper,lower,shape,spacing,slot,count,lower_color)
    result['mode']='translated perpendiculars (source construction does not fit)'
    return result


def _translated_perpendicular_construction(upper, lower, shape, spacing, slot=0, count=1, lower_color=YELLOW):
    """Linked, translated perpendicular construction wholly within the image.

    Work in physical coordinates, including the arc and right-angle markers.
    Translation is explicit: no claim that the two source endplates intersect here.
    Both normals use the same rotation, retaining severe angles above 90 degrees.
    """
    h, w = shape
    scale = np.array([spacing[1], spacing[0]], dtype=float)
    extent = np.array([w-1, h-1])*scale
    radius = min(min(extent)*.12, extent[1]/(max(1, count)*3.8))
    source_center = np.mean([upper, lower], axis=(0, 1))*scale
    y = source_center[1] if count == 1 else extent[1]*(slot+.5)/count-radius*.5
    origin = np.array([extent[0]*(.78 if source_center[0] < extent[0]/2 else .22),
                       np.clip(y, radius*2, extent[1]-radius*2)])
    lines, normals, angles = [], [], []
    def add(a, b, color, dashed=False):
        lines.append(dict(points=[(a/scale).tolist(), (b/scale).tolist()], color=color, dashed=dashed, handles=False))
    for pair, color in ((upper, BLUE), (lower, lower_color)):
        pair = np.asarray(pair)*scale
        d = pair[1]-pair[0]; d = d/np.linalg.norm(d)
        normal = np.array([-d[1], d[0]])
        end = origin+normal*radius*1.4
        normals.append([(origin/scale).tolist(), (end/scale).tolist()])
        add(origin, end, color)
        add(end-d*radius*.3, end+d*radius*.3, color)
        # A square at the translated endplate documents the 90-degree relation.
        corner = end-normal*radius*.15+d*radius*.15
        add(end-normal*radius*.15, corner, color)
        add(corner, end+d*radius*.15, color)
        angles.append(math.atan2(normal[1], normal[0]))
    lo, hi = sorted(angles)
    arc = [origin+radius*.65*np.array([math.cos(t), math.sin(t)]) for t in np.linspace(lo, hi, 41)]
    for a, b in zip(arc, arc[1:]): add(a, b, '#ffffff')
    return dict(lines=lines, normals=normals, angle_deg=math.degrees(hi-lo),
                label_at=(origin/scale).tolist())


def extended_line(pair, shape):
    h, w = shape
    a, b = np.asarray(pair, dtype=float)
    d = b-a
    candidates = []
    for axis, limit in ((0, 0), (0, w-1), (1, 0), (1, h-1)):
        if abs(d[axis]) < 1e-9: continue
        p = a + (limit-a[axis])/d[axis]*d
        if -.001 <= p[0] <= w-1+.001 and -.001 <= p[1] <= h-1+.001:
            candidates.append(p.tolist())
    if len(candidates) < 2: return pair.tolist()
    return [min(candidates, key=lambda p:p[0]), max(candidates, key=lambda p:p[0])]


def overlay_primitives(view, measured):
    shape = view['image']['pixels'].shape
    lines, labels = [], []
    centers = body_centers(view)
    for slot, curve in enumerate(measured['curves']):
        number = curve.get('curve_number', slot+1)
        for level, plate, color in ((curve['upper'], 'superior', BLUE),
                                     (curve['lower'], curve['lower_endplate'], BLUE if curve['lower_endplate']=='superior' else YELLOW)):
            pair = endplate_points(view['points'][level], plate)
            lines.append(dict(points=pair.tolist(), color=color, dashed=False))
            labels.append(dict(at=pair.mean(0).tolist(), color=color,
                text=f'C{number} {level} {plate}: {curve["cobb_deg"]:.1f} deg'))
        construction = perpendicular_construction(
            endplate_points(view['points'][curve['upper']], 'superior'),
            endplate_points(view['points'][curve['lower']], curve['lower_endplate']),
            shape, view['image']['spacing'], slot,
            len(measured['curves']), BLUE if curve['lower_endplate']=='superior' else YELLOW)
        lines.extend(construction['lines'])
        labels.append(dict(at=construction['label_at'], color='#ffffff',
            text=f'C{number} {curve["cobb_deg"]:.1f} deg | {construction["mode"]}'))
        apex = curve['apex'] or curve.get('coronal_assessment', {}).get('apex_csvl_candidate') or curve['apex_candidate']
        if apex:
            levels = apex.split('/')
            if all(k in centers for k in levels):
                at = np.mean([centers[k].mean(0) for k in levels], axis=0).tolist()
                status = 'reader' if curve['apex'] else 'candidate'
                labels.append(dict(at=at, color=GREEN, text=f'C{number} Apex {apex} ({status})'))
        assessment = curve.get('coronal_assessment', {})
        candidate = assessment.get('apex_csvl_candidate')
        offset = assessment.get('apex_csvl_offset')
        if candidate in centers and offset:
            at = centers[candidate].mean(0).tolist()
            x = view['markers']['Sacral center'][0]
            lines.append(dict(points=[[x, at[1]], at], color=GREEN, dashed=True))
            labels.append(dict(at=at, color=GREEN,
                text=f'CSVL offset ({candidate} proposal): {offset["value"]:+.2f} {offset["unit"]}'))
        for key in ('stable', 'neutral', 'last_touched'):
            selected = assessment.get('reader', {}).get(key)
            level = selected or assessment.get(key+'_candidate')
            if level in centers:
                body = centers[level]
                for a, b in ((0, 1), (1, 3), (3, 2), (2, 0)):
                    lines.append(dict(points=[body[a].tolist(), body[b].tolist()], color=PINK, dashed=not bool(selected)))
                labels.append(dict(at=centers[level].mean(0).tolist(), color=PINK,
                    text=f'C{number} {key.replace("_", " ")} {level} ({"reader" if selected else "proposal"})'))
    for level, pedicles in view.get('pedicles', {}).items():
        if level in centers:
            body = centers[level]
            # Body center and thirds are visual guides, not an automatic grade.
            for fraction in (1/6, 1/3, 1/2, 2/3, 5/6):
                top = body[0]+fraction*(body[1]-body[0])
                bottom = body[2]+fraction*(body[3]-body[2])
                lines.append(dict(points=[top.tolist(), bottom.tolist()], color=PINK, dashed=True))
        for side, p in pedicles.items():
            x, y = p; size = min(shape)*.006
            for a, b in (([max(0,x-size),y], [min(shape[1]-1,x+size),y]),
                         ([x,max(0,y-size)], [x,min(shape[0]-1,y+size)])):
                lines.append(dict(points=[a,b], color=PINK, dashed=False))
            labels.append(dict(at=p, color=PINK, text=f'{level} {side.replace("_", " ")} pedicle (reader)'))
    h, w = shape
    for name, p in view.get('markers', {}).items():
        title = 'CSVL' if name == 'Sacral center' else ('C7 plumb line' if name == 'C7 center' else 'S1 reference')
        color = GREEN if name == 'Sacral center' else PINK
        lines.append(dict(points=[[p[0], 0], [p[0], h-1]], color=color, dashed=True))
        labels.append(dict(at=[p[0], max(0, p[1]-h*.025)], color=color, text=title))
    if measured['balance']:
        markers = view['markers']; a = markers['C7 center']
        b = markers['Sacral center' if view['image']['projection']=='coronal' else 'S1 posterior superior']
        lines.append(dict(points=[[a[0], a[1]], [b[0], a[1]]], color=PINK, dashed=False))
        m = measured['balance']
        labels.append(dict(at=[(a[0]+b[0])/2, a[1]], color=PINK,
                           text=f'{m["name"]}: {m["value"]:+.2f} {m["unit"]}'))
    for rotation in measured['rotations']:
        level = rotation['level']
        if level in centers:
            labels.append(dict(at=centers[level].mean(0).tolist(), color=PINK,
                text=f'{level} Nash-Moe {rotation["grade"]} {rotation["direction"]} (reader)'))
    return dict(lines=lines, labels=labels)


def annotated_image(view, measured, *, reviewed=False):
    """Render off-thread. The image panel preserves recorded row/column aspect."""
    from PIL import Image, ImageDraw, ImageFont
    image = view['image']; h, w = image['pixels'].shape
    row, col = image['spacing']; aspect = col/row
    scale = min(1500/(w*aspect), 2400/h)
    iw, ih = max(1, round(w*aspect*scale)), max(1, round(h*scale))
    panel = 650; header = 86
    height = max(ih+header, 240+len(measured['curves'])*440+len(measured['rotations'])*36)
    canvas = Image.new('RGB', (iw+panel, height), '#0c1522')
    raster = Image.fromarray(image['pixels']).convert('RGB').resize((iw, ih), Image.Resampling.LANCZOS)
    canvas.paste(raster, (0, header)); draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=21); small = ImageFont.load_default(size=17)
    large = ImageFont.load_default(size=28)
    state = 'MEASUREMENT LANDMARKS REVIEWED' if reviewed else 'DRAFT - VERIFY LANDMARKS AND NUMBERING'
    draw.text((20, 12), 'TOTAL SPINE | '+image['projection'].upper(), fill='white', font=large)
    draw.text((20, 50), state, fill=YELLOW, font=small)
    def mapped(p): return (p[0]*iw/w, header+p[1]*ih/h)
    overlay = overlay_primitives(view, measured)
    for line in overlay['lines']:
        a, b = map(mapped, line['points'])
        if line['dashed']:
            n = max(1, int(math.dist(a,b)/12))
            for k in range(0,n,2):
                u=np.asarray(a)+(np.asarray(b)-a)*k/n; v=np.asarray(a)+(np.asarray(b)-a)*min(k+1,n)/n
                draw.line([tuple(u),tuple(v)], fill=line['color'], width=2)
        else:
            draw.line([a,b], fill=line['color'], width=4)
            if line.get('handles', True):
                for x,y in (a,b): draw.ellipse((x-5,y-5,x+5,y+5), fill=line['color'])
    occupied = []
    for label in overlay['labels']:
        x,y=mapped(label['at']); text=label['text']
        tw=draw.textlength(text,font=small); x=max(4,min(x+8,iw-tw-4)); y=max(header,min(y,header+ih-24))
        while any(abs(y-v)<22 for v in occupied) and y<header+ih-46: y+=22
        occupied.append(y)
        draw.text((x,y),text,fill=label['color'],font=small,stroke_width=2,stroke_fill='black')
    px=iw+24; y=header
    draw.text((px,y),'Blue: superior | Yellow: inferior',fill='white',font=small);y+=34
    for number, curve in enumerate(measured['curves'],1):
        number = curve.get('curve_number', number)
        draw.text((px,y),f'C{number} {curve["name"]}: {curve["cobb_deg"]:.1f} deg',fill='white',font=large)
        draw.text((px,y+38),f'{curve["upper"]} superior -> {curve["lower"]} {curve["lower_endplate"]}',fill=YELLOW,font=font)
        draw.text((px,y+68),'Confirmed pair' if curve['endplates_reviewed'] else 'Pair needs review',fill=GREEN if curve['endplates_reviewed'] else YELLOW,font=small)
        # Translate the measured endplate directions to a common origin; never use
        # the uncorrected display-pixel angle when pixel spacing is anisotropic.
        ox,oy=px+120,y+160; radius=65
        a,b=curve['upper_tilt_deg']+90,curve['lower_tilt_deg']+90
        for tilt,color in ((a,BLUE),(b,BLUE if curve['lower_endplate']=='superior' else YELLOW)):
            rad=math.radians(tilt);draw.line([(ox,oy),(ox+100*math.cos(rad),oy+100*math.sin(rad))],fill=color,width=4)
        draw.arc((ox-radius,oy-radius,ox+radius,oy+radius),start=min(a,b),end=max(a,b),fill='white',width=3)
        draw.text((px+260,y+140),f'{curve["cobb_deg"]:.1f} deg',fill='white',font=large)
        draw.text((px,y+235),'Angle diagram: translated perpendiculars',fill='#cbd5e1',font=small)
        assessment=curve.get('coronal_assessment',{})
        draw.text((px,y+267),'Apex: '+(curve['apex'] or 'not selected')+' | CSVL proposal: '+str(assessment.get('apex_csvl_candidate') or '-'),fill=GREEN,font=small)
        for j,key in enumerate(('stable','neutral','last_touched')):
            chosen=assessment.get('reader',{}).get(key) or '-'; proposed=assessment.get(key+'_candidate') or '-'
            draw.text((px,y+295+j*28),f'{key.replace("_"," ").title()}: {chosen} | proposal: {proposed}',fill='#cbd5e1',font=small)
        y+=420
    for rotation in measured['rotations']:
        draw.text((px,y),f'{rotation["level"]}: Nash-Moe {rotation["grade"]}, {rotation["direction"]} (reader)',fill=PINK,font=small);y+=32
    if not measured['rotations']:
        draw.text((px,y),'Axial rotation: not assessed',fill=PINK,font=small);y+=30
    draw.text((px,y),'Proposals use available levels only; verify coverage.',fill='#cbd5e1',font=small)
    return canvas
