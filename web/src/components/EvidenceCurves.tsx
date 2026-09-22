import { useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'

interface Curve {
  run_id: string
  candidate: string
  verdict: string | null
}

interface Pt { conc: number; value: number }

const METRIC_WORDS: Record<string, string> = {
  potency_pct: 'potency (%)', potency: 'potency',
  tensile_strength_mpa: 'tensile strength (MPa)',
  strength_mpa: 'strength (MPa)', density: 'density',
  thermal_stability: 'thermal stability', stability: 'stability',
  aggregation: 'aggregation', immunogenicity: 'immunogenicity',
  expression: 'expression', sterility: 'sterility',
  phenotype_stability: 'phenotype stability',
  organism_dose_response: 'organism response',
  phytotoxicity: 'phytotoxicity', ic50_um: 'IC50 (µM)', ic50: 'IC50',
}

function metricLabel(metric?: string | null): string {
  if (!metric) return 'response'
  return METRIC_WORDS[metric.toLowerCase()] ?? metric.replace(/_/g, ' ')
}

function parseConc(raw: string): number {
  // '0.5uM' / '10uM' / '500nM' / '2' — recorded well concentrations
  const m = raw.trim().toLowerCase().match(/^([\d.]+)\s*(nm|um|µm|m)?$/)
  if (!m) return NaN
  const v = Number(m[1])
  if (!Number.isFinite(v)) return NaN
  const unit = m[2] ?? 'um'
  if (unit === 'nm') return v / 1000
  if (unit === 'm') return v * 1e6
  return v
}

function parseCsv(text: string, candidate: string): Pt[] {
  const lines = text.trim().split(/\r?\n/)
  if (lines.length < 2) return []
  const header = lines[0].split(',').map((s) => s.trim().toLowerCase())
  const pick = (...names: string[]) =>
    header.findIndex((h) => names.some((n) => h === n || h.includes(n)))
  const iS = pick('sample', 'compound')
  const iC = pick('conc_um', 'conc')
  const iV = pick('value', 'rfu')
  let pts: Pt[] = []
  for (const line of lines.slice(1)) {
    const cells = line.split(',').map((s) => s.trim())
    if (cells.length < 3) continue
    const sample = iS >= 0 ? cells[iS] : ''
    if (candidate && sample && sample.toLowerCase() !== candidate.toLowerCase())
      continue
    if (sample === 'ctrl' || sample.startsWith('ctrl')) continue
    const conc = parseConc(cells[iC] ?? '')
    const value = Number(cells[iV])
    if (Number.isFinite(conc) && Number.isFinite(value) && conc > 0)
      pts.push({ conc, value })
  }
  // median per concentration (replicates) for a clean curve
  const byConc = new Map<number, number[]>()
  for (const p of pts) {
    if (!byConc.has(p.conc)) byConc.set(p.conc, [])
    byConc.get(p.conc)!.push(p.value)
  }
  pts = [...byConc.entries()]
    .map(([conc, vs]) => ({
      conc,
      value: vs.sort((a, b) => a - b)[Math.floor(vs.length / 2)],
    }))
    .sort((a, b) => a.conc - b.conc)
  return pts
}

function CurveSvg({ pts, verdict, gate, gateLabel, ylabel = 'response', width = 300, height = 170 }: {
  pts: Pt[]; verdict: string | null; gate?: number | null
  gateLabel?: string | null; ylabel?: string
  width?: number; height?: number
}) {
  const geom = useMemo(() => {
    const pad = { l: 38, r: 10, t: 12, b: 26 }
    if (pts.length === 0) return null
    const xs = pts.map((p) => Math.log10(p.conc))
    const ys = pts.map((p) => p.value)
    const x0 = Math.min(...xs) - 0.15, x1 = Math.max(...xs) + 0.15
    const gateVal = typeof gate === 'number' && Number.isFinite(gate) ? gate : null
    const y0 = Math.min(0, ...ys, gateVal ?? 0)
    const y1 = Math.max(...ys, gateVal ?? 0) * 1.15 || 1
    const X = (v: number) =>
      pad.l + ((Math.log10(v) - x0) / (x1 - x0 || 1)) * (width - pad.l - pad.r)
    const Y = (v: number) =>
      height - pad.b - ((v - y0) / (y1 - y0 || 1)) * (height - pad.t - pad.b)
    const path = pts.map((p, i) => `${i ? 'L' : 'M'}${X(p.conc)},${Y(p.value)}`).join(' ')
    const ticks = [0.1, 1, 10, 100, 1000].filter(
      (t) => Math.log10(t) >= x0 && Math.log10(t) <= x1)
    const gateY = gateVal !== null ? Y(gateVal) : null
    return { X, Y, path, y0, y1, ticks, pts, gateY }
  }, [pts, width, height])

  if (!geom) return <span className="muted" style={{ fontSize: 11 }}>no plottable wells</span>
  const color = verdict === 'confirmed' || verdict === 'validated'
    ? 'var(--ok)' : verdict === 'refuted' ? 'var(--bad)' : 'var(--teal)'
  return (
    <svg width={width} height={height} style={{ background: 'var(--card)', border: '1px solid var(--line)', borderRadius: 8 }}>
      {geom.ticks.map((t) => (
        <g key={t}>
          <line x1={geom.X(t)} y1={12} x2={geom.X(t)} y2={height - 26} stroke="var(--line)" strokeDasharray="2 3" />
          <text x={geom.X(t)} y={height - 12} fontSize="9" textAnchor="middle" fill="var(--muted)">{t}</text>
        </g>
      ))}
      {[geom.y0, geom.y1].map((v, i) => (
        <text key={i} x={33} y={geom.Y(v) + 3} fontSize="9" textAnchor="end" fill="var(--muted)">
          {v.toFixed(0)}
        </text>
      ))}
      {geom.gateY !== null && (
        <g>
          <line x1={34} y1={geom.gateY} x2={width - 10} y2={geom.gateY}
            stroke="var(--warn)" strokeDasharray="4 3" strokeWidth="1" />
          <text x={width - 10} y={geom.gateY - 4} fontSize="8.5"
            textAnchor="end" fill="var(--warn)">
            {gateLabel ?? 'gate'}
          </text>
        </g>
      )}
      <path d={`${geom.path} L${geom.X(pts[pts.length - 1].conc)},${height - 26} L${geom.X(pts[0].conc)},${height - 26} Z`}
        fill={color} opacity="0.07" stroke="none" />
      <path d={geom.path} fill="none" stroke={color} strokeWidth="1.6" />
      {geom.pts.map((p, i) => (
        <circle key={i} cx={geom.X(p.conc)} cy={geom.Y(p.value)} r="3" fill={color} />
      ))}
      <text x={width - 10} y={16} fontSize="9" textAnchor="end" fill="var(--muted)">
        log dose (µM) → {ylabel}
      </text>
    </svg>
  )
}

export default function EvidenceCurves({ eid, curves, metric, gate }: {
  eid: string
  curves: Curve[]
  metric?: string | null
  gate?: number | null
}) {
  if (!curves.length) return null
  return (
    <div>
      <h3 style={{ fontSize: 14, margin: '10px 0 6px' }}>Analyze — evidence</h3>
      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
        {curves.map((c) => (
          <CurveCard key={c.run_id} eid={eid} curve={c} metric={metric}
            gate={gate} />
        ))}
      </div>
      <p className="muted" style={{ fontSize: 11, marginTop: 6 }}>
        raw recorded plate points per run — the verdict reads the curve
        against the pre-registered gate
      </p>
    </div>
  )
}

function CurveCard({ eid, curve, metric, gate }: {
  eid: string; curve: Curve; metric?: string | null; gate?: number | null
}) {
  const q = useQuery({
    queryKey: ['evidence', eid, curve.run_id],
    queryFn: () =>
      fetch(`/api/experiments/${eid}/evidence/${curve.run_id}.csv`)
        .then((r) => (r.ok ? r.text() : '')),
  })
  const pts = useMemo(
    () => (q.data ? parseCsv(q.data, curve.candidate) : []),
    [q.data, curve.candidate])
  return (
    <div style={{ display: 'inline-block' }}>
      <div style={{ fontSize: 11, marginBottom: 2 }}>
        <strong>{curve.candidate}</strong>
        {curve.verdict && (
          <span className={`chip ${curve.verdict}`} style={{ marginLeft: 6, fontSize: 10 }}>
            {curve.verdict}
          </span>
        )}
        <span className="muted" style={{ marginLeft: 6 }}>{curve.run_id}</span>
      </div>
      {q.isLoading ? (
        <div className="muted" style={{ fontSize: 11, width: 300, height: 170 }}>loading…</div>
      ) : (
        <CurveSvg pts={pts} verdict={curve.verdict} gate={gate}
          gateLabel={metric ? `gate ${metric}` : 'gate'}
          ylabel={metricLabel(metric)} />
      )}
    </div>
  )
}
