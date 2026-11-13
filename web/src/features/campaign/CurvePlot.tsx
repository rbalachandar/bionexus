import { scaleLinear, scaleLog } from '@visx/scale'
import { AxisBottom, AxisLeft } from '@visx/axis'
import { LinePath } from '@visx/shape'
import { ParentSize } from '@visx/responsive'
import type { Schemas } from '../../api/v1'
import { Tag } from '../../ui/Chip'
import { niceLogTicks, sig } from './format'

type Curve = Schemas['Curve']
const H = 230, M = { t: 12, r: 16, b: 38, l: 54 }

function Plot({ width, c, gate, unit }: { width: number; c: Curve; gate?: number | null; unit: string }) {
  const xs = c.points.map((p) => p.conc_um)
  const ys = c.points.map((p) => p.value).concat(c.fit?.line.map((p) => p.value) ?? [])
  const lo = Math.min(...xs) / 1.6, hi = Math.max(...xs) * 1.6
  const x = scaleLog({ domain: [lo, hi], range: [M.l, width - M.r] })
  const ymax = Math.max(...ys) * 1.08
  const y = scaleLinear({ domain: [Math.min(0, ...ys), ymax], range: [H - M.b, M.t] })
  const f = c.fit
  return (
    <svg width={width} height={H} role="img" aria-label={`Dose–response for ${c.label}`}>
      {f?.ci && <rect x={x(f.ci[0])} y={M.t} width={Math.max(2, x(f.ci[1]) - x(f.ci[0]))} height={H - M.b - M.t} fill="var(--accent-soft)" />}
      {gate != null && gate > lo && gate < hi && (
        <>
          <line x1={x(gate)} x2={x(gate)} y1={M.t} y2={H - M.b} stroke="var(--ink)" strokeDasharray="4 3" />
          <text x={x(gate) + 4} y={M.t + 9} fontSize={10} fill="var(--muted)" className="num">gate {sig(gate)}</text>
        </>
      )}
      {f && f.line.length > 0 && (
        <LinePath data={f.line} x={(p) => x(p.conc_um)} y={(p) => y(p.value)} stroke="var(--accent)" strokeWidth={2} />
      )}
      {f?.ic50_um && f.ic50_um > lo && f.ic50_um < hi && (
        <line x1={x(f.ic50_um)} x2={x(f.ic50_um)} y1={M.t} y2={H - M.b} stroke="var(--accent)" strokeWidth={1} strokeDasharray="2 3" />
      )}
      {c.points.map((p, i) => <circle key={i} cx={x(p.conc_um)} cy={y(p.value)} r={3.6} fill="var(--ink)" fillOpacity={0.8} />)}
      <AxisBottom top={H - M.b} scale={x} tickValues={niceLogTicks(lo, hi)} stroke="var(--line-strong)" tickStroke="var(--line-strong)"
        tickFormat={(v) => sig(v as number, 2)} label={`concentration (${unit})`}
        labelProps={{ fill: 'var(--muted)', fontSize: 10, textAnchor: 'middle' }} labelOffset={4}
        tickLabelProps={() => ({ fill: 'var(--muted)', fontSize: 10, textAnchor: 'middle', dy: 2, fontFamily: 'var(--font-mono)' })} />
      <AxisLeft left={M.l} scale={y} numTicks={5} stroke="var(--line-strong)" tickStroke="var(--line-strong)" label="response" labelProps={{ fill: 'var(--muted)', fontSize: 10, textAnchor: 'middle' }} labelOffset={30}
        tickLabelProps={() => ({ fill: 'var(--muted)', fontSize: 10, textAnchor: 'end', dx: -2, dy: 3, fontFamily: 'var(--font-mono)' })} />
    </svg>
  )
}

/** One recorded plate for one candidate: every point, the fitted curve, the
 *  IC50 with its interval, and the plate's QC. */
export function CurveCard({ c, gate, unit = 'µM' }: { c: Curve; gate?: number | null; unit?: string }) {
  const f = c.fit
  return (
    <div className="rounded-lg border border-line">
      <div className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
        <span className="text-sm font-semibold">{c.label}</span>
        <span className="num text-xs text-faint">{c.run_id}</span>
        {c.z_prime != null && (
          <Tag tone={c.z_prime >= 0.5 ? 'ok' : 'warn'}>Z′ {c.z_prime.toFixed(2)}{c.z_kind === 'heuristic' ? ' (heuristic)' : ''}</Tag>
        )}
        <span className="num ml-auto text-sm">
          {f?.ic50_um != null ? <>IC50 <b>{sig(f.ic50_um)}</b> {unit}{f.ci && <span className="text-faint"> [{sig(f.ci[0])} – {sig(f.ci[1])}]</span>}</>
            : <span className="text-faint">no IC50 fitted</span>}
        </span>
      </div>
      <div className="px-1 pt-2" style={{ height: H + 8 }}><ParentSize debounceTime={30}>{({ width }) => (width > 0 ? <Plot width={width} c={c} gate={gate} unit={unit} /> : null)}</ParentSize></div>
      <p className="border-t border-line px-3 py-2 text-[11px] text-faint">
        {f?.model ?? 'curve model not recorded'}{f?.method ? ` · ${f.method}` : ''}
        {f?.right_censored && ' · right-censored: no transition in range'}{f?.left_censored && ' · left-censored: below the measurable window'}
      </p>
    </div>
  )
}
