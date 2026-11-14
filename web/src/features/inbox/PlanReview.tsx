import { Link } from 'react-router-dom'
import { useState } from 'react'
import { BadgeCheck, BadgeX, Check, ClipboardList, X } from 'lucide-react'
import { useDecideApproval } from '../../api/hooks'
import { useToast } from '../../app/toast'
import type { Schemas } from '../../api/v1'
import { Button } from '../../ui/Button'
import { Tag } from '../../ui/Chip'
import { Input } from '../../ui/Field'
import { cn } from '../../ui/cn'
import { ago } from '../campaign/format'

type Item = Pick<Schemas['InboxItem'], 'id' | 'title' | 'ts'> & Partial<Schemas['InboxItem']> & { plan: Schemas['Plan'] }

/** The research plan a model proposed, shown BEFORE anything reaches the lab: read each idea's mechanism and what
 *  would refute it, remove any hypothesis you do not want tested, then approve or decline. */
export function PlanReview({ item, compact }: { item: Item; compact?: boolean }) {
  const decide = useDecideApproval()
  const toast = useToast()
  const [removed, setRemoved] = useState<Set<string>>(new Set())
  const [note, setNote] = useState('')
  const all = item.plan.families.flatMap((f) => f.variants)
  const kept = all.length - removed.size
  const toggle = (id: string) => setRemoved((s) => { const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n })
  const go = (approve: boolean) => decide.mutate({ id: item.id, approve, exclude: [...removed], note }, {
    onSuccess: () => toast({ tone: 'ok', text: approve ? `Plan approved: ${kept} of ${all.length} hypotheses go ahead.` : 'Plan declined. Nothing will be submitted to the lab.' }),
  })
  return (
    <div className="px-4 py-3">
      <div className="flex items-start gap-3">
        <ClipboardList size={18} className="mt-0.5 shrink-0 text-warn" aria-hidden />
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">Review the research plan</div>
          <div className="text-xs text-muted">
            A model proposed {all.length} hypotheses in {item.plan.families.length} famil{item.plan.families.length === 1 ? 'y' : 'ies'}. Nothing reaches the lab until you decide; verdicts will still come from the fixed rule, not from the model.
            <span className="text-faint"> {ago(item.ts)}{!compact && item.campaign_id && <> · <Link className="text-accent hover:underline" to={`/campaigns/${item.campaign_id}`}>{item.campaign_title}</Link></>}</span>
          </div>
        </div>
      </div>

      <div className="mt-3 space-y-3">
        {item.plan.families.map((f) => (
          <section key={f.id} className="rounded-lg border border-line">
            <header className="flex flex-wrap items-center gap-2 border-b border-line px-3 py-2">
              <span className="num text-xs font-semibold">{f.id}</span>
              {f.confidence != null && <Tag title="the model's own confidence in this idea">model confidence {Math.round(f.confidence * 100)}%</Tag>}
              {f.citation && (f.citation_status === 'verified'
                ? <Tag tone="ok"><BadgeCheck size={11} className="mr-1" />citation verified</Tag>
                : f.citation_status === 'invalid'
                  ? <Tag tone="bad" title="This citation could not be resolved: treat it as unsupported"><BadgeX size={11} className="mr-1" />citation unresolvable</Tag>
                  : <Tag tone="warn">citation unchecked</Tag>)}
            </header>
            <div className="space-y-1.5 px-3 py-2 text-[13px]">
              {f.claim && <p className="font-medium">{f.claim}</p>}
              {f.mechanism && <p className="text-muted"><span className="text-faint">Mechanism · </span>{f.mechanism}</p>}
              {f.refuted_if && <p><span className="rounded bg-bad-soft px-1.5 py-0.5 text-bad">Refuted if · {f.refuted_if}</span></p>}
            </div>
            <ul className="divide-y divide-line border-t border-line">
              {f.variants.map((v) => {
                const off = removed.has(v.hypothesis_id)
                return (
                  <li key={v.hypothesis_id}>
                    <label className="flex cursor-pointer items-start gap-2.5 px-3 py-2 hover:bg-sunken">
                      <input type="checkbox" className="mt-1 shrink-0" checked={!off} onChange={() => toggle(v.hypothesis_id)} aria-label={`Test ${v.candidate}`} />
                      <span className={cn('min-w-0 flex-1 text-[13px]', off && 'text-faint line-through')}>
                        <b className="num">{v.candidate}</b> <span className="text-muted">{v.statement}</span>
                        {v.predicted && <span className="mt-0.5 block text-[11px] text-faint"><span className="font-medium">Predicts</span> · {v.predicted}</span>}
                        {v.rationale && <span className="block text-[11px] text-faint"><span className="font-medium">Why</span> · {v.rationale}</span>}
                      </span>
                    </label>
                  </li>
                )
              })}
            </ul>
          </section>
        ))}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Input className="min-w-0 flex-1" placeholder="Note for the record (optional), e.g. why you removed something" value={note} onChange={(e) => setNote(e.target.value)} />
        <Button size="sm" variant="secondary" disabled={decide.isPending} onClick={() => go(false)}><X size={14} /> Decline plan</Button>
        <Button size="sm" variant="primary" disabled={decide.isPending || kept === 0} onClick={() => go(true)}>
          <Check size={14} /> Approve {removed.size ? `${kept} of ${all.length}` : `all ${all.length}`}
        </Button>
      </div>
      {kept === 0 && <p className="mt-1 text-right text-[11px] text-warn">Every hypothesis is removed: decline the plan instead.</p>}
      {decide.error && <div role="alert" className="mt-1 text-xs text-bad">{(decide.error as Error).message}</div>}
    </div>
  )
}
