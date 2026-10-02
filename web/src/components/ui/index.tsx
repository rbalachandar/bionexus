import type { ReactNode } from 'react'

/** One visual language for verdicts, shared by workspace rows and the
 * experiment page: ✓ confirmed · ✗ refuted · ∅ abstained. */
export const VERDICT_GLYPH: Record<string, string> = {
  confirmed: '✓', validated: '✓',
  refuted: '✗', invalidated: '✗', refused: '✗', failed: '✗',
  inconclusive: '∅',
}

/** Status badge: dot + label, tinted. Pulse for running states. */
export function Badge({ status, children }: { status: string; children?: ReactNode }) {
  return (
    <span className={`chip ${status}`}>
      {children ?? status.replace(/_/g, ' ')}
    </span>
  )
}

/** Loading placeholder with shimmer. */
export function Skeleton({ w = '100%', h = 14, style }: {
  w?: number | string; h?: number; style?: React.CSSProperties
}) {
  return <div className="skeleton" style={{ width: w, height: h, ...style }} />
}

/** Empty state: icon + copy + optional action. */
export function EmptyState({ icon, title, hint, action }: {
  icon?: ReactNode; title: string; hint?: string; action?: ReactNode
}) {
  return (
    <div className="card" style={{
      display: 'grid', justifyItems: 'center', gap: 8,
      padding: '40px 24px', textAlign: 'center',
    }}>
      {icon && <div style={{ color: 'var(--faint)' }}>{icon}</div>}
      <div style={{ fontWeight: 600 }}>{title}</div>
      {hint && <div className="muted" style={{ fontSize: 12, maxWidth: 420 }}>{hint}</div>}
      {action}
    </div>
  )
}

/** Page header: eyebrow + title + right-side content. */
export function PageHeader({ eyebrow, title, right }: {
  eyebrow?: string; title: string; right?: ReactNode
}) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between',
      alignItems: 'center', marginBottom: 'var(--s4)' }}>
      <div>
        {eyebrow && (
          <div className="muted" style={{ fontSize: 11, textTransform: 'uppercase',
            letterSpacing: '0.05em', marginBottom: 2 }}>{eyebrow}</div>
        )}
        <h1 style={{ fontSize: 'var(--fs-xl)', margin: 0, fontWeight: 650 }}>{title}</h1>
      </div>
      {right}
    </div>
  )
}

/** Page band: numbered eyebrow + hairline rule — explicit visual
 * sectioning for detail pages. */
export function Section({ n, title, children }: {
  n: number; title: string; children: ReactNode
}) {
  return (
    <section style={{ marginTop: 'var(--s4)', maxWidth: 980,
      borderTop: '1px solid var(--border)', paddingTop: 12 }}>
      <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--ink-2)',
        textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
        <span style={{ color: 'var(--brand)', fontWeight: 700 }}>{n}</span>
        {' · '}{title}
      </div>
      {children}
    </section>
  )
}

/** Definition row: label + value (meta cards). */
export function DefRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <span className="muted" style={{ fontSize: 12 }}>{label}</span>
      <span style={{ fontSize: 12 }}>{children}</span>
    </>
  )
}

/** Mono data value. */
export function Data({ children }: { children: ReactNode }) {
  return <span className="mono" style={{ fontSize: '0.92em' }}>{children}</span>
}
