import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useParams } from 'react-router-dom'
import { ShieldAlert, Target } from 'lucide-react'
import { api } from '../api/client'
import type { ExperimentDetail, PipelineCard } from '../api/client'
import EvidenceCurves from '../components/EvidenceCurves'
import { Badge, Section, VERDICT_GLYPH } from '../components/ui'
import { useCampaignEvents } from '../api/useEvents'

function Chip({ status }: { status: string }) {
  return <span className={`chip ${status}`}>{status.replace('_', ' ')}</span>
}

const BRIEF_STATES = new Set(['proposed', 'not_selected'])

/** "ORGANISM_DOSE_RESPONSE (%)" -> "%": the metric belongs to the gate
 * label; the evidence strip only needs the unit. */
function unitOf(unitLabel: string | null) {
  if (!unitLabel) return ''
  return /\(([^)]+)\)/.exec(unitLabel)?.[1] ?? unitLabel
}

function PipelineCards({ cards }: {
  cards: ExperimentDetail['cards']
}) {
  const detailed = cards.filter((c) => !BRIEF_STATES.has(c.state))
  if (detailed.length === 0)
    return (
      <p className="muted" style={{ fontSize: 12 }}>
        No tested hypotheses yet — the agent proposes them in round 1 (or
        they come from your candidate list).
      </p>
    )
  return (
    <div style={{ maxWidth: 980 }}>
      <div style={{ display: 'grid', gap: 8 }}>
        {detailed.map((c) => (
          <div key={c.key} className="card" style={{ padding: '10px 14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between',
              alignItems: 'center', gap: 10 }}>
              <span style={{ display: 'flex', alignItems: 'baseline', gap: 8,
                minWidth: 0 }}>
                <strong style={{ flex: 'none' }}>{c.candidate ?? c.head}</strong>
                {c.statement && <span className="muted" style={{
                  overflow: 'hidden', textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap' }}>{c.statement}</span>}
              </span>
              <span style={{ whiteSpace: 'nowrap', flex: 'none' }}>
                <Badge status={c.state}>
                  {`${VERDICT_GLYPH[c.state] ?? ''} ${c.state.replace(/_/g, ' ')}`.trim()}
                </Badge>
              </span>
            </div>
            {(c.verdict && c.verdict.observed !== null) || c.gate_label ? (
              <div className="mono" style={{ fontSize: 11.5, marginTop: 8,
                display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'baseline',
                background: 'var(--surface-2)', borderRadius: 6,
                padding: '5px 10px' }}>
                {c.verdict && c.verdict.observed !== null && (
                  <span>observed <strong style={{
                    color: c.state === 'confirmed' || c.state === 'validated'
                      ? 'var(--ok)'
                      : c.state === 'refuted' ? 'var(--bad)'
                      : c.state === 'inconclusive' ? 'var(--warn)'
                      : 'var(--ink)' }}>
                    {c.verdict.observed} {unitOf(c.verdict.unit_label)}</strong></span>)}
                {c.verdict?.ci && <span className="muted">
                  95% CI {c.verdict.ci[0]}–{c.verdict.ci[1]}</span>}
                {c.verdict?.margin && <span className="muted">{c.verdict.margin}</span>}
                {c.gate_label && <span className="muted">gate: {c.gate_label}</span>}
              </div>
            ) : null}
            <div className="muted" style={{ fontSize: 12, marginTop: 6,
              display: 'grid', gridTemplateColumns: 'minmax(0, 1fr)',
              gap: 1 }}>
              {c.stage && !BRIEF_STATES.has(c.state)
                && c.stage !== c.state.replace(/_/g, ' ')
                && <div>{c.stage.split(/\s+[—–]\s/)[0].trim()}</div>}
              {c.round && <div>tested in round {c.round}</div>}
              {(c.mechanism || c.refutation_condition || c.citation ||
                c.predicted) && (
                <div style={{ display: 'grid',
                  gridTemplateColumns: 'minmax(72px, auto) minmax(0, 1fr)',
                  gap: '1px 10px', marginTop: 4 }}>
                  {c.predicted && <>
                    <span style={{ color: 'var(--faint)' }}>predicted</span>
                    <span>{c.predicted}</span></>}
                  {c.mechanism && <>
                    <span style={{ color: 'var(--faint)' }}>mechanism</span>
                    <span>{c.mechanism}</span></>}
                  {c.refutation_condition && <>
                    <span style={{ color: 'var(--faint)' }}>refuted if</span>
                    <span>{c.refutation_condition}</span></>}
                  {c.citation && <>
                    <span style={{ color: 'var(--faint)' }}>citation</span>
                    <span>{c.citation}
                      {c.citation_status === 'invalid' && (
                        <strong style={{ color: 'var(--bad)' }}> FABRICATED</strong>
                      )}</span></>}
                </div>
              )}
            </div>
           </div>
         ))}
       </div>
     </div>
   )
}

/** One consolidated "not tested" list: proposed-but-unselected cards +
 * filter-eliminated hypotheses merged by candidate, statement snippet
 * joined with the filter's reason and score. Replaces the three
 * overlapping blocks (proposed / not selected / eliminated). */
function NotTested({ cards, eliminated }: {
  cards: PipelineCard[]
  eliminated: NonNullable<ExperimentDetail['eliminated']>
}) {
  const brief = cards.filter((c) => BRIEF_STATES.has(c.state))
  const byCand = new Map(eliminated.map((e) => [e.candidate, e]))
  const rows: { cand: string; statement: string | null;
    reason: string | null; score: number | null }[] = []
  const seen = new Set<string>()
  for (const c of brief) {
    const cand = c.candidate ?? c.head
    // family-level proposal statements carry no candidate: they were
    // never testable units — their variants are the hypotheses
    if (c.state === 'proposed' && !c.candidate) continue
    seen.add(cand)
    const e = byCand.get(cand)
    rows.push({ cand, statement: c.statement ?? null,
      reason: e?.reason ?? (c.state === 'proposed'
        ? 'no recorded filter decision — budget exhausted before ranking'
        : null), score: e?.score ?? null })
  }
  for (const e of eliminated)
    if (!seen.has(e.candidate))
      rows.push({ cand: e.candidate, statement: null,
        reason: e.reason, score: e.score })
  if (rows.length === 0) return null
  return (
    <details style={{ marginTop: 12 }}>
      <summary style={{ cursor: 'pointer', fontSize: 13,
        display: 'inline-flex', gap: 6, alignItems: 'center' }}>
        <span className="chip" style={{ color: 'var(--muted)' }}>
          Not tested ({rows.length})
        </span>
        <span className="muted" style={{ fontSize: 11 }}>
          proposed or cut by the filter — with the reasons
        </span>
      </summary>
      <div className="card" style={{ padding: '8px 12px', marginTop: 6,
        display: 'grid', gap: 2 }}>
        {rows.map((r) => (
          <div key={r.cand} style={{ display: 'grid', gap: 2,
            padding: '6px 0', borderBottom: '1px solid var(--border)' }}>
            <div style={{ display: 'flex', gap: 10, alignItems: 'baseline',
              minWidth: 0 }}>
              <span className="mono" style={{ flex: 'none',
                fontWeight: 600 }}>{r.cand}</span>
              {r.reason && <span className="muted" title={r.reason}
                style={{ fontSize: 11, minWidth: 0, overflow: 'hidden',
                  textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {r.reason}</span>}
              {r.score !== null && r.score !== undefined && (
                <span className="muted mono" style={{ marginLeft: 'auto',
                  flex: 'none', fontSize: 11 }}>
                  score {r.score}</span>
              )}
            </div>
            {r.statement && <span className="muted" style={{
              fontSize: 11.5, overflow: 'hidden', display: '-webkit-box',
              WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>
              {r.statement}</span>}
          </div>
        ))}
      </div>
    </details>
  )
}

function PendingApprovals({ eid, active }: { eid: string; active: boolean }) {  const qc = useQueryClient()
  const q = useQuery({
    queryKey: ['approvals-inline', eid],
    queryFn: () => fetch('/api/approvals').then((r) => r.json()),
    enabled: active,
    refetchInterval: 4000,
  })
  const pending: { id: string; title: string; detail: string }[] =
    q.data?.pending ?? []
  if (!active || pending.length === 0) return null
  return (
    <div className="card" style={{ borderColor: '#f59e0b', background: '#fffbeb',
      padding: '10px 14px', margin: '10px 0', display: 'grid', gap: 8 }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 13,
        fontWeight: 600 }}>
        <ShieldAlert size={15} color="#d97706" />
        Waiting on your approval — the campaign is paused at the gate
      </div>
      {pending.map((a) => (
        <div key={a.id} style={{ display: 'flex', gap: 10, alignItems: 'center',
          fontSize: 12 }}>
          <span className="mono" style={{ flex: 'none' }}>{a.title}</span>
          {a.detail && <span className="muted" style={{ minWidth: 0,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
            {a.detail}</span>}
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, flex: 'none' }}>
            <button className="primary" style={{ fontSize: 11, padding: '3px 12px' }}
              onClick={async () => {
                await fetch(`/api/approvals/${a.id}/decide`, { method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ approve: true }) })
                qc.invalidateQueries({ queryKey: ['approvals-inline', eid] })
              }}>
              Approve
            </button>
            <button style={{ fontSize: 11, padding: '3px 12px' }}
              onClick={async () => {
                await fetch(`/api/approvals/${a.id}/decide`, { method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ approve: false }) })
                qc.invalidateQueries({ queryKey: ['approvals-inline', eid] })
              }}>
              Deny
            </button>
          </span>
        </div>
      ))}
    </div>
  )
}

function DmtaCounts({ counts, rounds, bare }: { counts: Record<string, number>; rounds: { round: number; candidates: string[]; verdicts: Record<string, string> }[]; bare?: boolean }) {
  const chips: [string, number | string][] = [
    ['Design', `${counts.proposed ?? 0} proposed · ${counts.selected ?? 0} selected`],
    ['Make', `${counts.submitted ?? 0} submitted`],
    ['Test', `${counts.runs ?? 0} run(s) analyzed`],
    ['Analyze', `${counts.verdicts ?? 0} verdict(s)`],
  ]
  const judged = (counts.validated ?? 0) + (counts.confirmed ?? 0)
    + (counts.refuted ?? 0) + (counts.inconclusive ?? 0)
  const selected = counts.selected ?? 0
  const funnel: string[] = []
  if ((counts.proposed ?? 0) > 0 || selected > 0) {
    funnel.push(`${counts.proposed ?? 0} proposed`)
    funnel.push(`${selected} selected`)
    funnel.push(`${counts.runs ?? 0} tested`)
    funnel.push(`${judged} judged`)
  }
  const elim = selected > 0 && judged > 0
    ? Math.round((1 - judged / selected) * 100) : null
  return (
    <div style={bare ? undefined : { margin: '10px 0' }}>
      {!bare && (
        <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
          letterSpacing: '0.04em', marginBottom: 4 }}>DMTA loop</div>
      )}
      <div style={{ display: 'flex', alignItems: 'stretch', gap: 0,
        maxWidth: 980, marginBottom: 'var(--s2)' }}>
        {chips.map(([label, v], i) => (
          <div key={label} style={{ flex: 1, display: 'flex', alignItems: 'center' }}>
            <div style={{ flex: 1, border: '1px solid var(--border)',
              background: 'var(--surface)', borderRadius: 'var(--radius)',
              padding: '7px 12px' }}>
              <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
                letterSpacing: '0.05em' }}>
                {i + 1} · {label}
              </div>
              <div style={{ fontSize: 12 }}>{v}</div>
            </div>
            {i < chips.length - 1 && (
              <div style={{ width: 14, height: 1, background: 'var(--border-strong)',
                flex: 'none' }} />
            )}
          </div>
        ))}
      </div>
      {funnel.length > 0 && (
        <div className="muted mono" style={{ fontSize: 11, margin: '2px 0 10px',
          display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'baseline' }}>
          {funnel.map((s, i) => (
            <span key={s} style={{ display: 'inline-flex', gap: 6 }}>
              {i > 0 && <span style={{ color: 'var(--faint)' }}>→</span>}
              <span>{s}</span>
            </span>
          ))}
          {elim !== null && <span style={{ color: 'var(--brand)' }}>
            · {elim}% of selected eliminated</span>}
        </div>
      )}
      {rounds.length > 0 && (
        <table className="data-table" style={{ marginTop: 8 }}>
          <thead>
            <tr>
              <th>round</th>
              <th>tested</th>
              <th>verdicts</th>
            </tr>
          </thead>
          <tbody>
            {rounds.map((r) => (
              <tr key={r.round}>
                <td>{r.round}</td>
                <td>{r.candidates.join(', ')}</td>
                <td>
                  {Object.entries(r.verdicts).map(([c, v]) => (
                    <span key={c} className={`chip ${v}`} style={{ marginRight: 6, fontSize: 11 }}>
                      {`${VERDICT_GLYPH[v] ?? ''} ${c}: ${v.replace(/_/g, ' ')}`.trim()}
                    </span>
                  )) || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

function RecordOfThisRun({ record, onRereview, eid, metric, gate, running }: {
  record: Record<string, any>
  onRereview: () => Promise<void>
  eid: string
  metric?: string | null
  gate?: number | null
  running?: boolean
}) {
  const [tab, setTab] = useState<'verdicts' | 'evidence' | 'reviewer' | 'trust'>('verdicts')
  const tabs: [string, typeof tab, boolean][] = [
    ['Verdicts', 'verdicts', !!record.verdicts],
    ['Evidence', 'evidence', !!record.evidence],
    ['Reviewer', 'reviewer', !!record.reviewer],
    ['Trust', 'trust', !!record.trust],
  ]
  const empty = (msg: string) => (
    <p className="muted" style={{ fontSize: 12 }}>
      {running ? `${msg} — the campaign is still running; this fills in as rounds complete.` : msg}
    </p>
  )
  return (
    <section>
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--border)',
        marginBottom: 10 }}>
        {tabs.map(([label, key, has]) => (
          <button key={key} onClick={() => setTab(key)}
            title={has ? undefined : 'nothing recorded for this section'}
            style={{
              border: 'none', background: 'transparent', borderRadius: 0,
              padding: '6px 12px', fontSize: 12, fontWeight: 500,
              cursor: has ? 'pointer' : 'not-allowed',
              color: tab === key ? 'var(--brand)' : 'var(--muted)',
              borderBottom: tab === key
                ? '2px solid var(--brand)' : '2px solid transparent',
              opacity: has ? 1 : 0.4,
            }}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'verdicts' && (!record.verdicts
        ? empty('No verdicts recorded yet — nothing to audit.')
        : (
          <>
            <table className="data-table">
              <thead>
                <tr>
                  {Object.keys(record.verdicts.rows[0] ?? {}).map((k) => (
                    <th key={k}>{k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {record.verdicts.rows.map((r: any, i: number) => (
                  <tr key={i}>
                    {Object.values(r).map((v, j) => (
                      <td key={j}>{String(v ?? '—')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted" style={{ fontSize: 12 }}>
              {record.verdicts.claimed} claimed ·{' '}
              {record.verdicts.abstained} abstained/refused
            </p>
          </>
        ))}

      {tab === 'evidence' && (!record.evidence
        ? empty('No evidence recorded — no plate files found for this run.')
        : record.evidence.curves?.length > 0
          ? <EvidenceCurves eid={eid} curves={record.evidence.curves}
            metric={metric} gate={gate} />
          : empty(record.evidence.empty_note ??
              'No recorded plate files found for these runs.'))}

      {tab === 'reviewer' && (!record.reviewer
        ? empty('No reviewer pass recorded for this run yet.')
        : (
          <>
            <p style={{ fontSize: 13, margin: '4px 0' }}>
              {record.reviewer.findings?.length === 0 ? (
                <span style={{ color: 'var(--ok)' }}>
                  Independent review ({record.reviewer.review}):{' '}
                  {record.reviewer.verdicts_reviewed} verdict(s) audited — no findings.
                </span>
              ) : (
                <span style={{ color: record.reviewer.critical
                  ? 'var(--bad)' : 'var(--warn)' }}>
                  {record.reviewer.critical} critical / {record.reviewer.warnings} warnings
                </span>
              )}
            </p>
            {(record.reviewer.findings?.length ?? 0) > 0 && (
              <table className="data-table">
                <thead>
                  <tr><th>severity</th><th>kind</th><th>candidate</th><th>detail</th></tr>
                </thead>
                <tbody>
                  {record.reviewer.findings.map((f: any, i: number) => (
                    <tr key={i}>
                      <td>{f.severity}</td><td>{f.kind}</td>
                      <td>{f.candidate ?? '—'}</td><td>{f.detail}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {record.reviewer.llm && (
              <p className="muted" style={{ fontSize: 12 }}>
                LLM reviewer (advisory) — {record.reviewer.llm.model}:{' '}
                {record.reviewer.llm.unavailable
                  ? `unavailable (${record.reviewer.llm.unavailable})`
                  : `${record.reviewer.llm.flags?.length ?? 0} flag(s)`}
              </p>
            )}
            <div style={{ margin: '8px 0 0' }}>
              <button style={{ fontSize: 11 }} disabled={record.isFetching}
                onClick={onRereview}>
                Re-run review
              </button>
            </div>
          </>
        ))}

      {tab === 'trust' && (!record.trust
        ? empty('No trust checks recorded for this run yet.')
        : record.trust.checks.map((c: string, i: number) => (
            <p key={i} className="muted" style={{ fontSize: 12, margin: '2px 0' }}>
              • {c}
            </p>
          )))}
    </section>
  )
}

function TraceLog({ eid, active, revision }: {
  eid: string
  active: boolean
  revision: number
}) {
  const q = useQuery({
    // revision (record fetch timestamp) in the key: whenever any other
    // section updates, the trace re-pulls too — nothing goes stale
    queryKey: ['trace', eid, revision],
    queryFn: () => api.trace(eid),
    enabled: true,
    refetchInterval: active ? 5000 : false,
  })
  return (
    <pre
      className="card"
      style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}
    >
      {q.data?.lines?.join('\n') || '(waiting for output...)'}
    </pre>
  )
}

export default function Experiment() {
  const qc = useQueryClient()
  const { eid } = useParams<{ eid: string }>()
  const q = useQuery({
    queryKey: ['experiment', eid],
    queryFn: () => api.experiment(eid!),
    enabled: !!eid,
    refetchInterval: 10000,   // safety net if SSE drops; cheap read
  })
  const record = useQuery({
    queryKey: ['record', eid],
    queryFn: () => api.record(eid!),
    enabled: !!eid,
  }) as { data: any | undefined; isLoading: boolean; isError: boolean; dataUpdatedAt: number; isFetching: boolean; refetch: () => unknown }
  const status = q.data?.status
  const running = status === 'running' || status === 'executing'
  useCampaignEvents(eid, running)

  if (q.isLoading) return <p className="muted">Loading…</p>
  if (q.isError || !q.data)
    return <p className="chip failed">Experiment not found.</p>
  const d = q.data!

  return (
    <main>
      <a href="/" className="muted" style={{ fontSize: 12 }}>← All experiments</a>
      <div style={{ position: 'sticky', top: 0, zIndex: 5, background: 'var(--bg)',
        padding: '10px 0 8px', borderBottom: '1px solid var(--border)',
        marginBottom: 'var(--s3)' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <h1 style={{ fontSize: 'var(--fs-lg)', margin: 0, fontWeight: 650,
            overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
            flex: 1, minWidth: 0 }}>
            {d.question}
          </h1>
          <Chip status={d.status} />
        </div>
        <p className="muted" style={{ fontSize: 11, margin: '2px 0 0' }}>
          {d.program && <><strong style={{ color: 'var(--ink-2)' }}>{d.program.name}</strong> · </>}
          <span className="mono">ID: {d.id}</span>
        </p>
      </div>
      {d.program && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 'var(--s2)' }}>
          <span className="chip" style={{ background: 'var(--brand-tint)',
            borderColor: 'var(--brand-border)', color: 'var(--brand)' }}>
            <Target size={11} /> {d.program.name}
          </span>
          <span className="chip mono">
            gate {d.program.gate.symbol} {d.program.gate.value} {d.program.gate.unit}
          </span>
          {d.program.modality && <span className="chip">{d.program.modality}</span>}
          <span className="chip">{d.program.mode}</span>
        </div>
      )}
      <Section n={1} title="Campaign setup">
        {d.spec && (
          <div className="card" style={{ padding: '10px 14px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '110px 1fr', gap: '3px 12px', fontSize: 12 }}>
              <span className="muted">Objective</span>
              <span>{d.objective}</span>
              <span className="muted">Constraints</span>
              <span>{d.constraints.map((c) => `${c.name}: ${c.description}`).join(' · ') || '—'}</span>
              <span className="muted">Success</span>
              <span>{d.success_metric ?? '—'}</span>
              <span className="muted">Budget</span>
              <span>top-{d.spec.k} hypotheses/round · {d.spec.rounds} DMTA rounds ·
                autonomy: {d.spec.autonomy} · candidates:{' '}
                {d.spec.hypothesis_source === 'agent'
                  ? 'agent-proposed'
                  : `${d.spec.n_candidates} named`}</span>
            </div>
          </div>
        )}
        {running && (
          <p className="chip running" style={{ marginTop: 8 }}>
            In progress — this page updates as the agent works.
          </p>
        )}
      </Section>

      {running && (
        <Section n={2} title="Approvals">
          <PendingApprovals eid={d.id} active={running} />
        </Section>
      )}

      <Section n={running ? 3 : 2} title="DMTA loop">
        <DmtaCounts counts={d.counts} rounds={d.rounds} bare />
      </Section>

      <Section n={running ? 4 : 3} title="Hypothesis pipeline">
        <PipelineCards cards={d.cards} />

        <NotTested cards={d.cards} eliminated={d.eliminated ?? []} />
      </Section>

      {record.data && (
        <Section n={running ? 5 : 4} title="The record of this run">
          <RecordOfThisRun record={record.data} eid={d.id}
            metric={d.program?.gate.metric ?? null}
            gate={d.program?.gate.value ?? null}
            onRereview={async () => {
              await fetch(`/api/experiments/${d.id}/rereview`, { method: 'POST' })
              // everything on the page derives from these queries — refresh all
              for (const key of [['record', eid], ['experiment', eid],
                ['pipeline', eid], ['trace', eid]]) {
                qc.invalidateQueries({ queryKey: key })
              }
            }} />
        </Section>
      )}

      <Section n={running ? 6 : 5} title="Trace log">
        <TraceLog eid={d.id} active={running}
          revision={record.dataUpdatedAt} />
      </Section>
    </main>
  )
}
