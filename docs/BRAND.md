# BioNexus — brand

## The mark: the gated loop

Three shapes, one argument:

- **Ring** — the design–make–test–analyze cycle, endless by design
- **Gate bar** (the only gap in the ring) — every piece of evidence passes
  one non-bypassable gate to count; the accent colour marks it as the
  active element
- **Nexus dot** — the centre where verified evidence becomes recorded
  knowledge; also the period in `bionexus.`

## The wordmark: the mark hides in the word

`bionexus.` is drawn as a custom geometric monoline (same stroke weight and
round caps as the mark) — and the **o is the gated loop**: ring, gate bar
rising like an ascender, nexus dot at its center. The i-dot and the final
period are teal: three accents, one system. The word *is* the argument.

Deliberately *not*: helices, molecules, lightning bolts, gradients, or
any emoji-adjacent biology stock vocabulary. The mark survives: 16px
favicon, single-colour etching, dark mode, embroidery.

## Assets (all derived from the banner — never hand-edit)

Source of truth: `assets/logo/bionexus-banner.png` (dark navy card,
matrix-grid icon with coral path dots, "bionexus." wordmark).
Regenerate everything with `python scripts/make_brand_assets.py`:

| File | Use |
|---|---|
| `bionexus-banner.png` | README / social — the canonical banner (icon + title + subtitle) |
| `bionexus-mark.png` | icon only, transparent — light surfaces (workbench header) |
| `bionexus-mark-tile.png` | icon on its navy panel — chips, avatars |
| `bionexus-wordmark.png` | title only, ink recolor — light surfaces |
| `bionexus-wordmark-onDark.png` | title only, original white + coral — dark surfaces |
| `bionexus-lockup.png` | icon + title, light-surface recolor |
| `bionexus-lockup-onDark.png` | icon + title, original colors |
| `favicon.png` | browser tab — icon on a navy rounded square |

## Palette

Brand (from the banner):

| Token | Hex | Role |
|---|---|---|
| navy | `#0d1117` | deep background (icon panel, favicon) |
| panel | `#191e26` | card background |
| coral | `#f9826c` | the path dots, "nexus." — brand accent |
| snow | `#f0f6fc` | "bio", path lines — dark-surface type |

Workbench (light theme, status semantics in `docs/UX.md` §8):

| Token | Hex | Role |
|---|---|---|
| ink | `#2a2823` | type, rules |
| paper | `#f3f1ea` | background |
| card | `#faf8f2` | surfaces |
| teal | `#1f7a86` | progress / autonomous accents |

Wordmark: lowercase, geometric sans, weight 600; "bio" light,
"nexus" coral, sentence-final coral period.
