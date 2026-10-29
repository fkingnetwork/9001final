"""Run: python -m benchmarks.run_small_patterns [--image path ...].

Writes source/legacy/optimized comparisons and honest diagnostics. The built-in
fixtures are procedural; --image adds real local photographs without downloading
or copying their source files. Output metrics are diagnostics, not a quality score.
"""
import argparse
from collections import deque
from dataclasses import replace
import json
from pathlib import Path
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from backend.color_science import _lab_array
from backend.image_processing import COLORS, Parameters, convert_image
from .materials import Fixture, materials


def render(pattern):
    a = np.zeros((len(pattern), len(pattern[0]), 4), dtype=np.uint8)
    for y, row in enumerate(pattern):
        for x, cell in enumerate(row):
            if cell.code:
                a[y, x] = (*COLORS[cell.code]['rgb'].values(), 255)
    return Image.fromarray(a)


def on_white(image):
    bg = Image.new('RGBA', image.size, 'white')
    bg.alpha_composite(image.convert('RGBA'))
    return bg.convert('RGB')


def topology(mask):
    h, w = mask.shape
    def components(values, exclude_border=False):
        seen = np.zeros_like(values)
        count = 0
        for y, x in zip(*np.nonzero(values)):
            if seen[y, x]:
                continue
            todo = deque([(y, x)])
            seen[y, x] = True
            border = False
            while todo:
                cy, cx = todo.popleft()
                border |= cy == 0 or cx == 0 or cy == h-1 or cx == w-1
                for ny, nx in ((cy-1, cx), (cy+1, cx), (cy, cx-1), (cy, cx+1)):
                    if 0 <= ny < h and 0 <= nx < w and values[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        todo.append((ny, nx))
            count += not (exclude_border and border)
        return int(count)
    return components(mask), components(~mask, True)


def foreground(image):
    rgba = np.asarray(image.convert('RGBA'))
    if np.any(rgba[..., 3] == 0):
        return rgba[..., 3] >= 128
    lab = _lab_array(rgba[..., :3])
    border = np.concatenate((lab[0], lab[-1], lab[:, 0], lab[:, -1]))
    return np.linalg.norm(lab-np.median(border, axis=0), axis=-1) > 20


def edges(rgb):
    lab = _lab_array(rgb)
    e = np.zeros(lab.shape[:2], dtype=bool)
    e[1:] |= np.linalg.norm(lab[1:]-lab[:-1], axis=-1) > 20
    e[:, 1:] |= np.linalg.norm(lab[:, 1:]-lab[:, :-1], axis=-1) > 20
    return e


def metrics(source, output, pattern, elapsed):
    ref = ImageOps.contain(source, (256, 256), Image.Resampling.LANCZOS)
    padded = Image.new('RGBA', (256, 256))
    padded.paste(ref, ((256-ref.width)//2, (256-ref.height)//2))
    reconstruction = output.resize((256, 256), Image.Resampling.NEAREST)
    a, b = np.asarray(on_white(padded)), np.asarray(on_white(reconstruction))
    error = float(np.linalg.norm(_lab_array(a)-_lab_array(b), axis=-1).mean())
    ea, eb = edges(a), edges(b)
    radius = max(1, int(np.ceil(128/output.width)))
    def dilate(e):
        return np.asarray(Image.fromarray(e.astype(np.uint8)*255).filter(ImageFilter.MaxFilter(radius*2+1))) > 0
    precision = float((eb & dilate(ea)).sum()/max(eb.sum(), 1))
    recall = float((ea & dilate(eb)).sum()/max(ea.sum(), 1))
    f1 = 2*precision*recall/max(precision+recall, 1e-8)
    ids = np.array([[c.code or '-' for c in row] for row in pattern])
    singleton = np.ones(ids.shape, dtype=bool) & (ids != '-')
    singleton[1:] &= ids[1:] != ids[:-1]
    singleton[:-1] &= ids[:-1] != ids[1:]
    singleton[:, 1:] &= ids[:, 1:] != ids[:, :-1]
    singleton[:, :-1] &= ids[:, :-1] != ids[:, 1:]
    components, holes = topology(foreground(output))
    return dict(seconds=round(elapsed, 3), colors=len(set(ids.ravel())-{'-'}),
                occupied=int((ids != '-').sum()), singleton_cells=int(singleton.sum()),
                foreground_components=components, foreground_holes=holes,
                reconstruction_lab76=round(error, 3), edge_f1=round(f1, 3))


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--image', action='append', default=[])
    parser.add_argument('--output', default='outputs/low-resolution')
    args = parser.parse_args()
    fixtures = materials()
    for index, path in enumerate(args.image, 1):
        with Image.open(path) as opened:
            photo = ImageOps.exif_transpose(opened).convert('RGBA')
        fixtures.append(Fixture(f'local-photo-{index}', 'photo', photo, f'Local photograph: {Path(path).name}'))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for size in (16, 32, 48, 64):
        sheet = Image.new('RGB', (1016, len(fixtures)*236+45), '#ece9e0')
        draw = ImageDraw.Draw(sheet)
        draw.text((12, 12), f'{size} x {size} | source | existing | optimized | diagnostics (8-colour budget)', fill='black')
        for row, fixture in enumerate(fixtures):
            y = 45+row*236
            src = ImageOps.contain(on_white(fixture.image), (208, 208), Image.Resampling.LANCZOS)
            sheet.paste(src, (12+(208-src.width)//2, y+(208-src.height)//2))
            draw.text((12, y+212), fixture.name, fill='black')
            pair = []
            for column, enabled in enumerate((False, True)):
                frames = []
                p = Parameters(width=size, height=size, sampling=fixture.profile, auto_background=False,
                               max_colors=8, cleanup_size=2, low_resolution=enabled)
                start = time.perf_counter()
                pattern = convert_image(fixture.image, p, preview=frames.append)
                elapsed = time.perf_counter()-start
                output = render(pattern)
                label = 'optimized' if enabled else 'existing'
                output.save(out/f'{fixture.name}-{size}-{label}.png')
                sheet.paste(on_white(output).resize((208, 208), Image.Resampling.NEAREST), (240+column*228, y))
                m = metrics(fixture.image, output, pattern, elapsed)
                sampling = next(f.detail for f in frames if f.stage == 'sampling')
                records.append(dict(material=fixture.name, size=size, variant=label, profile=fixture.profile,
                                    description=fixture.description, sampling=sampling, **m))
                pair.append(m)
                draw.text((240+column*228, y+212), f"{label}: {m['colors']} colors, {m['seconds']:.2f}s", fill='black')
            for i, key in enumerate(('edge_f1', 'reconstruction_lab76', 'foreground_components', 'foreground_holes', 'singleton_cells')):
                draw.text((704, y+16+i*28), f'{key}: {pair[0][key]} -> {pair[1][key]}', fill='black')
            print(f'{size:2d} {fixture.name}: {pair[0]["seconds"]:.2f}s / {pair[1]["seconds"]:.2f}s', flush=True)
        sheet.save(out/f'comparison-{size}.png')
    (out/'metrics.json').write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding='utf-8')
    lines = ['# Small-pattern regression report', '',
             'Eight deterministic procedural materials plus any explicitly supplied local photos. '
             'Procedural shaded objects and landscapes are not real photographs. '
             'Background removal is disabled to isolate sampling and palette behaviour; all comparisons use an 8-colour budget.', '',
             'Edge F1 measures strong Lab boundaries within half a target cell. '
             'Reconstruction Lab76 measures average error against the full source enlarged to 256px; '
             'emphasising a thin line can increase it. Component/hole and singleton counts are descriptive: '
             'an intentional eye is also a singleton. No aggregate score or universal improvement is claimed.', '',
             '| Material | Grid | Edge F1 old → new | Lab76 old → new | Components old → new | Holes old → new | Seconds new |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for i in range(0, len(records), 2):
        a, b = records[i:i+2]
        lines.append(f"| {b['material']} | {b['size']} | {a['edge_f1']} → {b['edge_f1']} | {a['reconstruction_lab76']} → {b['reconstruction_lab76']} | {a['foreground_components']} → {b['foreground_components']} | {a['foreground_holes']} → {b['foreground_holes']} | {b['seconds']} |")
    lines += ['', 'Inspect the source/existing/optimized contact sheets at native and enlarged scale:', '']
    lines += [f'- [Comparison {n}×{n}](comparison-{n}.png)' for n in (16, 32, 48, 64)]
    (out/'report.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
