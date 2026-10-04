import { useQuery } from '@tanstack/react-query'
import { FlaskConical, ShieldCheck, Gauge } from 'lucide-react'

interface EvalTask {
  task: string
  suite: string
  score: number
  passed: boolean
  skipped: boolean
  honest_deduction: boolean
  notes: string
  duration_s?: number | null
}
interface EvalsPayload {
  available: boolean
  reason?: string
  run_line?: string
  mean?: number | null
  all_pass?: boolean | null
  pass_bar?: number
  n_tasks?: number
  honest_deductions?: string[]
  failing?: string[]
  tasks: EvalTask[]
}

function ScoreBar({ t }: { t: EvalTask }) {
  const color = t.skipped ? 'var(--muted)' : t.passed
    ? (t.honest_deduction ? 'var(--warn)' : 'var(--ok)') : 'var(--bad)'
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8,
      minWidth: 120 }}>
      <div className="mono" style={{ fontSize: 12, width: 42,
        color, fontWeight: 600 }}>
        {t.skipped ? '—' : t.score.toFixed(3)}
      </div>
      <div style={{ flex: 1, height: 5, borderRadius: 3,
        background: 'rgba(0,0,0,0.08)', overflow: 'hidden' }}>
        <div style={{ width: `${Math.round(t.score * 100)}%`, height: '100%',
          background: color }} />
      </div>
    </div>
  )
}

export default function Evals() {
  const q = useQuery({ queryKey: ['evals'],
    queryFn: () => fetch('/api/evals').then((r) => r.json()) })
  const p: EvalsPayload | undefined = q.data

  if (q.isLoading) return <p className="muted">loading eval leaderboard…</p>
  if (!p || !p.available) {
    return (
      <main>
        <h1 style={{ fontSize: 'var(--fs-xl)', margin: '0 0 6px' }}>
          Evals</h1>
        <div className="card" style={{ padding: 24, textAlign: 'center' }}>
          <p className="muted">{p?.reason ?? 'no eval data'}</p>
          <p className="mono" style={{ fontSize: 12 }}>bn eval</p>
        </div>
      </main>
    )
  }

  const mean = p.mean ?? 0
  return (
    <main>
      <div style={{ display: 'flex', justifyContent: 'space-between',
        alignItems: 'flex-start', gap: 16, marginBottom: 6 }}>
        <div>
          <h1 style={{ fontSize: 'var(--fs-xl)', margin: 0, fontWeight: 650,
            display: 'flex', alignItems: 'center', gap: 10 }}>
            <Gauge size={22} color="var(--brand)" /> Evals — the product pitch
          </h1>
          <p className="muted" style={{ margin: '6px 0 0', fontSize: 13 }}>
            “Agentic science” is a measurable claim or it is marketing.
            <strong> Every task runs a real campaign and is scored against
            seeded ground truth — offline, deterministic, in CI.</strong>
          </p>
        </div>
        <div className="card" style={{ textAlign: 'center', minWidth: 150,
          padding: '14px 20px' }}>
          <div className="mono" style={{ fontSize: 30, fontWeight: 700,
            color: p.all_pass ? 'var(--ok)' : 'var(--bad)' }}>
            {mean.toFixed(3)}
          </div>
          <div className="muted" style={{ fontSize: 11, textTransform:
            'uppercase', letterSpacing: '0.1em' }}>mean epistemics</div>
          <div className="mono" style={{ fontSize: 12, marginTop: 4,
            color: p.all_pass ? 'var(--ok)' : 'var(--bad)' }}>
            {p.all_pass ? '✅ all pass' : '❌ FAILING'} · bar {p.pass_bar}
          </div>
        </div>
      </div>

      {/* the honesty is the differentiator — lead with the deductions */}
      <div className="card" style={{ margin: '12px 0 16px',
        borderColor: 'var(--warn)', display: 'flex', gap: 12,
        alignItems: 'flex-start' }}>
        <ShieldCheck size={18} color="var(--warn)"
          style={{ marginTop: 2, flex: 'none' }} />
        <div>
          <strong style={{ fontSize: 13 }}>
            No competitor ships a harness that punishes its own overclaims.
          </strong>
          <p className="muted" style={{ margin: '4px 0 0', fontSize: 12 }}>
            {(p.honest_deductions ?? []).length} passing tasks deliberately
            score <strong>below</strong> 1.0 because honest abstentions are
            credited at 0.5, not 1.0 — the system is graded down for the
            confidence it refused to claim.
            {(p.honest_deductions ?? []).length > 0 && (
              <> {' '}(<span className="mono">
                {p.honest_deductions!.join(' · ')}</span>)</>
            )}
            {(p.failing ?? []).length > 0 && (
              <> · failing: <span className="mono">
                {p.failing!.join(', ')}</span></>
            )}
          </p>
        </div>
      </div>

      <table className="data-table" style={{ width: '100%', fontSize: 12 }}>
        <thead>
          <tr className="muted" style={{ textAlign: 'left' }}>
            <th>task</th><th>suite</th><th>score</th><th></th><th>notes</th>
          </tr>
        </thead>
        <tbody>
          {(p.tasks ?? []).map((t) => (
            <tr key={t.task} style={{ borderTop: '1px solid var(--border)' }}>
              <td className="mono" style={{ fontWeight: 600 }}>
                <span style={{ display: 'inline-flex', alignItems: 'center',
                  gap: 6 }}>
                  <FlaskConical size={13}
                    color={t.skipped ? 'var(--muted)' : t.passed
                      ? (t.honest_deduction ? 'var(--warn)' : 'var(--ok)')
                        : 'var(--bad)'} />
                  {t.task}
                </span>
              </td>
              <td className="muted">{t.suite}</td>
              <td><ScoreBar t={t} /></td>
              <td className="mono" style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                {t.skipped ? '⏭ skip'
                  : (t.passed ? (t.honest_deduction ? 'honest ↓' : '✅') : '❌')}
                {t.duration_s != null ? ` · ${t.duration_s}s` : ''}
              </td>
              <td className="muted" style={{ maxWidth: 420 }}>{t.notes}</td>
            </tr>
          ))}
        </tbody>
      </table>

      <p className="muted mono" style={{ fontSize: 11, marginTop: 12 }}>
        {p.run_line ?? 'leaderboard regenerated on every `bn eval` run'} ·
        {' '}CI fails if any score drops below the pass bar
      </p>
    </main>
  )
}
