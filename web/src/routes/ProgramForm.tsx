import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Rocket, Target } from 'lucide-react'

interface ModalityPack {
  name: string
  production_action: string
  test_assays: string[]
  safety_rule_names: string[]
  notes: string
}

export default function ProgramForm({ onLaunched, onDone }: {
  onLaunched?: () => void
  onDone?: () => void
} = {}) {
  const qc = useQueryClient()
  const nav = useNavigate()
  const packsQ = useQuery({
    queryKey: ['modalities'],
    queryFn: () => fetch('/api/system/modalities').then((r) => r.json()),
  })
  const packs: ModalityPack[] = packsQ.data?.packs ?? []
  const packNames = [...packs.map((p: ModalityPack) => p.name), 'Other']

  const [name, setName] = useState('')
  const [objective, setObjective] = useState('')
  const [modality, setModality] = useState('small molecule')
  const [customModality, setCustomModality] = useState('')
  const [metric, setMetric] = useState('ic50')
  const [unit, setUnit] = useState('µM')
  const [direction, setDirection] = useState('min')
  const [gateValue, setGateValue] = useState(20)
  const [mode, setMode] = useState('autonomous')
  const [autonomy, setAutonomy] = useState('act')
  const [k, setK] = useState(2)
  const [rounds, setRounds] = useState(2)
  const [candidates, setCandidates] = useState('')
  const [decompose, setDecompose] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const effectiveModality = modality === 'Other' ? customModality.trim() : modality
  const pack = packs.find((p) => p.name === modality)

  async function launch() {
    setBusy(true)
    setError('')
    try {
      const doc = {
        program: name, objective, modality: effectiveModality, metric,
        unit, direction, gate_value: gateValue, mode, autonomy,
        k, rounds, candidates, decompose: decompose && mode === 'autonomous',
      }
      const r = await fetch('/api/programs', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(doc),
      })
      if (!r.ok) throw new Error((await r.json()).detail ?? 'save failed')
      const { slug } = await r.json()
      onDone?.()
      if (mode !== 'autonomous') {
        onLaunched?.()
        nav(`/wizard?program=${encodeURIComponent(slug)}`)
        return
      }
      const lr = await fetch(`/api/programs/${slug}/launch`, { method: 'POST' })
      if (!lr.ok) throw new Error((await lr.json()).detail ?? 'launch failed')
      const { eid, decomposed } = await lr.json()
      onLaunched?.()
      // decomposed launches fan out into leaf campaigns — there is no
      // single experiment page to open; land on the workspace instead
      nav(decomposed || !eid ? '/' : `/experiments/${eid}`)
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  const canLaunch = name.trim() && objective.trim() && !busy

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1fr) 300px',
      gap: 14, alignItems: 'start' }}>
      <div className="card" style={{ display: 'grid', gap: 10 }}>
        <label>
          Program name *
          <input value={name} onChange={(e) => setName(e.target.value)}
            style={inputStyle} placeholder="Material-14" />
        </label>
        <label>
          Objective *
          <input value={objective} onChange={(e) => setObjective(e.target.value)}
            style={inputStyle}
            placeholder="objective: e.g. Find crosslinker density maximizing tensile strength" />
        </label>
        <label>
          Modality
          <select value={modality} onChange={(e) => setModality(e.target.value)}
            style={inputStyle}>
            {packNames.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        {modality === 'Other' && (
          <label>
            Custom modality
            <input value={customModality}
              onChange={(e) => setCustomModality(e.target.value)}
              style={inputStyle} />
          </label>
        )}
        {pack && (
          <p className="muted" style={{ fontSize: 12, margin: 0 }}>
            pack: {pack.production_action} in Make · Test via{' '}
            {pack.test_assays.join(', ')} · gate rules:{' '}
            {pack.safety_rule_names.join(', ')}
          </p>
        )}
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 90px 90px 120px', gap: 8 }}>
          <label>Metric
            <input value={metric} onChange={(e) => setMetric(e.target.value)} style={inputStyle} />
          </label>
          <label>Unit
            <input value={unit} onChange={(e) => setUnit(e.target.value)} style={inputStyle} />
          </label>
          <label>Better is
            <select value={direction} onChange={(e) => setDirection(e.target.value)} style={inputStyle}>
              <option>min</option><option>max</option>
            </select>
          </label>
          <label>Gate value
            <input type="number" value={gateValue}
              onChange={(e) => setGateValue(Number(e.target.value))} style={inputStyle} />
          </label>
        </div>
        <label>
          Execution mode
          <select value={mode} onChange={(e) => setMode(e.target.value)} style={inputStyle}>
            <option>autonomous</option>
            <option>guided</option>
          </select>
        </label>

        <details>
          <summary style={{ cursor: 'pointer', fontSize: 13 }}>Launch settings</summary>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, marginTop: 8 }}>
            <label>Autonomy
              <select value={autonomy} onChange={(e) => setAutonomy(e.target.value)} style={inputStyle}>
                <option>act</option><option>gate</option><option>observe</option>
              </select>
            </label>
            <label>Top-k per round
              <input type="number" min={1} max={6} value={k}
                onChange={(e) => setK(Number(e.target.value))} style={inputStyle} />
            </label>
            <label>DMTA rounds
              <input type="number" min={1} max={6} value={rounds}
                onChange={(e) => setRounds(Number(e.target.value))} style={inputStyle} />
            </label>
          </div>
            <label style={{ display: 'flex', gap: 6, alignItems: 'center',
              marginTop: 4 }}>
              <input type="checkbox" checked={decompose}
                onChange={(e) => setDecompose(e.target.checked)} />
              Let the agent split the objective into sub-problems (problem
              tree, runs longer)
            </label>
          <label style={{ display: 'block', marginTop: 8 }}>
            Candidates (optional — empty = agent proposes them)
            <input value={candidates} onChange={(e) => setCandidates(e.target.value)}
              style={inputStyle} placeholder="gefitinib, erlotinib" />
          </label>
        </details>

        {error && <p className="chip failed">{error}</p>}
        <div>
          <button className="primary" disabled={!canLaunch} onClick={launch}
            style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}>
            <Rocket size={15} /> Launch program
          </button>
          <span className="muted" style={{ fontSize: 12, marginLeft: 10 }}>
            {mode === 'autonomous'
              ? 'spawns the campaign immediately and opens it'
              : 'opens the guided wizard'}
          </span>
        </div>
      </div>

      <div className="card" style={{
        position: 'sticky', top: 16, display: 'grid', gap: 8,
        borderColor: 'var(--brand-border)', background: 'var(--brand-tint)' }}>
        <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
          letterSpacing: '0.05em' }}>Launch summary</div>
        <div style={{ fontSize: 12, display: 'grid', gap: 5 }}>
          <div><strong>{name || '—'}</strong></div>
          <div className="muted">{objective || 'objective not set'}</div>
          <div className="hairline" style={{ margin: 0 }} />
          <div>gate: <span className="mono">{metric} {direction === 'min' ? '≤' : '≥'} {gateValue} {unit}</span></div>
          <div>modality: {effectiveModality || '—'}</div>
          <div>mode: {mode} · autonomy: {autonomy}</div>
          <div>budget: top-{k}/round × {rounds} round{rounds > 1 ? 's' : ''}</div>
          <div>candidates: {candidates.trim()
            ? `${candidates.split(',').filter((s) => s.trim()).length} named`
            : 'agent-proposed'}</div>
        </div>
      </div>
    </div>
  )
}

const inputStyle: React.CSSProperties = {
  display: 'block', width: '100%', marginTop: 2, marginBottom: 4,
  padding: '5px 8px', border: '1px solid var(--line)',
  borderRadius: 'var(--radius)', font: 'inherit', background: '#fff',
}
