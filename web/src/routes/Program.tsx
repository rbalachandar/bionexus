import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { Plus, Target, Trash2 } from 'lucide-react'
import { api } from '../api/client'
import { LeafRow, ProgramTreeFull, TasteLines } from '../components/program'
import { EmptyState, Section, Skeleton } from '../components/ui'

function ProgramPage() {
  const { slug } = useParams<{ slug: string }>()
  const qc = useQueryClient()
  const nav = useNavigate()
  const q = useQuery({ queryKey: ['program', slug], queryFn: () => api.program(slug!),
    enabled: !!slug, refetchInterval: 15000 })
  const [deleting, setDeleting] = useState(false)

  if (q.isLoading) return (
    <main style={{ display: 'grid', gap: 12 }}>
      <Skeleton w={220} h={24} /><Skeleton w="100%" h={110} />
    </main>
  )
  if (q.isError || !q.data)
    return <EmptyState title="Program not found"
      hint="It may have been deleted."
      action={<button onClick={() => nav('/')}>← All programs</button>} />

  const p = q.data!
  const done = p.tally['completed'] ?? 0
  const running = p.tally['running'] ?? 0
  const total = Object.values(p.tally).reduce((a, b) => a + b, 0)
  const leaves = p.links.filter((l) => l.role === 'leaf' && l.live !== false)
  const hasTree = (p.trees?.length ?? (p.tree ? 1 : 0)) > 0

  async function doDelete(mode: 'archive' | 'purge') {
    const qp = mode === 'archive' ? '?archive=true' : '?purge=true'
    await fetch(`/api/programs/${slug}${qp}`, { method: 'DELETE' })
    nav('/')
  }

  return (
    <main>
      <a href="/" className="muted" style={{ fontSize: 12 }}>← All programs</a>
      <div style={{ display: 'flex', justifyContent: 'space-between',
        alignItems: 'flex-start', gap: 12, marginTop: 8,
        marginBottom: 'var(--s2)' }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Target size={16} color="var(--brand)" style={{ flex: 'none' }} />
            <h1 style={{ fontSize: 'var(--fs-xl)', margin: 0, fontWeight: 650 }}>
              {p.name}
            </h1>
            <span className="muted mono" title={`id ${p.slug}`}
              style={{ fontSize: 11 }}>{p.pid ?? p.slug}</span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 4,
            maxWidth: 760 }}>{p.objective ?? p.gate_summary}</div>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap',
            alignItems: 'center', marginTop: 8 }}>
            {p.modality && <span className="chip meta">{p.modality}</span>}
            <span className="chip meta">{p.mode}</span>
            {running > 0 && <span className="chip running">{running} running</span>}
            <span className="muted mono" style={{ fontSize: 11 }}>
              {total} exp{total === 1 ? '' : 's'}{done > 0 && ` · ${done} done`}
            </span>
          </div>
        </div>
        {deleting ? (
          <span style={{ display: 'inline-flex', gap: 4, flex: 'none' }}>
            <button className="danger" style={{ fontSize: 11 }}
              onClick={() => doDelete('archive')}>
              + archive exps
            </button>
            <button className="danger" style={{ fontSize: 11 }}
              title="irreversible — provenance ledger keeps the audit trail"
              onClick={() => doDelete('purge')}>
              delete exps
            </button>
          </span>
        ) : (
          <button style={{ display: 'inline-flex', gap: 4, alignItems: 'center',
            flex: 'none' }} title="delete this program"
            onClick={() => setDeleting(true)}>
            <Trash2 size={11} /> Delete
          </button>
        )}
      </div>

      <Section n={1} title="Experiments">
        {leaves.length === 0 ? (
          <p className="muted" style={{ fontSize: 12 }}>
            no experiments yet — launch one from the New-program form
          </p>
        ) : hasTree ? (
          <ProgramTreeFull p={p} />
        ) : (
          <div style={{ display: 'grid' }}>
            {leaves.map((l, i) => <LeafRow key={l.eid} l={l} i={i} p={p} wide />)}
          </div>
        )}
      </Section>

      {p.taste && p.taste.n > 0 && (
        <Section n={2} title="Selection profile">
          <TasteLines taste={p.taste} />
          <p className="muted" style={{ fontSize: 10.5, marginTop: 8 }}>
            advisory — accept-rate deltas describe the portfolio filter's
            observed behavior; nothing is applied automatically
          </p>
        </Section>
      )}

      <Section n={p.taste && p.taste.n > 0 ? 3 : 2} title="Gate">
        <p style={{ fontSize: 12.5, margin: 0 }}>{p.gate_summary ?? '—'}</p>
      </Section>
    </main>
  )
}

export default ProgramPage
