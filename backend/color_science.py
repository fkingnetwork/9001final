from __future__ import annotations

import math

import numpy as np

RgbColor = tuple[int, int, int]
LabColor = tuple[float, float, float]


def _linearize_srgb(channel: int) -> float:
    normalized = channel / 255
    if normalized > 0.04045:
        return ((normalized + 0.055) / 1.055) ** 2.4
    return normalized / 12.92


def _lab_transform(value: float) -> float:
    return value ** (1 / 3) if value > 0.008856 else 7.787 * value + 16 / 116


def rgb_to_lab(rgb: RgbColor) -> LabColor:
    """Convert an sRGB colour to CIE L*a*b* using a D65 reference white."""
    red, green, blue = (_linearize_srgb(channel) for channel in rgb)
    x = (red * 0.4124 + green * 0.3576 + blue * 0.1805) / 0.95047
    y = red * 0.2126 + green * 0.7152 + blue * 0.0722
    z = (red * 0.0193 + green * 0.1192 + blue * 0.9505) / 1.08883
    x, y, z = (_lab_transform(component) for component in (x, y, z))
    return 116 * y - 16, 500 * (x - y), 200 * (y - z)


def _hue_angle(a_component: float, b_component: float) -> float:
    return math.degrees(math.atan2(b_component, a_component)) % 360


def delta_e_2000(first: LabColor, second: LabColor) -> float:
    """Return the perceptual CIEDE2000 difference between two L*a*b* colours."""
    lightness_1, a_1, b_1 = first
    lightness_2, a_2, b_2 = second
    radians = math.pi / 180

    chroma_1 = math.hypot(a_1, b_1)
    chroma_2 = math.hypot(a_2, b_2)
    average_chroma = (chroma_1 + chroma_2) / 2
    compensation = 0.5 * (
        1 - math.sqrt(average_chroma**7 / (average_chroma**7 + 25**7))
    )

    adjusted_a_1 = (1 + compensation) * a_1
    adjusted_a_2 = (1 + compensation) * a_2
    adjusted_chroma_1 = math.hypot(adjusted_a_1, b_1)
    adjusted_chroma_2 = math.hypot(adjusted_a_2, b_2)
    hue_1 = _hue_angle(adjusted_a_1, b_1)
    hue_2 = _hue_angle(adjusted_a_2, b_2)

    lightness_delta = lightness_2 - lightness_1
    chroma_delta = adjusted_chroma_2 - adjusted_chroma_1
    raw_hue_delta = hue_2 - hue_1
    if abs(raw_hue_delta) <= 180:
        hue_delta = raw_hue_delta
    else:
        hue_delta = raw_hue_delta + (360 if hue_2 <= hue_1 else -360)
    hue_distance = (
        2 * math.sqrt(adjusted_chroma_1 * adjusted_chroma_2)
        * math.sin(hue_delta * radians / 2)
    )

    average_lightness = (lightness_1 + lightness_2) / 2
    average_adjusted_chroma = (adjusted_chroma_1 + adjusted_chroma_2) / 2
    if abs(hue_1 - hue_2) <= 180:
        average_hue = (hue_1 + hue_2) / 2
    elif hue_1 + hue_2 < 360:
        average_hue = (hue_1 + hue_2 + 360) / 2
    else:
        average_hue = (hue_1 + hue_2 - 360) / 2

    hue_weight = (
        1 - 0.17 * math.cos((average_hue - 30) * radians)
        + 0.24 * math.cos(2 * average_hue * radians)
        + 0.32 * math.cos((3 * average_hue + 6) * radians)
        - 0.2 * math.cos((4 * average_hue - 63) * radians)
    )
    lightness_weight = 1 + (
        0.015 * (average_lightness - 50) ** 2
        / math.sqrt(20 + (average_lightness - 50) ** 2)
    )
    chroma_weight = 1 + 0.045 * average_adjusted_chroma
    hue_scale = 1 + 0.015 * average_adjusted_chroma * hue_weight
    rotation = -2 * math.sqrt(
        average_adjusted_chroma**7 / (average_adjusted_chroma**7 + 25**7)
    ) * math.sin(60 * math.exp(-((average_hue - 275) / 25) ** 2) * radians)

    normalized_lightness = lightness_delta / lightness_weight
    normalized_chroma = chroma_delta / chroma_weight
    normalized_hue = hue_distance / hue_scale
    return math.sqrt(
        normalized_lightness**2
        + normalized_chroma**2
        + normalized_hue**2
        + rotation * normalized_chroma * normalized_hue
    )


def _linear(rgb):
    rgb = np.asarray(rgb, dtype=np.float32) / 255
    return np.where(rgb <= .04045, rgb / 12.92, ((rgb + .055) / 1.055) ** 2.4)


def _srgb(linear):
    linear = np.clip(linear, 0, 1)
    return np.clip(np.rint(255 * np.where(linear <= .0031308, linear * 12.92,
                                         1.055 * linear ** (1 / 2.4) - .055)), 0, 255).astype(np.uint8)


def _lab_array(rgb):
    linear = _linear(rgb)
    xyz = linear @ np.array([[.4124, .2126, .0193], [.3576, .7152, .1192],
                              [.1805, .0722, .9505]], dtype=np.float32)
    xyz /= np.array([.95047, 1, 1.08883], dtype=np.float32)
    value = np.where(xyz > .008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack((116 * value[..., 1] - 16,
                     500 * (value[..., 0] - value[..., 1]),
                     200 * (value[..., 1] - value[..., 2])), axis=-1)


