import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { FileSpreadsheet, Upload } from 'lucide-react'

const ORIGIN_LABEL: Record<string, string> = {
  measured: 'measured', historical: 'historical deposit',
  simulated: 'simulated', predicted: 'predicted', unknown: 'origin unknown',
}

const STATE_LABEL: Record<string, string> = {
  uploaded: 'uploaded', preview_ready: 'preview ready — confirm the setup',
  configured: 'setup confirmed', analyzed: 'analyzed',
  reviewed: 'reviewed', unreadable: 'unreadable',
  needs_input: 'needs input', analysis_failed: 'analysis failed',
  needs_mapping: 'needs mapping', unsupported_regime: 'regime not validated',
  qc_hold: 'QC hold',
}

const CALL_STYLE: Record<string, React.CSSProperties> = {
  validated: { color: 'var(--ok)' },
  invalidated: { color: 'var(--bad)' },
  inconclusive: { color: 'var(--warn)' },
  no_call: { color: 'var(--muted)' },
}

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 2, marginBottom: 4,
  padding: '5px 8px', border: '1px solid var(--line)',
  borderRadius: 'var(--radius)', font: 'inherit', background: '#fff',
}

function post(path: string, body?: unknown) {
  return fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  }).then(async (r) => {
    if (!r.ok) {
      const b = await r.json().catch(() => ({}))
      const d = b.detail
      throw new Error(typeof d === 'object' ? `${d.code}: ${d.detail}` : (d ?? `${r.status}`))
    }
    return r.json()
  })
}

// ------------------------------------------------------------- new analysis
function NewAnalysis() {
  const nav = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [layout, setLayout] = useState<File | null>(null)
  const [threshold, setThreshold] = useState('10')
  const [direction, setDirection] = useState('min')
  const [maxResponse, setMaxResponse] = useState('100')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit() {
    if (!file) return
    setBusy(true); setError('')
    try {
      const fd = new FormData()
      fd.append('file', file)
      if (layout) fd.append('layout', layout)
      fd.append('profile', 'plate_assay')
      const cfg: Record<string, unknown> = { metric: 'ic50_um', direction }
      if (threshold.trim() !== '') cfg.threshold = Number(threshold)
      if (maxResponse.trim() !== '') cfg.max_response = Number(maxResponse)
      fd.append('config', JSON.stringify(cfg))
      const r = await fetch('/api/analyses', { method: 'POST', body: fd })
      if (!r.ok) {
        const b = await r.json().catch(() => ({}))
        const d = b.detail
        throw new Error(typeof d === 'object' ? `${d.code}: ${d.detail}` : (d ?? `${r.status}`))
      }
      nav(`/analyses/${(await r.json()).id}`)
    } catch (e) {
      setError(String(e).replace('Error: ', ''))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main>
      <h1 style={{ fontSize: 20 }}>Analyze experiment data</h1>
      <p className="muted" style={{ fontSize: 12, maxWidth: 640 }}>
        Profile: <strong>Plate-reader assay</strong> (the first available
        profile). Your file is stored unchanged and hashed; nothing is fitted
        until you confirm the interpretation.
      </p>
      <div className="card" style={{ maxWidth: 640, display: 'grid', gap: 10 }}>
        <label>Instrument export * (CSV / TSV / XLSX)
          <input type="file" accept=".csv,.tsv,.txt,.xlsx,.npy"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <label>Plate layout (optional — well → sample/concentration map)
          <input type="file" accept=".csv,.tsv,.txt"
            onChange={(e) => setLayout(e.target.files?.[0] ?? null)} />
        </label>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8 }}>
          <label>Gate (threshold)
            <input value={threshold} onChange={(e) => setThreshold(e.target.value)}
              style={inputStyle} placeholder="blank = no calls" />
          </label>
          <label>Good direction
            <select value={direction} onChange={(e) => setDirection(e.target.value)}
              style={inputStyle}>
              <option value="min">lower is better</option>
              <option value="max">higher is better</option>
            </select>
          </label>
          <label>Full-scale response
            <input value={maxResponse} onChange={(e) => setMaxResponse(e.target.value)}
              style={inputStyle} />
          </label>
        </div>
        {error && <p className="chip failed">{error}</p>}
        <div>
          <button className="primary" disabled={!file || busy}
            style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
            onClick={submit}>
            <Upload size={14} /> {busy ? 'Uploading…' : 'Upload & preview'}
          </button>
        </div>
      </div>
    </main>
  )
}

// ------------------------------------------------------- analysis detail
function OriginChip({ origin }: { origin?: string }) {
  if (!origin) return null
  return (
    <span className="chip meta" title="evidence origin — never inferred from the filename">
      {ORIGIN_LABEL[origin] ?? origin}
    </span>
  )
}

const RUNNABLE = ['configured', 'analyzed', 'reviewed', 'qc_hold',
  'unsupported_regime']

function ResultView({ result }: { result: any }) {
  const calls = result?.calls ?? []
  const compounds: Record<string, any> = result?.compounds ?? {}
  return (
    <div style={{ display: 'grid', gap: 10 }}>
      {result?.regime_refused && (
        <p className="chip failed">
          Regime not validated — no absolute claims on this normalization
          frame. {result.regime?.note}
        </p>
      )}
      {result?.qc_hold && !result?.regime_refused && (
        <p className="chip warning">QC hold — Z′ below the QC floor.</p>
      )}
      {result?.shape_only && Object.keys(result.shape_only).length > 0 && (
        <details>
          <summary style={{ fontSize: 12, cursor: 'pointer' }}>
            Shape-only admits ({Object.keys(result.shape_only).length}) — no IC50 claims
          </summary>
          <table style={{ fontSize: 12, borderCollapse: 'collapse', marginTop: 6 }}>
            <thead><tr>
              <th style={{ textAlign: 'left', paddingRight: 12 }}>sample</th>
              <th style={{ textAlign: 'left', paddingRight: 12 }}>class</th>
              <th style={{ textAlign: 'left' }}>midpoint (µM)</th>
            </tr></thead>
            <tbody>
              {Object.entries(result.shape_only as Record<string, any>).map(([s, v]) => (
                <tr key={s}>
                  <td style={{ paddingRight: 12 }}>{s}</td>
                  <td style={{ paddingRight: 12 }}>{v.class}</td>
                  <td>{v.midpoint_uM ?? '—'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
      <table style={{ fontSize: 12, borderCollapse: 'collapse' }}>
        <thead><tr>
          <th style={{ textAlign: 'left', paddingRight: 14 }}>sample</th>
          <th style={{ textAlign: 'left', paddingRight: 14 }}>IC50 (µM) [95% CI]</th>
          <th style={{ textAlign: 'left', paddingRight: 14 }}>fit</th>
          <th style={{ textAlign: 'left' }}>call</th>
        </tr></thead>
        <tbody>
          {Object.entries(compounds).map(([s, c]) => {
            const call = calls.find((x: any) => x.entity === s)
            return (
              <tr key={s} title={call?.reason ?? ''}>
                <td style={{ paddingRight: 14 }}>{s}</td>
                <td style={{ paddingRight: 14 }}>
                  {c.ic50_um != null ? c.ic50_um.toFixed(2) : '> range'}
                  {c.ic50_ci ? ` [${c.ic50_ci[0]}–${c.ic50_ci[1]}]` : ''}
                </td>
                <td style={{ paddingRight: 14 }} className="muted">
                  {c.fit_method}{c.right_censored ? ' · right-censored' : ''}
                  {c.left_censored ? ' · left-censored' : ''}
                </td>
                <td style={{ ...CALL_STYLE[call?.call ?? ''], fontWeight: 600 }}>
                  {call ? call.call : (result.threshold_registered ? '' : '—')}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
      {calls.length > 0 && (
        <details>
          <summary style={{ fontSize: 12, cursor: 'pointer' }}>Why these calls?</summary>
          <div style={{ fontSize: 11, display: 'grid', gap: 3, marginTop: 6 }}>
            {calls.map((c: any) => (
              <div key={c.entity}>
                <strong>{c.entity}</strong>: {c.call} — {c.reason}
              </div>
            ))}
          </div>
        </details>
      )}
    </div>
  )
}

function AnalysisDetail({ id }: { id: string }) {
  const nav = useNavigate()
  const qc = useQuery({
    queryKey: ['analysis', id],
    queryFn: () => fetch(`/api/analyses/${id}`).then((r) => {
      if (!r.ok) throw new Error(`${r.status}`)
      return r.json()
    }),
  })
  const client = useQueryClient()
  const [error, setError] = useState('')
  const [threshold, setThreshold] = useState<string | null>(null)
  const [reviewReason, setReviewReason] = useState('')
  const [reviewActor, setReviewActor] = useState('scientist')

  if (qc.isLoading) return <main><p className="muted">loading…</p></main>
  if (qc.isError) return <main><p className="chip failed">not found</p></main>
  const doc = qc.data
  const preview = doc.preview ?? {}
  const result = doc.result
  const cfg = doc.config ?? {}
  const th = threshold ?? (cfg.threshold != null ? String(cfg.threshold) : '')
  const refresh = () => client.invalidateQueries({ queryKey: ['analysis', id] })

  async function act(fn: () => Promise<unknown>) {
    setError('')
    try { await fn(); await refresh() } catch (e) {
      setError(String(e).replace('Error: ', ''))
    }
  }

  const diag = (preview.diagnostics ?? []).concat(result?.diagnostics ?? [])

  return (
    <main>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h1 style={{ fontSize: 20, margin: 0 }}>
          <FileSpreadsheet size={16} style={{ verticalAlign: '-2px', marginRight: 6 }} />
          Analysis {id}
        </h1>
        <span className="chip meta">{doc.profile} · rev {doc.revision}</span>
        <OriginChip origin={result?.evidence_origin ?? preview.evidence_origin} />
        <strong style={{ fontSize: 13 }}>
          {STATE_LABEL[doc.state] ?? doc.state}
        </strong>
        <span style={{ flex: 1 }} />
        <button onClick={() => nav('/analyses/new')}>New analysis</button>
      </div>
      {error && <p className="chip failed">{error}</p>}

      {/* preview / interpretation panel */}
      <section className="card" style={{ marginTop: 12, maxWidth: 760 }}>
        <h3 style={{ margin: '0 0 6px', fontSize: 14 }}>Interpretation</h3>
        <div style={{ fontSize: 12, display: 'grid', gap: 2 }}>
          <div>format: <span className="mono">{preview.format}</span> ·{' '}
            {preview.n_wells} wells ·{' '}
            {preview.controls_detected ?? 0} control wells ·{' '}
            {preview.response_unit}</div>
          <div>
            Z′: {preview.z_prime ?? '—'}
            {preview.z_prime_kind === 'heuristic' && (
              <span className="muted"> (heuristic — real Z′ needs both control classes)</span>)}
            {preview.z_prime_kind === 'real' && <span className="muted"> (real)</span>}
          </div>
          {preview.instrument && Object.keys(preview.instrument).length > 0 && (
            <div className="muted">
              {Object.entries(preview.instrument as Record<string, unknown>)
                .slice(0, 4).map(([k, v]) => `${k}: ${v}`).join(' · ')}
            </div>
          )}
        </div>
        {diag.length > 0 && (
          <div style={{ marginTop: 8, display: 'grid', gap: 3 }}>
            {diag.map((d: any, i: number) => (
              <div key={i} style={{ fontSize: 11 }}>
                <span style={{
                  fontWeight: 700, textTransform: 'uppercase', fontSize: 9.5,
                  color: d.severity === 'blocker' ? 'var(--bad)'
                    : d.severity === 'warning' ? 'var(--warn)' : 'var(--muted)',
                }}>{d.severity}</span>{' '}
                <span className="mono">{d.code}</span> — {d.message}
              </div>
            ))}
          </div>
        )}
        {(preview.needs_confirmation ?? []).length > 0 && (
          <div style={{ marginTop: 6 }}>
            {(preview.needs_confirmation as string[]).map((k) => (
              <span key={k} className="chip warning" style={{ fontSize: 11 }}>
                confirm {k.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* configure */}
      {(doc.state === 'preview_ready' || doc.state === 'configured'
        || doc.state === 'analyzed' || doc.state === 'reviewed'
        || doc.state === 'qc_hold' || doc.state === 'unsupported_regime'
        || doc.state === 'needs_mapping') && (
        <section className="card" style={{ marginTop: 10, maxWidth: 760 }}>
          <h3 style={{ margin: '0 0 6px', fontSize: 14 }}>Gate & re-run</h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'end', flexWrap: 'wrap' }}>
            <label style={{ fontSize: 12 }}>Threshold (blank = estimates only)
              <input value={th} onChange={(e) => setThreshold(e.target.value)} style={inputStyle} />
            </label>
            <button className="primary" onClick={() => act(() =>
              post(`/api/analyses/${id}/configure`, {
                config: { ...cfg, threshold: th.trim() === '' ? null : Number(th) },
              }))}>
              Confirm setup
            </button>
            <button className="primary" disabled={!RUNNABLE.includes(doc.state)}
              title={RUNNABLE.includes(doc.state) ? '' : 'confirm the interpretation first'}
              onClick={() => act(() =>
                post(`/api/analyses/${id}/run`))}>
              Run analysis
            </button>
          </div>
        </section>
      )}

      {/* results */}
      {result && (
        <section className="card" style={{ marginTop: 10, maxWidth: 760 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 12 }}>
            <h3 style={{ margin: '0 0 6px', fontSize: 14 }}>Results</h3>
            <a href={`/api/analyses/${id}/report`} target="_blank"
              rel="noreferrer" style={{ fontSize: 12 }}>Open report</a>
            <a href={`/api/analyses/${id}/export.csv`}
              style={{ fontSize: 12 }}>Export CSV</a>
            <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
              engine {result.engine_version ?? '—'}
            </span>
          </div>
          <ResultView result={result} />
        </section>
      )}

      {/* review */}
      {result && (doc.state === 'analyzed' || doc.state === 'qc_hold'
        || doc.state === 'reviewed') && (
        <section className="card" style={{ marginTop: 10, maxWidth: 760 }}>
          <h3 style={{ margin: '0 0 6px', fontSize: 14 }}>
            Scientist review
            <span className="muted" style={{ fontSize: 11, marginLeft: 8, fontWeight: 400 }}>
              recorded beside the computed calls — never over them
            </span>
          </h3>
          {(doc.dispositions ?? []).map((d: any, i: number) => (
            <div key={i} style={{ fontSize: 11 }} className="muted">
              {d.action} by {d.actor}{d.reason ? ` — ${d.reason}` : ''}
            </div>
          ))}
          {doc.state !== 'reviewed' && (
            <div style={{ display: 'flex', gap: 8, alignItems: 'end', flexWrap: 'wrap', marginTop: 6 }}>
              <label style={{ fontSize: 12 }}>Your name
                <input value={reviewActor} onChange={(e) => setReviewActor(e.target.value)} style={inputStyle} />
              </label>
              <label style={{ fontSize: 12, flex: 1, minWidth: 220 }}>Reason
                <input value={reviewReason} onChange={(e) => setReviewReason(e.target.value)} style={inputStyle} />
              </label>
              <button className="primary" onClick={() => act(() =>
                post(`/api/analyses/${id}/review`, {
                  action: 'acknowledge', reason: reviewReason, actor: reviewActor,
                }))}>
                Acknowledge
              </button>
              <button onClick={() => act(() =>
                post(`/api/analyses/${id}/review`, {
                  action: 'override', reason: reviewReason, actor: reviewActor,
                }))}>
                Override
              </button>
            </div>
          )}
        </section>
      )}
    </main>
  )
}

export default function Analysis() {
  const { id } = useParams()
  if (!id || id === 'new') return <NewAnalysis />
  return <AnalysisDetail id={id} />
}
