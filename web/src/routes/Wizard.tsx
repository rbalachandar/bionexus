import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSearchParams } from 'react-router-dom'

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 2, marginBottom: 4,
  padding: '5px 8px', border: '1px solid var(--line)',
  borderRadius: 'var(--radius)', font: 'inherit', background: '#fff',
}

const CLAIMS = ['causal_modification', 'gain_of_function',
  'loss_of_function', 'interaction_capture', 'occupancy_vs_catalysis',
  'turnover_or_pulse_cohort', 'detection_or_pulldown']

export default function Wizard() {
  const nav = useNavigate()
  const [params] = useSearchParams()
  const program = params.get('program') ?? ''
  const [sid, setSid] = useState('')
  const [eid, setEid] = useState('')
  const [step, setStep] = useState(1)
  const [question, setQuestion] = useState('')
  const [target, setTarget] = useState('c-Myc')
  const [claim, setClaim] = useState('causal_modification')
  const [site, setSite] = useState('S62')
  const [halfLife, setHalfLife] = useState(120)
  const [editedFrac, setEditedFrac] = useState(false)
  const [mimetic, setMimetic] = useState(false)
  const [controls, setControls] = useState('')
  const [mechanism, setMechanism] = useState('')
  const [refutation, setRefutation] = useState('')
  const [citation, setCitation] = useState('')
  const [readiness, setReadiness] = useState<any>(null)
  const [plate, setPlate] = useState<any>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [error, setError] = useState('')

  async function call(path: string, body?: any, file?: File) {
    setError('')
    let r: Response
    if (file) {
      const fd = new FormData()
      fd.append('file', file)
      r = await fetch(path, { method: 'POST', body: fd })
    } else {
      r = await fetch(path, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: body ? JSON.stringify(body) : undefined,
      })
    }
    if (!r.ok) {
      setError((await r.json()).detail ?? `${r.status}`)
      return null
    }
    return r.json()
  }

  const StepBar = ({ current }: { current: number }) => (
    <div style={{ display: 'flex', gap: 4, marginBottom: 14, maxWidth: 640 }}>
      {[1, 2, 3, 4, 5, 6].map((n) => (
        <div key={n} style={{ flex: 1, textAlign: 'center' }}>
          <div style={{
            height: 3, borderRadius: 2, marginBottom: 4,
            background: n < current ? 'var(--brand)'
              : n === current ? 'var(--brand)' : 'var(--border)',
            opacity: n === current ? 1 : n < current ? 0.55 : 1,
          }} />
          <span className="muted" style={{
            fontSize: 10,
            color: n === current ? 'var(--brand)' : 'var(--muted)',
            fontWeight: n === current ? 600 : 400,
          }}>
            {['problem', 'design', 'readiness', 'execute', 'upload', 'analyze'][n - 1]}
          </span>
        </div>
      ))}
    </div>
  )

  // step 1
  if (!sid) {
    return (
      <main>
        <StepBar current={1} />
        <h1 style={{ fontSize: 20 }}>1 · Define the problem</h1>
        {program && (
          <p className="muted" style={{ fontSize: 12 }}>
            guided launch under program <strong>{program}</strong> — the
            experiment will be linked to it
          </p>
        )}
        <div className="card" style={{ maxWidth: 640, display: 'grid', gap: 10 }}>
          <label>Scientific question *
            <textarea value={question} onChange={(e) => setQuestion(e.target.value)}
              style={inputStyle} rows={3}
              placeholder="Does S62 phosphorylation cause c-Myc degradation?" />
          </label>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <label>Target (protein/pathway)
              <input value={target} onChange={(e) => setTarget(e.target.value)} style={inputStyle} />
            </label>
            <label>Claim type
              <select value={claim} onChange={(e) => setClaim(e.target.value)} style={inputStyle}>
                {CLAIMS.map((c) => <option key={c}>{c}</option>)}
              </select>
            </label>
          </div>
          {error && <p className="chip failed">{error}</p>}
          <div>
            <button className="primary" disabled={!question.trim()}
              onClick={async () => {
                const r = await call('/api/wizard/sessions',
                  { question, target, claim, program })
                if (r) { setSid(r.sid); setEid(r.eid); setStep(2) }
              }}>
              Continue →
            </button>
          </div>
        </div>
      </main>
    )
  }

  // step 2 — design
  if (step === 2) {
    return (
      <main>
        <StepBar current={ 2 } />
        <h1 style={{ fontSize: 20 }}>2 · Design the experiment</h1>
        <p className="muted" style={{ fontSize: 12 }}>
          session {sid} · experiment {eid}
        </p>
        <div className="card" style={{ maxWidth: 640, display: 'grid', gap: 10 }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            <label>Site / variant
              <input value={site} onChange={(e) => setSite(e.target.value)} style={inputStyle} />
            </label>
            <label>Target half-life (min)
              <input type="number" value={halfLife}
                onChange={(e) => setHalfLife(Number(e.target.value))} style={inputStyle} />
            </label>
          </div>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={editedFrac}
              onChange={(e) => setEditedFrac(e.target.checked)} />
            Readout measures edited fraction
          </label>
          <label style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <input type="checkbox" checked={mimetic}
              onChange={(e) => setMimetic(e.target.checked)} />
            Distinguishes real from mimetic phenotype
          </label>
          <label>Controls (one per line)
            <textarea value={controls} onChange={(e) => setControls(e.target.value)}
              style={inputStyle} rows={2} />
          </label>
          <label>Mechanism (optional)
            <input value={mechanism} onChange={(e) => setMechanism(e.target.value)} style={inputStyle} />
          </label>
          <label>Refuted if… (optional)
            <input value={refutation} onChange={(e) => setRefutation(e.target.value)} style={inputStyle} />
          </label>
          <label>Citation (PMID/DOI, optional)
            <input value={citation} onChange={(e) => setCitation(e.target.value)} style={inputStyle} />
          </label>
          {error && <p className="chip failed">{error}</p>}
          <button className="primary" onClick={async () => {
            const r = await call(`/api/wizard/sessions/${sid}/design`, {
              site, half_life: halfLife, edited_frac: editedFrac,
              mimetic, controls: controls.split('\n').map((s) => s.trim()).filter(Boolean),
              mechanism, refutation, citation,
            })
            if (r) { setReadiness(r.readiness); setStep(3) }
          }}>
            Check readiness →
          </button>
        </div>
      </main>
    )
  }

  // step 3 — readiness
  if (step === 3) {
    const blocked = readiness?.verdict === 'blocked'
    return (
      <main>
        <StepBar current={ 3 } />
        <h1 style={{ fontSize: 20 }}>3 · Readiness check</h1>
        <div className="card" style={{ maxWidth: 640 }}>
          <h3 style={{ margin: '0 0 8px' }}>
            {(readiness?.verdict ?? '').replace('_', ' ')}
          </h3>
          {readiness?.findings?.map((f: any, i: number) => (
            <p key={i} style={{ fontSize: 12, margin: '2px 0' }}>
              <span style={{
                fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
                textTransform: 'uppercase',
                color: f.severity === 'blocker' ? 'var(--bad)'
                  : f.severity === 'warning' ? 'var(--warn)' : 'var(--ok)',
              }}>{f.severity}</span>{' '}
              <strong>{f.check}</strong>: {f.message}
            </p>
          ))}
          {error && <p className="chip failed">{error}</p>}
          <div style={{ display: 'flex', gap: 8, marginTop: 10 }}>
            <button onClick={() => setStep(2)}>← Redesign</button>
            <button className="primary" disabled={blocked} onClick={async () => {
              const r = await call(`/api/wizard/sessions/${sid}/execute`)
              if (r) setStep(4)
            }}>
              Proceed to execution →
            </button>
          </div>
        </div>
      </main>
    )
  }

  // step 4 — execute
  if (step === 4) {
    return (
      <main>
        <StepBar current={ 4 } />
        <h1 style={{ fontSize: 20 }}>4 · Execute</h1>
        <div className="card" style={{ maxWidth: 640 }}>
          <p>
            Run the experiment defined in step 2 with the declared controls.
            When the instrument has written its export, continue to step 5.
          </p>
          <p className="muted" style={{ fontSize: 12 }}>
            experiment {eid}
          </p>
          <button className="primary" onClick={() => setStep(5)}>
            I have the export →
          </button>
        </div>
      </main>
    )
  }

  // step 5 — upload
  if (step === 5) {
    return (
      <main>
        <StepBar current={ 5 } />
        <h1 style={{ fontSize: 20 }}>5 · Upload instrument export</h1>
        <div className="card" style={{ maxWidth: 640, display: 'grid', gap: 10 }}>
          <input type="file" accept=".csv,.tsv,.xlsx"
            onChange={async (e) => {
              const f = e.target.files?.[0]
              if (!f) return
              const r = await call(`/api/wizard/sessions/${sid}/upload`, undefined, f)
              if (r) { setPlate(r.plate); setStep(6) }
            }} />
          {error && <p className="chip failed">{error}</p>}
        </div>
      </main>
    )
  }

  // step 6 — analyze
  const samples: string[] = plate?.samples ?? []
  const compounds = plate?.compounds ?? {}
  return (
    <main>
      <h1 style={{ fontSize: 20 }}>6 · Analyze hits & verdict</h1>
      <div className="card" style={{ maxWidth: 720 }}>
        {plate && (
          <p className="muted" style={{ fontSize: 12 }}>
            Loaded: {plate.format} · {plate.n_wells} wells · Z' = {plate.z_prime}
          </p>
        )}
        <table style={{ fontSize: 12, borderCollapse: 'collapse', marginBottom: 10 }}>
          <thead>
            <tr>
              <th style={{ textAlign: 'left', paddingRight: 14 }}>sample</th>
              <th style={{ textAlign: 'left', paddingRight: 14 }}>IC50 (µM)</th>
              <th style={{ textAlign: 'left' }}>hit</th>
            </tr>
          </thead>
          <tbody>
            {samples.map((s) => (
              <tr key={s}>
                <td style={{ paddingRight: 14 }}>{s}</td>
                <td style={{ paddingRight: 14 }}>
                  {compounds[s]?.ic50_um?.toFixed(2) ?? '> range'}
                </td>
                <td>
                  <input type="checkbox" checked={selected.includes(s)}
                    onChange={(e) => setSelected(
                      e.target.checked ? [...selected, s]
                        : selected.filter((x) => x !== s))} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {error && <p className="chip failed">{error}</p>}
        <button className="primary" onClick={async () => {
          const r = await call(`/api/wizard/sessions/${sid}/analyze`,
            { selected })
          if (r) nav(`/experiments/${eid}`)
        }}>
          Record verdict & finish
        </button>
      </div>
    </main>
  )
}
