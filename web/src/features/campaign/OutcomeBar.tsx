import { Tip } from '../../ui/Tooltip'
import type { Detail } from './format'

const Step = ({ label, n, of }: { label: string; n: number; of: number }) => (
  <div className="min-w-[88px]">
    <div className="num text-xl font-semibold leading-none">{n}<span className="text-sm font-normal text-faint">/{of}</span></div>
    <div className="mt-1 text-[11px] uppercase tracking-wider text-muted">{label}</div>
  </div>
)

/** The campaign at a glance: how far the funnel got, and how the judged
 *  candidates split into claims / refutations / honest abstentions. */
export function OutcomeBar({ d }: { d: Detail }) {
  const f = d.funnel
  const seg = [
    { k: 'claimed', n: f.claimed, c: 'bg-ok', t: 'Claimed — the whole 95% interval meets the gate' },
    { k: 'refuted', n: f.refuted, c: 'bg-bad', t: 'Refuted — the whole interval is on the wrong side of the gate' },
    { k: 'abstained', n: f.abstained, c: 'bg-abstain', t: 'Abstained — the interval straddles the gate; no claim either way' },
  ]
  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-3">
      <div className="flex gap-6">
        <Step label="Proposed" n={f.proposed} of={f.proposed} />
        <Step label="Selected" n={f.selected} of={f.proposed} />
        <Step label="Tested" n={f.tested} of={f.selected || f.proposed} />
        <Step label="Judged" n={f.judged} of={f.tested || f.selected || f.proposed} />
      </div>
      <div className="min-w-[260px] flex-1">
        <div className="mb-1.5 flex gap-4 text-xs text-muted">
          {seg.map((s) => (
            <span key={s.k} className="flex items-center gap-1.5"><span className={`h-2 w-2 rounded-sm ${s.c}`} />
              <span className="num font-semibold text-ink">{s.n}</span> {s.k}</span>
          ))}
        </div>
        <div className="flex h-2.5 overflow-hidden rounded-full bg-sunken" role="img"
          aria-label={`${f.claimed} claimed, ${f.refuted} refuted, ${f.abstained} abstained of ${f.judged} judged`}>
          {f.judged > 0 && seg.map((s) => s.n > 0 && (
            <Tip key={s.k} label={s.t}><div className={s.c} style={{ width: `${(s.n / f.judged) * 100}%` }} /></Tip>
          ))}
        </div>
      </div>
    </div>
  )
}
