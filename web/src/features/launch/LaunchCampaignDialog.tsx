import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useLaunchCampaign, useProgram, useSystemStatus } from '../../api/hooks'
import { Button } from '../../ui/Button'
import { Dialog, DialogContent } from '../../ui/Dialog'
import { Field, Input, Select, Textarea } from '../../ui/Field'
import { useToast } from '../../app/toast'

const AUTONOMY = {
  gate: 'Ask me first — every lab submission waits for my approval',
  observe: 'Preview only — read, fit and recommend; submit nothing',
  act: 'Autonomous — run within the safety gate, including confirmations',
} as const

/** Start a campaign against a program's gate. Defaults to the safest mode. */
export function LaunchCampaignDialog({ open, onOpenChange, slug, title = 'New campaign', defaults, onLaunched }: {
  open: boolean; onOpenChange: (o: boolean) => void; slug: string; title?: string
  defaults?: { objective?: string; candidates?: string[] }
  onLaunched?: (campaignId: string) => Promise<unknown> | void
}) {
  const toast = useToast()
  const nav = useNavigate()
  const launch = useLaunchCampaign(slug)
  const model = useSystemStatus().data?.model
  const maxRounds = useProgram(slug).data?.limits.max_rounds ?? 8
  const [objective, setObjective] = useState(defaults?.objective ?? '')
  const [cands, setCands] = useState((defaults?.candidates ?? []).join('\n'))
  const [autonomy, setAutonomy] = useState<keyof typeof AUTONOMY>('gate')
  const [rounds, setRounds] = useState(2)
  const cappedRounds = Math.min(rounds, maxRounds)
  const [hand, setHand] = useState(false)
  useEffect(() => { if (open) { setObjective(defaults?.objective ?? ''); setCands((defaults?.candidates ?? []).join('\n')) } }, [open])  // eslint-disable-line

  const list = cands.split(/[\n,]+/).map((c) => c.trim()).filter(Boolean)
  const submit = () => launch.mutate(
    { objective: objective || null, candidates: list, mode: hand ? 'hand' : 'agent', autonomy, rounds: cappedRounds, k: Math.max(1, Math.min(list.length || 2, 4)) },
    {
      onSuccess: async (c) => {
        await onLaunched?.(c.id)
        onOpenChange(false)
        toast({ tone: 'ok', text: hand ? 'Campaign created. Its gate is registered — run the plate, then use Submit results.' : autonomy === 'gate' ? 'Campaign started. It will pause and ask for your approval before anything reaches the lab.' : 'Campaign started.' })
        nav(`/campaigns/${c.id}`)
      },
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description="Candidates are judged against the program's pre-registered gate.">
        <Field label="Objective" hint="Leave blank to use the program's objective."><Input value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
        <Field label="Candidates" hint={list.length ? `${list.length} candidate${list.length > 1 ? 's' : ''}` : 'One per line or comma-separated. Leave empty to let a language model propose them.'}>
          <Textarea value={cands} onChange={(e) => setCands(e.target.value)} placeholder="EG-02&#10;EG-03" />
        </Field>
        <label className="mb-3 flex cursor-pointer items-start gap-2 rounded-md border border-line px-3 py-2 text-sm">
          <input type="checkbox" className="mt-1" checked={hand} onChange={(e) => setHand(e.target.checked)} />
          <span><b>I’ll run the experiment myself</b><span className="block text-xs text-muted">No agent, no lab submission. The gate is registered on each candidate now; you run the plate and submit the CSV, and it is judged against that gate.</span></span>
        </label>
        {hand ? !list.length && <p className="mb-3 text-xs text-warn">Name at least one candidate.</p> : (
        <div className="grid grid-cols-[1fr_90px] gap-3">
          <Field label="How much should the agent do on its own?">
            <Select value={autonomy} onChange={(e) => setAutonomy(e.target.value as keyof typeof AUTONOMY)}>
              {Object.entries(AUTONOMY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </Select>
          </Field>
          <Field label="Rounds" hint={`up to ${maxRounds}`}><Input type="number" min={1} max={maxRounds} value={cappedRounds} onChange={(e) => setRounds(Number(e.target.value))} /></Field>
        </div>)}
        <ModeNote hand={hand} n={list.length} model={model} />
        {launch.error && <p role="alert" className="mb-2 text-xs text-bad">{(launch.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={launch.isPending || (hand && !list.length) || (!hand && !list.length && !model?.configured)} onClick={submit}>{launch.isPending ? 'Starting…' : hand ? 'Create campaign' : 'Start campaign'}</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Which of the two ways to run this launch will use — before it starts, not after. */
function ModeNote({ hand, n, model }: { hand: boolean; n: number; model?: { configured: boolean; model?: string | null } }) {
  const box = 'mb-3 rounded-md px-3 py-2 text-xs'
  if (hand) return <p className={`${box} bg-sunken text-muted`}><b className="text-ink">You run it.</b> No agent and no model; the gate is registered now and your plate is judged against it.</p>
  if (n > 0) return <p className={`${box} bg-sunken text-muted`}><b className="text-ink">Autonomous code · no LLM.</b> The agent tests your {n} candidate{n > 1 ? 's' : ''}; selection, runs, fits and verdicts are all code, and the run can be replayed exactly.</p>
  if (model?.configured) return <p className={`${box} bg-accent-soft text-accent`}><b>LLM-assisted · {model.model}</b> will propose the hypotheses. A fresh run may propose different ones. Verdicts still come from the fixed rule, never from the model.</p>
  return <p role="alert" className={`${box} bg-warn-soft text-warn`}><b>No model is configured</b>, so nothing can propose candidates. Name them above, or set <code>PROEF_LLM_MODEL</code> and <code>PROEF_LLM_TOKEN</code> (see docs/MODELS.md) and restart the server.</p>
}
