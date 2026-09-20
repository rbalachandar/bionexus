import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ShieldAlert } from 'lucide-react'

export function HaltBanner() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['halt'], queryFn: () =>
    fetch('/api/halt').then((r) => r.json()) })
  const [busy, setBusy] = useState(false)
  if (q.isLoading) return null
  const halted = q.data?.halted
  if (!halted) return null
  return (
    <div className="card" style={{ borderColor: 'var(--bad)', marginBottom: 12,
      display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
      <span style={{ display: 'inline-flex', gap: 8, alignItems: 'center' }}>
        <ShieldAlert size={16} color="var(--bad)" />
        <strong>Operator halt engaged</strong>
        <span className="muted" style={{ fontSize: 12 }}>
          {q.data.detail?.reason ?? 'manual halt'} — campaigns will refuse
          to proceed
        </span>
      </span>
      <button disabled={busy} onClick={async () => {
        setBusy(true)
        await fetch('/api/halt', { method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ halted: false }) })
        qc.invalidateQueries({ queryKey: ['halt'] })
        setBusy(false)
      }}>
        Lift halt
      </button>
    </div>
  )
}

export default function Approvals() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['approvals'], queryFn: () =>
    fetch('/api/approvals').then((r) => r.json()) })
  const haltQ = useQuery({ queryKey: ['halt'], queryFn: () =>
    fetch('/api/halt').then((r) => r.json()) })
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  async function decide(id: string, approve: boolean) {
    await fetch(`/api/approvals/${id}/decide`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve }) })
    qc.invalidateQueries({ queryKey: ['approvals'] })
  }

  return (
    <main>
      <h1 style={{ fontSize: 20 }}>Approvals & governance</h1>

      <div className="card" style={{ marginBottom: 12 }}>
        <h3 style={{ margin: '0 0 8px', display: 'flex', gap: 8, alignItems: 'center' }}>
          <ShieldAlert size={15} color={haltQ.data?.halted ? 'var(--bad)' : 'var(--muted)'} />
          Operator halt
        </h3>
        {haltQ.data?.halted ? (
          <p style={{ fontSize: 13 }}>
            <strong>Halted</strong> — {haltQ.data.detail?.reason}
          </p>
        ) : (
          <div style={{ display: 'flex', gap: 8 }}>
            <input value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="reason (recorded in the audit trail)"
              style={{ flex: 1, padding: '5px 8px', border: '1px solid var(--line)',
                borderRadius: 'var(--radius)', font: 'inherit' }} />
            <button className="danger" disabled={busy} onClick={async () => {
              setBusy(true)
              await fetch('/api/halt', { method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ halted: true, reason: reason || 'operator halt (web)' }) })
              qc.invalidateQueries({ queryKey: ['halt'] })
              setBusy(false)
            }}>
              Engage halt
            </button>
          </div>
        )}
      </div>

      <div className="card">
        <h3 style={{ margin: '0 0 8px' }}>
          Pending approvals ({q.data?.pending?.length ?? 0})
        </h3>
        {(q.data?.pending ?? []).map((a: any) => (
          <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between',
            alignItems: 'center', padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
            <div>
              <strong style={{ fontSize: 13 }}>{a.title}</strong>
              {a.detail && <div className="muted" style={{ fontSize: 12 }}>{a.detail}</div>}
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button className="primary" onClick={() => decide(a.id, true)}>Approve</button>
              <button className="danger" onClick={() => decide(a.id, false)}>Deny</button>
            </div>
          </div>
        ))}
        {q.data?.pending?.length === 0 && (
          <p className="muted" style={{ fontSize: 12 }}>Nothing pending.</p>
        )}
      </div>
    </main>
  )
}

export function ApprovalsBanner() {
  const qc = useQueryClient()
  const q = useQuery({ queryKey: ['approvals'], queryFn: () =>
    fetch('/api/approvals').then((r) => r.json()) })
  const [busy, setBusy] = useState(false)
  const pending = q.data?.pending ?? []
  if (q.isLoading || pending.length === 0) return null
  async function decide(id: string, approve: boolean) {
    setBusy(true)
    await fetch(`/api/approvals/${id}/decide`, { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ approve }) })
    qc.invalidateQueries({ queryKey: ['approvals'] })
    setBusy(false)
  }
  return (
    <div className="card" style={{ borderColor: 'var(--amber)', marginBottom: 12 }}>
      <strong style={{ display: 'block', marginBottom: 6 }}>
        Pending approvals ({pending.length})
      </strong>
      {pending.map((a: any) => (
        <div key={a.id} style={{ display: 'flex', justifyContent: 'space-between',
          alignItems: 'center', padding: '4px 0', gap: 10 }}>
          <div style={{ fontSize: 12 }}>
            <strong>{a.title}</strong>
            {a.detail && <span className="muted"> — {a.detail}</span>}
          </div>
          <div style={{ display: 'flex', gap: 6, whiteSpace: 'nowrap' }}>
            <button className="primary" disabled={busy}
              onClick={() => decide(a.id, true)}>Approve</button>
            <button className="danger" disabled={busy}
              onClick={() => decide(a.id, false)}>Deny</button>
          </div>
        </div>
      ))}
    </div>
  )
}
