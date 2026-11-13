import type { Schemas } from '../../api/v1'

export type Hyp = Schemas['HypothesisSummary']
export type Detail = Schemas['CampaignDetail']

export const sig = (x: number | null | undefined, n = 3) =>
  x == null ? '—' : Number(x.toPrecision(n)).toString()

export const ago = (ts: number | null | undefined) => {
  if (!ts) return ''
  const s = Math.max(0, Date.now() / 1000 - ts)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.floor(s / 60)} min ago`
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`
  return `${Math.floor(s / 86400)} d ago`
}

/** Unit label for a gate such as "IC50 (µM) ≤ 20" → "µM". */
export const unitOf = (gateLabel?: string | null) => /\(([^)]+)\)/.exec(gateLabel ?? '')?.[1] ?? ''

/** What the interval means for the gate, in plain language. */
export function explain(h: Hyp, gate: Schemas['Gate']): string {
  const v = h.verdict
  const g = gate.threshold
  if (!v) return 'No verdict yet.'
  const side = gate.direction === 'max' ? 'above' : 'below'
  if (v.status === 'abstained') {
    return v.extrapolation
      ? 'The value came from a model outside its applicability domain, so no claim is made either way.'
      : `The 95% interval straddles the gate (${sig(g)}), so the data cannot say which side the true value is on. No claim either way.`
  }
  if (v.status === 'validated')
    return `The whole 95% interval lies ${side} the gate (${sig(g)}). Preliminary — pending an orthogonal confirmation.`
  if (v.status === 'confirmed')
    return `Confirmed: an orthogonal re-measurement agrees, and the 95% interval lies ${side} the gate (${sig(g)}).`
  return `The whole 95% interval lies on the wrong side of the gate (${sig(g)}): this candidate does not meet the criterion.`
}

/** A concrete next step for an abstention — the part a scientist acts on. */
export function suggestion(h: Hyp, gate: Schemas['Gate']): string | null {
  if (h.verdict?.status !== 'abstained') return null
  if (h.verdict.extrapolation)
    return 'Test it in the lab: a model prediction outside its training chemistry is a question, not evidence.'
  return `Resolve it with more data near the gate: add replicates and a tighter dose ladder around ${sig(gate.threshold)}.`
}

/** 1–2–5 tick values inside a log-axis domain (a scientist reads 0.5, 1, 2, 5, 10 — not 0.4 0.5 0.6 …). */
export function niceLogTicks(lo: number, hi: number): number[] {
  const out: number[] = []
  const start = Math.floor(Math.log10(lo)) - 1, end = Math.ceil(Math.log10(hi)) + 1
  for (let e = start; e <= end; e++)
    for (const m of [1, 2, 5]) {
      const v = m * 10 ** e
      if (v >= lo && v <= hi) out.push(Number(v.toPrecision(6)))
    }
  return out.length >= 3 ? out : [lo, Math.sqrt(lo * hi), hi].map((v) => Number(v.toPrecision(3)))
}
