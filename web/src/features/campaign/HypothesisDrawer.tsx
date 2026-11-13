import * as D from '@radix-ui/react-dialog'
import * as Tabs from '@radix-ui/react-tabs'
import { X } from 'lucide-react'
import { useCurves, useHypothesis } from '../../api/hooks'
import { StateChip, Tag, type State } from '../../ui/Chip'
import { Skeleton } from '../../ui/Card'
import { CurveCard } from './CurvePlot'
import { ReviewControls } from '../inbox/ReviewControls'
import { ago, explain, sig, suggestion, unitOf, type Detail, type Hyp } from './format'

const tab = 'border-b-2 border-transparent px-3 py-2 text-sm text-muted hover:text-ink data-[state=active]:border-accent data-[state=active]:font-medium data-[state=active]:text-ink'

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="mb-4"><div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-muted">{label}</div><div className="text-sm">{children}</div></div>
}

export function HypothesisDrawer({ campaign, hid, onClose }: { campaign: Detail; hid: string | null; onClose: () => void }) {
  const { data: h } = useHypothesis(campaign.id, hid)
  const curves = useCurves(campaign.id, hid)
  const unit = unitOf(campaign.gate.label) || 'µM'
  const summary: Hyp | undefined = h
  const tip = summary ? suggestion(summary, campaign.gate) : null
  return (
    <D.Root open={!!hid} onOpenChange={(o) => !o && onClose()}>
      <D.Portal>
        <D.Overlay className="fixed inset-0 z-40 bg-black/30" />
        <D.Content aria-describedby={undefined} className="fixed right-0 top-0 z-50 flex h-full w-[min(600px,96vw)] flex-col border-l border-line-strong bg-surface shadow-2xl">
          <div className="flex items-start gap-3 border-b border-line px-5 py-4">
            <div className="min-w-0 flex-1">
              <D.Title className="num truncate text-lg font-semibold">{h?.head ?? '…'}</D.Title>
              <div className="mt-1 flex flex-wrap items-center gap-2">
                {h && <StateChip state={h.state as State} />}
                {h?.round && <Tag>round {h.round}</Tag>}
                {h?.gate_label && <span className="num text-xs text-muted">{h.gate_label}</span>}
              </div>
            </div>
            <D.Close aria-label="Close" className="rounded p-1 text-faint hover:bg-sunken hover:text-ink"><X size={18} /></D.Close>
          </div>
          {!h ? <div className="space-y-3 p-5"><Skeleton className="h-6" /><Skeleton className="h-24" /></div> : (
            <Tabs.Root defaultValue="overview" className="flex min-h-0 flex-1 flex-col">
              <Tabs.List className="flex gap-1 border-b border-line px-3">
                <Tabs.Trigger value="overview" className={tab}>Overview</Tabs.Trigger>
                <Tabs.Trigger value="evidence" className={tab}>Evidence</Tabs.Trigger>
                <Tabs.Trigger value="timeline" className={tab}>Timeline</Tabs.Trigger>
              </Tabs.List>
              <div className="min-h-0 flex-1 overflow-auto p-5">
                <Tabs.Content value="overview">
                  <Field label="Hypothesis">{h.statement}</Field>
                  {h.verdict && (
                    <div className="mb-4 rounded-lg border border-line bg-sunken p-3">
                      <div className="num text-xl font-semibold">{sig(h.verdict.observed)} <span className="text-sm font-normal text-muted">{unit}</span>
                        {h.verdict.ci && <span className="ml-2 text-sm font-normal text-muted">95% CI [{sig(h.verdict.ci[0])} – {sig(h.verdict.ci[1])}]</span>}</div>
                      <p className="mt-1.5 text-[13px]">{explain(h, campaign.gate)}</p>
                      {h.verdict.margin && h.verdict.status !== 'abstained' && <p className="mt-1 text-xs text-muted">{h.verdict.margin}</p>}
                      {tip && <p className="mt-2 rounded bg-abstain-soft px-2.5 py-1.5 text-[13px] text-abstain"><b>Next step:</b> {tip}</p>}
                    </div>
                  )}
                  {h.state === 'abstained' && (
                    <div className="mb-4 rounded-lg border border-abstain/30 p-3">
                      <div className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-abstain">Your decision</div>
                      <ReviewControls campaignId={campaign.id} hid={h.id} candidate={h.head} review={h.review} />
                    </div>
                  )}
                  {h.refutation_condition && (
                    <Field label="Pre-registered: this is refuted if…"><span className="rounded bg-bad-soft px-1.5 py-0.5 text-bad">{h.refutation_condition}</span></Field>
                  )}
                  {h.predicted && <Field label="Predicted before the experiment">{h.predicted}
                    {h.predicted_by && typeof h.predicted_by === 'object' && 'model' in h.predicted_by && <span className="text-xs text-muted"> · by {String(h.predicted_by.model)}</span>}
                    {h.predicted_by && 'note' in h.predicted_by && <p className="mt-1 text-xs text-abstain">{String(h.predicted_by.note)}</p>}</Field>}
                  {h.mechanism && <Field label="Mechanism">{h.mechanism}</Field>}
                  {h.rationale && <Field label="Rationale">{h.rationale}</Field>}
                  {h.citation && <Field label="Citation">{h.citation}{h.citation_status && <Tag className="ml-2" tone={h.citation_status === 'verified' ? 'ok' : 'warn'}>{h.citation_status}</Tag>}</Field>}
                  {h.derivation && <Field label="How the verdict was derived"><span className="text-muted">{h.derivation}</span></Field>}
                </Tabs.Content>
                <Tabs.Content value="evidence" className="space-y-4">
                  {curves.isLoading && <Skeleton className="h-56" />}
                  {curves.data?.curves.map((c) => <CurveCard key={c.run_id} c={c} gate={campaign.gate.threshold} unit={unit} />)}
                  {curves.data && !curves.data.curves.length && <p className="py-8 text-center text-sm text-faint">{curves.data.note ?? 'No recorded plate for this candidate.'}</p>}
                  {curves.data?.curves.length ? <p className="text-xs text-faint">A confirmed verdict is judged on the latest measurement. Evidence is re-read from the recorded plate files, not simulated.</p> : null}
                </Tabs.Content>
                <Tabs.Content value="timeline">
                  <ol className="space-y-2">
                    {h.events.map((e, i) => (
                      <li key={i} className="flex gap-3 text-[13px]"><time className="num w-20 shrink-0 text-[11px] text-faint">{ago(e.ts)}</time><span>{e.text}</span></li>
                    ))}
                  </ol>
                </Tabs.Content>
              </div>
            </Tabs.Root>
          )}
        </D.Content>
      </D.Portal>
    </D.Root>
  )
}
