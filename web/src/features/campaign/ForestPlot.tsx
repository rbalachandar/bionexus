import { scaleLinear, scaleLog } from '@visx/scale'
import { AxisBottom } from '@visx/axis'
import { ParentSize } from '@visx/responsive'
import type { Hyp } from './format'
import { niceLogTicks, sig } from './format'

const COLOR: Record<string, string> = {
  confirmed: 'var(--ok)', validated: 'var(--ok)', refuted: 'var(--bad)', abstained: 'var(--abstain)',
}
export const ROW_H = 44
export const AXIS_H = 34

type Row = { id: string; est: number | null; lo: number | null; hi: number | null; state: string }

function Marker({ x, y, state, r = 5 }: { x: number; y: number; state: string; r?: number }) {
  const c = COLOR[state] ?? 'var(--faint)'
  // distinct SHAPES as well as colours: circle = claimed, square = refuted, diamond = abstained
  if (state === 'refuted') return <rect x={x - r} y={y - r} width={2 * r} height={2 * r} fill={c} />
  if (state === 'abstained')
    return <path d={`M${x},${y - r - 1} L${x + r + 1},${y} L${x},${y + r + 1} L${x - r - 1},${y} Z`} fill="var(--surface)" stroke={c} strokeWidth={2} />
  return <circle cx={x} cy={y} r={r} fill={c} />
}

function Plot({ width, rows, gate, direction, unit }: {
  width: number; rows: Row[]; gate: number | null; direction: 'min' | 'max' | null; unit: string
}) {
  const vals = rows.flatMap((r) => [r.est, r.lo, r.hi]).concat(gate).filter((v): v is number => v != null && isFinite(v))
  const height = rows.length * ROW_H + AXIS_H
  const pad = 14
  if (!rows.some((r) => r.est != null))
    return (
      <svg width={width} height={rows.length * ROW_H + AXIS_H} role="img" aria-label="No estimates yet">
        <text x={width / 2} y={(rows.length * ROW_H) / 2} textAnchor="middle" fontSize={12} fill="var(--faint)">waiting for the first measurement</text>
      </svg>
    )
  if (!vals.length) return <svg width={width} height={height} />
  const mn = Math.min(...vals), mx = Math.max(...vals)
  const log = mn > 0 && mx / mn > 8
  const dom: [number, number] = log ? [mn / 1.6, mx * 1.6] : [mn - (mx - mn) * 0.08 - 1e-9, mx + (mx - mn) * 0.08 + 1e-9]
  const x = (log ? scaleLog : scaleLinear)({ domain: dom, range: [pad, width - pad] }) as (v: number) => number
  const plotH = rows.length * ROW_H
  const gx = gate != null ? x(gate) : null
  const good = direction === 'max' ? [gx ?? 0, width - pad] : [pad, gx ?? 0]

  return (
    <svg width={width} height={height} role="img" aria-label={`Estimates with 95% intervals against the gate${gate != null ? ` at ${sig(gate)} ${unit}` : ''}`}>
      {gx != null && <rect x={good[0]} y={0} width={Math.max(0, good[1] - good[0])} height={plotH} fill="var(--ok-soft)" opacity={0.55} />}
      {rows.map((r, i) => (
        <line key={`g${i}`} x1={0} x2={width} y1={(i + 1) * ROW_H} y2={(i + 1) * ROW_H} stroke="var(--line)" />
      ))}
      {gx != null && (
        <>
          <line x1={gx} x2={gx} y1={0} y2={plotH} stroke="var(--ink)" strokeWidth={1.5} strokeDasharray="4 3" />
          <text x={gx + 4} y={11} fontSize={10} fill="var(--muted)" className="num">gate {sig(gate)}</text>
        </>
      )}
      {rows.map((r, i) => {
        if (r.est == null) return null
        const y = i * ROW_H + ROW_H / 2
        const c = COLOR[r.state] ?? 'var(--faint)'
        return (
          <g key={r.id}>
            {r.lo != null && r.hi != null && (
              <>
                <line x1={x(r.lo)} x2={x(r.hi)} y1={y} y2={y} stroke={c} strokeWidth={2.5} strokeLinecap="round" />
                <line x1={x(r.lo)} x2={x(r.lo)} y1={y - 5} y2={y + 5} stroke={c} strokeWidth={2} />
                <line x1={x(r.hi)} x2={x(r.hi)} y1={y - 5} y2={y + 5} stroke={c} strokeWidth={2} />
              </>
            )}
            <Marker x={x(r.est)} y={y} state={r.state} />
          </g>
        )
      })}
      <g transform={`translate(0,${plotH})`}>
        <AxisBottom scale={x as never} tickValues={log ? (niceLogTicks(dom[0], dom[1]) as never[]) : undefined} numTicks={log ? undefined : 6} stroke="var(--line-strong)" tickStroke="var(--line-strong)"
          tickLabelProps={() => ({ fill: 'var(--muted)', fontSize: 10, textAnchor: 'middle', dy: 2, fontFamily: 'var(--font-mono)' })}
          tickFormat={(v) => sig(v as number, 2)} label={unit} labelProps={{ fill: 'var(--muted)', fontSize: 10, textAnchor: 'middle' }} labelOffset={6} />
      </g>
    </svg>
  )
}

/** Estimates with 95% intervals against the pre-registered gate — the one
 *  picture that answers "which candidates actually meet the criterion, and how
 *  sure are we?". Log axis when values span an order of magnitude (potency). */
export function ForestPlot({ hyps, gate, direction, unit }: {
  hyps: Hyp[]; gate: number | null; direction: 'min' | 'max' | null; unit: string
}) {
  const rows: Row[] = hyps.map((h) => ({
    id: h.id, state: h.state,
    est: h.verdict?.observed ?? null,
    lo: h.verdict?.ci?.[0] ?? null, hi: h.verdict?.ci?.[1] ?? null,
  }))
  return (
    <div style={{ height: rows.length * ROW_H + AXIS_H }}>
      <ParentSize debounceTime={30}>{({ width }) => (width > 0 ? <Plot width={width} rows={rows} gate={gate} direction={direction} unit={unit} /> : null)}</ParentSize>
    </div>
  )
}
