import { useQuery } from '@tanstack/react-query'
import { Activity, ChevronRight, FlaskConical, Target, Users } from 'lucide-react'
import { useQueryClient } from '@tanstack/react-query'
import { Plus } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api/client'
import ProgramForm from './ProgramForm'
import { ApprovalsBanner } from './Approvals'
import type { ProblemTreeOut, ProgramOut } from '../api/client'

function statusChip(status: string) {
  return <span className={`chip ${status}`}>{status}</span>
}

function tallyText(tally: Record<string, number>) {
  const parts = Object.entries(tally).map(([s, n]) => `${n} ${s}`)
  return parts.length ? parts.join(' · ') : 'no experiments yet'
}

function ProgramHeader({ p }: { p: ProgramOut }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
      <Activity size={16} color="var(--teal)" />
      <strong>{p.name}</strong>
      <span className="muted" style={{ fontSize: 12 }}>
        {tallyText(p.tally)} · mode: {p.mode}
      </span>
    </div>
  )
}

function TreeBlock({ tree }: { tree: ProblemTreeOut }) {
  const roots = tree.nodes.filter((n) => !n.parent)
  const kids = (id: string) => tree.nodes.filter((n) => n.parent === id)
  const render = (id: string, depth: number) => {
    const n = tree.nodes.find((x) => x.id === id)!
    const isLeaf = kids(id).length === 0
    const stat = tree.leaf_stats[id]
    const alloc = tree.alloc[id] ?? 0
    return (
      <div key={id} style={{ marginLeft: depth * 18 }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '2px 0' }}>
          {isLeaf ? (
            <FlaskConical size={13} color="var(--teal)" />
          ) : (
            <ChevronRight size={13} color="var(--muted)" />
          )}
          <span style={{ fontSize: 13 }}>{n.objective}</span>
          <span className="muted" style={{ fontSize: 11 }}>
            {n.status}
            {n.metric ? ` · gate ${n.metric} ${n.direction === 'min' ? '≤' : '≥'} ${n.gate}` : ''}
            {isLeaf
              ? ` · ${stat?.runs ?? 0}/${alloc} runs`
              : ''}
          </span>
        </div>
        {kids(id).map((k) => render(k.id, depth + 1))}
      </div>
    )
  }
  return <div>{roots.map((r) => render(r.id, 0))}</div>
}

export default function Workspace({ initialForm = false }: {
  initialForm?: boolean
}) {
  const q = useQuery({ queryKey: ['workspace'], queryFn: api.workspace })
  const qc = useQueryClient()
  const [showForm, setShowForm] = useState(initialForm)
  if (q.isLoading) return <p className="muted">Loading…</p>
  if (q.isError) return <p className="chip failed">API unreachable — is uvicorn on :8000?</p>
  const ws = q.data!

  return (
    <main>
      <ApprovalsBanner />
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
        <div>
          <h1 style={{ fontSize: 20, margin: '0 0 2px' }}>Programs</h1>
          <p className="muted" style={{ margin: 0, fontSize: 12 }}>
            Program ▸ campaign ▸ problem ▸ experiment — click an experiment to open it
          </p>
        </div>
        <button className="primary" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
          onClick={() => setShowForm((s) => !s)}>
          <Plus size={15} /> New program
        </button>
      </div>

      {showForm && (
        <section className="card" style={{ marginBottom: 12 }}>
          <h2 style={{ fontSize: 15, margin: '0 0 8px', display: 'flex', gap: 6, alignItems: 'center' }}>
            <Target size={15} color="var(--teal)" /> New program — pick the
            launch type: autonomous (agent runs the DMTA loop) or guided
            (wizard)
          </h2>
          <ProgramForm onLaunched={() => { setShowForm(false); qc.invalidateQueries() }} />
        </section>
      )}

      {ws.programs.map((p) => (
        <section key={p.slug} className="card" style={{ marginBottom: 12 }}>
          <ProgramHeader p={p} />
          {p.links.filter((l) => l.role === 'leaf').length === 0 && (
            <p className="muted" style={{ fontSize: 12, margin: '6px 0 0 24px' }}>
              no experiments yet — open the Program page in the workbench to launch
            </p>
          )}
          <div style={{ marginLeft: 24 }}>
            {p.links
              .filter((l) => l.role === 'leaf')
              .map((l) => (
                <div key={l.eid} style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0' }}>
                  <FlaskConical size={13} color="var(--teal)" />
                  <a href={`/experiments/${l.eid}`} style={{ fontSize: 13 }}>
                    {l.question || l.eid}
                  </a>
                  {statusChip(l.status)}
                </div>
              ))}
          </div>
        </section>
      ))}

      {ws.trees.filter((t) => !t.is_linked).map((t) => (
        <section key={t.root_id} className="card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <Activity size={16} color="var(--amber)" />
            <strong>{t.objective}</strong>
            <span className="muted" style={{ fontSize: 12 }}>
              {t.rollup[t.root_id] ?? 'open'}
            </span>
          </div>
          <div style={{ marginLeft: 24 }}>
            <TreeBlock tree={t} />
          </div>
        </section>
      ))}

      {Object.entries(ws.groups).map(([group, entries]) => (
        <section key={group} className="card" style={{ marginBottom: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <Users size={16} color="var(--amber)" />
            <strong>
              {group === 'autonomous' ? 'Autonomous campaigns' : 'Guided experiments'}
            </strong>
            <span className="muted" style={{ fontSize: 12 }}>
              {entries.length} experiment(s)
            </span>
          </div>
          <div style={{ marginLeft: 24 }}>
            {entries.map((e) => (
              <div key={e.eid} style={{ display: 'flex', alignItems: 'baseline', gap: 8, padding: '3px 0' }}>
                <FlaskConical size={13} color="var(--teal)" />
                <a href={`/experiments/${e.eid}`} style={{ fontSize: 13 }}>
                  {e.question || e.eid}
                </a>
                {statusChip(e.status)}
              </div>
            ))}
          </div>
        </section>
      ))}

      {ws.archived.length > 0 && (
        <details className="card">
          <summary style={{ cursor: 'pointer' }}>
            Archived ({ws.archived.length}) — retired from the working set
          </summary>
          {ws.archived.map((a) => (
            <div key={a.eid} className="muted" style={{ fontSize: 12, padding: '2px 0' }}>
              {a.question || a.eid}
            </div>
          ))}
        </details>
      )}
    </main>
  )
}
