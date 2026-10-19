# DDD Tachograph Reader: icon set

Monochrome, flat line icons for the desktop interface. They replace the emoji
used before, so they look the same on every platform.

## Contents

- `png/<size>/<name>.png`: every icon at 16, 20, 24, 32, 40 and 48 px square.
  PNG, 8-bit RGBA, fully transparent background, no border, no shadow.
- `svg/<name>.svg`: editable vector masters, one per icon (28 files).
- `svg/20/<name>.svg`: pixel-snapped masters used for the 20 px PNGs.
- `svg/16/<name>.svg`: simplified 16 px masters for the six softest icons
  (`toolbar-language`, `generation`, `status-ok`, `status-error`,
  `status-unknown`, `sensor`). The 16 px and 20 px PNGs of those six come from
  these; sizes 24 to 48 px keep the original masters.

26 icons are delivered as specified, plus 2 optional accent-blue variants:
`summary-accent` and `security-accent`. The optional `#37474f` variant is not
included.

## Colours

| Group | Icons | Colour |
|-------|-------|--------|
| A: sections | `summary` … `search` (19 icons) | `#1c2733` |
| B: status | `status-ok` | `#2e7d32` |
| B: status | `status-warning` | `#e65100` |
| B: status | `status-error` | `#c62828` |
| B: status | `status-unknown` | `#90a4ae` |
| C: toolbar | `toolbar-open`, `toolbar-export`, `toolbar-language` | `#1c2733` |
| Accent (optional) | `summary-accent`, `security-accent` | `#1565c0` |

## Grid and stroke

- Masters are drawn on a 16-unit grid with a 1.5-unit stroke, round caps and
  round joins. Straight strokes are snapped to the pixel grid so that each one
  fully covers one pixel column or row.
- Corner radius is 1 unit (about 1 px at 16 px) across the whole set.
- The art sits inside a 1-unit margin, so the margin is 1 px at 16 px, about
  2 px at 32 px and 3 px at 48 px.
- Larger sizes are rendered from the same master, so the stroke scales
  proportionally: about 1.9 px at 20 px and 4.5 px at 48 px.
- 20 px uses its own 20-unit master (`svg/20/`), made from the 16-unit master by
  a snapping script: scale x1.25, then snap every path endpoint and rect edge to
  the pixel grid. Stroke is 1.875 px there. This is not a freehand redraw.

## Status icons: shapes for greyscale

The four status icons are told apart by shape, not only by colour:

- `status-ok`: circle with a check mark
- `status-warning`: triangle with an exclamation mark
- `status-error`: circle with a cross
- `status-unknown`: circle with a question mark

## Known limitations

- **Softness at 16 px.** The six softest icons were redrawn with simpler
  geometry: 2 px strokes on whole-pixel coordinates, except `toolbar-language`,
  which keeps 1.5 px so the globe does not fill in. Curves and diagonals still
  leave partly covered pixels. The set therefore mixes 2 px and 1.5 px strokes
  at 16 px.
- **Pixel alignment at 16 px.** The 16 px master snaps straight strokes to the
  pixel grid, but a 1.5 px stroke cannot be fully crisp: it always leaves a
  partly covered pixel on each edge. About 80% of the drawn pixels at 16 px
  are partly transparent. A crisp 16 px set needs a 1 px or 2 px stroke, which
  the brief rules out. This is a decision for the brief, not a fix in the
  artwork.
- **Low contrast: `status-unknown`.** `#90a4ae` on white gives about 2.6:1,
  below the 3:1 that WCAG 1.4.11 asks for non-text graphics. The shape carries
  the meaning, but a darker grey would be needed for strict compliance. The
  palette was used as specified.
- **`recovered`** is a counter-clockwise arrow with a plus inside. The plus is
  what separates it from a plain undo or refresh arrow. It has no handle, so it
  cannot be mistaken for `search`.
- **`raw-data`** is a dashed outline, a stand-in for undecoded data.
- **`completeness`** is a 3/4 filled disc inside a ring. The small fill is
  intentional, for legibility at 16 px.
- **`tachograph`** is an open gauge arc with a needle. It is deliberately not a
  full clock face.
