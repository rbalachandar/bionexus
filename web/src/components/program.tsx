import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import type { ProgramLink, ProblemTreeOut, ProgramOut, TasteReport } from '../api/client'
import { Badge, VERDICT_LABEL } from './ui'

export const NO_LABEL_STATUS = new Set(['completed', 'archived'])

/** Leaf label: never re-print the program objective — campaigns are
 * numbered and named by what they tested; tree leaves keep their own
 * short objective head. `wide` (program page) drops the truncation. */
export function leafLabel(question: string | null,
  objective: string | null, i: number, candidates?: string[],
  wide = false) {
  const cands = wide
    ? (candidates?.length ?? 0) > 8
      ? `${candidates!.length} candidates screened`
      : (candidates ?? []).join(', ')
    : (candidates ?? []).slice(0, 3).join(', ') +
      ((candidates?.length ?? 0) > 3 ? ` +${candidates!.length - 3}` : '')
  if (!objective) return question ?? `Experiment ${i + 1}`
  const q = question ?? ''
  const head = q.split(/\s+[—–]\s/)[0].trim()
  if (!q || q.trim() === objective.trim() || head === objective.trim())
    return cands ? `Campaign ${i + 1} · ${cands}` : `Campaign ${i + 1}`
  const label = !wide && head.length > 56 ? `${head.slice(0, 53)}…` : head
  return cands ? `${label} · ${cands}` : label
}

/** Row tooltip: what this experiment actually did — not the objective
 * the card above it already shows. */
export function leafTitle(l: { eid: string; question: string | null;
  runs?: number; verdicts?: { confirmed: number; preliminary?: number;
  refuted: number; inconclusive: number }; candidates?: string[] }) {
  const bits: string[] = []
  if (l.candidates?.length) bits.push(`tested: ${l.candidates.join(', ')}`)
  if (l.runs) bits.push(`${l.runs} runs`)
  const v = l.verdicts
  if (v && (v.confirmed || v.preliminary || v.refuted || v.inconclusive))
    bits.push(`${v.confirmed} confirmed` +
      (v.preliminary ? ` · ${v.preliminary} preliminary` : '') +
      ` · ${v.refuted} refuted · ${v.inconclusive} abstained`)
  bits.push(l.eid)
  return bits.join(' · ')
}

export function VerdictTally({ v }: {
  v?: { confirmed: number; preliminary?: number; refuted: number;
    inconclusive: number }
}) {
  if (!v) return null
  const parts = [
    [v.confirmed, VERDICT_LABEL.confirmed] as const,
    [v.preliminary ?? 0, VERDICT_LABEL.preliminary] as const,
    [v.refuted, VERDICT_LABEL.refuted] as const,
    [v.inconclusive, VERDICT_LABEL.inconclusive] as const]
  const shown = parts.filter(([n]) => n > 0)
  if (shown.length === 0) return null
  return (
    <span className="mono" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
      {shown.map(([n, l], i) => (
        <span key={l.word} style={{ color: l.color, marginRight: 8 }}>
          {i > 0 ? '' : ''}{n} {l.word}
        </span>
      ))}
    </span>
  )
}

/** Leaf experiment row (dot · label · tally · stats · badge). */
export function LeafRow({ l, i, p, indent, wide }: { l: ProgramLink; i: number;
  p: ProgramOut; indent?: number; wide?: boolean }) {
  return (
    <a key={l.eid} href={`/experiments/${l.eid}`}
      onClick={(e) => e.stopPropagation()}
      title={leafTitle(l)}
      style={{ display: 'grid', gridTemplateColumns: '7px minmax(0, 1fr) auto',
        gap: 8, alignItems: wide ? 'baseline' : 'center', padding: '3px 0',
        fontSize: 12, marginLeft: indent ?? 0 }}>
      <span className={`dot ${l.status}`} style={wide
        ? { marginTop: 4 } : undefined} />
      <span style={wide
        ? { minWidth: 0 }
        : { overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {leafLabel(l.question, p.objective, i, l.candidates, wide)}
      </span>
      <span style={{ display: 'flex', gap: 8, alignItems: 'center',
        justifySelf: 'end', flexWrap: 'wrap', justifyContent: 'flex-end',
        minWidth: 0 }}>
        <VerdictTally v={l.verdicts} />
        <span className="muted mono" style={{ fontSize: 11 }}>
          {l.runs ?? 0} runs · r{l.rounds_done ?? 0}{l.rounds_planned ? `/${l.rounds_planned}` : ''}
        </span>
        {!NO_LABEL_STATUS.has(l.status) && <Badge status={l.status} />}
      </span>
    </a>
  )
}

/** Full (uncapped) problem tree for the program page: sub-problems as
 * indented intermediate nodes, leaves as experiment rows. Multiple
 * trees (one per decomposed launch) render with headers. */
export function ProgramTreeFull({ p }: { p: ProgramOut }) {
  const trees = p.trees ?? (p.tree ? [p.tree] : [])
  const linkByEid = new Map(
    p.links.filter((l) => l.role === 'leaf').map((l) => [l.eid, l]))
  const used = new Set<string>()

  const buildTree = (tree: ProblemTreeOut, multi: boolean): React.ReactNode[] => {
    const kids = (id: string) => tree.nodes.filter((n) => n.parent === id)
    const render = (id: string, depth: number): React.ReactNode[] => {
      const n = tree.nodes.find((x) => x.id === id)!
      const children = kids(id)
      const indent = Math.min(depth, 4) * 16
      if (children.length === 0) {
        const eid = tree.leaf_stats[id]?.eid
        const l = eid ? linkByEid.get(eid) : undefined
        if (l) {
          used.add(l.eid)
          return [<LeafRow key={`${tree.root_id}-${id}`} l={l} i={depth}
            p={p} indent={indent} wide />]
        }
        return [<div key={`${tree.root_id}-${id}`} style={{ marginLeft: indent,
          display: 'flex', gap: 6, alignItems: 'baseline', padding: '2px 0',
          fontSize: 11.5, minWidth: 0 }}>
          <span className={`dot ${n.status}`} />
          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' }}>{n.objective}</span>
          <span className="muted mono" style={{ fontSize: 10,
            flexShrink: 0 }}>{n.status}</span>
        </div>]
      }
      return [
        <div key={`${tree.root_id}-${id}`} style={{ marginLeft: indent,
          display: 'flex', gap: 6, alignItems: 'baseline', padding: '3px 0 1px',
          minWidth: 0 }}>
          <ChevronRight size={11} color="var(--muted)"
            style={{ flex: 'none', transform: 'rotate(90deg)' }} />
          <span style={{ fontSize: 12, fontWeight: 600,
            overflow: 'hidden', textOverflow: 'ellipsis',
            whiteSpace: 'nowrap' }}>{n.objective}</span>
          {n.metric && <span className="muted mono" style={{ fontSize: 10.5,
            flexShrink: 0 }}>
            {n.metric} {n.direction === 'min' ? '≤' : '≥'} {n.gate}</span>}
        </div>,
        ...children.flatMap((c) => render(c.id, depth + 1)),
      ]
    }
    return tree.nodes.filter((x) => !x.parent)
      .flatMap((r) => render(r.id, 0))
  }

  let all: React.ReactNode[] = []
  for (const t of trees) all = all.concat(buildTree(t, false))
  const rest = p.links.filter((l) => l.role === 'leaf' && l.live !== false
    && !used.has(l.eid))
  return (
    <>
      {all}
      {rest.length > 0 && (
        <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
          letterSpacing: '0.04em', marginTop: 8 }}>
          {rest.length} separate campaign{rest.length === 1 ? '' : 's'} · not
          part of any tree
        </div>
      )}
      {rest.map((l, i) => <LeafRow key={l.eid} l={l} i={i} p={p} />)}
    </>
  )
}

/** Selection profile (advisory): accept-rate deltas + amendments.
 * Rows self-suppress without a contrast group. */
export function TasteLines({ taste, compact }: { taste: TasteReport; compact?: boolean }) {
  const rows = (['mechanism', 'refutation', 'citation_verified'] as const)
    .map((k) => ({ key: k, s: taste.by_feature[k] }))
    .filter((r) => r.s?.rate !== null && r.s?.rate !== undefined)
  const LABEL: Record<string, string> = {
    mechanism: 'mechanism stated',
    refutation: 'refutation condition stated',
    citation_verified: 'citation verified (PubMed)' }
  const informative = rows.filter((r) => r.s.rate_without !== null)
  return (
    <div style={{ display: 'grid', gap: 2 }}>
      <div className="muted" style={{ fontSize: compact ? 10 : 11,
        textTransform: 'uppercase', letterSpacing: '0.04em' }}>
        Selection profile — {taste.n} decisions · {taste.accepted} accepted
        {' '}({Math.round(taste.overall_rate * 100)}%) · advisory
      </div>
      {informative.length === 0 ? (
        <div className="muted" style={{ fontSize: 11 }}>
          No within-program contrast: all {taste.n} hypotheses carry the
          demanded features, so accept-rate deltas can't be computed.
          {' '}{taste.accepted}/{taste.n} accepted.
        </div>
      ) : informative.map((r) => {
        const same = Math.abs(r.s.rate! - r.s.rate_without!) < 0.005
        return (
          <div key={r.key} style={{ display: 'flex', flexWrap: 'wrap',
            gap: '2px 10px', alignItems: 'baseline',
            fontSize: compact ? 11 : 12 }}>
            <span>{LABEL[r.key]}</span>
            <span className="mono" style={{ marginLeft: 'auto',
              textAlign: 'right', minWidth: 0, overflowWrap: 'anywhere' }}>
              {same ? 'no difference'
                : `accepted with: ${Math.round(r.s.rate! * 100)}% · without: ${Math.round(r.s.rate_without! * 100)}%`}
              <span className="muted"> (n={r.s.n})</span>
            </span>
          </div>
        )
      })}
      {taste.amendments.map((a) => (
        <div key={a} className="muted" style={{ fontSize: 11 }}>
          • {a}
        </div>
      ))}
    </div>
  )
}
