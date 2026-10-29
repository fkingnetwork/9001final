from __future__ import annotations

from typing import Any

from .color_science import rgb_to_lab

# Digital screen approximations of the official Hama Midi colour chart.
PALETTE_DATA = [
    ("01", "White", "#f2f0e8"), ("02", "Cream", "#e8d7ad"),
    ("03", "Yellow", "#f5d328"), ("04", "Orange", "#ed7a28"),
    ("05", "Red", "#d83b35"), ("06", "Pink", "#e995b2"),
    ("07", "Purple", "#73509b"), ("08", "Blue", "#244c91"),
    ("09", "Light blue", "#4e9fd0"), ("10", "Green", "#318558"),
    ("11", "Light green", "#75bd62"), ("12", "Brown", "#7b4b32"),
    ("17", "Grey", "#898b8c"), ("18", "Black", "#242526"),
    ("20", "Reddish brown", "#a14e33"), ("21", "Light brown", "#b98257"),
    ("22", "Dark red", "#9c2632"), ("26", "Matt rose", "#dc8f9d"),
    ("27", "Beige", "#d8bd91"), ("28", "Dark green", "#24563e"),
    ("29", "Claret", "#8d344e"), ("30", "Burgundy", "#6f273a"),
    ("31", "Turquoise", "#28a5a3"), ("32", "Neon fuchsia", "#ed3b92"),
    ("33", "Cerise", "#c82b63"), ("34", "Neon yellow", "#e8ef3d"),
    ("35", "Neon red", "#ef4a34"), ("36", "Neon blue", "#2879d0"),
    ("37", "Neon green", "#5bc83f"), ("38", "Neon orange", "#ff7b28"),
    ("42", "Fluorescent green", "#c7e334"),
    ("43", "Pastel yellow", "#f3df78"), ("44", "Pastel red", "#e8796e"),
    ("45", "Pastel purple", "#a98dc3"), ("46", "Pastel blue", "#82b6d1"),
    ("47", "Pastel green", "#9acb93"), ("48", "Pastel pink", "#efb5c3"),
    ("49", "Azure", "#347ea7"), ("60", "Teddybear brown", "#b68b54"),
    ("70", "Light grey", "#babbbc"), ("71", "Dark grey", "#575b60"),
    ("75", "Light nougat", "#d0a681"), ("76", "Nougat", "#b97b61"),
    ("77", "Cloudy white", "#dce2dc"),
    ("78", "Light peach", "#efb18f"), ("79", "Apricot", "#e89a68"),
    ("82", "Plum", "#724263"), ("83", "Petrol blue", "#266575"),
    ("84", "Olive green", "#6f7b45"), ("95", "Pastel rose", "#d8a9af"),
    ("96", "Pastel lilac", "#b9a7c6"), ("97", "Pastel ice blue", "#a9ced5"),
    ("98", "Pastel mint", "#a7d1bd"), ("101", "Eucalyptus", "#6c9980"),
    ("102", "Forest green", "#245c46"),
]


def hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[index:index + 2], 16) for index in (1, 3, 5))


def build_bead_colors() -> list[dict[str, Any]]:
    colors = []
    for code, name, display_hex in PALETTE_DATA:
        rgb = hex_to_rgb(display_hex)
        colors.append(
            {
                "brand": "HAMA", "series": "Midi", "code": code,
                "name": name, "displayHex": display_hex,
                "rgb": dict(zip(("r", "g", "b"), rgb)), "lab": rgb_to_lab(rgb),
            }
        )
    return colors


BEAD_COLORS = build_bead_colors()
