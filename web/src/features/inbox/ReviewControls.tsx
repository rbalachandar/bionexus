import { useState } from 'react'
import { useReviewHypothesis } from '../../api/hooks'
import type { Schemas } from '../../api/v1'
import { Button } from '../../ui/Button'
import { Input } from '../../ui/Field'
import { ago } from '../campaign/format'

type Decision = Schemas['ReviewIn']['decision']
const LABEL: Record<Decision, string> = { follow_up: 'Follow up', accept: 'Accept as inconclusive', drop: 'Drop' }

/** Record a decision on an abstained candidate. It is sealed in the same
 *  hash chain as everything the agents did, under YOUR name. */
export function ReviewControls({ campaignId, hid, review, onFollowUp }: {
  campaignId: string; hid: string; review?: Schemas['Review'] | null; onFollowUp?: () => void
}) {
  const m = useReviewHypothesis(campaignId)
  const [note, setNote] = useState('')
  const [showNote, setShowNote] = useState(false)
  if (review)
    return (
      <p className="text-[13px]"><b>{review.by}</b> decided to <b>{LABEL[review.decision].toLowerCase()}</b>
        {review.note && <> — “{review.note}”</>} <span className="text-faint">· {ago(review.ts)}</span></p>
    )
  const go = (decision: Decision) => m.mutate({ hid, decision, note }, { onSuccess: () => { if (decision === 'follow_up') onFollowUp?.() } })
  return (
    <div>
      {showNote && <Input autoFocus value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (recorded with your decision)" aria-label="Decision note" className="mb-2" />}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="primary" disabled={m.isPending} onClick={() => go('follow_up')}>Follow up…</Button>
        <Button size="sm" variant="secondary" disabled={m.isPending} onClick={() => go('accept')}>Accept as inconclusive</Button>
        <Button size="sm" variant="ghost" disabled={m.isPending} onClick={() => go('drop')}>Drop</Button>
        {!showNote && <button className="text-xs text-faint hover:text-ink" onClick={() => setShowNote(true)}>+ add a note</button>}
      </div>
      {m.error && <p role="alert" className="mt-1 text-xs text-bad">{(m.error as Error).message}</p>}
    </div>
  )
}
