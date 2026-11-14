import { Ban, Check, CircleDashed, Clock, Contrast, Dot, X } from 'lucide-react'
import { cn } from './cn'

export type State =
  | 'confirmed' | 'validated' | 'abstained' | 'refuted' | 'refused'
  | 'in_lab' | 'selected' | 'not_selected' | 'proposed'

/** One visual language for hypothesis state. Colour is never the only signal:
 *  each state has its own icon and label (WCAG 1.4.1). */
const META: Record<State, { label: string; icon: typeof Check; cls: string }> = {
  confirmed: { label: 'Confirmed', icon: Check, cls: 'bg-ok-soft text-ok' },
  validated: { label: 'Validated', icon: Check, cls: 'bg-ok-soft text-ok' },
  refuted: { label: 'Refuted', icon: X, cls: 'bg-bad-soft text-bad' },
  abstained: { label: 'Abstained', icon: Contrast, cls: 'bg-abstain-soft text-abstain' },
  refused: { label: 'Refused', icon: Ban, cls: 'bg-refused-soft text-refused' },
  in_lab: { label: 'In lab', icon: Clock, cls: 'bg-lab-soft text-lab' },
  selected: { label: 'Selected', icon: CircleDashed, cls: 'bg-sunken text-muted' },
  not_selected: { label: 'Not selected', icon: Dot, cls: 'bg-sunken text-faint' },
  proposed: { label: 'Proposed', icon: Dot, cls: 'bg-sunken text-muted' },
}

export function StateChip({ state, className }: { state: State; className?: string }) {
  const m = META[state] ?? META.proposed
  const Icon = m.icon
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium', m.cls, className)}>
      <Icon size={12} strokeWidth={2.5} aria-hidden /> {m.label}
    </span>
  )
}

export function Tag({ children, tone = 'neutral', className, title }: {
  children: React.ReactNode; tone?: 'neutral' | 'ok' | 'warn' | 'bad' | 'accent'; className?: string; title?: string
}) {
  const tones = {
    neutral: 'bg-sunken text-muted', ok: 'bg-ok-soft text-ok', warn: 'bg-warn-soft text-warn',
    bad: 'bg-bad-soft text-bad', accent: 'bg-accent-soft text-accent',
  }
  return <span title={title} className={cn('inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium', tones[tone], className)}>{children}</span>
}
