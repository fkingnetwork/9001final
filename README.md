# Fuse Bead Studio — automatic Python desktop converter

Python + PySide6 + Pillow + NumPy. Image processing runs locally in the Python
backend on a Qt worker thread. No API server, OpenCV, downloaded models or
network service is needed.

## Run (Python 3.12)

From the project root, reuse the environment or create one with
`python -m venv backend\.venv`:

```powershell
backend\.venv\Scripts\python.exe -m pip install -r requirements.txt
backend\.venv\Scripts\python.exe main.py
```

Startup shows a black terminal-style animation across the main window's entire
content area, adapted from `minimal_boot_v2.py`. The editor title, side panels,
canvas, controls and status bar remain hidden until the animation finishes.
The same window then reveals the complete editor, preserving its size and position.
A rotating
symbol and module-readiness checks precede a Fuse Bead Studio ASCII logo fading
in and out. The animation lasts about 4–5 seconds after the editor is built;
module checks are paced for presentation and may reuse already imported modules.
Editing controls are disabled until it finishes. Press Esc, Space, Enter or click
the animation to skip, or run `main.py --no-animation` to edit immediately.
Qt timers drive playback; no separate loading window or extra dependency is needed.

Drag one local PNG, JPG/JPEG or WEBP image into the dashed upload area, or use
**Choose image**, then **Convert to beads**. Dropping a new image replaces the
source preview; invalid images leave the previous source intact. Automatic processing runs during
conversion, without rectangles, foreground/background strokes or another dialog.
The source file is never modified. **Compare source** shows the original image.

During conversion, the centre display shows actual backend snapshots: source,
edge analysis, foreground mask, sampling grid, bead colours and region cleanup.
Each snapshot directly replaces the previous image, with a small stage caption.
There are no scan lines, fades, decorative overlays, replay delays or completion
popups. The existing progress bar reports computation progress. Once conversion
finishes, the display immediately returns to the editable final pattern. A failed
conversion clears the preview and preserves the previous document.

## Desktop layout

The pinned **Choose image** and **Convert to beads** buttons stay outside the
padded parameter scroller. **Size & Crop**, **Image Adjustments** and
**Automatic Image Processing** collapse instantly; folding a section preserves
all its parameter values. Image Adjustments starts collapsed. Width and height
share one row. The scroller uses a 6px scrollbar, inner spacing and static edge
shading, without transition animations.

The empty canvas supports clicking or pressing Enter/Space to choose an image,
and accepts the same single local PNG/JPG/WEBP drops as the upload area. Drops on
a generated pattern do not replace it. The canvas has a warm grey viewport,
a compact segmented top bar and a grouped painting footer.

The colour list includes aligned swatches, an empty-state message and a summary
card. **Export PNG** contains Pattern / With Grid / With Codes; **Export CSV**
contains Bead List / Matrix. These call the same export handlers as before.
Menus are disabled until a document is available and during conversion.

Visual styling is in `desktop/theme.qss`; the small control arrows/checkmark are
local SVGs in `desktop/assets/`. Keep these files with the Python desktop sources
when copying or packaging the app. `desktop/ui_components.py` contains the
collapsible sections, inset scroller and table/viewport helpers.

## Automatic processing

1. Correct EXIF orientation and choose a sampling mode. Analysis uses a working
   image bounded to 1200 pixels per side to limit memory and background-fill cost.
2. **Remove plain connected background**: estimate a background from at least
   three agreeing corners and learn background noise from robust border
   statistics. **Edge protection** constrains colour-based growth and detects
   brightness/colour boundaries using Sobel gradients at two Gaussian scales.
   Flood only eligible regions connected to the border. This protects dark hair
   and clothing close to black backdrops, and enclosed white details remain beads.
   Inconsistent borders and uniform swatches are left intact.
3. Apply brightness, contrast and saturation. Photo mode optionally applies a
   light median filter to opaque interior pixels, protecting transparent edges.
4. **Keep whole image** (default) fits the complete source with empty padding.
   **Centre crop to fill** is available when cropping is intentional.
5. **Image type**: Automatic checks colour concentration, neutral line drawings,
   native sprites and regularly repeated pixel blocks; it falls back to Photo. Photo uses alpha-weighted area sampling in linear light;
   Cartoon chooses an alpha-weighted dominant colour bin for each grid cell;
   Pixel art uses nearest-neighbour sampling.
6. **Foreground coverage** controls when a partially covered grid cell becomes
   a bead. Foreground colour is independent of the selected background while
   **Transparent pixels become empty** is enabled. For originally opaque images
   with automatically removed backgrounds, disabling it fills each edge cell
   with either its foreground colour or the selected background according to
   coverage. This avoids grey/white fringes from blending the segmentation mask
   into edge beads. Intentional source translucency and other images still
   composite onto the selected background in linear light.
7. **Maximum colours** automatically selects up to the chosen number from the
   enabled real Hama colours, minimizing weighted image colour error with a
   deterministic greedy selection. Zero uses all enabled colours. Match colours
   with Lab + CIEDE2000. Optional Floyd–Steinberg dithering has adjustable strength
   and never assigns beads to empty cells; it defaults to off.
8. **Clean islands up to** merges small four-connected colour islands into larger
   similar neighbours. A colour-distance constraint protects high-contrast
   details. Zero turns cleanup off. Statistics and exports use the final colours.

Grid width and height each support 1–256 beads (up to 256 × 256 = 65,536 beads).
Square presets include 128, 192 and 256; larger patterns require more conversion
time and memory, especially when exporting PNGs with colour codes.

Default settings: automatic background removal, tolerance 12, edge protection
70%, foreground coverage
128/255, whole-image fit, automatic sampling, maximum 24 colours, cleanup up to
2 cells, light photo denoising, no dithering. Background tolerance is Euclidean
Lab distance; final palette matching and island similarity use CIEDE2000.

For hair or clothing being cut away, raise **Edge protection** toward 100%.
For remaining thin background fringes, lower it gradually or adjust background
tolerance. Zero disables adaptive/edge protection and restores colour-only flood
fill. Protection does not synthesize missing hair: if subject and background
pixels are identical with no visible boundary, their separation remains ambiguous.

Plain-background detection is a colour/connected-region method, not semantic
segmentation. It cannot reliably separate a person from a busy scene or separate
a subject that shares the connected background's colour. Disable automatic
background removal for those inputs; use an already transparent PNG if needed.
Likewise, aggressive cleanup can remove small low-contrast intentional details;
reduce its size or turn it off. Dithering preserves gradients through texture and
can make a pattern more laborious to build.

## Small patterns (16–64 cells per side)

**Optimise small patterns (≤64)** is enabled by default when both dimensions
are at most 64. Disable it for an immediate comparison using the existing sampler.
Larger grids use the existing pipeline. Pixel art always retains nearest-neighbour
sampling, including with the optimization enabled. Maximum dimensions remain 256×256.

The five improvements work together:

1. **Material-aware downsampling.** An 8× supersampled, alpha-weighted grid keeps
   continuous regions in linear light and selects coherent colours at strong
   boundaries. Cartoon favours colour regions; Photo retains continuous tones;
   **Logo / line art** promotes traversing strokes; **Landscape** uses a higher
   threshold before replacing a mixed cell with one side of an edge. Landscape
   does not automatically disable background removal: uncheck that control when
   the scene itself should remain.
2. **Grid alignment.** Search the centre and eight quarter-cell phase offsets.
   The objective combines within-cluster colour variance, mixed-boundary cost,
   clipped alpha mass and a small offset penalty. Ties retain the original phase.
   The sampling preview reports the selected phase; the whole picture shifts by
   at most a quarter cell, with edge extension for opaque sources.
3. **Structural details.** Thin paths can turn through adjacent cell sides.
   Diagonal grid fragments are connected only when the source contains a path
   through a candidate bridging cell. Enclosed transparent holes, and enclosed
   background-colour holes in flat/line art, receive a protected cell when their
   source area reaches 1/8 cell. Protected cells survive region cleanup. Strong,
   narrow alpha paths receive minimum 0.51 coverage; the user's higher coverage
   threshold can still exclude them. This may thicken sub-cell strokes by one bead.
4. **Shape and palette fitting.** Important contours receive higher weights in
   colour selection. Two alternating passes fit neighbouring labels and real
   bead-colour medoids. A neighbour penalty smooths weak transitions and falls
   rapidly across genuine source edges; protected details keep their assignments.
   Every result stays within enabled Hama colours and the requested colour budget.
   Explicit dithering bypasses spatial smoothing so the gradient dots remain.
5. **Cross-material regression.** Eight deterministic fixtures cover logo holes
   and accent colour, thin lettering, cartoon, animal, shaded object, landscape,
   pixel sprite and transparent frame. The shaded object and landscape are
   procedural fixtures, not photographs. Local photos can be supplied separately.
   The runner compares existing/optimized output at 16, 32, 48 and 64, writes
   native-size PNGs, enlarged contact sheets, JSON measurements and a report.

Run the complete comparison (outputs are ignored by source control):

```powershell
backend\.venv\Scripts\python.exe -B -m benchmarks.run_small_patterns
# Include additional real local photographs; --image may be repeated:
backend\.venv\Scripts\python.exe -B -m benchmarks.run_small_patterns --image "C:\images\sample.jpg"
```

Results are under `outputs/low-resolution/`. Edge fidelity, reconstruction error,
component/hole counts, singleton counts and timings are reported separately.
Preserving a tiny stroke can increase average colour error, and a legitimate eye
is also a singleton, so these metrics do not form a universal quality score.
At 16×16, detail must be simplified; this method cannot restore information absent
from the source or guarantee readable arbitrary text. Choose the material type
explicitly if automatic classification is unsuitable.

## Architecture

- `main.py`: desktop entry point.
- `desktop/startup.py`: boot animation and deferred application startup.
- `backend/image_processing.py`: immutable Parameters/Cell, automatic background
  detection, sampling, palette selection, dithering, region cleanup and conversion.
  It has no Qt dependency and can also be called directly from Python.
- `backend/low_resolution.py`: adaptive sampling, grid phase search, structural
  guides and alternating spatial/palette fitting.
- `benchmarks/`: deterministic multi-material fixtures and comparison runner.
- `backend/color_science.py`, `backend/palette.py`: colour science and 55 Hama Midi
  reference colours.
- `desktop/app.py`: controls, conversion worker and document controller.
- `desktop/model.py`: document state, edit history, statistics and PNG/CSV exports;
  re-exports the backend conversion API for compatibility.
- `desktop/canvas.py`: bead rendering and mouse coordinate signals.
- `desktop/processing_view.py`: plain intermediate-image display; all Qt image
  rendering stays on the GUI thread.
- `tests/`: image-processing regressions and headless Qt integration tests.
- `hama-codes.png`: optional reference chart, not loaded by the application.

Direct Python usage:

```python
from backend.image_processing import Parameters, convert_image

pattern = convert_image('input.png', Parameters(width=58, height=58, max_colors=16))
```

Conversion parameters are snapshotted and editing is disabled during conversion.
Progress is reported by the worker. Closing during conversion requests
cancellation; close again once it finishes. Threads keep the Qt event loop
available but are not CPU multiprocessing.

Click to paint, Shift-click to pick, erase, Ctrl+Z/Ctrl+Shift+Z to undo/redo.
Grid, codes, zoom/fit, source comparison, PNG variants, CSV material list and CSV
matrix are supported. History retains 200 edits; documents stay in memory until
exported. White beads retain their colour codes; empty exported cells are grey.

Run checks:

```powershell
backend\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

## Design references

This implementation independently combines processing ideas from:

- [pypindou](https://github.com/HansBug/pypindou): automatic colour budgets,
  preprocessing, small-region cleanup and optional dithering.
- [Zippland/perler-beads](https://github.com/Zippland/perler-beads): dominant/average
  cell sampling and border-connected background removal.
- [Fusible-Beads-Studio](https://github.com/yourlin/Fusible-Beads-Studio): whole-image
  fitting, pixel-art sampling and optional error diffusion.

Hama names/codes come from the official Hama Midi chart. RGB/HEX values are
approximate screen references, not calibrated measurements of physical beads.

## Submission

Include `main.py`, `desktop/`, the Python files in `backend/`, `requirements.txt`,
`tests/`, `benchmarks/` and this README. Omit virtual environments, caches, research reports and
personal images. The Hama reference chart is optional.
