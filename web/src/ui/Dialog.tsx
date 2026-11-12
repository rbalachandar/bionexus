import * as D from '@radix-ui/react-dialog'
import { X } from 'lucide-react'
import { cn } from './cn'

export const Dialog = D.Root
export const DialogTrigger = D.Trigger
export const DialogClose = D.Close

export function DialogContent({ title, description, children, className }: {
  title: string; description?: string; children: React.ReactNode; className?: string
}) {
  return (
    <D.Portal>
      <D.Overlay className="fixed inset-0 z-40 bg-black/40 backdrop-blur-[1px]" />
      <D.Content className={cn(
        'fixed left-1/2 top-[18%] z-50 w-[min(520px,92vw)] -translate-x-1/2 rounded-xl border ' +
          'border-line-strong bg-surface p-5 shadow-2xl', className)}>
        <D.Title className="text-base font-semibold">{title}</D.Title>
        {description && <D.Description className="mt-1 text-sm text-muted">{description}</D.Description>}
        <div className="mt-4">{children}</div>
        <D.Close aria-label="Close" className="absolute right-3 top-3 rounded p-1 text-faint hover:bg-sunken hover:text-ink">
          <X size={16} />
        </D.Close>
      </D.Content>
    </D.Portal>
  )
}
