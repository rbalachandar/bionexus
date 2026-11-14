#!/usr/bin/env node
/**
 * Draws the whole Proef logo family from one definition (no pixel cropping, no hand edits).
 *
 *   mark          a dose–response curve traced through a well plate; the node that sits on the
 *                 gate is hollow — an honest abstention
 *   wordmark      "proef." where the o is that hollow node
 *
 * Usage:  node scripts/make_brand_assets.mjs        (needs web/node_modules: Playwright + Inter)
 */
import { chromium } from '../web/node_modules/@playwright/test/index.mjs'
import { mkdtempSync, writeFileSync, mkdirSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const OUT = join(ROOT, 'assets', 'logo')
const FONT = join(ROOT, 'web/node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2')
const CORAL = '#f9826c', NAVY = '#0d1117', PANEL = '#262c36'
const T = {
  dark: { grid: '#2a303b', curve: '#eef1f8', text: '#eef1f8', sub: '#8b94a3' },
  light: { grid: '#d5d9e0', curve: '#2a2823', text: '#2a2823', sub: '#6b7280' },
}
const sig = (x) => 1 / (1 + Math.exp(-(x - 2.5) * 1.25))

/** The mark, in a 240-unit box. grid=false gives the simplified small-size version. */
function mark(t, { grid = true } = {}) {
  const s = 32, x0 = 40, y0 = 40
  const at = (i) => [x0 + i * s, y0 + (5 - sig(i) * 5) * s]
  let d = ''
  for (let k = 0; k <= 100; k++) { const [x, y] = at(k / 20); d += `${k ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)} ` }
  const nodes = [0, 1, 2, 3, 4, 5].map((i) => [x0 + i * s, y0 + (5 - Math.round(sig(i) * 5)) * s])
  const [hx, hy] = nodes[3]
  let o = ''
  if (grid) for (let i = 0; i < 6; i++) for (let j = 0; j < 6; j++) o += `<circle cx="${x0 + i * s}" cy="${y0 + j * s}" r="5.5" fill="${t.grid}"/>`
  o += `<mask id="m"><rect width="240" height="240" fill="#fff"/><circle cx="${hx}" cy="${hy}" r="${grid ? 10 : 12}" fill="#000"/></mask>`
  o += `<line x1="${hx}" y1="20" x2="${hx}" y2="220" stroke="${CORAL}" stroke-width="2.5" stroke-dasharray="5 5" opacity=".75"/>`
  o += `<path d="${d}" fill="none" stroke="${t.curve}" stroke-width="${grid ? 5 : 9}" stroke-linecap="round" stroke-linejoin="round" mask="url(#m)"/>`
  nodes.forEach(([x, y], i) => {
    o += i === 3 ? `<circle cx="${x}" cy="${y}" r="${grid ? 10 : 13}" fill="none" stroke="${CORAL}" stroke-width="${grid ? 4 : 7}"/>`
      : `<circle cx="${x}" cy="${y}" r="${grid ? 7.5 : 11}" fill="${CORAL}"/>`
  })
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 240">${o}</svg>`
}

/** "proef." with the o as the hollow node. size = font-size in px. */
const word = (t, size) => `<span class="w" style="font-size:${size}px;color:${t.text}">pr<svg viewBox="0 0 100 100" style="width:.585em;height:.585em;margin:0 .02em;vertical-align:-.012em"><circle cx="50" cy="50" r="38" fill="none" stroke="${CORAL}" stroke-width="19"/></svg>ef<i style="color:${CORAL};font-style:normal">.</i></span>`

const tile = (px, simple) => `<div style="width:${px}px;height:${px}px;border-radius:${px * .23}px;background:${NAVY};display:flex;align-items:center;justify-content:center"><div style="width:${px * (simple ? .8 : .86)}px">${mark(T.dark, { grid: !simple })}</div></div>`

const assets = {
  'proef-mark.png': [`<div style="width:512px">${mark(T.light)}</div>`, 512, 512],
  'proef-mark-onDark.png': [`<div style="width:512px">${mark(T.dark)}</div>`, 512, 512],
  'proef-mark-tile.png': [tile(512), 512, 512],
  'favicon.png': [tile(128, true), 128, 128],
  'proef-wordmark.png': [word(T.light, 200), null, null],
  'proef-wordmark-onDark.png': [word(T.dark, 200), null, null],
  'proef-lockup.png': [`<div style="display:flex;align-items:center;gap:36px"><div style="width:260px">${mark(T.light)}</div>${word(T.light, 200)}</div>`, null, null],
  'proef-lockup-onDark.png': [`<div style="display:flex;align-items:center;gap:36px"><div style="width:260px">${mark(T.dark)}</div>${word(T.dark, 200)}</div>`, null, null],
  'proef-banner.png': [`<div style="width:1080px;height:400px;box-sizing:border-box;border-radius:28px;border:2px solid ${PANEL};background:${NAVY} radial-gradient(#1b212b 1.2px,transparent 1.4px) 0 0/22px 22px;display:flex;align-items:center;padding-left:84px;gap:64px"><div style="width:230px;flex:none">${mark(T.dark)}</div><div>${word(T.dark, 150)}<div style="margin-top:14px;font:500 21px Inter;letter-spacing:.3em;color:${T.dark.sub}">AGENTIC SCIENCE FRAMEWORK</div></div></div>`, null, null],
}

const dir = mkdtempSync(join(tmpdir(), 'proef-brand-'))
const html = `<html><head><style>@font-face{font-family:Inter;src:url(file://${FONT});font-weight:100 900}
body{margin:0;background:transparent}.a{display:inline-block;margin:20px}.w{font:640 1em/1 Inter;letter-spacing:-.035em;white-space:nowrap}
.w svg{display:inline-block}</style></head><body>${Object.entries(assets).map(([n, [h]]) => `<div class="a" id="${n}">${h}</div>`).join('')}</body></html>`
writeFileSync(join(dir, 'a.html'), html)
mkdirSync(OUT, { recursive: true })
const b = await chromium.launch({ channel: 'msedge' })
const p = await b.newPage({ viewport: { width: 1400, height: 900 }, deviceScaleFactor: 1 })
await p.goto('file://' + join(dir, 'a.html'))
await p.evaluate(() => document.fonts.ready)
for (const n of Object.keys(assets)) {
  await p.locator(`[id="${n}"]`).screenshot({ path: join(OUT, n), omitBackground: true })
  console.log('wrote', n)
}
// the small tile also serves the workbench header and favicon
await p.locator('[id="favicon.png"]').screenshot({ path: join(ROOT, 'web/public/proef-mark.png'), omitBackground: true })
await b.close()
