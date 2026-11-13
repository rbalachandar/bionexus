import { AlertTriangle, FlaskConical, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { usePreviewResults, useSubmitResults } from '../../api/hooks'
import type { Schemas } from '../../api/v1'
import { useToast } from '../../app/toast'
import { Button } from '../../ui/Button'
import { Dialog, DialogContent } from '../../ui/Dialog'
import { Tag } from '../../ui/Chip'
import { Field, Select } from '../../ui/Field'

/** A person submits a measured plate. It is judged by this campaign's
 *  pre-registered criteria — the same code a live run uses — and only for
 *  hypotheses that are still open. */
export function SubmitResultsDialog({ id, open, onOpenChange }: { id: string; open: boolean; onOpenChange: (o: boolean) => void }) {
  const [file, setFile] = useState<File>()
  const [origin, setOrigin] = useState<'measured' | 'historical'>('measured')
  const [done, setDone] = useState<Schemas['ResultsOutcome']>()
  const ref = useRef<HTMLInputElement>(null)
  const prev = usePreviewResults(id)
  const submit = useSubmitResults(id)
  const toast = useToast()
  const { mutate: preview, reset } = prev

  useEffect(() => { if (file) preview({ file, origin }) }, [file, origin, preview])
  useEffect(() => { if (!open) { setFile(undefined); setDone(undefined); reset() } }, [open, reset])

  const p = prev.data
  const blocked = !p || !!p.failure || p.already_submitted || p.matches.length === 0
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="Submit measured results" className="!w-[min(640px,94vw)] !top-[8%]"
        description="Export the plate as CSV. It is judged against the gate this campaign registered before it ran, for hypotheses that are still open.">
        {done ? (
          <div>
            <p className="mb-2 text-sm font-medium">Judged {done.verdicts.length} hypothes{done.verdicts.length === 1 ? 'is' : 'es'}. Recorded under your name.</p>
            <ul className="divide-y divide-line rounded-md border border-line">
              {done.verdicts.map((v) => (
                <li key={v.hypothesis_id} className="flex items-center gap-3 px-3 py-2 text-sm">
                  <b className="num">{v.candidate}</b><Tag tone={v.status === 'validated' ? 'ok' : v.status === 'inconclusive' ? 'warn' : 'bad'}>{v.status === 'inconclusive' ? 'abstained' : v.status}</Tag>
                  {v.observed != null && <span className="num ml-auto text-xs text-muted">{Number(v.observed.toPrecision(3))} µM</span>}
                </li>
              ))}
            </ul>
            {done.failure && <p className="mt-2 text-xs text-warn">{done.failure}</p>}
            <div className="mt-4 flex justify-end"><Button variant="primary" onClick={() => onOpenChange(false)}>Done</Button></div>
          </div>
        ) : (<>
          <div className="flex items-center gap-3">
            <Button onClick={() => ref.current?.click()}><Upload size={14} />{file ? 'Choose another file' : 'Choose CSV'}</Button>
            <span className="min-w-0 truncate text-sm text-muted">{file?.name ?? 'no file chosen'}</span>
            <input ref={ref} type="file" hidden accept=".csv" onChange={(e) => setFile(e.target.files?.[0])} />
          </div>
          {file && prev.isPending && <p className="mt-3 text-sm text-muted">Reading…</p>}
          {prev.error && <p className="mt-3 rounded-md bg-bad-soft px-3 py-2 text-sm text-bad">{prev.error.message}</p>}
          {p && (
            <div className="mt-4 space-y-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                <Tag>{p.n_wells} wells</Tag>
                <Tag tone={p.qc_ok ? 'ok' : 'warn'}>Z′ {p.z_prime != null ? p.z_prime.toFixed(2) : 'n/a'}{p.z_kind === 'heuristic' ? ' (heuristic)' : ''}</Tag>
                {!p.qc_ok && <span className="text-xs text-warn">below the QC floor: verdicts are recorded with QC failed</span>}
              </div>
              {p.failure && <p className="flex items-start gap-2 rounded-md bg-bad-soft px-3 py-2 text-bad"><AlertTriangle size={14} className="mt-0.5 shrink-0" />Physical failure: {p.failure}. No verdicts will be derived — re-run the plate.</p>}
              {p.already_submitted && <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">This exact file was already submitted to this campaign.</p>}
              <div>
                <div className="mb-1 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted"><FlaskConical size={12} />Will be judged ({p.matches.length})</div>
                {p.matches.length ? (
                  <ul className="divide-y divide-line rounded-md border border-line">
                    {p.matches.map((m) => <li key={m.hypothesis_id} className="flex items-center gap-3 px-3 py-1.5"><b className="num">{m.candidate}</b><span className="min-w-0 flex-1 truncate text-xs text-muted">{m.statement}</span><span className="num text-xs">{m.gate}</span></li>)}
                  </ul>
                ) : <p className="rounded-md bg-warn-soft px-3 py-2 text-warn">No open hypothesis in this campaign matches a sample in the file.</p>}
              </div>
              {!!p.already_judged.length && <p className="text-xs text-muted">Already have a verdict and will be left alone: <span className="num">{p.already_judged.join(', ')}</span></p>}
              {!!p.in_file_only.length && <p className="text-xs text-muted">In the file but not part of this campaign (ignored): <span className="num">{p.in_file_only.join(', ')}</span></p>}
              {!!p.waiting_for_data.length && <p className="text-xs text-muted">Still waiting for data: <span className="num">{p.waiting_for_data.join(', ')}</span></p>}
            </div>
          )}
          <div className="mt-5 flex items-end gap-3">
            <div className="w-56"><Field label="This data is"><Select value={origin} onChange={(e) => setOrigin(e.target.value as typeof origin)}>
              <option value="measured">measured on an instrument</option><option value="historical">historical (prior run / paper)</option></Select></Field></div>
            <div className="mb-3 ml-auto flex gap-2">
              <Button onClick={() => onOpenChange(false)}>Cancel</Button>
              <Button variant="primary" disabled={blocked || submit.isPending}
                onClick={() => file && submit.mutate({ file, origin }, { onSuccess: (o) => { setDone(o); toast({ tone: 'ok', text: 'Results recorded and judged.' }) }, onError: (e) => toast({ tone: 'bad', text: e.message }) })}>
                {submit.isPending ? 'Judging…' : 'Submit and judge'}</Button>
            </div>
          </div>
        </>)}
      </DialogContent>
    </Dialog>
  )
}
