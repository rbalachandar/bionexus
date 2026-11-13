import { cn } from './cn'

const base = 'w-full rounded-md border border-line-strong bg-canvas px-3 text-sm placeholder:text-faint focus-visible:outline-accent'

export const Input = ({ className, ...p }: React.InputHTMLAttributes<HTMLInputElement>) =>
  <input className={cn(base, 'h-9', className)} {...p} />

export const Textarea = ({ className, ...p }: React.TextareaHTMLAttributes<HTMLTextAreaElement>) =>
  <textarea className={cn(base, 'min-h-[84px] py-2', className)} {...p} />

export const Select = ({ className, ...p }: React.SelectHTMLAttributes<HTMLSelectElement>) =>
  <select className={cn(base, 'h-9', className)} {...p} />

export function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-xs font-medium text-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-faint">{hint}</span>}
    </label>
  )
}
