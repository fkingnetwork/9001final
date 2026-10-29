"""Structure-aware sampling and alternating palette/label fitting for <=64 grids.

All coordinates are image-relative; no face detector, portrait template or model
is used. Sampling searches nine quarter-cell phases and reports its objective.
"""
from collections import deque
from dataclasses import dataclass

import numpy as np
from PIL import Image

from .color_science import _linear, _srgb, _lab_array


@dataclass
class StructureGuide:
    protected: np.ndarray
    importance: np.ndarray
    offset: tuple[float, float] = (0., 0.)
    baseline_score: float = 0.
    selected_score: float = 0.
    profile: str = 'photo'


def check(cancelled):
    if cancelled():
        raise InterruptedError('Conversion cancelled.')


def classify(image):
    probe = image.copy()
    probe.thumbnail((96, 96), Image.Resampling.NEAREST)
    rgba = np.asarray(probe)
    visible = rgba[..., 3] >= 128
    rgb = rgba[..., :3][visible]
    if not len(rgb):
        return 'pixel'
    _, counts = np.unique(rgb // 8, axis=0, return_counts=True)
    count = len(counts)
    concentrated = np.sort(counts)[-8:].sum()/len(rgb) > .92
    # Native small sprites remain exact; a large two-colour logo is not a sprite.
    if max(image.size) <= 64 and count <= 64 and concentrated:
        return 'pixel'
    neutral = np.mean(np.ptp(rgb.astype(float), axis=1) < 18)
    extreme = np.mean((rgb.mean(axis=1) < 65) | (rgb.mean(axis=1) > 210))
    if neutral > .85 and extreme > .85:
        return 'lineart'
    if count <= 64 and concentrated and max(image.size) <= 768:
        # Integer-upscaled sprites have repeated, globally aligned block edges.
        original = np.array(image)
        original[original[..., 3] == 0] = 0
        xp = np.flatnonzero(np.any(original[:, 1:] != original[:, :-1], axis=(0, 2)))+1
        yp = np.flatnonzero(np.any(original[1:] != original[:-1], axis=(1, 2)))+1
        if len(xp) >= 3 and len(yp) >= 3 and any(np.all(xp % k == 0) and np.all(yp % k == 0) for k in range(2, 17)):
            return 'pixel'
    if count <= 96 and concentrated:
        return 'cartoon'
    return 'photo'


def _resize_float(values, size):
    return np.asarray(Image.fromarray(values.astype(np.float32)).resize(size, Image.Resampling.BOX))


def _blocks(array, h, w, q):
    if array.ndim == 2:
        return array.reshape(h, q, w, q).transpose(0, 2, 1, 3)
    return array.reshape(h, q, w, q, 3).transpose(0, 2, 1, 3, 4)


def _enclosed(mask, cancelled):
    """Return four-connected components excluding any that touch the border."""
    h, w = mask.shape
    seen = np.zeros_like(mask)
    components = []
    for y, x in zip(*np.nonzero(mask)):
        if seen[y, x]:
            continue
        check(cancelled)
        queue = deque([(y, x)])
        seen[y, x] = True
        points, border = [], False
        while queue:
            cy, cx = queue.popleft()
            points.append((cy, cx))
            if len(points) % 1024 == 0:
                check(cancelled)
            border |= cy == 0 or cx == 0 or cy == h - 1 or cx == w - 1
            for ny, nx in ((cy-1, cx), (cy+1, cx), (cy, cx-1), (cy, cx+1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    queue.append((ny, nx))
        if not border:
            components.append(points)
    return components


def _connects(block, sides):
    """A real source path must join both sides before bridging a grid diagonal."""
    q = block.shape[0]
    def face(side):
        result = np.zeros_like(block)
        if side == 'top': result[0] = block[0]
        if side == 'bottom': result[-1] = block[-1]
        if side == 'left': result[:, 0] = block[:, 0]
        if side == 'right': result[:, -1] = block[:, -1]
        return result
    starts, goals = face(sides[0]), face(sides[1])
    if not starts.any() or not goals.any():
        return False
    queue = deque(zip(*np.nonzero(starts)))
    seen = starts.copy()
    while queue:
        y, x = queue.popleft()
        if goals[y, x]:
            return True
        for ny, nx in ((y-1, x), (y+1, x), (y, x-1), (y, x+1)):
            if 0 <= ny < q and 0 <= nx < q and block[ny, nx] and not seen[ny, nx]:
                seen[ny, nx] = True
                queue.append((ny, nx))
    return False


def _bridge_diagonals(mask, support, cancelled):
    """Route diagonal cells through the better-supported side, never blind dilation."""
    result = mask.copy()
    promoted = np.zeros_like(mask)
    for y in range(mask.shape[0]-1):
        check(cancelled)
        for x in range(mask.shape[1]-1):
            a, b, c, d = result[y, x], result[y, x+1], result[y+1, x], result[y+1, x+1]
            choices = []
            if a and d and not b and not c:
                choices = [(y, x+1, ('left', 'bottom')), (y+1, x, ('top', 'right'))]
            elif b and c and not a and not d:
                choices = [(y, x, ('right', 'bottom')), (y+1, x+1, ('top', 'left'))]
            viable = [(float(support[cy, cx].mean()), cy, cx) for cy, cx, sides in choices
                      if _connects(support[cy, cx], sides)]
            if viable:
                _, cy, cx = max(viable)
                result[cy, cx] = promoted[cy, cx] = True
    return promoted


def adaptive_sample(image, size, profile, cancelled=lambda: False):
    w, h = size
    q = 8
    rgba = np.asarray(image)
    a = rgba[..., 3].astype(np.float32) / 255
    alpha = _resize_float(a, (w*q, h*q))
    weighted = _linear(rgba[..., :3]) * a[..., None]
    linear = np.stack([_resize_float(weighted[..., c], (w*q, h*q)) for c in range(3)], axis=-1)
    micro = _srgb(linear / np.maximum(alpha[..., None], 1e-8))
    lab = _lab_array(micro)
    opaque = bool(np.all(alpha > .999))
    padded_lab = np.pad(lab, ((2, 2), (2, 2), (0, 0)), mode='edge')
    padded_a = np.pad(alpha, 2, mode='edge' if opaque else 'constant')
    padded_rgb = np.pad(micro, ((2, 2), (2, 2), (0, 0)), mode='edge')
    border_rgb = np.concatenate((micro[0], micro[-1], micro[:, 0], micro[:, -1]))
    border_ref = _lab_array(np.median(border_rgb, axis=0))
    best = None
    baseline = 0.
    # Zero first: identical candidates keep the source alignment.
    for dx, dy in ((0, 0), (-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, -2), (-2, 2), (2, 2)):
        check(cancelled)
        sl = np.s_[2+dy:2+dy+h*q, 2+dx:2+dx+w*q]
        aa = _blocks(padded_a[sl], h, w, q)
        rr = _blocks(padded_rgb[sl], h, w, q)
        ll = _blocks(padded_lab[sl], h, w, q).reshape(h, w, q*q, 3)
        weights = aa.reshape(h, w, q*q)
        total = weights.sum(axis=-1)
        mean = (ll * weights[..., None]).sum(axis=-2) / np.maximum(total[..., None], 1e-8)
        far = (np.sum((ll - mean[..., None, :])**2, axis=-1) * (weights > .05)).argmax(axis=-1)
        first = np.take_along_axis(ll, far[..., None, None], axis=2)[..., 0, :]
        far = (np.sum((ll - first[..., None, :])**2, axis=-1) * (weights > .05)).argmax(axis=-1)
        second = np.take_along_axis(ll, far[..., None, None], axis=2)[..., 0, :]
        for _ in range(3):
            d1 = np.sum((ll-first[..., None, :])**2, axis=-1)
            d2 = np.sum((ll-second[..., None, :])**2, axis=-1)
            group = d1 <= d2
            n1 = (weights * group).sum(axis=-1)
            n2 = total - n1
            first = (ll * (weights*group)[..., None]).sum(axis=-2) / np.maximum(n1[..., None], 1e-8)
            second = (ll * (weights*~group)[..., None]).sum(axis=-2) / np.maximum(n2[..., None], 1e-8)
        fraction = n1 / np.maximum(total, 1e-8)
        separation = np.linalg.norm(first-second, axis=-1)
        residual = np.minimum(np.sum((ll-first[..., None, :])**2, axis=-1),
                              np.sum((ll-second[..., None, :])**2, axis=-1))
        variance = (residual * weights).sum() / max(float(total.sum()), 1.)
        mixed = np.mean(fraction*(1-fraction)*np.minimum(separation, 70)**2)
        # Visible features clipped by a phase shift are charged explicitly.
        mass_loss = abs(float(alpha.sum()-padded_a[sl].sum())) / (q*q)
        score = float(variance + .35*mixed + 12*mass_loss + .03*(abs(dx)+abs(dy)))
        if dx == dy == 0:
            baseline = score
        if best is None or score < best[0] - 1e-6:
            best = (score, dx, dy, aa.copy(), rr.copy(), group.copy(), fraction.copy(),
                    separation.copy(), first.copy(), second.copy())
    score, dx, dy, aa, rr, group, fraction, separation, first, second = best
    weights = aa.reshape(h, w, q*q)
    grouped = group.reshape(h, w, q, q)
    chosen = fraction >= .5
    foreground = np.linalg.norm(first-border_ref, axis=-1) > np.linalg.norm(second-border_ref, axis=-1)
    fg = np.where(foreground[..., None, None], grouped, ~grouped) & (aa > .25)
    # Turning strokes touch adjacent sides; straight strokes touch opposite sides.
    # Both need source support, which excludes isolated dots from line promotion.
    shifted_lab = padded_lab[2+dy:2+dy+h*q, 2+dx:2+dx+w*q]
    if profile == 'lineart' and opaque:
        fg = _blocks(np.linalg.norm(shifted_lab-border_ref, axis=-1) > 20, h, w, q)
    sides = sum(side.astype(int) for side in
                (fg[..., 0, :].any(axis=-1), fg[..., -1, :].any(axis=-1),
                 fg[..., :, 0].any(axis=-1), fg[..., :, -1].any(axis=-1)))
    stroke = (sides >= 2) & (fg.mean(axis=(-2, -1)) >= .06)
    if profile == 'lineart':
        chosen = np.where(stroke, foreground, chosen)
    mask = np.where(chosen[..., None, None], grouped, ~grouped)
    cluster_w = aa * mask
    representative = (rr.astype(float)*cluster_w[..., None]).sum(axis=(-3, -2)) / np.maximum(cluster_w.sum(axis=(-2, -1))[..., None], 1e-8)
    linear_mean = (_linear(rr)*aa[..., None]).sum(axis=(-3, -2)) / np.maximum(aa.sum(axis=(-2, -1))[..., None], 1e-8)
    average = _srgb(linear_mean)
    if profile in ('cartoon', 'lineart'):
        crisp = separation > 10
    else:
        # Keep continuous tones; select one side only for strong coherent edges.
        crisp = (separation > (32 if profile == 'scene' else 26)) & (np.maximum(fraction, 1-fraction) > .68)
    colors = np.where(crisp[..., None], np.rint(representative).astype(np.uint8), average)
    coverage = aa.mean(axis=(-2, -1))
    alpha_support = aa > .25
    alpha_sides = sum(side.astype(int) for side in
                      (alpha_support[..., 0, :].any(axis=-1), alpha_support[..., -1, :].any(axis=-1),
                       alpha_support[..., :, 0].any(axis=-1), alpha_support[..., :, -1].any(axis=-1)))
    thin_alpha = ((alpha_sides >= 2) & (coverage >= .06) & (coverage < .51)
                  & (aa.max(axis=(-2, -1)) > .8))
    coverage[thin_alpha] = .51
    protected = thin_alpha | (stroke if profile == 'lineart' else False)
    if profile == 'lineart' and opaque:
        support = fg
        foreground_cells = stroke | (fg.mean(axis=(-2, -1)) >= .5)
        bridge = _bridge_diagonals(foreground_cells, support, cancelled)
        promote = stroke | bridge
        fg_weight = aa * fg
        fg_rgb = (rr.astype(float)*fg_weight[..., None]).sum(axis=(-3, -2)) / np.maximum(fg_weight.sum(axis=(-2, -1))[..., None], 1e-8)
        colors[promote] = np.rint(fg_rgb[promote]).astype(np.uint8)
        protected |= promote
    elif not opaque:
        bridge = _bridge_diagonals(coverage >= .5, alpha_support, cancelled)
        coverage[bridge] = .51
        protected |= bridge
    # Preserve enclosed negative space at least 1/8 of a target cell. Do not
    # manufacture holes in photographs from small bright skin highlights.
    holes = _enclosed(padded_a[2+dy:2+dy+h*q, 2+dx:2+dx+w*q] < .1, cancelled)
    if profile in ('lineart', 'cartoon') and opaque:
        l = padded_lab[2+dy:2+dy+h*q, 2+dx:2+dx+w*q]
        holes += _enclosed(np.linalg.norm(l-border_ref, axis=-1) < 10, cancelled)
    for points in holes:
        if len(points) < q*q/8:
            continue
        ys, xs = np.array(points).T
        keys, counts = np.unique((ys//q)*w+xs//q, return_counts=True)
        candidates = keys[counts == counts.max()]
        center = np.array([ys.mean()/q, xs.mean()/q])
        centers = np.stack((candidates//w+.5, candidates%w+.5), axis=-1)
        key = candidates[np.sum((centers-center)**2, axis=-1).argmin()]
        cy, cx = divmod(int(key), w)
        protected[cy, cx] = True
        if not opaque:
            coverage[cy, cx] = 0
        elif profile in ('lineart', 'cartoon'):
            colors[cy, cx] = np.rint(np.mean(padded_rgb[2+dy:2+dy+h*q, 2+dx:2+dx+w*q][ys, xs], axis=0)).astype(np.uint8)
    target_lab = _lab_array(colors)
    local_difference = np.zeros((h, w), dtype=np.float32)
    for axis in (0, 1):
        delta = np.linalg.norm(np.diff(target_lab, axis=axis), axis=-1)
        if axis == 0:
            local_difference[1:] = np.maximum(local_difference[1:], delta)
            local_difference[:-1] = np.maximum(local_difference[:-1], delta)
        else:
            local_difference[:, 1:] = np.maximum(local_difference[:, 1:], delta)
            local_difference[:, :-1] = np.maximum(local_difference[:, :-1], delta)
    importance = 1 + np.minimum(local_difference/25, 2)
    importance[protected] = 6
    guide = StructureGuide(protected, importance, (dx/q, dy/q), baseline, score, profile)
    return colors, coverage, guide


def optimize_labels(distances, inverse, active, palette_indices, guide, labs, cancelled):
    """Alternate edge-aware label fitting and real-colour medoid updates twice.

    Unary costs are CIEDE2000. Neighbour agreement is weakened across actual
    source edges. Protected strokes/holes keep their nearest colour assignment.
    Every medoid is an enabled physical bead colour; the budget cannot increase.
    """
    ids = np.full(active.shape, -1, dtype=int)
    ids[active] = inverse
    unary = np.zeros((*active.shape, distances.shape[1]), dtype=np.float32)
    unary[active] = distances[inverse]
    selected = np.asarray(palette_indices).copy()
    labels = np.full(active.shape, -1, dtype=int)
    labels[active] = unary[active][:, selected].argmin(axis=1)
    edges = []
    for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        shifted_lab = np.roll(labs, (dy, dx), (0, 1))
        valid = active & np.roll(active, (dy, dx), (0, 1))
        if dy == 1: valid[0] = False
        if dy == -1: valid[-1] = False
        if dx == 1: valid[:, 0] = False
        if dx == -1: valid[:, -1] = False
        weight = np.exp(-np.sum((labs-shifted_lab)**2, axis=-1)/(2*12**2))*valid*2.5
        edges.append((dy, dx, weight))
    yy, xx = np.indices(active.shape)
    locked = guide.protected & active
    # A well-defined rare accent should not disappear just to save one colour.
    for _ in range(2):
        check(cancelled)
        for parity in (0, 1):
            costs = unary[..., selected]*guide.importance[..., None]
            for dy, dx, weight in edges:
                neighbour = np.roll(labels, (dy, dx), (0, 1))
                costs += weight[..., None]*(np.arange(len(selected)) != neighbour[..., None])
            candidate = costs.argmin(axis=-1)
            change = active & ~locked & ((yy+xx)%2 == parity)
            labels[change] = candidate[change]
        # Cluster medoids use the current spatial assignments, not just counts
        # from independent nearest-colour matching. Locked clusters keep colour.
        for cluster in range(len(selected)):
            members = active & (labels == cluster)
            if not members.any() or (members & locked).any():
                continue
            weights = np.bincount(ids[members], weights=guide.importance[members], minlength=len(distances))
            costs = weights @ distances
            occupied = selected[np.arange(len(selected)) != cluster]
            costs[occupied] = np.inf
            selected[cluster] = int(costs.argmin())
    labels[active] = selected[labels[active]]
    return labels
