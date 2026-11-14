import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FlaskConical, ListChecks, Sparkles } from 'lucide-react'
import { useLaunchCampaign, useProgram, useSystemStatus } from '../../api/hooks'
import { Button } from '../../ui/Button'
import { Dialog, DialogContent } from '../../ui/Dialog'
import { Field, Input, Select, Textarea } from '../../ui/Field'
import { cn } from '../../ui/cn'
import { useToast } from '../../app/toast'

export type How = 'research' | 'list' | 'hand'

/** "Autonomy" is only about approvals: how much happens without a person saying yes. It applies to both research and a candidate list. */
const AUTONOMY = {
  gate: 'Ask me first',
  observe: 'Preview only — plan and explain, submit nothing',
  act: 'Run on its own, within the safety gate — no approvals',
} as const

/** Start work against a program's gate. Defaults to the safest setting. */
export function LaunchCampaignDialog({ open, onOpenChange, slug, title = 'New campaign', defaults, initialHow, onLaunched }: {
  open: boolean; onOpenChange: (o: boolean) => void; slug: string; title?: string
  defaults?: { objective?: string; candidates?: string[] }; initialHow?: How
  onLaunched?: (campaignId: string) => Promise<unknown> | void
}) {
  const toast = useToast()
  const nav = useNavigate()
  const launch = useLaunchCampaign(slug)
  const model = useSystemStatus().data?.model
  const maxRounds = useProgram(slug).data?.limits.max_rounds ?? 8
  const start = (): How => initialHow ?? (defaults?.candidates?.length ? 'list' : model?.configured ? 'research' : 'list')
  const [how, setHow] = useState<How>(start())
  const [objective, setObjective] = useState(defaults?.objective ?? '')
  const [cands, setCands] = useState((defaults?.candidates ?? []).join('\n'))
  const [autonomy, setAutonomy] = useState<keyof typeof AUTONOMY>('gate')
  const [rounds, setRounds] = useState(2)
  const cappedRounds = Math.min(rounds, maxRounds)
  useEffect(() => { if (open) { setHow(start()); setObjective(defaults?.objective ?? ''); setCands((defaults?.candidates ?? []).join('\n')) } }, [open, model?.configured])  // eslint-disable-line

  const list = cands.split(/[\n,]+/).map((c) => c.trim()).filter(Boolean)
  const needsList = how !== 'research'
  const blocked = (needsList && !list.length) || (how === 'research' && !model?.configured)
  const submit = () => launch.mutate(
    { objective: objective || null, candidates: how === 'research' ? [] : list, mode: how === 'hand' ? 'hand' : 'agent', autonomy,
      rounds: cappedRounds, ...(how === 'list' ? { k: Math.max(1, Math.min(list.length, 4)) } : {}) },
    {
      onSuccess: async (c) => {
        await onLaunched?.(c.id)
        onOpenChange(false)
        toast({ tone: 'ok', text:
          how === 'hand' ? 'Campaign created. Its gate is registered — run the plate, then use Submit results.'
          : how === 'research' ? (autonomy === 'gate' ? 'Research started. The model is proposing hypotheses; you will review the plan before anything reaches the lab.' : 'Research started.')
          : autonomy === 'gate' ? 'Campaign started. It will pause and ask for your approval before anything reaches the lab.' : 'Campaign started.' })
        nav(`/campaigns/${c.id}`)
      },
    })

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title={title} description="Everything is judged against the program's pre-registered gate." className="!w-[min(600px,94vw)] !top-[6%]">
        <div role="radiogroup" aria-label="How should this run?" className="mb-3 grid gap-2">
          <Choice on={how === 'research'} disabled={!model?.configured} icon={Sparkles} onSelect={() => setHow('research')}
            title="Start research" sub={model?.configured ? `${model.model} proposes the hypotheses; you review the plan; the agent runs it.` : 'A model proposes the hypotheses. Needs a configured model (see docs/MODELS.md).'} />
          <Choice on={how === 'list'} icon={ListChecks} onSelect={() => setHow('list')}
            title="I have candidates" sub="You list them; the agent tests them. No language model is involved." />
          <Choice on={how === 'hand'} icon={FlaskConical} onSelect={() => setHow('hand')}
            title="I’ll run the plate myself" sub="No agent, no lab submission. The gate is registered now; you submit the CSV and it is judged against it." />
        </div>

        <Field label="Objective" hint="Leave blank to use the program's objective."><Input value={objective} onChange={(e) => setObjective(e.target.value)} /></Field>
        {needsList && (
          <Field label="Candidates" hint={list.length ? `${list.length} candidate${list.length > 1 ? 's' : ''}` : 'One per line or comma-separated.'}>
            <Textarea value={cands} onChange={(e) => setCands(e.target.value)} placeholder="EG-02&#10;EG-03" />
          </Field>
        )}
        {how !== 'hand' && (
          <div className="grid grid-cols-[1fr_90px] gap-3">
            <Field label="Approvals" hint={how === 'research' && autonomy === 'gate' ? 'You approve the plan, then each lab submission.' : autonomy === 'act' ? 'Nothing waits for you; the safety gate still applies.' : undefined}>
              <Select value={autonomy} onChange={(e) => setAutonomy(e.target.value as keyof typeof AUTONOMY)}>
                {Object.entries(AUTONOMY).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>
            </Field>
            <Field label="Rounds" hint={`up to ${maxRounds}`}><Input type="number" min={1} max={maxRounds} value={cappedRounds} onChange={(e) => setRounds(Number(e.target.value))} /></Field>
          </div>
        )}
        {how === 'research' && autonomy === 'act' && (
          <p className="mb-3 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn">With no approvals there is no plan review: the model’s hypotheses are tested straight away.</p>
        )}
        {how === 'research' && !model?.configured && (
          <p role="alert" className="mb-3 rounded-md bg-warn-soft px-3 py-2 text-xs text-warn"><b>No model is configured.</b> Set <code>PROEF_LLM_MODEL</code> and <code>PROEF_LLM_TOKEN</code> (see docs/MODELS.md) and restart the server, or choose “I have candidates”.</p>
        )}
        {launch.error && <p role="alert" className="mb-2 text-xs text-bad">{(launch.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={launch.isPending || blocked} onClick={submit}>
            {launch.isPending ? 'Starting…' : how === 'research' ? 'Start research' : how === 'hand' ? 'Create campaign' : 'Start campaign'}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function Choice({ on, disabled, icon: Icon, title, sub, onSelect }: {
  on: boolean; disabled?: boolean; icon: typeof Sparkles; title: string; sub: string; onSelect: () => void
}) {
  return (
    <button type="button" role="radio" aria-checked={on} disabled={disabled} onClick={onSelect}
      className={cn('flex items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors',
        on ? 'border-accent bg-accent-soft' : 'border-line hover:bg-sunken', disabled && 'cursor-not-allowed opacity-55')}>
      <Icon size={17} className={cn('mt-0.5 shrink-0', on ? 'text-accent' : 'text-muted')} aria-hidden />
      <span className="min-w-0"><span className="block text-sm font-medium">{title}</span><span className="block text-xs text-muted">{sub}</span></span>
    </button>
  )
}
