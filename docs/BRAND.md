# Proef — brand

*proef* is Dutch for **experiment**, **trial** and **proof**: the three things this tool is about.

## The mark

A **hairline Mondrian grid** — the most famous Dutch abstract composition, used as a map of work.

- **Every cell is one hypothesis experiment.** Blue cells are settled or in progress, blank cells are
  still untested.
- **The single orange cell is the result** — the one worth looking at.
- Hairlines, not heavy rules: the grid should feel precise and quiet, like a lab notebook ruling.

Deliberately *not*: helices, molecules, flasks, charts, gradients.

## The wordmark

`proef.` in Inter (medium, tight tracking), Delft blue on light and pale blue-white on dark, with an
**orange full stop** that repeats the accent of the mark. Lowercase on purpose: the p and f give the
word its rhythm, and it sits quietly beside the hairline grid.

## How to write the name

| Where | Form | Example |
|---|---|---|
| The logo / wordmark | lowercase, with the orange full stop | `proef.` |
| Anything technical | lowercase, no full stop | `pip install proef`, `proef campaign …`, `import proef`, `PROEF_DATA_DIR`, `proef.db` |
| Prose and headings | capital P, no full stop | "Proef runs the experiment and a scientist decides." |

The full stop belongs to the logo only. Never write "Proef." as the name: it collides with sentence
punctuation and breaks every technical identifier.

## Colour

| Token | Light | Dark | Role |
|---|---|---|---|
| paper / night | `#f7f5ef` | `#0b1020` | tile background |
| line | `#1f3a8a` | `#7d94d6` | grid hairlines |
| deep blue | `#1f3a8a` | `#2b4fc4` | tall left cell |
| mid blue | `#6f93d6` | `#b4c9f5` | corner cell |
| pale blue | `#dfe8f8` | `#1a2860` | bottom bar |
| **orange** | `#ff8a1f` | `#ff8a1f` | **the result — the only accent** |

On dark the blues are separated by *lightness* (vivid / pale / deep), not hue, so no two merge.
Orange is blue's complement, so it carries on both backgrounds and in 16–48 px icons. It is
deliberately not one of the workbench's verdict colours (validated blue, refuted vermilion,
abstained purple), so the logo never reads as a verdict.

## Assets

Everything is drawn by one script from one definition — never hand-edit a PNG:

```sh
node scripts/make_brand_assets.mjs     # needs web/node_modules (Playwright + Inter)
```

| File | Use |
|---|---|
| `proef-banner.png` | README / social card |
| `proef-mark.png` · `proef-mark-onDark.png` | grid only, transparent — light / dark surfaces |
| `proef-mark-tile.png` · `proef-mark-tile-light.png` | grid on its tile — avatars, chips |
| `proef-wordmark.png` · `-onDark.png` | title only |
| `proef-lockup.png` · `-onDark.png` | grid + title |
| `favicon.png` | browser tab; plain filled blocks instead of hairlines so it survives 16–32 px. Also written to `web/public/proef-mark.png` (the workbench header) |

The workbench UI keeps its own teal accent for state and interaction; orange is reserved for the brand.
