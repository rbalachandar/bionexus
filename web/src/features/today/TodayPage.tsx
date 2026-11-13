import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Inbox, Layers, Plus, TriangleAlert } from 'lucide-react'
import { useToday } from '../../api/hooks'
import { Button } from '../../ui/Button'
import { Card, CardHeader, EmptyState, Skeleton } from '../../ui/Card'
import { Tag } from '../../ui/Chip'
import { StatusTag, when } from '../../routes/Campaigns'
import { MiniOutcome, OutcomeCounts } from '../campaign/MiniOutcome'
import { goalLine } from '../program/goal'
import { NewProgramDialog } from '../launch/NewProgramDialog'

const TONE = { ok: 'text-ok', warn: 'text-warn', neutral: 'text-muted' }

export default function TodayPage() {
  const { data, isLoading, error } = useToday()
  const [np, setNp] = useState(false)
  if (isLoading) return <div className="mx-auto max-w-6xl space-y-4 p-6"><Skeleton className="h-8 w-40" /><Skeleton className="h-28" /><Skeleton className="h-48" /></div>
  if (error || !data) return <div className="mx-auto max-w-3xl p-10"><EmptyState title="Could not load" hint={(error as Error | null)?.message} /></div>
  const { attention: a, programs, standalone } = data
  const clear = !a.pending_approvals && !a.abstentions.length && !a.halted

  return (
    <div className="mx-auto max-w-6xl p-6">
      <NewProgramDialog open={np} onOpenChange={setNp} />
      <div className="mb-4 flex items-baseline gap-3">
        <h1 className="text-xl font-semibold tracking-tight">Today</h1>
        <span className="text-sm text-muted">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</span>
        {!!a.running && <Tag tone="accent">{a.running} running</Tag>}
      </div>

      <Card className="mb-6">
        <CardHeader title="Needs you" />
        {clear ? (
          <p className="flex items-center gap-2 px-4 py-4 text-sm text-muted"><CheckCircle2 size={16} className="text-ok" /> All clear — nothing is waiting on a decision.</p>
        ) : (
          <ul className="divide-y divide-line">
            {!!a.pending_approvals && (
              <li><Link to="/inbox" className="flex items-center gap-3 px-4 py-3 text-sm hover:bg-sunken">
                <Inbox size={16} className="text-warn" /><span><b>{a.pending_approvals}</b> lab submission{a.pending_approvals > 1 ? 's' : ''} awaiting your approval</span>
              </Link></li>
            )}
            {a.abstentions.map((n) => (
              <li key={n.campaign_id}><Link to="/inbox" className="flex items-start gap-3 px-4 py-3 text-sm hover:bg-sunken">
                <TriangleAlert size={16} className="mt-0.5 shrink-0 text-abstain" />
                <span><b>{n.candidates.join(', ')}</b> abstained in “{n.campaign_title}” — the data can’t say which side of the gate they’re on. Decide: follow up, accept, or drop.</span>
              </Link></li>
            ))}
          </ul>
        )}
      </Card>

      <div className="mb-3 flex items-center">
        <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Programs</h2>
        <Button size="sm" variant="secondary" className="ml-auto" onClick={() => setNp(true)}><Plus size={14} /> New program</Button>
      </div>
      {!programs.length ? (
        <Card><EmptyState icon={<Layers size={28} />} title="No programs yet"
          hint="A program is the scientific goal — a metric, a direction and a gate, such as “IC50 ≤ 20 µM”. Campaigns are runs that try to meet it, and every candidate in all of them is judged against the same gate." /></Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {programs.map((p) => {
            const g = goalLine(p.goal, p.gate)
            return (
              <Link key={p.slug} to={`/programs/${p.slug}`} className="block rounded-[var(--radius-card)] border border-line bg-surface p-4 transition-colors hover:border-line-strong hover:bg-sunken">
                <div className="flex items-start gap-2">
                  <h3 className="min-w-0 flex-1 text-base font-semibold leading-snug">{p.name}</h3>
                  {p.running > 0 && <Tag tone="accent">{p.running} running</Tag>}
                </div>
                {p.objective && <p className="mt-0.5 line-clamp-2 text-[13px] text-muted">{p.objective}</p>}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {p.gate.label && <Tag className="num">gate {p.gate.label}</Tag>}
                  {p.modality && <Tag>{p.modality}</Tag>}
                </div>
                <div className={`mt-3 rounded-md bg-sunken px-3 py-2 text-[13px] ${TONE[g.tone]}`}>
                  <b>{g.title}</b> <span className="text-ink/80">· {g.detail}</span>
                </div>
                <div className="mt-3 flex items-center gap-3 text-xs text-muted">
                  <span><b className="num text-ink">{p.campaigns}</b> campaign{p.campaigns === 1 ? '' : 's'}</span>
                  <OutcomeCounts f={{ proposed: 0, selected: 0, tested: 0, judged: p.goal.judged, claimed: p.goal.claimed, refuted: p.goal.refuted, abstained: p.goal.abstained }} />
                </div>
              </Link>
            )
          })}
        </div>
      )}

      {!!standalone.length && (
        <div className="mt-8">
          <h2 className="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted">Campaigns without a program</h2>
          <p className="mb-3 text-xs text-faint">Not judged against a shared gate. Attach them to a program to track progress.</p>
          <Card className="overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                {standalone.map((c) => (
                  <tr key={c.id} className="border-b border-line last:border-0 hover:bg-sunken">
                    <td className="px-4 py-2.5"><Link to={`/campaigns/${c.id}`} className="font-medium hover:text-accent">{c.title}</Link></td>
                    <td className="px-3"><StatusTag status={c.status} /></td>
                    <td className="px-3"><MiniOutcome f={c.funnel} /></td>
                    <td className="num px-4 text-right text-xs text-muted">{when(c.updated_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </div>
      )}
    </div>
  )
}
