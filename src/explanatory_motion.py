"""Deterministic original schematics. No external media, numeric plots or LLM drawing.

The same bounded spec is validated by reviewers and rendered against measured audio
length. Text is data, never FFmpeg filter syntax. Fail rather than invent a diagram.
"""
import json
from functools import lru_cache
import math
import os
import subprocess

VISUAL_RULES = '''VISUAL EXECUTION CONTRACT:
Every scene has visual_type (stock or authored_diagram), keyword (3-6 literal stock
search words, even when an unused establishing-shot alternative), production_brief,
visual_source_notes and, for authored_diagram, diagram_description and diagram_spec.
Use authored_diagram for mechanisms that stock cannot truthfully show. Never label
schematics as stock, brain scans, measured data, or proof. Do not invent causal arrows.
Only explain supplied facts, label uncertainty and hypothetical examples.
diagram_spec is an object with title (<=60 chars), nodes (2-4 distinct labels, each
<=32 chars), edges (0-4 objects: from and to are zero-based node indices, label <=28
chars), steps (2-4 ordered objects: caption <=100 chars, highlight is a nonempty list
of node indices, edge is an optional zero-based edge index). The renderer arranges
nodes left to right, draws labeled arrows, and sequentially highlights each step.
Each step needs a different caption and state, timed in narration order. No arbitrary
coordinates, charts, percentages, images or renderer code. Keep every field through
all revisions. Each diagram must explain a distinct part of the narration, not use
the same graph with renamed titles. Stock is only an illustrative real-world action.
'''


def _text(value, limit, field):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f'Invalid diagram {field} (nonempty, max {limit} chars)')
    if any(ord(c) < 32 for c in value):
        raise ValueError(f'Control character in diagram {field}')
    return value.strip()


def validate_spec(spec):
    if not isinstance(spec, dict):
        raise ValueError('Missing structured diagram_spec')
    _text(spec.get('title'), 60, 'title')
    nodes, edges, steps = spec.get('nodes'), spec.get('edges'), spec.get('steps')
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 4:
        raise ValueError('Diagram needs 2-4 nodes')
    for n in nodes:
        _text(n, 32, 'node')
    if len(set(n.strip().casefold() for n in nodes)) != len(nodes):
        raise ValueError('Duplicate diagram nodes')
    def index(i, size):
        return type(i) is int and 0 <= i < size
    if not isinstance(edges, list) or len(edges) > 4:
        raise ValueError('Diagram needs 0-4 edges')
    for e in edges:
        if (not isinstance(e, dict) or not index(e.get('from'), len(nodes))
                or not index(e.get('to'), len(nodes)) or e['from'] == e['to']):
            raise ValueError('Invalid diagram edge')
        _text(e.get('label'), 28, 'edge label')
    if not isinstance(steps, list) or not 2 <= len(steps) <= 4:
        raise ValueError('Diagram needs 2-4 ordered steps')
    states = set()
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError('Invalid diagram step')
        _text(step.get('caption'), 100, 'step caption')
        hi = step.get('highlight')
        if not isinstance(hi, list) or not hi or any(not index(i, len(nodes)) for i in hi):
            raise ValueError('Invalid highlighted diagram nodes')
        if 'edge' in step and not index(step['edge'], len(edges)):
            raise ValueError('Invalid highlighted diagram edge')
        states.add((tuple(sorted(set(hi))), step.get('edge')))
    if len(states) < 2 or len({s['caption'].casefold() for s in steps}) != len(steps):
        raise ValueError('Diagram steps must advance distinct states')
    return spec


def validate_scene(scene):
    kind = scene.get('visual_type', 'stock')
    if kind not in ('stock', 'authored_diagram'):
        raise ValueError('Unknown visual_type')
    if kind == 'authored_diagram':
        for field in ('diagram_description', 'production_brief', 'visual_source_notes'):
            if not isinstance(scene.get(field), str) or not scene[field].strip():
                raise ValueError(f'Missing diagram {field}')
        validate_spec(scene.get('diagram_spec'))
    elif scene.get('diagram_spec') or scene.get('diagram_description'):
        raise ValueError('Diagram brief mislabeled as stock')
    return kind


def review_brief(scene):
    kind = validate_scene(scene)
    if kind == 'stock':
        return {'visual_type': kind, 'keyword': scene.get('keyword'),
                'production_brief': scene.get('production_brief', ''),
                'visual_source_notes': scene.get('visual_source_notes', '')}
    return {k: scene.get(k) for k in ('visual_type', 'diagram_description', 'diagram_spec',
                                     'production_brief', 'visual_source_notes', 'narration')}


@lru_cache(maxsize=24)
def _font(size, bold=False):
    from PIL import ImageFont
    path = '/usr/share/fonts/truetype/dejavu/DejaVuSans' + ('-Bold' if bold else '') + '.ttf'
    return ImageFont.truetype(path, size)


def _wrapped(draw, text, font, width):
    lines = ['']
    for word in text.split():
        candidate = (lines[-1] + ' ' + word).strip()
        if draw.textlength(candidate, font=font) <= width:
            lines[-1] = candidate
        else:
            # Long unbroken strings fail instead of clipping outside the safe area.
            if draw.textlength(word, font=font) > width:
                raise ValueError('Diagram label does not fit safe width')
            lines.append(word)
    return '\n'.join(lines)


def frame(spec, progress, size=(1920, 1080)):
    """Render safe-area frame. Bottom 170px reserved for narration captions."""
    from PIL import Image, ImageDraw
    validate_spec(spec)
    im = Image.new('RGB', (1920, 1080), '#0f172a')
    d = ImageDraw.Draw(im)
    white, muted, accent = '#f8fafc', '#94a3b8', '#FFD700'
    d.text((120, 66), 'ORIGINAL SCHEMATIC  /  ILLUSTRATIVE, NOT MEASURED DATA', font=_font(22), fill=muted)
    if d.textlength(spec['title'], font=_font(48, True)) > 1680:
        raise ValueError('Diagram title exceeds safe width')
    d.text((120, 120), spec['title'], font=_font(48, True), fill=white)
    steps = spec['steps']
    position = max(0, min(progress, .999999)) * len(steps)
    si = int(position)
    step = steps[si]
    phase = position - si
    count = len(spec['nodes'])
    centers = [270 + i * (1380 / (count - 1)) for i in range(count)]
    # Route each edge in its own lane above or below node row, preventing overlaps.
    for ei, edge in enumerate(spec['edges']):
        x1, x2 = centers[edge['from']], centers[edge['to']]
        y = 270 if ei < 2 else 630 + (ei - 2) * 70
        if ei == 1:
            y = 350
        active = step.get('edge') == ei
        col = accent if active else muted
        points = [(x1, 420 if ei < 2 else 570), (x1, y), (x2, y), (x2, 420 if ei < 2 else 570)]
        d.line(points, fill=col, width=5 if active else 3)
        end_y = points[-1][1]
        direction = 1 if ei < 2 else -1
        d.polygon([(x2, end_y), (x2-10, end_y-direction*18), (x2+10, end_y-direction*18)], fill=col)
        label = edge['label']
        f = _font(25, active)
        tw = d.textlength(label, font=f)
        tx = max(120, min(1800-tw, (x1+x2-tw)/2))
        d.rectangle((tx-10, y-37, tx+tw+10, y-2), fill='#0f172a')
        d.text((tx, y-37), label, font=f, fill=col)
        if active:
            # A moving dot traverses the real directed arrow, not a fake data trace.
            q = phase * 3
            seg = min(2, int(q)); local = q-seg
            a, b = points[seg], points[seg+1]
            px, py = a[0]+(b[0]-a[0])*local, a[1]+(b[1]-a[1])*local
            d.ellipse((px-9,py-9,px+9,py+9),fill=accent)
    for ni, (x, label) in enumerate(zip(centers, spec['nodes'])):
        active = ni in step['highlight']
        d.rounded_rectangle((x-140,420,x+140,570), radius=20, fill='#1e293b',
                            outline=accent if active else '#475569', width=5 if active else 2)
        text = _wrapped(d, label, _font(29, True), 250)
        if len(text.splitlines()) > 3:
            raise ValueError('Diagram node text exceeds safe height')
        d.multiline_text((x,495),text,font=_font(29, True),fill=white,anchor='mm',align='center',spacing=8)
    caption = _wrapped(d, step['caption'], _font(34), 1540)
    if len(caption.splitlines()) > 2:
        raise ValueError('Diagram caption exceeds safe height')
    d.text((120, 770), f'{si+1:02d} / {len(steps):02d}',font=_font(26,True),fill=accent)
    d.multiline_text((300,760),caption,font=_font(34),fill=white,spacing=12)
    d.rounded_rectangle((120,880,1800,888),radius=4,fill='#334155')
    d.rounded_rectangle((120,880,120+max(2,1680*min(1,progress)),888),radius=4,fill=accent)
    return im if size == (1920, 1080) else im.resize(size)


def render(spec, duration, out, fps=12):
    validate_spec(spec)
    if not isinstance(duration, (float, int)) or not math.isfinite(duration) or not 0 < duration <= 180:
        raise ValueError('Invalid diagram duration')
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    # Twelve distinct motion frames/sec, encoded at the editor's 24fps baseline.
    n = max(2, math.ceil(duration*fps))
    cmd = ['ffmpeg','-v','error','-y','-f','rawvideo','-pix_fmt','rgb24','-s','1920x1080',
           '-r',str(fps),'-i','pipe:0','-t',str(duration),'-an','-r','24','-c:v','libx264',
           '-threads','2','-preset','fast','-crf','16','-pix_fmt','yuv420p',out]
    with subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE) as proc:
        try:
            for i in range(n):
                proc.stdin.write(frame(spec, i/max(1,n-1)).tobytes())
            proc.stdin.close()
            error = proc.stderr.read().decode()
            if proc.wait(timeout=180) != 0:
                raise RuntimeError('Diagram encode failed: '+error[-1000:])
        except Exception:
            proc.kill()
            raise
    return out
