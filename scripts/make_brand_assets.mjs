#!/usr/bin/env node
/**
 * Draws the whole Proef logo family from one definition (no pixel cropping, no hand edits).
 *
 *   mark      a hairline Mondrian grid: every cell is one hypothesis experiment. Most are
 *             untested or settled in quiet blues; the single orange cell is the result.
 *   wordmark  "proef." in Inter, Delft blue (light) / pale blue-white (dark), with an orange full stop
 *
 * Usage:  node scripts/make_brand_assets.mjs     (needs web/node_modules: Playwright + Inter)
 */
import { chromium } from '../web/node_modules/@playwright/test/index.mjs'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = join(ROOT, 'assets', 'logo')
const FONT = join(ROOT, 'web/node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2')
const ACCENT = '#ff8a1f'

// light: Delft-tile blues on bone paper. dark: separated by lightness so no two blues merge.
const T = {
  light: { bg: '#f7f5ef', line: '#1f3a8a', text: '#1f3a8a', sub: '#5b6478', A: '#1f3a8a', G: '#6f93d6', F: '#dfe8f8' },
  dark: { bg: '#0b1020', line: '#7d94d6', text: '#e9eefc', sub: '#8b94a3', A: '#2b4fc4', G: '#b4c9f5', F: '#1a2860' },
}
// [id, x, y, w, h] in a 240-unit box. D is the result.
const CELLS = [['A', 24, 24, 52, 104], ['B', 24, 128, 52, 88], ['C', 76, 24, 140, 44], ['D', 76, 68, 64, 88],
  ['E', 140, 68, 76, 88], ['F', 76, 156, 96, 60], ['G', 172, 156, 44, 60]]

/** hairline = the full grid with 1px-ish edges; small = plain filled blocks that survive 16–32 px. */
function mark(t, { small = false } = {}) {
  // small sizes: every block must stay visible on the navy tile, so the deep cell is lifted
  const lightTile = t === T.light
  const fill = small
    ? (lightTile ? { A: '#1f3a8a', D: ACCENT, G: '#bcd0f2', F: '#6f93d6' } : { A: '#2b4fc4', D: ACCENT, G: '#cfdcfa', F: '#5b7fe0' })
    : { A: t.A, D: ACCENT, G: t.G, F: t.F }
  let o = ''
  for (const [k, x, y, w, h] of CELLS) {
    if (small) { if (fill[k]) o += `<rect x="${x + 2.5}" y="${y + 2.5}" width="${w - 5}" height="${h - 5}" rx="2" fill="${fill[k]}"/>` }
    else o += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill[k] ?? 'none'}" stroke="${t.line}" stroke-width="1.3"/>`
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${small ? '20 20 200 200' : '0 0 240 240'}">${o}</svg>`
}
const word = (t, size) => `<span class="w" style="font-size:${size}px;color:${t.text}">proef<i style="color:${ACCENT};font-style:normal">.</i></span>`
const tile = (t, px, small) => `<div style="width:${px}px;height:${px}px;border-radius:${px * .23}px;background:${t.bg};box-sizing:border-box;${t === T.light ? 'border:2px solid #e3dfd2;' : ''}display:flex;align-items:center;justify-content:center"><div style="width:${px * (small ? .74 : .8)}px">${mark(t, { small })}</div></div>`
const lockup = (t, w = 260, size = 200) => `<div style="display:flex;align-items:center;gap:40px"><div style="width:${w}px">${mark(t)}</div>${word(t, size)}</div>`

const assets = {
  'proef-mark.png': [`<div style="width:512px">${mark(T.light)}</div>`],
  'proef-mark-onDark.png': [`<div style="width:512px">${mark(T.dark)}</div>`],
  'proef-mark-tile.png': [tile(T.dark, 512, false)],
  'proef-mark-tile-light.png': [tile(T.light, 512, false)],
  'favicon.png': [tile(T.dark, 128, true)],
  'favicon-light.png': [tile(T.light, 128, true)],
  'proef-wordmark.png': [word(T.light, 200)],
  'proef-wordmark-onDark.png': [word(T.dark, 200)],
  'proef-lockup.png': [lockup(T.light)],
  'proef-lockup-onDark.png': [lockup(T.dark)],
  'proef-banner.png': [`<div style="width:1080px;height:400px;box-sizing:border-box;border-radius:28px;border:2px solid #262c36;background:${T.dark.bg} radial-gradient(#171e33 1.2px,transparent 1.4px) 0 0/22px 22px;display:flex;align-items:center;padding-left:92px;gap:70px"><div style="width:224px;flex:none">${mark(T.dark)}</div><div>${word(T.dark, 150)}<div style="margin-top:16px;font:500 21px Inter;letter-spacing:.3em;color:${T.dark.sub}">AGENTIC SCIENCE FRAMEWORK</div></div></div>`],
}

const dir = mkdtempSync(join(tmpdir(), 'proef-brand-'))
writeFileSync(join(dir, 'a.html'), `<html><head><style>@font-face{font-family:Inter;src:url(file://${FONT});font-weight:100 900}
body{margin:0;background:transparent}.a{display:inline-block;margin:20px}.w{font:500 1em/1 Inter;letter-spacing:-.03em;white-space:nowrap;padding-right:.07em}</style></head>
<body>${Object.entries(assets).map(([n, [h]]) => `<div class="a" id="${n}">${h}</div>`).join('')}</body></html>`)
mkdirSync(OUT, { recursive: true })
const b = await chromium.launch({ channel: 'msedge' })
const p = await b.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 })
await p.goto('file://' + join(dir, 'a.html'))
await p.evaluate(async () => { await document.fonts.load('500 100px Inter'); await document.fonts.load('500 21px Inter'); await document.fonts.ready })
for (const n of Object.keys(assets)) {
  await p.locator(`[id="${n}"]`).screenshot({ path: join(OUT, n), omitBackground: true })
  console.log('wrote', n)
}
await p.locator('[id="favicon.png"]').screenshot({ path: join(ROOT, 'web/public/proef-mark.png'), omitBackground: true })   // header + browser tab
await p.locator('[id="favicon-light.png"]').screenshot({ path: join(ROOT, 'web/public/proef-mark-light.png'), omitBackground: true })   // header icon in the light theme
await b.close()
