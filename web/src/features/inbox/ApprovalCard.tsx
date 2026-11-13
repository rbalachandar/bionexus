import { Link } from 'react-router-dom'
import { Check, ShieldQuestion, X } from 'lucide-react'
import { useDecideApproval } from '../../api/hooks'
import { useToast } from '../../app/toast'
import type { Schemas } from '../../api/v1'
import { Button } from '../../ui/Button'
import { ago } from '../campaign/format'

/** A lab submission paused at the gate. The decider is whoever is signed in. */
export function ApprovalCard({ item, compact }: { item: Pick<Schemas['InboxItem'], 'id' | 'title' | 'detail' | 'ts'> & Partial<Schemas['InboxItem']>; compact?: boolean }) {
  const decide = useDecideApproval()
  const toast = useToast()
  const go = (approve: boolean) => decide.mutate({ id: item.id, approve }, {
    onSuccess: () => toast({ tone: 'ok', text: approve ? 'Approved. The agent will continue with this submission.' : 'Declined. The agent will not run this submission.' }),
  })
  const title = item.title.replace(/\s*\[problem\/[^\]]+\]/, '')
  return (
    <div className="flex items-start gap-3 px-4 py-3">
      <ShieldQuestion size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{title}</div>
        {item.detail && <div className="mt-0.5 text-xs text-muted">{item.detail}</div>}
        <div className="mt-1 text-[11px] text-faint">
          The agent paused here: nothing reaches the lab until you decide. {ago(item.ts)}
          {!compact && item.campaign_id && <> · <Link className="text-accent hover:underline" to={`/campaigns/${item.campaign_id}`}>{item.campaign_title}</Link></>}
        </div>
        {decide.error && <div role="alert" className="mt-1 text-xs text-bad">{(decide.error as Error).message}</div>}
      </div>
      <div className="flex shrink-0 gap-2">
        <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => go(false)}><X size={14} /> Decline</Button>
        <Button size="sm" variant="primary" disabled={decide.isPending} onClick={() => go(true)}><Check size={14} /> Approve</Button>
      </div>
    </div>
  )
}
