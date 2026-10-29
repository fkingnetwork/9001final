"""Local image-to-bead pipeline. No UI, network, OpenCV or model downloads."""
from collections import Counter, deque
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageColor, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from .color_science import delta_e_2000, rgb_to_lab, _linear, _srgb, _lab_array
from .palette import BEAD_COLORS
from .low_resolution import adaptive_sample, classify, optimize_labels

COLORS = {color['code']: color for color in BEAD_COLORS}
MAX_DIMENSION = 256


@dataclass(frozen=True)
class Parameters:
    width: int = 32
    height: int = 32
    brightness: int = 0
    contrast: int = 0
    saturation: int = 0
    background: str = '#ffffff'
    empty_transparent: bool = True
    enabled: tuple[str, ...] = tuple(COLORS)
    auto_background: bool = True
    background_tolerance: int = 12
    edge_protection: int = 70
    alpha_threshold: int = 128
    fit: str = 'contain'
    sampling: str = 'auto'
    max_colors: int = 24  # zero means all enabled colours
    cleanup_size: int = 2  # zero disables small-region merging
    cleanup_tolerance: int = 12
    denoise: bool = True  # light median filter, photo mode only
    dither_strength: int = 0
    low_resolution: bool = True  # structure-aware pipeline when both sides <=64


@dataclass(frozen=True)
class Cell:
    code: str | None
    original: tuple[int, int, int]
    difference: float = 0


@dataclass(frozen=True)
class ProcessingFrame:
    stage: str
    title: str
    detail: str
    image: Image.Image
    skipped: bool = False


def _emit_frame(preview, stage, title, image, detail='', skipped=False):
    if preview is None:
        return
    snapshot = image.convert('RGBA')
    snapshot.thumbnail((640, 640), Image.Resampling.NEAREST)
    preview(ProcessingFrame(stage, title, detail, snapshot.copy(), skipped))


def _grid_image(colors, active):
    rgba = np.empty((*active.shape, 4), dtype=np.uint8)
    rgba[..., :3] = colors
    rgba[..., 3] = active.astype(np.uint8) * 255
    return Image.fromarray(rgba)


def _mapped_image(grid, palette):
    rgba = np.zeros((*grid.shape, 4), dtype=np.uint8)
    active = grid >= 0
    values = np.array([tuple(color['rgb'].values()) + (255,) for color in palette], dtype=np.uint8)
    rgba[active] = values[grid[active]]
    return Image.fromarray(rgba)


def _check_cancelled(cancelled):
    if cancelled():
        raise InterruptedError('Conversion cancelled.')


def _validate(params):
    if any(not isinstance(value, int) or not 1 <= value <= MAX_DIMENSION
           for value in (params.width, params.height)):
        raise ValueError(f'Dimensions must be between 1 and {MAX_DIMENSION}.')
    if any(not -100 <= value <= 100 for value in
           (params.brightness, params.contrast, params.saturation)):
        raise ValueError('Adjustments must be between -100 and 100.')
    for name, low, high in (('background_tolerance', 0, 50), ('edge_protection', 0, 100),
                            ('alpha_threshold', 1, 255),
                            ('max_colors', 0, len(COLORS)), ('cleanup_size', 0, 20),
                            ('cleanup_tolerance', 0, 50), ('dither_strength', 0, 100)):
        value = getattr(params, name)
        if not isinstance(value, int) or not low <= value <= high:
            raise ValueError(f'{name} must be an integer between {low} and {high}.')
    if params.fit not in ('contain', 'cover'):
        raise ValueError('Fit must be contain or cover.')
    if params.sampling not in ('auto', 'photo', 'cartoon', 'pixel', 'lineart', 'scene'):
        raise ValueError('Unknown sampling mode.')
    if len(ImageColor.getrgb(params.background)) != 3:
        raise ValueError('Background must be an RGB colour.')
    palette = [COLORS[code] for code in dict.fromkeys(params.enabled) if code in COLORS]
    if not palette:
        raise ValueError('Enable at least one bead colour.')
    return palette


def _border_values(array):
    return np.concatenate((array[0], array[-1], array[:, 0], array[:, -1]))


def _sobel_strength(lab):
    """Colour gradient in Lab units/pixel, using a normalized Sobel kernel."""
    padded = np.pad(lab, ((1, 1), (1, 1), (0, 0)), mode='edge')
    gx = (padded[:-2, 2:] + 2 * padded[1:-1, 2:] + padded[2:, 2:]
          - padded[:-2, :-2] - 2 * padded[1:-1, :-2] - padded[2:, :-2]) / 8
    gy = (padded[2:, :-2] + 2 * padded[2:, 1:-1] + padded[2:, 2:]
          - padded[:-2, :-2] - 2 * padded[:-2, 1:-1] - padded[:-2, 2:]) / 8
    return np.sqrt(np.sum(gx * gx + gy * gy, axis=-1))


def _robust_noise(values, minimum):
    if not len(values):
        return minimum
    median = float(np.median(values))
    return max(minimum, median + 4.5 * float(np.median(np.abs(values - median))))


def _edge_aware_candidates(rgb, reference, eligible, opaque, tolerance, protection, cancelled, preview=None):
    """Constrain weak background pixels by learned noise and edge barriers.

    Lab compresses near-black RGB differences: a permissive Lab radius alone
    can join black hair to a black backdrop. Estimate the backdrop's variation
    from robust border statistics, then block uncertain growth at multi-scale
    colour/brightness edges. No foreground category or portrait coordinates
    are assumed. Protection=0 retains the original colour-only behaviour.
    """
    if not protection:
        return eligible
    strength = protection / 100
    residual = np.max(np.abs(rgb.astype(np.float32) - reference), axis=-1)
    border_background = _border_values(eligible & opaque)
    noise = _robust_noise(_border_values(residual)[border_background], 3)
    noise *= tolerance / 12
    candidate = eligible & (residual <= noise / strength)
    _check_cancelled(cancelled)
    source = Image.fromarray(rgb)
    fine = _sobel_strength(_lab_array(np.asarray(source.filter(ImageFilter.GaussianBlur(.6)))))
    _check_cancelled(cancelled)
    coarse = _sobel_strength(_lab_array(np.asarray(source.filter(ImageFilter.GaussianBlur(1.2)))))
    gradient = np.maximum(fine, coarse)
    if preview is not None:
        heat = np.clip(gradient / max(float(np.percentile(gradient, 98)), .01), 0, 1)
        overlay = np.clip(rgb.astype(np.float32) * .32 + heat[..., None] *
                          np.array([25, 215, 230]), 0, 255).astype(np.uint8)
        _emit_frame(preview, 'edges', 'Protecting subject contours', Image.fromarray(overlay),
                    f'Edge protection {protection}% · fine and broad contours')
    reliable_border = border_background & (_border_values(residual) <= noise)
    edge_noise = _robust_noise(_border_values(gradient)[reliable_border], .65)
    edge_barrier = (gradient > edge_noise * (2 - strength) / strength) & (residual > noise)
    return candidate & ~edge_barrier


def remove_connected_background(image, tolerance=12, cancelled=lambda: False, edge_protection=70, preview=None):
    """Infer a plain background from 3 agreeing corners, then flood from borders.

    Busy/inconsistent borders and uniform swatches are left intact. Enclosed
    regions never become background solely because they have the same colour.
    """
    _check_cancelled(cancelled)
    rgba = np.array(image.convert('RGBA'))
    height, width = rgba.shape[:2]
    opaque = rgba[..., 3] >= 128
    patch = max(1, min(5, min(width, height) // 10))
    corners = []
    for ys, xs in ((slice(0, patch), slice(0, patch)),
                   (slice(0, patch), slice(-patch, None)),
                   (slice(-patch, None), slice(0, patch)),
                   (slice(-patch, None), slice(-patch, None))):
        values = rgba[ys, xs, :3][opaque[ys, xs]]
        if len(values):
            corners.append(np.median(values, axis=0))
    if len(corners) < 3:
        return image.copy()
    corner_lab = _lab_array(corners)
    agreement = np.linalg.norm(corner_lab[:, None] - corner_lab[None, :], axis=-1) <= tolerance
    cluster = agreement[np.argmax(agreement.sum(axis=1))]
    if cluster.sum() < 3:
        return image.copy()
    reference_rgb = np.median(np.asarray(corners)[cluster], axis=0)
    reference = _lab_array(reference_rgb)
    distance = np.linalg.norm(_lab_array(rgba[..., :3]) - reference, axis=-1)
    eligible = _edge_aware_candidates(rgba[..., :3], reference_rgb, distance <= tolerance,
                                      opaque, tolerance, edge_protection, cancelled, preview)
    eligible |= rgba[..., 3] == 0
    border = _border_values(eligible)
    if np.mean(border) < .65:
        return image.copy()
    # Flood a padded binary mask. The padding joins all eligible border seeds.
    flood = Image.fromarray(np.pad(eligible.astype(np.uint8), 1, constant_values=1)).copy()
    ImageDraw.floodfill(flood, (0, 0), 2)
    _check_cancelled(cancelled)
    removed = np.asarray(flood)[1:-1, 1:-1] == 2
    if not np.any(opaque & ~removed):
        return image.copy()  # a plain swatch is not an empty subject
    rgba[removed, 3] = 0
    return Image.fromarray(rgba)


def _sampling_mode(image, requested):
    if requested != 'auto':
        return requested
    return classify(image)


def _resize_float(channel, size):
    return np.asarray(Image.fromarray(channel.astype(np.float32)).resize(size, Image.Resampling.BOX))


def _sample(image, size, mode, cancelled):
    rgba = np.asarray(image)
    alpha = rgba[..., 3].astype(np.float32) / 255
    if mode == 'pixel':
        sampled = np.asarray(image.resize(size, Image.Resampling.NEAREST))
        return sampled[..., :3].copy(), sampled[..., 3].astype(np.float32) / 255
    coverage = np.clip(_resize_float(alpha, size), 0, 1)
    if mode in ('photo', 'scene'):
        weighted = _linear(rgba[..., :3]) * alpha[..., None]
        sampled = np.stack([_resize_float(weighted[..., c], size) for c in range(3)], axis=-1)
        return _srgb(sampled / np.maximum(coverage[..., None], 1e-8)), coverage
    # Cluster RGB into small bins before selecting a dominant colour. Weight
    # both the winning bin and its representative RGB by alpha, not background.
    width, height = size
    result = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        _check_cancelled(cancelled)
        top, bottom = y * image.height // height, max(1, int(np.ceil((y + 1) * image.height / height)))
        for x in range(width):
            left, right = x * image.width // width, max(1, int(np.ceil((x + 1) * image.width / width)))
            pixels = rgba[top:bottom, left:right].reshape(-1, 4)
            pixels = pixels[pixels[:, 3] > 0]
            if not len(pixels):
                continue
            bins = pixels[:, :3].astype(np.int32) // 8
            keys = bins[:, 0] * 1024 + bins[:, 1] * 32 + bins[:, 2]
            _, inverse = np.unique(keys, return_inverse=True)
            weights = pixels[:, 3].astype(np.float32)
            winner = np.bincount(inverse, weights=weights).argmax()
            chosen = inverse == winner
            result[y, x] = np.rint(np.average(pixels[chosen, :3], axis=0, weights=weights[chosen]))
    return result, coverage


def _prepare(image, params, cancelled, preview=None):
    mode = _sampling_mode(image, params.sampling)
    original_opaque = image.getchannel('A').getextrema() == (255, 255)
    # Bound automatic analysis/working memory, while avoiding unnecessary
    # resampling of pixel-art sources. Input files are never written back.
    image.thumbnail((1200, 1200), Image.Resampling.NEAREST if mode == 'pixel' else Image.Resampling.LANCZOS)
    _emit_frame(preview, 'edges', 'Inspecting image boundaries', image,
                'Finding a consistent background' if params.auto_background else 'Background removal is off',
                skipped=not params.auto_background)
    removed = 0
    if params.auto_background:
        before_alpha = np.asarray(image.getchannel('A'))
        image = remove_connected_background(image, params.background_tolerance, cancelled,
                                             params.edge_protection, preview)
        removed = int(np.count_nonzero(before_alpha > np.asarray(image.getchannel('A'))))
        if preview is not None:
            _emit_frame(preview, 'background', 'Separating foreground', image,
                        f'{removed:,} background pixels removed' if removed else
                        'No confident connected background found · source preserved')
    else:
        _emit_frame(preview, 'background', 'Keeping original background', image,
                    'Background removal is off', skipped=True)
    _check_cancelled(cancelled)
    rgb = image.convert('RGB')
    if mode in ('photo', 'scene') and params.denoise and min(image.size) > 3:
        filtered = rgb.filter(ImageFilter.MedianFilter(3))
        # Do not pull the removed background into foreground boundary colours.
        interior = np.asarray(image.getchannel('A').filter(ImageFilter.MinFilter(3))) == 255
        rgb = Image.fromarray(np.where(interior[..., None], np.asarray(filtered), np.asarray(rgb)))
    for enhancer, value in ((ImageEnhance.Brightness, params.brightness),
                            (ImageEnhance.Contrast, params.contrast),
                            (ImageEnhance.Color, params.saturation)):
        if value:
            rgb = enhancer(rgb).enhance(1 + value / 100)
    rgb.putalpha(image.getchannel('A'))
    if params.fit == 'cover':
        ratio = params.width / params.height
        if rgb.width / rgb.height > ratio:
            width = max(1, round(rgb.height * ratio))
            left = (rgb.width - width) // 2
            rgb = rgb.crop((left, 0, left + width, rgb.height))
        else:
            height = max(1, round(rgb.width / ratio))
            top = (rgb.height - height) // 2
            rgb = rgb.crop((0, top, rgb.width, top + height))
        size = (params.width, params.height)
    else:
        scale = min(params.width / rgb.width, params.height / rgb.height)
        size = (max(1, min(params.width, round(rgb.width * scale))),
                max(1, min(params.height, round(rgb.height * scale))))
    optimized = params.low_resolution and max(params.width, params.height) <= 64 and mode != 'pixel'
    guide = None
    if optimized:
        sampled, coverage, guide = adaptive_sample(rgb, size, mode, cancelled)
    else:
        sampled, coverage = _sample(rgb, size, mode, cancelled)
    colors = np.zeros((params.height, params.width, 3), dtype=np.uint8)
    alpha = np.zeros((params.height, params.width), dtype=np.float32)
    x, y = (params.width - size[0]) // 2, (params.height - size[1]) // 2
    colors[y:y + size[1], x:x + size[0]] = sampled
    alpha[y:y + size[1], x:x + size[0]] = coverage
    if guide is not None:
        protected = np.zeros(alpha.shape, dtype=bool)
        importance = np.ones(alpha.shape, dtype=np.float32)
        protected[y:y+size[1], x:x+size[0]] = guide.protected
        importance[y:y+size[1], x:x+size[0]] = guide.importance
        guide.protected, guide.importance = protected, importance
    if params.empty_transparent:
        active = alpha * 255 >= params.alpha_threshold
    else:
        background_rgb = ImageColor.getrgb(params.background)
        if removed and original_opaque:
            # A bead is opaque: do not turn a dark, partially covered subject
            # cell into a grey bead by blending its mask coverage over white.
            # This coverage comes from automatic segmentation, not intentional
            # input translucency, so decide foreground/background first.
            foreground = alpha * 255 >= params.alpha_threshold
            colors = np.where(foreground[..., None], colors,
                              np.asarray(background_rgb, dtype=np.uint8))
        else:
            background = _linear(background_rgb)
            colors = _srgb(_linear(colors) * alpha[..., None] + background * (1 - alpha[..., None]))
        active = np.ones(alpha.shape, dtype=bool)
    if preview is not None:
        _emit_frame(preview, 'sampling', 'Building the sampling grid', _grid_image(colors, active),
                    f'{params.width} × {params.height} cells · {mode}' +
                    (f' · grid phase {guide.offset} · structure protected' if guide else ' sampling'))
    return colors, active, guide


def _palette_subset(distances, counts, limit, cancelled):
    if not limit or limit >= distances.shape[1]:
        return np.arange(distances.shape[1])
    # Greedy weighted facility selection: each added real bead colour must
    # reduce total source-image error. Rare high-contrast details have a say.
    best = np.full(len(counts), np.inf)
    selected = []
    for _ in range(limit):
        _check_cancelled(cancelled)
        costs = (np.minimum(best[:, None], distances) * counts[:, None]).sum(axis=0)
        if selected:
            costs[selected] = np.inf
        choice = int(costs.argmin())
        if selected and costs[choice] >= np.dot(best, counts) - 1e-6:
            break
        selected.append(choice)
        best = np.minimum(best, distances[:, choice])
    return np.asarray(selected)


def _dither(colors, active, palette, strength, cancelled):
    height, width = active.shape
    work = _linear(colors).copy()
    palette_linear = _linear([list(color['rgb'].values()) for color in palette])
    output = np.full(active.shape, -1, dtype=np.int32)
    for y in range(height):
        _check_cancelled(cancelled)
        for x in range(width):
            if not active[y, x]:
                continue
            rgb = tuple(int(v) for v in _srgb(work[y, x]))
            lab = rgb_to_lab(rgb)
            match = min(range(len(palette)), key=lambda i: delta_e_2000(lab, palette[i]['lab']))
            output[y, x] = match
            error = (np.clip(work[y, x], 0, 1) - palette_linear[match]) * strength / 100
            for dx, dy, weight in ((1, 0, 7 / 16), (-1, 1, 3 / 16), (0, 1, 5 / 16), (1, 1, 1 / 16)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and ny < height and active[ny, nx]:
                    work[ny, nx] += error * weight
    return output


def _clean_regions(grid, palette, size, tolerance, cancelled, protected=None):
    if not size:
        return grid
    height, width = grid.shape
    labels = np.full(grid.shape, -1, dtype=np.int32)
    regions = []
    for y in range(height):
        _check_cancelled(cancelled)
        for x in range(width):
            if grid[y, x] < 0 or labels[y, x] >= 0:
                continue
            label, code = len(regions), grid[y, x]
            queue, region = deque([(y, x)]), []
            labels[y, x] = label
            while queue:
                cy, cx = queue.popleft()
                region.append((cy, cx))
                for ny, nx in ((cy - 1, cx), (cy + 1, cx), (cy, cx - 1), (cy, cx + 1)):
                    if (0 <= ny < height and 0 <= nx < width and labels[ny, nx] < 0
                            and grid[ny, nx] == code):
                        labels[ny, nx] = label
                        queue.append((ny, nx))
            regions.append(region)
    result = grid.copy()
    for region in regions:
        if len(region) > size or (protected is not None and any(protected[y, x] for y, x in region)):
            continue
        _check_cancelled(cancelled)
        neighbours = Counter()
        for y, x in region:
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width and grid[ny, nx] >= 0:
                    other = regions[labels[ny, nx]]
                    if len(other) > size:
                        neighbours[int(grid[ny, nx])] += 1
        if not neighbours:
            continue
        replacement, votes = neighbours.most_common(1)[0]
        original = int(grid[region[0]])
        if votes / sum(neighbours.values()) >= .6 and delta_e_2000(
                palette[original]['lab'], palette[replacement]['lab']) <= tolerance:
            for y, x in region:
                result[y, x] = replacement
    return result


def convert_image(path, params, progress=lambda value: None, cancelled=lambda: False, preview=None):
    """Load → automatic mask → sample → select palette → match → clean."""
    palette = _validate(params)
    _check_cancelled(cancelled)
    progress(0)
    if isinstance(path, Image.Image):
        image = ImageOps.exif_transpose(path).convert('RGBA')
    else:
        with Image.open(path) as opened:
            image = ImageOps.exif_transpose(opened).convert('RGBA')
    progress(5)
    _emit_frame(preview, 'source', 'Reading source image', image,
                f'{image.width:,} × {image.height:,} pixels · orientation corrected')
    colors, active, guide = _prepare(image, params, cancelled, preview)
    progress(25)
    grid = np.full(active.shape, -1, dtype=np.int32)
    if preview is not None:
        _emit_frame(preview, 'matching', 'Selecting bead colours', _grid_image(colors, active),
                    f'Matching against {len(palette)} enabled Hama colours', skipped=not active.any())
    if active.any():
        unique, inverse, counts = np.unique(colors[active], axis=0, return_inverse=True, return_counts=True)
        distances = np.empty((len(unique), len(palette)), dtype=np.float32)
        for index, rgb in enumerate(unique):
            if index % 32 == 0:
                _check_cancelled(cancelled)
                progress(25 + round(45 * index / len(unique)))
            lab = rgb_to_lab(tuple(int(v) for v in rgb))
            distances[index] = [delta_e_2000(lab, color['lab']) for color in palette]
        weights = (np.bincount(inverse, weights=guide.importance[active], minlength=len(unique))
                   if guide is not None else counts)
        subset = _palette_subset(distances, weights, params.max_colors, cancelled)
        full_palette = palette
        palette = [palette[int(index)] for index in subset]
        if params.dither_strength:
            grid = _dither(colors, active, palette, params.dither_strength, cancelled)
        elif guide is not None:
            grid = optimize_labels(distances, inverse, active, subset, guide, _lab_array(colors), cancelled)
            palette = full_palette  # spatial fitting returns indices in the enabled palette
        else:
            grid[active] = distances[:, subset].argmin(axis=1)[inverse]
        if preview is not None:
            _emit_frame(preview, 'matching', 'Mapping the bead palette', _mapped_image(grid, palette),
                        f'{len(np.unique(grid[grid >= 0]))} bead colours · perceptual colour matching')
        progress(85)
        before_cleanup = grid.copy() if preview is not None else None
        grid = _clean_regions(grid, palette, params.cleanup_size, params.cleanup_tolerance, cancelled,
                              guide.protected if guide else None)
        if preview is not None:
            changed = int(np.count_nonzero(before_cleanup != grid))
            _emit_frame(preview, 'cleanup', 'Refining the pattern', _mapped_image(grid, palette),
                        f'{changed:,} cells refined · high-contrast details protected' if params.cleanup_size else
                        'Region cleanup is off', skipped=not params.cleanup_size)
    elif preview is not None:
        _emit_frame(preview, 'cleanup', 'Empty pattern ready', _mapped_image(grid, palette),
                    'No foreground cells to refine', skipped=True)
    result, cache = [], {}
    for y in range(params.height):
        _check_cancelled(cancelled)
        row = []
        for x in range(params.width):
            rgb = tuple(int(value) for value in colors[y, x])
            index = int(grid[y, x])
            code = palette[index]['code'] if index >= 0 else None
            key = (rgb, code)
            if key not in cache:
                difference = delta_e_2000(rgb_to_lab(rgb), palette[index]['lab']) if code else 0
                cache[key] = Cell(code, rgb, difference)
            row.append(cache[key])
        result.append(row)
    progress(100)
    return result
