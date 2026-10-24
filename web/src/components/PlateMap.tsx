// Compact plate map: well GEOMETRY + mapping coverage, icon + word (never
// color alone — UX doc §8/§9; accessible via per-cell text + titles).
export interface WellCell {
  well: string
  sample: string
  conc_um: number | null
  value: number | null
  control: 'pos' | 'neg' | null
  channel?: string | null
}

const ROWS = 'ABCDEFGHIJKLMNOP'

function glyph(w: WellCell | undefined): { sym: string; kind: string } {
  if (!w) return { sym: '', kind: 'no reading' }
  if (w.control === 'pos') return { sym: 'P', kind: 'positive control' }
  if (w.control === 'neg') return { sym: '−', kind: 'blank / negative control' }
  if (w.conc_um == null) return { sym: '?', kind: 'sample without dose — layout missing' }
  return { sym: '●', kind: `${w.sample} @ ${w.conc_um} µM` }
}

export default function PlateMap({ wells }: { wells: WellCell[] }) {
  if (!wells.length) return null
  const byWell = new Map(wells.map((w) => [w.well.toUpperCase(), w]))
  let maxCol = 12
  for (const w of wells) {
    const m = /^([A-P])(\d{1,2})$/i.exec(w.well)
    if (m) maxCol = Math.max(maxCol, Number(m[2]))
  }
  const maxRow = Math.max(...wells.map((w) => {
    const m = /^([A-P])/i.exec(w.well)
    return m ? ROWS.indexOf(m[1].toUpperCase()) + 1 : 1
  }))
  const S = 17, PAD = 16
  const W = PAD + maxCol * S + 4, H = PAD + maxRow * S + 4

  const cells = []
  for (let r = 0; r < maxRow; r++) {
    for (let c = 1; c <= maxCol; c++) {
      const name = `${ROWS[r]}${c}`
      const w = byWell.get(name)
      const g = glyph(w)
      cells.push(
        <g key={name} role="img" aria-label={`${name}: ${g.kind}`}>
          <title>{`${name} — ${g.kind}`}</title>
          <rect x={PAD + (c - 1) * S} y={PAD + r * S} width={S - 2} height={S - 2}
            rx={w && !w.control ? (S - 2) / 2 : 2}
            fill={w ? 'var(--brand-tint)' : 'var(--card)'}
            stroke={w ? 'var(--line)' : 'var(--border)'}
            strokeDasharray={w ? undefined : '2 2'} />
          <text x={PAD + (c - 1) * S + (S - 2) / 2}
            y={PAD + r * S + (S - 2) / 2 + 3}
            fontSize={w && !w.control ? 8 : 9} textAnchor="middle"
            fill={w?.control ? 'var(--muted)' : 'var(--brand)'}>
            {g.sym}
          </text>
        </g>)
    }
  }
  const labels = []
  for (let r = 0; r < maxRow; r++)
    labels.push(<text key={`r${r}`} x={PAD - 5} y={PAD + r * S + 11}
      fontSize={8} textAnchor="end" fill="var(--muted)">{ROWS[r]}</text>)
  for (let c = 1; c <= maxCol; c++)
    labels.push(<text key={`c${c}`} x={PAD + (c - 1) * S + 7} y={PAD - 5}
      fontSize={8} textAnchor="middle" fill="var(--muted)">{c}</text>)

  return (
    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', alignItems: 'start' }}>
      <svg width={W} height={H} style={{ flex: 'none' }}
        role="group" aria-label="plate map of mapped and unmapped wells">
        {cells}{labels}
      </svg>
      <div style={{ fontSize: 11, display: 'grid', gap: 3 }} className="muted">
        <span><strong>●</strong> mapped sample well (hover for compound + dose)</span>
        <span><strong>P</strong> positive (full-response) control</span>
        <span><strong>−</strong> blank / negative control</span>
        <span><strong>?</strong> sample without dose — needs a plate layout</span>
        <span><strong style={{ letterSpacing: 2 }}>┄</strong> no reading for this well</span>
      </div>
    </div>
  )
}
