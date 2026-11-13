import { useState } from 'react'
import { Link } from 'react-router-dom'
import { CheckCircle2, Contrast } from 'lucide-react'
import { useInbox } from '../../api/hooks'
import { Card, CardHeader, EmptyState, Skeleton } from '../../ui/Card'
import { ApprovalCard } from './ApprovalCard'
import { ReviewControls } from './ReviewControls'
import { FollowUpDialog } from '../launch/FollowUpDialog'
import type { Schemas } from '../../api/v1'

function ReviewRow({ item }: { item: Schemas['InboxItem'] }) {
  const [fu, setFu] = useState(false)
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <Contrast size={18} className="mt-0.5 shrink-0 text-abstain" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium"><span className="num">{item.candidate}</span> abstained
          <Link className="ml-2 text-xs font-normal text-accent hover:underline" to={`/campaigns/${item.campaign_id}?h=${encodeURIComponent(item.hypothesis_id ?? '')}`}>open evidence</Link></div>
        <div className="mt-0.5 text-xs text-muted">{item.detail}</div>
        <div className="mt-0.5 text-[11px] text-faint">{item.campaign_title}</div>
        <div className="mt-2"><ReviewControls campaignId={item.campaign_id!} hid={item.hypothesis_id!} onFollowUp={() => setFu(true)} /></div>
      </div>
      <FollowUpDialog open={fu} onOpenChange={setFu} campaignId={item.campaign_id!} candidates={[item.candidate!]} />
    </div>
  )
}

export default function InboxPage() {
  const { data, isLoading } = useInbox('pending')
  const approvals = data?.filter((i) => i.kind === 'approval') ?? []
  const reviews = data?.filter((i) => i.kind === 'review') ?? []
  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="mb-1 text-xl font-semibold tracking-tight">Inbox</h1>
      <p className="mb-5 text-sm text-muted">Everything an agent is waiting on you for. Decisions are recorded under your name in the tamper-evident ledger.</p>
      {isLoading && <Skeleton className="h-28" />}
      {data && !data.length && (
        <Card><EmptyState icon={<CheckCircle2 size={28} className="text-ok" />} title="All clear" hint="No lab submission is paused and no abstention is waiting for a decision." /></Card>
      )}
      {!!approvals.length && (
        <Card className="mb-5">
          <CardHeader title="Approvals" hint="lab submissions paused at the gate" />
          <div className="divide-y divide-line">{approvals.map((i) => <ApprovalCard key={i.id} item={i} />)}</div>
        </Card>
      )}
      {!!reviews.length && (
        <Card>
          <CardHeader title="Review" hint="abstentions nobody has decided on" />
          <div className="divide-y divide-line">{reviews.map((i) => <ReviewRow key={i.id} item={i} />)}</div>
        </Card>
      )}
    </div>
  )
}
