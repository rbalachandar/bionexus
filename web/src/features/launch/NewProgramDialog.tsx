import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useCreateProgram } from '../../api/hooks'
import { Button } from '../../ui/Button'
import { Dialog, DialogContent } from '../../ui/Dialog'
import { Field, Input, Select, Textarea } from '../../ui/Field'

const METRICS = [
  { v: 'ic50_um', l: 'IC50 (potency)', unit: 'µM', dir: 'min' as const },
  { v: 'percent_inhibition', l: '% inhibition at a fixed dose', unit: '%', dir: 'max' as const },
  { v: 'custom', l: 'Another metric…', unit: '', dir: 'max' as const },
]

/** A program is the goal: one metric, a direction and a gate every campaign is judged against. */
export function NewProgramDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const nav = useNavigate()
  const create = useCreateProgram()
  const [name, setName] = useState('')
  const [objective, setObjective] = useState('')
  const [modality, setModality] = useState('small molecule')
  const [metric, setMetric] = useState(METRICS[0])
  const [custom, setCustom] = useState('')
  const [direction, setDirection] = useState<'min' | 'max'>('min')
  const [gate, setGate] = useState(20)
  const [unit, setUnit] = useState('µM')
  const pick = (v: string) => { const m = METRICS.find((x) => x.v === v)!; setMetric(m); setDirection(m.dir); setUnit(m.unit) }
  const submit = () => create.mutate(
    { name, objective, modality, metric: metric.v === 'custom' ? custom : metric.v, direction, gate_value: gate, unit },
    { onSuccess: (p) => { onOpenChange(false); nav(`/programs/${p.slug}`) } })
  const ok = name.trim() && (metric.v !== 'custom' || custom.trim())
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent title="New program" description="The goal every campaign will be judged against, fixed before any data arrives.">
        <Field label="Name"><Input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="EGFR hit finding" /></Field>
        <Field label="Objective"><Textarea value={objective} onChange={(e) => setObjective(e.target.value)} placeholder="Find a small molecule that inhibits EGFR below 20 µM, confirmed by an orthogonal assay." /></Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="Modality"><Select value={modality} onChange={(e) => setModality(e.target.value)}>
            {['small molecule', 'biologic', 'cell therapy', 'mRNA', 'agrochemical', 'material'].map((m) => <option key={m}>{m}</option>)}</Select></Field>
          <Field label="Metric"><Select value={metric.v} onChange={(e) => pick(e.target.value)}>{METRICS.map((m) => <option key={m.v} value={m.v}>{m.l}</option>)}</Select></Field>
        </div>
        {metric.v === 'custom' && <Field label="Metric name"><Input value={custom} onChange={(e) => setCustom(e.target.value)} placeholder="tensile_strength_mpa" /></Field>}
        <div className="grid grid-cols-[1fr_110px_90px] gap-3">
          <Field label="Success means"><Select value={direction} onChange={(e) => setDirection(e.target.value as 'min' | 'max')}>
            <option value="min">at or below the gate (lower is better)</option><option value="max">at or above the gate (higher is better)</option></Select></Field>
          <Field label="Gate"><Input type="number" step="any" value={gate} onChange={(e) => setGate(Number(e.target.value))} /></Field>
          <Field label="Unit"><Input value={unit} onChange={(e) => setUnit(e.target.value)} /></Field>
        </div>
        {create.error && <p role="alert" className="mb-2 text-xs text-bad">{(create.error as Error).message}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" disabled={!ok || create.isPending} onClick={submit}>Create program</Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
