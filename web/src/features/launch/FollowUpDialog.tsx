import { Link } from 'react-router-dom'
import { useCampaign } from '../../api/hooks'
import { Dialog, DialogContent } from '../../ui/Dialog'
import { LaunchCampaignDialog } from './LaunchCampaignDialog'

/** "Follow up" on candidates that came back inconclusive: a new campaign in
 *  the SAME program, so the new data is judged against the same gate. */
export function FollowUpDialog({ open, onOpenChange, campaignId, candidates, onLaunched }: {
  open: boolean; onOpenChange: (o: boolean) => void; campaignId: string; candidates: string[]
  onLaunched?: (campaignId: string) => Promise<unknown> | void
}) {
  const { data: c } = useCampaign(campaignId)
  if (!open) return null
  if (c && !c.program)
    return (
      <Dialog open onOpenChange={onOpenChange}>
        <DialogContent title="Attach this to a program first" description="A follow-up is judged against a program's gate, and this campaign does not belong to one.">
          <p className="text-sm text-muted">Create a program on <Link className="text-accent hover:underline" to="/">Today</Link>, then start the follow-up from its page.</p>
        </DialogContent>
      </Dialog>
    )
  if (!c?.program) return null
  return <LaunchCampaignDialog open onOpenChange={onOpenChange} slug={c.program.slug} title="Follow up"
    defaults={{ objective: `Follow-up: resolve ${candidates.join(', ')}`, candidates }} onLaunched={onLaunched} />
}
