import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { CheckCircle2, FlaskConical, Plus, Sparkles, Target, Trash2,
  XCircle } from 'lucide-react'
import { api, type ProgramOut, type ProgramVerdict } from '../api/client'
import { LeafRow, ProgramTreeFull, TasteLines } from '../components/program'
import { Badge, EmptyState, Section, Skeleton } from '../components/ui'

const VERDICT_STYLE: Record<string, { icon: typeof CheckCircle2
  color: string; label: string }> = {
  supported: { icon: CheckCircle2, color: 'var(--ok, #2e7d32)',
    label: 'Objective supported' },
  partial: { icon: FlaskConical, color: '#b58a00',
    label: 'Partially supported' },
  refuted: { icon: XCircle, color: 'var(--bad, #c62828)',
    label: 'Objective refuted' },
  inconclusive: { icon: FlaskConical, color: 'var(--muted)',
    label: 'Inconclusive' },
  'no-tree': { icon: FlaskConical, color: 'var(--muted)',
    label: 'No problem tree' },
}

function BriefAction({ slug, idx, action, launched, status, qc }: {
  slug: string
  idx: number
  action: string
  launched?: string
  status?: string
  qc: ReturnType<typeof useQueryClient>
}) {
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setBusy(true)
    setErr(null)
    try {
      await api.launchAction(slug, idx)
      await qc.invalidateQueries({ queryKey: ['program', slug] })
      await qc.invalidateQueries({ queryKey: ['workspace'] })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start' }}>
      <span className="muted mono" style={{ fontSize: 11, marginTop: 2 }}>
        {idx + 1}.
      </span>
      <span style={{ fontSize: 12, flex: 1 }}>{action}</span>
      {launched
        ? <a href={`/experiments/${launched}`}
            title="view the launched campaign"
            style={{ flex: 'none', fontSize: 11, textDecoration: 'none',
              display: 'inline-flex', gap: 4, alignItems: 'center' }}>
            {status === 'completed'
              ? <Badge status="completed">done ✓</Badge>
              : status === 'failed'
                ? <Badge status="failed">failed</Badge>
                : <Badge status="running">running</Badge>}
            <span className="muted">view →</span>
          </a>
        : <button style={{ fontSize: 11, padding: '2px 8px', flex: 'none' }}
            disabled={busy} onClick={run} title="starts this as a single campaign (agent hypotheses), linked to the program">
            {busy ? 'launching…' : 'launch'}
          </button>}
      {err && <span style={{ fontSize: 11, color: 'var(--bad, #c62828)' }}>
        {err}</span>}
    </div>
  )
}

function ProgramVerdictBanner({ v, p }: { v: ProgramVerdict
  p: ProgramOut }) {
  const qc = useQueryClient()
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const st = VERDICT_STYLE[v.status] ?? VERDICT_STYLE.inconclusive
  const Icon = st.icon
  const brief = p.brief?.text
  const redraft = async () => {
    setLoading(true)
    setErr(null)
    try {
      await api.brief(p.slug)
      await qc.invalidateQueries({ queryKey: ['program', p.slug] })
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setLoading(false)
    }
  }
  return (
    <div style={{ border: '1px solid var(--border)', borderRadius: 10,
      padding: '10px 12px', display: 'grid', gap: 6, marginTop: 8,
      maxWidth: 760, background: 'color-mix(in srgb, var(--panel, #fff)'
      + ' 60%, transparent)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <Icon size={15} color={st.color} style={{ flex: 'none' }} />
        <strong style={{ fontSize: 13, color: st.color }}>{st.label}</strong>
        {v.leaves > 0 && <span className="muted mono" style={{ fontSize: 11 }}>
          {v.resolved}/{v.leaves} sub-problems resolved</span>}
        {v.gate && <span className="chip meta" title={v.gate.leaf}>
          gate {v.gate.metric}: {v.gate.status}</span>}
        <span style={{ flex: 1 }} />
        <button style={{ fontSize: 11, padding: '2px 8px',
          display: 'inline-flex', gap: 4, alignItems: 'center' }}
          title="model-drafted from the leaf evidence; the deterministic verdict above stays the source of truth"
          disabled={loading}
          onClick={redraft}>
          <Sparkles size={11} />
          {loading ? 'drafting…' : 'redraft'}
        </button>
      </div>
      <span className="muted" style={{ fontSize: 12 }}>{v.reason}</span>
      {err && <span style={{ fontSize: 12, color: 'var(--bad, #c62828)' }}>
        {err}</span>}
      {brief ? <div style={{ fontSize: 12, whiteSpace: 'pre-wrap',
        borderTop: '1px solid var(--border)', paddingTop: 6 }}>
        {brief}
        <div className="muted mono" style={{ fontSize: 10, marginTop: 4 }}>
          model-drafted{p.brief?.at
            ? ` · ${new Date(p.brief.at * 1000).toLocaleString()}`
            : ''} — verify against the recorded evidence</div>
        {(p.brief?.actions?.length ?? 0) > 0 && (
          <div style={{ display: 'grid', gap: 4, marginTop: 8 }}>
            <span className="muted" style={{ fontSize: 11 }}>
              launchable next actions — each starts one campaign linked
              to this program:
            </span>
            {p.brief!.actions!.map((a, i) => (
              <BriefAction key={i} slug={p.slug} idx={i} action={a}
                launched={p.brief?.launched?.[String(i)]}
                status={p.brief?.launched_status?.[String(i)]} qc={qc} />
            ))}
          </div>
        )}
      </div>
      : !loading && v.leaves > 0 && p.policy?.status !== 'escalated' && (
        <span className="muted mono" style={{ fontSize: 11 }}>
          drafting learning brief…
        </span>
      )}
      {p.policy?.status === 'escalated' && (
        <div style={{ fontSize: 12, borderTop: '1px solid var(--border)',
          paddingTop: 6, display: 'flex', gap: 6, alignItems: 'center',
          flexWrap: 'wrap' }}>
          <strong style={{ color: '#b58a00' }}>Loop paused</strong>
          <span className="muted">{p.policy.reason} — human decision
            required. Redraft to override.</span>
          <span className="muted mono" style={{ fontSize: 10 }}>
            {p.policy.runs} runs · {p.policy.cycles}/
            {p.policy.limits.max_cycles} cycles
          </span>
        </div>
      )}
    </div>
  )
}

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
          {p.verdict && <ProgramVerdictBanner v={p.verdict} p={p} />}
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
