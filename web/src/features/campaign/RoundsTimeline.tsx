import { useState } from 'react'
import { Ban, ChevronDown, ChevronRight } from 'lucide-react'
import { StateChip, type State } from '../../ui/Chip'
import { cn } from '../../ui/cn'
import { sig, type Detail } from './format'

type Round = Detail['rounds'][number]

function Why({ r, gate }: { r: Round; gate: Detail['gate'] }) {
  const w = r.why
  if (!w) return <p className="text-xs text-faint">The selection reasoning was not recorded for this round.</p>
  const ei = !!w.policy && w.policy.includes('ei')
  return (
    <div className="space-y-3 text-xs">
      <p className="text-muted">
        {ei
          ? <>Chosen by <b className="text-ink">expected improvement</b> ({w.policy}{w.policy_version ? ` v${w.policy_version}` : ''}): each candidate is scored by how likely it is to beat the gate{w.target != null ? <> (<span className="num">{sig(w.target)}</span>)</> : ''}, using its predicted value and uncertainty. A candidate outside the model’s applicability domain is never chosen.</>
          : <>Chosen by <b className="text-ink">portfolio score</b>: the highest-ranked hypotheses within the diversity cap.</>}
      </p>
      {!!w.picks.length && (
        <div>
          <div className="mb-1 font-semibold uppercase tracking-wider text-[10px] text-muted">Chosen</div>
          <ul className="space-y-1">
            {w.picks.map((p) => (
              <li key={p.candidate} className="flex items-baseline gap-2 rounded bg-sunken px-2 py-1">
                <span className="num whitespace-nowrap font-medium">{p.candidate}</span>
                <span className="min-w-0 flex-1 truncate text-faint" title={p.reason}>{p.reason}</span>
                {p.score != null && <span className="num text-muted">{ei ? 'EI ' : ''}{sig(p.score, 3)}</span>}
              </li>
            ))}
          </ul>
        </div>
      )}
      {!!w.refusals.length && (
        <div>
          <div className="mb-1 font-semibold uppercase tracking-wider text-[10px] text-muted">Not chosen — and why</div>
          <ul className="space-y-1">
            {w.refusals.map((p) => (
              <li key={p.candidate} className="flex items-start gap-2 px-2 py-0.5">
                <Ban size={13} className="mt-0.5 shrink-0 text-refused" aria-hidden />
                <span className="num whitespace-nowrap font-medium">{p.candidate}</span>
                <span className="text-muted">{p.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {w.note && <p className="text-faint">{w.note}</p>}
    </div>
  )
}

/** Rounds as a timeline. Each round says what was tested, what came back, and
 *  — one click away — WHY those candidates and not the others. */
export function RoundsTimeline({ d, onOpen }: { d: Detail; onOpen: (hid: string) => void }) {
  const [open, setOpen] = useState<number | null>(d.rounds.length ? d.rounds[d.rounds.length - 1].n : null)
  const byCand = new Map(d.hypotheses.map((h) => [h.candidate ?? h.head, h]))
  return (
    <ol className="relative px-4 py-3">
      {d.rounds.map((r, i) => {
        const isOpen = open === r.n
        return (
          <li key={r.n} className="relative pb-5 pl-6 last:pb-1">
            {i < d.rounds.length - 1 && <span className="absolute left-[7px] top-4 h-full w-px bg-line-strong" aria-hidden />}
            <span className="absolute left-0 top-1 h-[15px] w-[15px] rounded-full border-2 border-accent bg-surface" aria-hidden />
            <div className="mb-1.5 flex items-baseline gap-2">
              <span className="text-sm font-semibold">Round {r.n}</span>
              <span className="text-xs text-muted">{r.candidates.length} tested</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {r.candidates.map((c) => {
                const h = byCand.get(c)
                return (
                  <button key={c} onClick={() => h && onOpen(h.id)} className="flex items-center gap-1.5 rounded-md border border-line px-1.5 py-0.5 hover:bg-sunken">
                    <span className="num text-xs font-medium">{c}</span>
                    {h && <StateChip state={h.state as State} className="!px-1.5 !py-0 text-[11px]" />}
                  </button>
                )
              })}
            </div>
            <button onClick={() => setOpen(isOpen ? null : r.n)} aria-expanded={isOpen}
              className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-accent hover:underline">
              {isOpen ? <ChevronDown size={13} /> : <ChevronRight size={13} />} Why these?
            </button>
            <div className={cn('mt-2', !isOpen && 'hidden')}><Why r={r} gate={d.gate} /></div>
          </li>
        )
      })}
      {!d.rounds.length && <li className="py-6 text-center text-sm text-faint">No round has started yet.</li>}
    </ol>
  )
}
