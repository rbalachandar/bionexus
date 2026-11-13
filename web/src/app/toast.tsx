import { createContext, useCallback, useContext, useState } from 'react'
import { CheckCircle2, X, XCircle } from 'lucide-react'

type Toast = { id: number; text: string; tone: 'ok' | 'bad'; link?: { to: string; label: string } }
const Ctx = createContext<(t: Omit<Toast, 'id'>) => void>(() => {})
export const useToast = () => useContext(Ctx)

/** Every decision gets visible confirmation — nothing a scientist does should vanish silently. */
export function ToastProvider({ children, onNavigate }: { children: React.ReactNode; onNavigate: (to: string) => void }) {
  const [items, setItems] = useState<Toast[]>([])
  const push = useCallback((t: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.random()
    setItems((x) => [...x.slice(-3), { ...t, id }])
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), 7000)
  }, [])
  return (
    <Ctx.Provider value={push}>
      {children}
      <div role="status" aria-live="polite" className="pointer-events-none fixed bottom-12 right-5 z-[60] flex w-[min(380px,92vw)] flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} className="pointer-events-auto flex items-start gap-2.5 rounded-lg border border-line-strong bg-surface px-3.5 py-3 text-sm shadow-lg">
            {t.tone === 'ok' ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-ok" /> : <XCircle size={16} className="mt-0.5 shrink-0 text-bad" />}
            <div className="min-w-0 flex-1">{t.text}
              {t.link && <button className="ml-2 font-medium text-accent hover:underline" onClick={() => onNavigate(t.link!.to)}>{t.link.label}</button>}
            </div>
            <button aria-label="Dismiss" className="text-faint hover:text-ink" onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))}><X size={14} /></button>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  )
}
