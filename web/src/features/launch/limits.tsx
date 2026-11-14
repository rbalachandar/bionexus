import type { Schemas } from '../../api/v1'
import { Input } from '../../ui/Field'

export type Limits = Schemas['Limits']

export const DEFAULT_LIMITS: Limits = { max_rounds: 3, max_lab_runs: 20, max_hypotheses: 12, max_families: 3, max_variants_per_family: 3, breadth: 3 }

/** What each cap means, in a scientist's words. Hard caps: a campaign may use less, never more. */
export const LIMIT_FIELDS: { key: keyof Limits; label: string; hint: string; max: number }[] = [
  { key: 'max_rounds', label: 'Rounds', hint: 'each round’s results feed the next', max: 8 },
  { key: 'max_lab_runs', label: 'Lab runs', hint: 'including confirmation assays', max: 500 },
  { key: 'max_hypotheses', label: 'Hypotheses', hint: 'across all rounds', max: 200 },
  { key: 'max_families', label: 'Families', hint: 'distinct mechanistic bets a model may propose', max: 8 },
  { key: 'max_variants_per_family', label: 'Variants per family', hint: 'analogs of one idea', max: 8 },
  { key: 'breadth', label: 'Per round', hint: 'hypotheses taken to the lab each round', max: 12 },
]

export function LimitsEditor({ value, onChange }: { value: Limits; onChange: (l: Limits) => void }) {
  return (
    <div className="grid grid-cols-2 gap-x-3 gap-y-2 sm:grid-cols-3">
      {LIMIT_FIELDS.map((f) => (
        <label key={f.key} className="block" title={f.hint}>
          <span className="mb-1 block text-xs font-medium text-muted">{f.label}</span>
          <Input type="number" min={1} max={f.max} value={value[f.key]}
            onChange={(e) => onChange({ ...value, [f.key]: Math.max(1, Math.min(f.max, Number(e.target.value) || 1)) })} />
        </label>
      ))}
    </div>
  )
}

export const limitsLine = (l: Limits) =>
  `up to ${l.max_rounds} round${l.max_rounds > 1 ? 's' : ''} · ${l.max_lab_runs} lab runs · ${l.max_hypotheses} hypotheses ` +
  `(${l.max_families} families × ${l.max_variants_per_family} variants) · ${l.breadth} per round`
