import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLaunchCampaign } from '../../api/hooks'
import { Button } from '../../ui/Button'
import { Dialog, DialogContent } from '../../ui/Dialog'
import { Field, Input, Select, Textarea } from '../../ui/Field'

const AUTONOMY = {
  gate: 'Ask me first — every lab submission waits for my approval',
  observe: 'Preview only — read, fit and recommend; submit nothing',
  act: 'Autonomous — run within the safety gate, including confirmations',
} as const

/** Start a campaign against a program's gate. Defaults to the safest mode. */
export function LaunchCampaignDialog({ open, onOpenChange, slug, title = 'New campaign', defaults }: {
  open: boolean; onOpenChange: (o: boolean) => void; slug: string; title?: string
  defaults?: { objective?: string; candidates?: string[] }
}) {
  const nav = useNavigate()
  const launch = useLaunchCampaign(slug)
  const [objective, setObjective] = useState(defaults?.objective ?? '')
  const [cands, setCands] = useState((defaults?.candidates ?? []).join('\n'))
  const [autonomy, setAutonomy] = useState<keyof typeof AUTONOMY>('gate')
  const [rounds, setRounds] = useState(2)
  useEffect(() => { if (open) { setObjective(defaults?.objective ?? ''); setCands((defaults?.candidates ?? []).join('\n')) } }, [open])  // eslint-disable-line

  const list = cands.split(/[\n,]+/).map((c) => c.trim()).filter(Boolean)
  const submit = () => launch.mutate(
    { objective: objective || null, candidates: list, autonomy, rounds, k: Math.max(1, Math.min(list.length || 2, 4)) },
    { onSuccess: (c) => { onOpenChange(false); nav(`/campaigns/${c.id}`) } })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description="Candidates are judged against the program's pre-registered gate.">
        <Field label="Objective" hint="Leave blank to use the program's objective."><Input value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
        <Field label="Candidates" hint={list.length ? `${list.length} candidate${list.length > 1 ? 's' : ''}` : 'One per line or comma-separated. Leave empty to let the hypothesis agent propose them (needs a configured model).'}>
          <Textarea value={cands} onChange={(e) => setCands(e.target.value)} placeholder="EG-02&#10;EG-03" />
        </Field>
        <div className="grid grid-cols-[1fr_90px] gap-3">
          <Field label="How much should the agent do on its own?">
            <Select value={autonomy} onChange={(e) => setAutonomy(e.target.value as keyof typeof AUTONOMY)}>
              {Object.entries(AUTONOMY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Rounds"><Input type="number" min={1} max={8} value={rounds} onChange={(e) => setRounds(Number(e.target.value))} /></Field>
        </div>
        {launch.error && <p role="alert" className="mb-2 text-xs text-bad">{(launch.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={launch.isPending} onClick={submit}>{launch.isPending ? 'Starting…' : 'Start campaign'}</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
