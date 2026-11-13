import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { ChevronLeft, ClipboardCheck, ShieldCheck, ShieldX, TriangleAlert, Upload } from 'lucide-react'
import { useCampaign } from '../../api/hooks'
import { Card, CardHeader, EmptyState, Skeleton } from '../../ui/Card'
import { Button } from '../../ui/Button'
import { Tag } from '../../ui/Chip'
import { StatusTag } from '../../routes/Campaigns'
import { ApprovalCard } from '../inbox/ApprovalCard'
import { ActivityFeed } from './ActivityFeed'
import { AgentsCard } from './AgentsCard'
import { HypothesisDrawer } from './HypothesisDrawer'
import { OutcomeBar } from './OutcomeBar'
import { ResultsTable } from './ResultsTable'
import { RoundsTimeline } from './RoundsTimeline'
import { SubmitResultsDialog } from './SubmitResultsDialog'
import { sig } from './format'

/** Keyed by id so state (the open drawer, ?h=) never leaks from one campaign to the next. */
export default function CampaignPage() {
  const { id = '' } = useParams()
  return <CampaignView key={id} id={id} />
}

function CampaignView({ id }: { id: string }) {
  const { data: d, isLoading, error } = useCampaign(id)
  const [qs] = useSearchParams()
  const [open, setOpen] = useState<string | null>(qs.get('h'))
  const [submitting, setSubmitting] = useState(false)

  if (isLoading) return <div className="mx-auto max-w-7xl space-y-4 p-6"><Skeleton className="h-10 w-2/3" /><Skeleton className="h-24" /><Skeleton className="h-72" /></div>
  if (error || !d) return <div className="mx-auto max-w-3xl p-10"><EmptyState title="Campaign not found" hint={(error as Error | null)?.message ?? 'It may have been archived.'} /></div>

  const abstained = d.hypotheses.filter((h) => h.state === 'abstained' && !h.review)
  return (
    <div className="mx-auto max-w-7xl p-6">
      <Link to="/campaigns" className="mb-2 inline-flex items-center gap-1 text-xs text-muted hover:text-ink"><ChevronLeft size={14} /> Campaigns</Link>
      <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-xl font-semibold tracking-tight">{d.objective ?? d.title}</h1>
        <StatusTag status={d.status} />
        {d.gate.label && <Tag className="num !text-xs">gate {d.gate.label}</Tag>}
        {d.program && <Tag tone="accent">{d.program.name}</Tag>}
        {d.autonomy && <Tag>{d.autonomy}</Tag>}
        <Button size="sm" className="ml-auto" onClick={() => setSubmitting(true)}><Upload size={13} />Submit results</Button>
        <span className="num flex items-center gap-4 text-xs text-muted">
          <span>{d.budget.runs_used}{d.budget.runs_max ? ` / ${d.budget.runs_max}` : ''} lab runs</span>
          <span className={d.chain.verified ? 'flex items-center gap-1' : 'flex items-center gap-1 font-medium text-bad'}>
            {d.chain.verified ? <ShieldCheck size={14} className="text-ok" /> : <ShieldX size={14} />}
            {d.chain.verified ? `chain verified · ${d.chain.records} records` : 'chain integrity failed'}
          </span>
        </span>
      </div>

      <SubmitResultsDialog id={d.id} open={submitting} onOpenChange={setSubmitting} />
      {!!d.awaiting_approvals.length && (
        <Card className="mb-4 border-warn/50 bg-warn-soft">
          <div className="px-4 pt-3 text-sm font-semibold text-warn">Waiting for you — the agent has paused</div>
          <div className="divide-y divide-line">{d.awaiting_approvals.map((a) => <ApprovalCard key={a.id} item={a} compact />)}</div>
        </Card>
      )}

      <Card className="mb-4 px-5 py-4"><OutcomeBar d={d} /></Card>

      {!!abstained.length && (
        <div role="note" className="mb-4 flex items-start gap-2.5 rounded-lg border border-abstain/30 bg-abstain-soft px-4 py-3 text-sm text-abstain">
          <TriangleAlert size={16} className="mt-0.5 shrink-0" />
          <div>
            <b>{abstained.length} candidate{abstained.length > 1 ? 's' : ''} abstained</b> ({abstained.map((h) => h.head).join(', ')}): the interval straddles the gate
            {d.gate.threshold != null ? ` (${sig(d.gate.threshold)})` : ''}, so the data can’t say which side the true value is on. Open one to see its curve and record your decision: follow up, accept as inconclusive, or drop.
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-12">
        <div className="space-y-4 lg:col-span-4">
          <Card>
            <CardHeader title="Rounds" hint="what was tested, and why" />
            <RoundsTimeline d={d} onOpen={setOpen} />
          </Card>
          {!!d.eliminated.length && (
            <Card>
              <CardHeader title="Eliminated before testing" hint={`${d.eliminated.length}`} />
              <ul className="divide-y divide-line">
                {d.eliminated.map((e) => (
                  <li key={e.candidate} className="px-4 py-2 text-[13px]"><span className="num font-medium">{e.candidate}</span> <span className="text-muted">— {e.reason}</span></li>
                ))}
              </ul>
            </Card>
          )}
        </div>
        <div className="space-y-4 lg:col-span-8">
          <Card>
            <CardHeader title="Results" hint="click a candidate for the evidence" />
            <ResultsTable hyps={d.hypotheses} gate={d.gate} onOpen={(h) => setOpen(h.id)} selected={open} />
          </Card>
          {d.reviewer && (
            <Card className="flex items-start gap-3 px-4 py-3 text-sm">
              <ClipboardCheck size={16} className={d.reviewer.findings.length ? 'mt-0.5 text-warn' : 'mt-0.5 text-ok'} />
              <div className="flex-1">
                <b>Independent reviewer</b> — {d.reviewer.findings.length
                  ? `${d.reviewer.critical} critical · ${d.reviewer.warnings} warnings`
                  : 'no findings; the analysis is internally consistent.'}
                {d.reviewer.findings.map((f, i) => <p key={i} className="mt-1 text-xs text-muted"><b>{f.severity}</b> {f.candidate ? `${f.candidate}: ` : ''}{f.detail}</p>)}
              </div>
            </Card>
          )}
          <Card>
            <CardHeader title="Agents" hint="who did what — click for the full trace" />
            <AgentsCard id={d.id} />
          </Card>
          <Card>
            <CardHeader title="Activity" hint="live" />
            <ActivityFeed id={d.id} />
          </Card>
        </div>
      </div>
      <HypothesisDrawer campaign={d} hid={open} onClose={() => setOpen(null)} />
    </div>
  )
}
