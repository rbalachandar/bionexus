import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { Activity } from 'lucide-react'
import { api } from '../api/client'
import type { ExperimentDetail } from '../api/client'
import EvidenceCurves from '../components/EvidenceCurves'
import { useCampaignEvents } from '../api/useEvents'

function Chip({ status }: { status: string }) {
  return <span className={`chip ${status}`}>{status.replace('_', ' ')}</span>
}

function PipelineCards({ cards }: { cards: ExperimentDetail['cards'] }) {
  if (cards.length === 0)
    return (
      <p className="muted" style={{ fontSize: 12 }}>
        No hypotheses yet — the agent proposes them in round 1 (or they
        come from your candidate list).
      </p>
    )
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {cards.map((c) => (
        <div key={c.key} className="card" style={{ padding: '10px 12px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10 }}>
            <span>
              <strong>{c.candidate ?? c.head}</strong>
              {c.statement && <span> — {c.statement}</span>}
            </span>
            <span className={`chip ${c.state}`} style={{ whiteSpace: 'nowrap' }}>
              {c.stage}
            </span>
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            {c.predicted && <div>predicted: {c.predicted}</div>}
            {c.mechanism && <div>mechanism: {c.mechanism}</div>}
            {c.refutation_condition && <div>refuted if: {c.refutation_condition}</div>}
            {c.citation && (
              <div>
                citation: {c.citation}
                {c.citation_status === 'invalid' && (
                  <strong style={{ color: 'var(--bad)' }}> FABRICATED</strong>
                )}
              </div>
            )}
            {c.gate_label && <div>gate: {c.gate_label}</div>}
            {c.round && <div>tested in round {c.round}</div>}
          </div>
        </div>
      ))}
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
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
        {chips.map(([label, v]) => (
          <span key={label} className="chip">
            <strong>DMTA · {label}</strong>&nbsp;{v}
          </span>
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

function RecordOfThisRun({ record }: { record: Record<string, any> }) {
  return (
    <section>
      <h2 style={{ fontSize: 16 }}>{record.title ?? 'The record of this run'}</h2>
      {record.verdicts && (
        <>
          <h3 style={{ fontSize: 14 }}>Analyze — verdicts</h3>
          <table style={{ fontSize: 12, borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {Object.keys(record.verdicts.rows[0] ?? {}).map((k) => (
                  <th key={k} style={{ textAlign: 'left', paddingRight: 14 }}>{k}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {record.verdicts.rows.map((r: any, i: number) => (
                <tr key={i}>
                  {Object.values(r).map((v, j) => (
                    <td key={j} style={{ paddingRight: 14 }}>{String(v ?? '—')}</td>
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
          <h3 style={{ fontSize: 14 }}>Reviewer pass</h3>
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
          {record.reviewer.findings?.map((f: any, i: number) => (
            <p key={i} style={{ fontSize: 12, margin: '2px 0' }}>
              <strong>{f.severity}</strong> · {f.kind}
              {f.candidate ? ` · ${f.candidate}` : ''} — {f.detail}
            </p>
          ))}
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

function TraceLog({ eid, active }: { eid: string; active: boolean }) {
  const q = useQuery({
    queryKey: ['trace', eid],
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
  const { eid } = useParams<{ eid: string }>()
  const q = useQuery({
    queryKey: ['experiment', eid],
    queryFn: () => api.experiment(eid!),
    enabled: !!eid,
  })
  const record = useQuery({
    queryKey: ['record', eid],
    queryFn: () => api.record(eid!),
    enabled: !!eid,
  }) as { data: any | undefined; isLoading: boolean; isError: boolean }
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
        ID: <code>{d.id}</code> · agent · autonomy: {d.agent.autonomy}
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
        <>
          <p className="muted" style={{ fontSize: 12, margin: '2px 0' }}>
            objective: {d.objective} · constraints:{' '}
            {d.constraints.map((c) => `${c.name}: ${c.description}`).join(' · ') || '—'}
          </p>
          <p className="muted" style={{ fontSize: 12, margin: '2px 0' }}>
            budget: top-{d.spec.k} hypotheses/round · {d.spec.rounds} DMTA rounds ·
            autonomy: {d.spec.autonomy} · candidates:{' '}
            {d.spec.hypothesis_source === 'agent'
              ? 'agent-proposed candidates'
              : `${d.spec.n_candidates} named candidates`}
          </p>
        </>
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
      <PipelineCards cards={d.cards} />

      {record.data && <RecordOfThisRun record={record.data} />}
      {record.data?.evidence?.curves?.length > 0 && (
        <EvidenceCurves eid={d.id} curves={record.data.evidence.curves} />
      )}

      <TraceLog eid={d.id} active={running} />
    </main>
  )
}
