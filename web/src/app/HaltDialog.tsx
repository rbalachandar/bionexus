import { useState } from 'react'
import { OctagonAlert, Play } from 'lucide-react'
import { useHalt, useSystemStatus } from '../api/hooks'
import { Button } from '../ui/Button'
import { Dialog, DialogContent } from '../ui/Dialog'

/** The operator stop-condition. Engaging is one click + a reason; clearing it
 *  is deliberately a separate, explicit human act. */
export function HaltControl() {
  const { data } = useSystemStatus()
  const halt = useHalt()
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const halted = !!data?.halted

  return (
    <>
      <Button variant={halted ? 'secondary' : 'danger'} size="sm" onClick={() => setOpen(true)}
        aria-label={halted ? 'Resume agents' : 'Halt all agents'}>
        {halted ? <Play size={14} /> : <OctagonAlert size={14} />}
        {halted ? 'Resume' : 'Halt'}
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent
          title={halted ? 'Resume agents?' : 'Halt all agents?'}
          description={halted
            ? 'Agents will be allowed to submit to the lab again. Only a human can do this.'
            : 'No further lab submission will pass the gateway until a human resumes. Running plates finish; nothing new starts.'}>
          {!halted && (
            <input autoFocus value={reason} onChange={(e) => setReason(e.target.value)}
              placeholder="Reason (recorded in provenance)"
              className="mb-3 h-9 w-full rounded-md border border-line-strong bg-canvas px-3 text-sm" />
          )}
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant={halted ? 'primary' : 'danger'} disabled={halt.isPending}
              onClick={() => halt.mutate({ halted: !halted, reason: reason || 'operator halt (workbench)' },
                { onSuccess: () => { setOpen(false); setReason('') } })}>
              {halted ? 'Resume agents' : 'Halt agents'}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  )
}
