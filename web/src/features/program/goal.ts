import type { Schemas } from '../../api/v1'
import { sig } from '../campaign/format'

type Goal = Schemas['Goal']
type Gate = Schemas['Gate']

/** The program's progress, in the words a scientist would use. */
export function goalLine(goal: Goal, gate: Gate): { tone: 'ok' | 'warn' | 'neutral'; title: string; detail: string } {
  const unit = gate.unit ? ` ${gate.unit}` : ''
  const b = goal.best
  if (goal.met && b)
    return { tone: 'ok', title: 'Goal met', detail: `${b.candidate} — ${sig(b.observed)}${unit} against ${gate.label} (${b.state}, ${b.campaign_title})` }
  if (b)
    return { tone: 'warn', title: 'Not met yet',
      detail: `closest so far: ${b.candidate} at ${sig(b.observed)}${unit} (${b.state})${goal.abstained ? ` · ${goal.abstained} abstained candidate${goal.abstained > 1 ? 's' : ''} could still resolve it` : ''}` }
  return { tone: 'neutral', title: 'No results yet', detail: 'No candidate has been judged against the gate.' }
}
