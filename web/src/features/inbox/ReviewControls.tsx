import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useReviewHypothesis } from '../../api/hooks'
import { useToast } from '../../app/toast'
import type { Schemas } from '../../api/v1'
import { Button } from '../../ui/Button'
import { Input } from '../../ui/Field'
import { ago } from '../campaign/format'
import { FollowUpDialog } from '../launch/FollowUpDialog'

type Decision = Schemas['ReviewIn']['decision']
const DONE: Record<Decision, string> = { follow_up: 'followed up', accept: 'accepted as inconclusive', drop: 'dropped' }

/** Record a decision on an abstained candidate. "Follow up" starts the follow-up
 *  campaign FIRST and records the decision (linked to it) only once it started;
 *  accept / drop are recorded at once. Each is sealed in the ledger under YOUR name. */
export function ReviewControls({ campaignId, hid, candidate, review }: {
  campaignId: string; hid: string; candidate: string; review?: Schemas['Review'] | null
}) {
  const m = useReviewHypothesis(campaignId)
  const toast = useToast()
  const [note, setNote] = useState('')
  const [showNote, setShowNote] = useState(false)
  const [fu, setFu] = useState(false)

  const record = (decision: Decision, followUpId?: string) =>
    m.mutateAsync({ hid, decision, note, followUpCampaignId: followUpId })
  if (review) {
    const pending = review.decision === 'follow_up' && !review.follow_up_campaign_id
    return (
      <div>
        <p className="text-[13px]"><b>{review.by}</b> {DONE[review.decision]} <span className="num">{candidate}</span>
          {review.note && <> — “{review.note}”</>}
          {review.follow_up_campaign_id && <> · <Link className="text-accent hover:underline" to={`/campaigns/${review.follow_up_campaign_id}`}>open the follow-up campaign</Link></>}
          <span className="text-faint"> · {ago(review.ts)}</span></p>
        {pending && (
          <div className="mt-2 flex items-center gap-2 text-[13px]">
            <span className="text-muted">No follow-up campaign was started for this.</span>
            <Button size="sm" variant="primary" onClick={() => setFu(true)}>Start it now…</Button>
          </div>
        )}
        <FollowUpDialog open={fu} onOpenChange={setFu} campaignId={campaignId} candidates={[candidate]} onLaunched={(cid) => record('follow_up', cid)} />
      </div>
    )
  }
  const quick = (decision: Decision) => record(decision).then(() =>
    toast({ tone: 'ok', text: `Recorded: ${DONE[decision]} ${candidate}. It is sealed in the ledger under your name.` }))

  return (
    <div>
      {showNote && <Input autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (recorded with your decision)" aria-label="Decision note" className="mb-2" />}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={m.isPending} onClick={() => setFu(true)}>Follow up…</Button>
        <Button size="sm" variant="secondary" disabled={m.isPending} onClick={() => quick('accept')}>Accept as inconclusive</Button>
        <Button size="sm" variant="ghost" disabled={m.isPending} onClick={() => quick('drop')}>Drop</Button>
        {!showNote && <button className="text-xs text-faint hover:text-ink" onClick={() => setShowNote(true)}>+ add a note</button>}
      </div>
      {m.error && <p role="alert" className="mt-1 text-xs text-bad">{(m.error as Error).message}</p>}
      <FollowUpDialog open={fu} onOpenChange={setFu} campaignId={campaignId} candidates={[candidate]}
        onLaunched={(cid) => record('follow_up', cid)} />
    </div>
  )
}
