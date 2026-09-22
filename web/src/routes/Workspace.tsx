import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ChevronRight, FlaskConical, Plus, Target, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ProblemTreeOut, ProgramOut } from '../api/client'
import { Badge, EmptyState, PageHeader, Skeleton } from '../components/ui'
import ProgramForm from './ProgramForm'

function statusChip(status: string) {
  return <Badge status={status} />
}

function tallyText(tally: Record<string, number>) {
  const parts = Object.entries(tally).map(([s, n]) => `${n} ${s}`)
  return parts.length ? parts.join(' · ') : 'no experiments yet'
}

function ArchiveButton({ label, confirmLabel, small, onConfirm }: {
  label: string
  confirmLabel: string
  small?: boolean
  onConfirm: () => Promise<void>
}) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  return (
    <button
      className={armed ? 'danger' : ''}
      style={{ fontSize: small ? 10 : 11, padding: small ? '1px 7px' : undefined,
        whiteSpace: 'nowrap', flex: 'none' }}
      disabled={busy}
      title={armed ? 'click again to confirm' : undefined}
      onClick={async () => {
        if (armed) {
          setBusy(true)
          await onConfirm()
          setBusy(false)
        } else {
          setArmed(true)
          setTimeout(() => setArmed(false), 6000)
        }
      }}>
      {armed ? confirmLabel : label}
    </button>
  )
}

function ProgramCard({ p, onDelete, deleting }: {
  p: ProgramOut
  onDelete: (slug: string) => void
  deleting: string | null
}) {
  const nav = useNavigate()
  const done = p.tally['completed'] ?? 0
  const running = p.tally['running'] ?? 0
  const total = Object.values(p.tally).reduce((a, b) => a + b, 0)
  const [open, setOpen] = useState(false)
  const leaves = p.links.filter((l) => l.role === 'leaf')
  return (
    <div className="card" style={{ display: 'grid', gap: 10 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', minWidth: 0,
          cursor: 'pointer', flex: 1 }} onClick={() => setOpen((o) => !o)}>
          <Target size={15} color="var(--brand)" style={{ flex: 'none' }} />
          <strong style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {p.name}
          </strong>
          <ChevronRight size={13} color="var(--muted)"
            style={{ flex: 'none', transform: open ? 'rotate(90deg)' : 'none',
              transition: 'transform var(--speed) var(--ease)' }} />
        </div>
        <button
          className={deleting === p.slug ? 'danger' : ''}
          style={{ fontSize: 11, padding: '2px 8px', display: 'inline-flex',
            gap: 4, alignItems: 'center', flex: 'none' }}
          title={deleting === p.slug
            ? 'click again to delete — experiments are kept'
            : 'delete this program (experiments are kept)'}
          onClick={(e) => {
            e.stopPropagation()
            if (deleting === p.slug) onDelete(p.slug)
            else onDelete(`arm:${p.slug}`)
          }}>
          <Trash2 size={11} />
          {deleting === p.slug ? 'Confirm?' : ''}
        </button>
      </div>
      <div className="muted" style={{ fontSize: 12, overflow: 'hidden',
        textOverflow: 'ellipsis', display: 'flex', gap: 6 }}>
        <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {p.objective ?? p.gate_summary}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {p.modality && <span className="chip">{p.modality}</span>}
        <span className="chip">{p.mode}</span>
        {running > 0 && <Badge status="running">{running} running</Badge>}
        <span className="muted" style={{ fontSize: 11, marginLeft: 'auto' }}>
          {total === 0 ? 'no experiments yet' : `${total} experiment(s)${done ? ` · ${done} completed` : ''}`}
        </span>
      </div>
      {open && (
        <div style={{ display: 'grid', gap: 4, borderTop: '1px solid var(--border)',
          paddingTop: 8 }}>
          {leaves.length === 0 && (
            <span className="muted" style={{ fontSize: 12 }}>
              no experiments yet — launch one from the New-program form
            </span>
          )}
          {leaves.map((l) => (
            <div key={l.eid} style={{ display: 'flex', alignItems: 'baseline', gap: 8 }}>
              <FlaskConical size={12} color="var(--brand)" />
              <a href={`/experiments/${l.eid}`} style={{ fontSize: 12 }}
                onClick={(e) => e.stopPropagation()}>
                {l.question || l.eid}
              </a>
              <Badge status={l.status} />
            </div>
          ))}
        </div>
      )}
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
            <FlaskConical size={13} color="var(--brand)" />
          ) : (
            <ChevronRight size={13} color="var(--muted)" />
          )}
          <span style={{ fontSize: 13 }}>{n.objective}</span>
          <span className="muted mono" style={{ fontSize: 11 }}>
            {n.status}
            {n.metric ? ` · ${n.metric} ${n.direction === 'min' ? '≤' : '≥'} ${n.gate}` : ''}
            {isLeaf ? ` · ${stat?.runs ?? 0}/${alloc} runs` : ''}
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
  const nav = useNavigate()
  const [showForm, setShowForm] = useState(initialForm)
  const [deleting, setDeleting] = useState<string | null>(null)

  async function doDelete(slug: string) {
    const r = await fetch(`/api/programs/${slug}`, { method: 'DELETE' })
    if (r.ok) {
      setDeleting(null)
      qc.invalidateQueries({ queryKey: ['workspace'] })
    } else {
      setDeleting(null)
    }
  }

  if (q.isLoading) {
    return (
      <main style={{ display: 'grid', gap: 12 }}>
        <Skeleton w={220} h={24} />
        <Skeleton w="100%" h={110} />
        <Skeleton w="100%" h={110} />
      </main>
    )
  }
  if (q.isError)
    return <EmptyState title="API unreachable"
      hint="Start the backend: make api (uvicorn on :8000)" />

  const ws = q.data!
  const runningTotal = Object.values(ws.groups)
    .flat().filter((e) => e.status === 'running').length
  const verdictTotal = Object.values(ws.groups)
    .flat().length

  return (
    <main>
      <PageHeader title="Programs" eyebrow="Workspace"
        right={
          <button className="primary" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
            onClick={() => setShowForm((s) => !s)}>
            <Plus size={15} /> New program
          </button>
        } />

      {/* live stats band */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))',
        gap: 8, maxWidth: 640, marginBottom: 'var(--s4)' }}>
        {[
          ['Programs', ws.programs.length],
          ['Running', runningTotal],
          ['Experiments', verdictTotal],
        ].map(([label, n]) => (
          <div key={String(label)} className="card"
            style={{ padding: '8px 14px', display: 'flex', gap: 8, alignItems: 'baseline' }}>
            <span className="mono" style={{ fontSize: 20, fontWeight: 600 }}>{n}</span>
            <span className="muted" style={{ fontSize: 11, textTransform: 'uppercase',
              letterSpacing: '0.04em' }}>{label}</span>
          </div>
        ))}
      </div>

      {showForm && (
        <section className="card" style={{ marginBottom: 'var(--s4)' }}>
          <h2 style={{ fontSize: 15, margin: '0 0 8px', display: 'flex', gap: 6, alignItems: 'center' }}>
            <Target size={15} color="var(--brand)" /> New program — pick the
            launch type: autonomous (agent runs the DMTA loop) or guided
            (wizard)
          </h2>
          <ProgramForm onDone={() => { setShowForm(false); qc.invalidateQueries() }} />
        </section>
      )}

      {/* program grid */}
      {ws.programs.length > 0 ? (
        <div style={{ display: 'grid', gridTemplateColumns:
          'repeat(auto-fill, minmax(340px, 1fr))', gap: 10,
          alignItems: 'start', marginBottom: 'var(--s5)' }}>
          {ws.programs.map((p) => (
            <ProgramCard key={p.slug} p={p} deleting={deleting}
              onDelete={(slug) => {
                if (slug.startsWith('arm:')) setDeleting(slug.slice(4))
                else doDelete(slug)
              }} />
          ))}
        </div>
      ) : (
        <EmptyState
          icon={<Target size={28} />}
          title="No programs yet"
          hint="Define a program — objective, gate, modality — then launch an autonomous campaign or the guided wizard."
          action={
            <button className="primary" style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}
              onClick={() => setShowForm(true)}>
              <Plus size={15} /> New program
            </button>
          } />
      )}

      {/* activity: free trees + groups */}
      {ws.trees.filter((t) => !t.is_linked).map((t) => (
        <section key={t.root_id} className="card" style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <Activity size={15} color="var(--brand)" />
            <strong style={{ fontSize: 13 }}>{t.objective}</strong>
            <span className="muted mono" style={{ fontSize: 11 }}>
              {t.rollup[t.root_id] ?? 'open'}
            </span>
          </div>
          <div style={{ marginLeft: 24 }}>
            <TreeBlock tree={t} />
          </div>
        </section>
      ))}

      {Object.entries(ws.groups).map(([group, entries]) => (
        <section key={group} className="card" style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
            <Users size={15} color="var(--muted)" />
            <strong style={{ fontSize: 13 }}>
              {group === 'autonomous' ? 'Autonomous campaigns' : 'Guided experiments'}
            </strong>
            <span className="muted" style={{ fontSize: 11 }}>
              {entries.length} experiment(s)
            </span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'flex-end', padding: '0 0 4px' }}>
            <ArchiveButton small label="Archive all" confirmLabel={`Archive all ${entries.length}?`}
              onConfirm={async () => {
                for (const e of entries) {
                  await fetch(`/api/experiments/${e.eid}/archive`, { method: 'POST' })
                }
                qc.invalidateQueries({ queryKey: ['workspace'] })
              }} />
          </div>
          {entries.map((e) => (
            <div key={e.eid}
              style={{ display: 'flex', alignItems: 'baseline', gap: 8,
                padding: '5px 0 5px 24px', borderBottom: '1px solid var(--border)' }}>
              <FlaskConical size={12} color="var(--brand)" />
              <a href={`/experiments/${e.eid}`} style={{ fontSize: 13 }}>{e.question || e.eid}</a>
              {statusChip(e.status)}
              <ArchiveButton small label="✕" confirmLabel="archive?"
                onConfirm={async () => {
                  await fetch(`/api/experiments/${e.eid}/archive`, { method: 'POST' })
                  qc.invalidateQueries({ queryKey: ['workspace'] })
                }} />
            </div>
          ))}
        </section>
      ))}

      {ws.archived.length > 0 && (
        <details className="card">
          <summary style={{ cursor: 'pointer', fontSize: 12 }}>
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
