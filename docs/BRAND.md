# Proef — brand

*proef* is Dutch for **experiment**, **trial** and **proof**: the three things this tool is about.

## The mark

A **dose–response curve traced through a well plate**.

- **Grid** — the plate. Where an experiment physically happens.
- **Curve with coral nodes** — the result, drawn as a path through the wells.
- **Dashed vertical line** — the gate: the success criterion, registered before any data.
- **Hollow node on the gate** — an honest abstention. The estimate sits where the data cannot say
  which side of the gate it is on, so no claim is made. It is the product's signature idea,
  drawn instead of hidden.

## The wordmark

`proef.` in Inter (semibold, tight tracking). The **o is the hollow node**; the full stop is coral.
The mark and the word say the same thing.

Deliberately *not*: helices, molecules, flasks, lightning bolts, gradients.

## Assets

Everything is drawn by one script from one definition — never hand-edit a PNG:

```sh
node scripts/make_brand_assets.mjs     # needs web/node_modules (Playwright + Inter)
```

| File | Use |
|---|---|
| `proef-banner.png` | README / social card |
| `proef-mark.png` · `proef-mark-onDark.png` | icon only, transparent — light / dark surfaces |
| `proef-mark-tile.png` | icon on its navy tile — avatars, chips |
| `proef-wordmark.png` · `-onDark.png` | title only |
| `proef-lockup.png` · `-onDark.png` | icon + title |
| `favicon.png` | browser tab; simplified mark (no grid) so it survives 16–32 px. Also copied to `web/public/proef-mark.png` |

## Palette

| Token | Hex | Role |
|---|---|---|
| navy | `#0d1117` | dark background, tile |
| coral | `#f9826c` | brand accent: nodes, gate, the o, the full stop |
| ink | `#2a2823` | curve and text on light surfaces |
| paper-white | `#eef1f8` | curve and text on dark surfaces |
| well | `#2a303b` / `#d5d9e0` | plate wells on dark / light |

The workbench UI uses its own teal accent for state and interaction; coral is reserved for the brand.
