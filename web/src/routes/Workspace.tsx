import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Activity, ChevronRight, FlaskConical, Plus, Target, Trash2, Users } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ProblemTreeOut, ProgramOut, TasteReport } from '../api/client'
import { Badge, EmptyState, Skeleton, VERDICT_GLYPH } from '../components/ui'
import ProgramForm from './ProgramForm'

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

const NO_LABEL_STATUS = new Set(['completed', 'archived'])

/** Leaf label: never re-print the program objective — campaigns are
 * numbered and named by what they tested; tree leaves keep their own
 * short objective head. */
function leafLabel(question: string | null, objective: string | null,
  i: number, candidates?: string[]) {
  const cands = (candidates ?? []).slice(0, 3).join(', ') +
    ((candidates?.length ?? 0) > 3 ? ` +${candidates!.length - 3}` : '')
  if (!objective) return question ?? `Experiment ${i + 1}`
  const q = question ?? ''
  const head = q.split(/\s+[—–]\s/)[0].trim()
  if (!q || q.trim() === objective.trim() || head === objective.trim())
    return cands ? `Campaign ${i + 1} · ${cands}` : `Campaign ${i + 1}`
  const label = head.length > 56 ? `${head.slice(0, 53)}…` : head
  return cands ? `${label} · ${cands}` : label
}

/** Row tooltip: what this experiment actually did — not the objective
 * the card above it already shows. */
function leafTitle(l: { eid: string; question: string | null; runs?: number;
  verdicts?: { confirmed: number; refuted: number; inconclusive: number };
  candidates?: string[] }) {
  const bits: string[] = []
  if (l.candidates?.length) bits.push(`tested: ${l.candidates.join(', ')}`)
  if (l.runs) bits.push(`${l.runs} runs`)
  const v = l.verdicts
  if (v && (v.confirmed || v.refuted || v.inconclusive))
    bits.push(`✓${v.confirmed} ✗${v.refuted} ∅${v.inconclusive}`)
  bits.push(l.eid)
  return bits.join(' · ')
}

function VerdictTally({ v }: {
  v?: { confirmed: number; refuted: number; inconclusive: number }
}) {
  if (!v) return null
  const parts = [[v.confirmed, VERDICT_GLYPH.confirmed, 'var(--ok)'],
    [v.refuted, VERDICT_GLYPH.refuted, 'var(--bad)'],
    [v.inconclusive, VERDICT_GLYPH.inconclusive, 'var(--warn)']] as const
  const shown = parts.filter(([n]) => n > 0)
  if (shown.length === 0) return null
  return (
    <span className="mono" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
      {shown.map(([n, g, c]) => (
        <span key={g} style={{ color: c, marginRight: 6 }}>{g}{n}</span>
      ))}
    </span>
  )
}

function TasteLines({ taste, compact }: { taste: TasteReport; compact?: boolean }) {
  const rows = (['mechanism', 'refutation', 'citation_verified'] as const)
    .map((k) => ({ key: k, s: taste.by_feature[k] }))
    .filter((r) => r.s?.rate !== null && r.s?.rate !== undefined)
  const LABEL: Record<string, string> = {
    mechanism: 'mechanism stated',
    refutation: 'refutation condition stated',
    citation_verified: 'citation verified (PubMed)' }
  return (
    <div style={{ display: 'grid', gap: 2 }}>
      <div className="muted" style={{ fontSize: compact ? 10 : 11,
        textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        Selection profile — {taste.n} decisions · {taste.accepted} accepted
        {' '}({Math.round(taste.overall_rate * 100)}%) · advisory
      </div>
      {(() => {
        const informative = rows.filter((r) => r.s.rate_without !== null)
        if (informative.length === 0)
          return (
            <div className="muted" style={{ fontSize: 11 }}>
              No within-program contrast: all {taste.n} hypotheses carry
              the demanded features, so accept-rate deltas can't be
              computed. {taste.accepted}/{taste.n} accepted.
            </div>
          )
        return informative.map((r) => {
          const same = Math.abs(r.s.rate! - r.s.rate_without!) < 0.005
          return (
            <div key={r.key} style={{ display: 'flex', flexWrap: 'wrap',
              gap: '2px 10px', alignItems: 'baseline',
              fontSize: compact ? 11 : 12 }}>
              <span>{LABEL[r.key]}</span>
              <span className="mono" style={{ marginLeft: 'auto',
                textAlign: 'right', minWidth: 0, overflowWrap: 'anywhere' }}>
                {same ? 'no difference' : `accepted with: ${Math.round(r.s.rate! * 100)}% · without: ${Math.round(r.s.rate_without! * 100)}%`}
                <span className="muted"> (n={r.s.n})</span>
              </span>
            </div>
          )
        })
      })()}
      {taste.amendments.map((a) => (
        <div key={a} className="muted" style={{ fontSize: 11 }}>
          • {a}
        </div>
      ))}
    </div>
  )
}

function ProgramCard({ p, onDelete, deleting }: {
  p: ProgramOut
  onDelete: (slug: string) => void
  deleting: string | null
}) {
  const done = p.tally['completed'] ?? 0
  const running = p.tally['running'] ?? 0
  const total = Object.values(p.tally).reduce((a, b) => a + b, 0)
  const [collapsed, setCollapsed] = useState(false)
  const [showAll, setShowAll] = useState(false)
  const leaves = p.links.filter((l) => l.role === 'leaf' && l.live !== false)
  const open = !collapsed
  const MAX_ROWS = 4
  const shown = showAll ? leaves : leaves.slice(0, MAX_ROWS)
  return (
    <div className="card" style={{ display: 'grid', gap: 10, width: '100%',
      marginBottom: 10, breakInside: 'avoid' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center', minWidth: 0,
          cursor: 'pointer', flex: 1 }} onClick={() => setCollapsed((c) => !c)}>
          <Target size={15} color="var(--brand)" style={{ flex: 'none' }} />
          <strong style={{ fontSize: 14, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {p.name}
          </strong>
          <ChevronRight size={13} color="var(--muted)"
            style={{ flex: 'none', transform: open ? 'rotate(90deg)' : 'none',
              transition: 'transform var(--speed) var(--ease)' }} />
          {total > 0 && (
            <span className="muted mono" style={{ fontSize: 11, whiteSpace: 'nowrap',
              overflow: 'hidden', textOverflow: 'ellipsis' }}>
              {total} exp{total === 1 ? '' : 's'}{done > 0 && ` · ${done} done`}
            </span>
          )}
        </div>
        <button
          className={deleting === p.slug ? 'danger' : ''}
          style={{ fontSize: 11, padding: '2px 8px', display: 'inline-flex',
            gap: 4, alignItems: 'center', flex: 'none' }}
          title={deleting === p.slug
            ? 'click again to confirm — experiments are kept'
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
      <div className="muted" style={{ fontSize: 12 }}>
        <span style={{ display: '-webkit-box', WebkitLineClamp: 3,
          WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {p.objective ?? p.gate_summary}
        </span>
      </div>
      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        {p.modality && <span className="chip meta">{p.modality}</span>}
        <span className="chip meta">{p.mode}</span>
        {running > 0 && <Badge status="running">{running} running</Badge>}
      </div>
      {open && (
        <div style={{ display: 'grid', gap: 2, borderTop: '1px solid var(--border)',
          paddingTop: 8 }}>
          {leaves.length === 0 && (
            <span className="muted" style={{ fontSize: 12 }}>
              no experiments yet — launch one from the New-program form
            </span>
          )}
          {shown.map((l, i) => (
            <a key={l.eid} href={`/experiments/${l.eid}`}
              onClick={(e) => e.stopPropagation()}
              title={leafTitle(l)}
              style={{ display: 'grid', gridTemplateColumns: '7px minmax(0, 1fr) auto',
                gap: 8, alignItems: 'center', padding: '3px 0', fontSize: 12 }}>
              <span className={`dot ${l.status}`} />
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis',
                whiteSpace: 'nowrap' }}>
                {leafLabel(l.question, p.objective, i, l.candidates)}
              </span>
              <span style={{ display: 'flex', gap: 8, alignItems: 'center',
                justifySelf: 'end', whiteSpace: 'nowrap' }}>
                <VerdictTally v={l.verdicts} />
                <span className="muted mono" style={{ fontSize: 11 }}>
                  {l.runs ?? 0} runs · r{l.rounds_done ?? 0}{l.rounds_planned ? `/${l.rounds_planned}` : ''}
                </span>
                {!NO_LABEL_STATUS.has(l.status) && <Badge status={l.status} />}
              </span>
            </a>
          ))}
          {leaves.length > MAX_ROWS && !showAll && (
            <button style={{ justifySelf: 'start', fontSize: 11, padding: '2px 8px',
              marginTop: 2 }} onClick={() => setShowAll(true)}>
              +{leaves.length - MAX_ROWS} more
            </button>
          )}
          {p.taste && p.taste.n >= 6 && (
            <div style={{ borderTop: '1px solid var(--border)', paddingTop: 8,
              marginTop: 4 }}>
              <TasteLines taste={p.taste} compact />
            </div>
          )}
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
          {isLeaf && stat?.eid ? (
            <a href={`/experiments/${stat.eid}`} style={{ fontSize: 13 }}>
              {n.objective}
            </a>
          ) : (
            <span style={{ fontSize: 13 }}>{n.objective}</span>
          )}
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
  const verdictTotal = ws.experiments_total ?? 0

  return (
    <main>
      <div style={{ display: 'flex', justifyContent: 'space-between',
        alignItems: 'baseline', gap: 12, marginBottom: 'var(--s2)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 14,
          minWidth: 0, flexWrap: 'wrap' }}>
          <h1 style={{ fontSize: 'var(--fs-xl)', margin: 0, fontWeight: 650 }}>
            Workspace
          </h1>
          <span className="muted mono" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>
            {ws.programs.length} program{ws.programs.length === 1 ? '' : 's'}
            {' · '}{runningTotal} running{' · '}{verdictTotal} experiment{verdictTotal === 1 ? '' : 's'}
          </span>
        </div>
        <button className="primary" style={{ display: 'inline-flex', gap: 6,
          alignItems: 'center', flex: 'none' }}
          onClick={() => setShowForm((s) => !s)}>
          <Plus size={15} /> New program
        </button>
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
        <div style={{ columns: '3 340px', columnGap: 10,
        marginBottom: 'var(--s5)' }}>
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
          <div style={{ display: 'flex', justifyContent: 'space-between',
            alignItems: 'center', gap: 10 }}>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, minWidth: 0 }}>
              <Activity size={15} color="var(--brand)" />
              <strong style={{ fontSize: 13, overflow: 'hidden',
                textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.objective}</strong>
              <span className="muted mono" style={{ fontSize: 11 }}>
                {t.rollup[t.root_id] ?? 'open'}
              </span>
            </div>
            <ArchiveButton small label="Delete" confirmLabel="Confirm delete?"
              onConfirm={async () => {
                await fetch(`/api/trees/${t.root_id}/archive`, { method: 'POST' })
                qc.invalidateQueries({ queryKey: ['workspace'] })
              }} />
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
          {entries.map((e, i) => (
            <div key={e.eid}
              style={{ display: 'grid', gridTemplateColumns: '7px minmax(0, 1fr) auto',
                gap: 8, alignItems: 'center', padding: '4px 0 4px 24px',
                borderBottom: '1px solid var(--border)', fontSize: 12 }}>
              <span className={`dot ${e.status}`} />
              <a href={`/experiments/${e.eid}`} style={{
                overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                title={leafTitle(e)}>
                {leafLabel(e.question, null, i, e.candidates)}
              </a>
              <span style={{ display: 'flex', gap: 8, alignItems: 'center',
                whiteSpace: 'nowrap' }}>
                <VerdictTally v={e.verdicts} />
                <span className="muted mono" style={{ fontSize: 11 }}>
                  {e.runs ?? 0} runs · r{e.rounds_done ?? 0}{e.rounds_planned ? `/${e.rounds_planned}` : ''}
                </span>
                {!NO_LABEL_STATUS.has(e.status) && <Badge status={e.status} />}
                <ArchiveButton small label="✕" confirmLabel="archive?"
                  onConfirm={async () => {
                    await fetch(`/api/experiments/${e.eid}/archive`, { method: 'POST' })
                    qc.invalidateQueries({ queryKey: ['workspace'] })
                  }} />
              </span>
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
