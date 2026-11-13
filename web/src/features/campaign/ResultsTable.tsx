import { StateChip, type State } from '../../ui/Chip'
import { Tip } from '../../ui/Tooltip'
import { cn } from '../../ui/cn'
import { AXIS_H, ForestPlot, ROW_H } from './ForestPlot'
import { sig, unitOf, type Detail, type Hyp } from './format'

const ORDER: Record<string, number> = { confirmed: 0, validated: 1, abstained: 2, refuted: 3, in_lab: 4, refused: 5, selected: 6, proposed: 7, not_selected: 8 }

export function ResultsTable({ d, onOpen, selected }: { d: Detail; onOpen: (h: Hyp) => void; selected?: string | null }) {
  const hyps = [...d.hypotheses].sort((a, b) => (ORDER[a.state] ?? 9) - (ORDER[b.state] ?? 9) || (a.round ?? 99) - (b.round ?? 99))
  const unit = unitOf(d.gate.label)
  return (
    <div className="grid grid-cols-[minmax(150px,200px)_1fr_minmax(130px,170px)]">
      <div className="px-4 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted">Candidate</div>
      <div className="px-2 pb-1 pt-2 text-[11px] font-semibold uppercase tracking-wider text-muted">
        Estimate and 95% interval <span className="font-normal normal-case text-faint">· shaded = meets the gate</span>
      </div>
      <div className="px-4 pb-1 pt-2 text-right text-[11px] font-semibold uppercase tracking-wider text-muted">Value</div>

      <div className="border-t border-line">
        {hyps.map((h) => (
          <button key={h.id} onClick={() => onOpen(h)} style={{ height: ROW_H }}
            className={cn('flex w-full items-center gap-2 border-b border-line px-4 text-left hover:bg-sunken', selected === h.id && 'bg-sunken')}>
            <span className="num min-w-0 flex-1 truncate text-sm font-medium">{h.head}</span>
            <StateChip state={h.state as State} />
          </button>
        ))}
        <div style={{ height: AXIS_H }} aria-hidden />
      </div>
      <div className="border-t border-line" style={{ minHeight: hyps.length * ROW_H + AXIS_H }}>
        <ForestPlot hyps={hyps} gate={d.gate.threshold ?? null} direction={d.gate.direction ?? null} unit={unit} />
      </div>
      <div className="border-t border-line">
        {hyps.map((h) => {
          const v = h.verdict
          return (
            <div key={h.id} style={{ height: ROW_H }} className="flex flex-col justify-center border-b border-line px-4 text-right">
              {v?.observed != null ? (
                <Tip label={v.ci ? `95% interval ${sig(v.ci[0])} – ${sig(v.ci[1])} ${unit}` : 'single estimate — no interval'}>
                  <span className="num cursor-default text-sm">{sig(v.observed)} <span className="text-xs text-faint">{unit}</span></span>
                </Tip>
              ) : (
                <span className="text-xs text-faint">{h.round ? `round ${h.round}` : 'not tested'}</span>
              )}
              {v?.ci && <span className="num text-[11px] text-faint">[{sig(v.ci[0])} – {sig(v.ci[1])}]</span>}
            </div>
          )
        })}
        <div style={{ height: AXIS_H }} aria-hidden />
      </div>
    </div>
  )
}
