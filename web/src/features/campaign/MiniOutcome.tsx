import type { Schemas } from '../../api/v1'

/** A compact claimed / refuted / abstained split — the same colours and order as the campaign page. */
export function MiniOutcome({ f }: { f: Schemas['Funnel'] }) {
  const seg = [{ n: f.claimed, c: 'bg-ok' }, { n: f.refuted, c: 'bg-bad' }, { n: f.abstained, c: 'bg-abstain' }]
  return (
    <div className="flex items-center gap-2" title={`${f.claimed} claimed · ${f.refuted} refuted · ${f.abstained} abstained of ${f.judged} judged`}>
      <div className="flex h-1.5 w-20 overflow-hidden rounded-full bg-sunken">
        {f.judged > 0 && seg.map((s, i) => s.n > 0 && <div key={i} className={s.c} style={{ width: `${(s.n / f.judged) * 100}%` }} />)}
      </div>
      <span className="num text-[11px] text-muted">{f.claimed}/{f.refuted}/{f.abstained}</span>
    </div>
  )
}

/** The same split spelled out — for cards where "1/4/4" would need a legend. */
export function OutcomeCounts({ f }: { f: Schemas['Funnel'] }) {
  const items = [
    { n: f.claimed, c: 'bg-ok', l: 'claimed' }, { n: f.refuted, c: 'bg-bad', l: 'refuted' }, { n: f.abstained, c: 'bg-abstain', l: 'abstained' },
  ]
  return (
    <span className="flex items-center gap-3 text-xs text-muted">
      {items.map((i) => (
        <span key={i.l} className="flex items-center gap-1"><span className={`h-2 w-2 rounded-sm ${i.c}`} aria-hidden /><b className="num text-ink">{i.n}</b> {i.l}</span>
      ))}
    </span>
  )
}
