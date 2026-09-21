import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Activity } from 'lucide-react'
import { api } from '../api/client'
import type { ExperimentDetail } from '../api/client'
import EvidenceCurves from '../components/EvidenceCurves'
import { useCampaignEvents } from '../api/useEvents'

function Chip({ status }: { status: string }) {
  return <span className={`chip ${status}`}>{status.replace('_', ' ')}</span>
}

const BRIEF_STATES = new Set(['proposed', 'not_selected'])

function PipelineCards({ cards, budgetNote }: {
  cards: ExperimentDetail['cards']
  budgetNote?: string
}) {
  if (cards.length === 0)
    return (
      <p className="muted" style={{ fontSize: 12 }}>
        No hypotheses yet — the agent proposes them in round 1 (or they
        come from your candidate list).
      </p>
    )
  const detailed = cards.filter((c) => !BRIEF_STATES.has(c.state))
  const brief = cards.filter((c) => BRIEF_STATES.has(c.state))
  return (
    <div style={{ maxWidth: 780 }}>
      <div style={{ display: 'grid', gap: 8 }}>
        {detailed.map((c) => (
          <div key={c.key} className="card" style={{ padding: '10px 12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
              <span>
                <strong>{c.candidate ?? c.head}</strong>
                {c.statement && <span> — {c.statement}</span>}
              </span>
              <span style={{ whiteSpace: 'nowrap', fontSize: 12, fontWeight: 600,
                color: c.state === 'confirmed' || c.state === 'validated'
                  ? 'var(--ok)'
                  : c.state === 'refuted' || c.state === 'refused'
                  ? 'var(--bad)'
                  : c.state === 'inconclusive' ? 'var(--warn)'
                  : 'var(--muted)' }}>
                {c.stage}
              </span>
            </div>
            <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
              {c.round && <div>tested in round {c.round}</div>}
              {c.gate_label && <div>gate: {c.gate_label}</div>}
              {(c.mechanism || c.refutation_condition || c.citation ||
                c.predicted) && (
                <details style={{ marginTop: 2 }}>
                  <summary style={{ cursor: 'pointer', fontSize: 11 }}>
                    hypothesis details
                  </summary>
                  <div style={{ marginTop: 4 }}>
                    {c.predicted && <div>predicted: {c.predicted}</div>}
                    {c.mechanism && <div>mechanism: {c.mechanism}</div>}
                    {c.refutation_condition && (
                      <div>refuted if: {c.refutation_condition}</div>)}
                    {c.citation && (
                      <div>
                        citation: {c.citation}
                        {c.citation_status === 'invalid' && (
                          <strong style={{ color: 'var(--bad)' }}> FABRICATED</strong>
                        )}
                      </div>
                    )}
                  </div>
                </details>
              )}
            </div>
          </div>
        ))}
      </div>
      {brief.length > 0 && (
        <div className="card" style={{ padding: '8px 12px', marginTop: detailed.length ? 8 : 0 }}>
          {(['proposed', 'not_selected'] as const).map((state) => {
            const group = brief.filter((c) => c.state === state)
            if (group.length === 0) return null
            return (
              <div key={state} style={state === 'not_selected' ? { marginTop: 8 } : undefined}>
                <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
                  letterSpacing: '0.04em', marginBottom: 2 }}>
                  {state === 'proposed'
                    ? `Proposed — not tested in this campaign (${group.length}${budgetNote ? `; budget ${budgetNote}` : ''})`
                    : `Designed but not selected (${group.length})`}
                </div>
                {group.map((c) => (
                  <div key={c.key}
                    style={{ display: 'flex', gap: 8, alignItems: 'baseline', padding: '2px 0' }}>
                    <span style={{ fontSize: 12 }}>
                      <strong>{c.candidate ?? c.head}</strong>
                      {c.statement ? ` — ${c.statement.slice(0, 110)}${c.statement.length > 110 ? '…' : ''}` : ''}
                    </span>
                  </div>
                ))}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

function DmtaCounts({ counts, rounds }: { counts: Record<string, number>; rounds: { round: number; candidates: string[]; verdicts: Record<string, string> }[] }) {
  const chips: [string, number | string][] = [
    ['Design', `${counts.proposed ?? 0} proposed · ${counts.selected ?? 0} selected`],
    ['Make', `${counts.submitted ?? 0} submitted`],
    ['Test', `${counts.runs ?? 0} run(s) analyzed`],
    ['Analyze', `${counts.verdicts ?? 0} verdict(s)`],
  ]
  return (
    <div style={{ margin: '10px 0' }}>
      <div className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
        letterSpacing: '0.04em', marginBottom: 4 }}>DMTA loop</div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))',
        gap: 6, maxWidth: 720 }}>
        {chips.map(([label, v]) => (
          <div key={label} className="card"
            style={{ padding: '6px 10px', display: 'grid', gap: 0 }}>
            <span className="muted" style={{ fontSize: 10, textTransform: 'uppercase',
              letterSpacing: '0.04em' }}>{label}</span>
            <span style={{ fontSize: 13 }}>{v}</span>
          </div>
        ))}
      </div>
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
                      {c}: {v}
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

function RecordOfThisRun({ record, onRereview }: {
  record: Record<string, any>
  onRereview: () => Promise<void>
}) {
  return (
    <section>
      <h2 style={{ fontSize: 16 }}>{record.title ?? 'The record of this run'}</h2>
      {record.verdicts && (
        <>
          <h3 style={{ fontSize: 14 }}>Analyze — verdicts</h3>
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
            {record.verdicts.claimed} claimed · {record.verdicts.abstained} abstained/refused
          </p>
        </>
      )}
      {record.reviewer && (
        <>
          <h3 style={{ fontSize: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
            Reviewer pass
            <button style={{ fontSize: 11 }} disabled={record.isFetching}
              onClick={onRereview}>
              Re-run review
            </button>
          </h3>
          <p style={{ fontSize: 12, margin: '4px 0' }}>
            {record.reviewer.findings?.length === 0 ? (
              <span style={{ color: 'var(--ok)' }}>
                Independent review ({record.reviewer.review}): {record.reviewer.verdicts_reviewed} verdict(s) audited — no findings.
              </span>
            ) : (
              <span style={{ color: record.reviewer.critical ? 'var(--bad)' : 'var(--warn)' }}>
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
        </>
      )}
      {record.trust && (
        <>
          <h3 style={{ fontSize: 14 }}>Trust checks</h3>
          {record.trust.checks.map((c: string, i: number) => (
            <p key={i} className="muted" style={{ fontSize: 12, margin: '2px 0' }}>• {c}</p>
          ))}
        </>
      )}
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
    <details style={{ marginTop: 12 }}>
      <summary style={{ cursor: 'pointer', fontSize: 13 }}>Trace log</summary>
      <pre
        className="card"
        style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 320, overflow: 'auto' }}
      >
        {q.data?.lines?.join('\n') || '(waiting for output...)'}
      </pre>
    </details>
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
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, margin: '8px 0 2px' }}>
        <h1 style={{ fontSize: 19, margin: 0 }}>{d.question}</h1>
        <Chip status={d.status} />
      </div>
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        ID: <code>{d.id}</code>
      </p>
      {d.program && (
        <p style={{ fontSize: 13 }}>
          <strong>Program: {d.program.name}</strong> · gate:{' '}
          {d.program.gate.metric} {d.program.gate.symbol} {d.program.gate.value}{' '}
          {d.program.gate.unit} · modality: {d.program.modality ?? '—'} · mode:{' '}
          {d.program.mode}
        </p>
      )}
      {d.spec && (
        <div className="card" style={{ margin: '8px 0', padding: '10px 14px', maxWidth: 780 }}>
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

      <DmtaCounts counts={d.counts} rounds={d.rounds} />

      <h2 style={{ fontSize: 16 }}>
        <Activity size={15} color="var(--teal)" /> Hypothesis pipeline
      </h2>
      <PipelineCards cards={d.cards}
        budgetNote={d.spec ? `top-${d.spec.k} hypotheses/round × ${d.spec.rounds} round${d.spec.rounds > 1 ? 's' : ''}` : ''} />

      {record.data && <RecordOfThisRun record={record.data}
        onRereview={async () => {
          await fetch(`/api/experiments/${d.id}/rereview`, { method: 'POST' })
          // everything on the page derives from these queries — refresh all
          for (const key of [['record', eid], ['experiment', eid],
            ['pipeline', eid], ['trace', eid]]) {
            qc.invalidateQueries({ queryKey: key })
          }
        }} />}
      {record.data?.evidence?.curves?.length > 0 && (
        <EvidenceCurves eid={d.id} curves={record.data.evidence.curves}
          metric={d.program?.gate.metric ?? null} />
      )}

      <TraceLog eid={d.id} active={running}
        revision={record.dataUpdatedAt} />
    </main>
  )
}
