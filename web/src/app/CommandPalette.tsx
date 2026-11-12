import { Command } from 'cmdk'
import * as D from '@radix-ui/react-dialog'
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FlaskConical, Moon, Search, Sun } from 'lucide-react'
import { useCampaigns } from '../api/hooks'
import { Kbd } from '../ui/Card'
import { NAV } from './nav'

export function CommandPalette({ onToggleTheme, dark }: { onToggleTheme: () => void; dark: boolean }) {
  const [open, setOpen] = useState(false)
  const nav = useNavigate()
  const campaigns = useCampaigns()

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); setOpen((o) => !o) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const go = (to: string) => { setOpen(false); nav(to) }
  const item = 'flex cursor-pointer items-center gap-2 rounded-md px-2.5 py-2 text-sm data-[selected=true]:bg-sunken'

  return (
    <>
      <button onClick={() => setOpen(true)}
        className="flex h-8 w-72 items-center gap-2 rounded-md border border-line-strong bg-surface px-2.5 text-left text-sm text-faint hover:bg-sunken">
        <Search size={14} /> <span className="flex-1">Search or jump to…</span> <Kbd>⌘K</Kbd>
      </button>
      <D.Root open={open} onOpenChange={setOpen}>
        <D.Portal>
          <D.Overlay className="fixed inset-0 z-40 bg-black/40" />
          <D.Content aria-label="Command palette"
            className="fixed left-1/2 top-[14%] z-50 w-[min(560px,92vw)] -translate-x-1/2 overflow-hidden rounded-xl border border-line-strong bg-surface shadow-2xl">
            <D.Title className="sr-only">Command palette</D.Title>
            <Command label="Command palette">
              <Command.Input autoFocus placeholder="Go to a screen, a campaign, or run an action…"
                className="h-12 w-full border-b border-line bg-transparent px-4 text-sm outline-none" />
              <Command.List className="max-h-[50vh] overflow-auto p-2">
                <Command.Empty className="px-3 py-6 text-center text-sm text-muted">Nothing matches.</Command.Empty>
                <Command.Group heading="Go to" className="text-[11px] uppercase tracking-wider text-faint [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
                  {NAV.map((n) => (
                    <Command.Item key={n.to} value={`go ${n.label}`} className={item} onSelect={() => go(n.to)}>
                      <n.icon size={15} className="text-muted" /> {n.label}
                    </Command.Item>
                  ))}
                </Command.Group>
                {!!campaigns.data?.length && (
                  <Command.Group heading="Campaigns" className="mt-1 text-[11px] uppercase tracking-wider text-faint [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
                    {campaigns.data.slice(0, 30).map((c) => (
                      <Command.Item key={c.id} value={`campaign ${c.title} ${c.id}`} className={item} onSelect={() => go(`/campaigns/${c.id}`)}>
                        <FlaskConical size={15} className="text-muted" />
                        <span className="truncate">{c.title}</span>
                        <span className="num ml-auto text-xs text-faint">{c.status}</span>
                      </Command.Item>
                    ))}
                  </Command.Group>
                )}
                <Command.Group heading="Actions" className="mt-1 text-[11px] uppercase tracking-wider text-faint [&_[cmdk-group-heading]]:px-2.5 [&_[cmdk-group-heading]]:py-1.5">
                  <Command.Item value="toggle theme dark light" className={item} onSelect={() => { onToggleTheme(); setOpen(false) }}>
                    {dark ? <Sun size={15} className="text-muted" /> : <Moon size={15} className="text-muted" />}
                    Switch to {dark ? 'light' : 'dark'} theme
                  </Command.Item>
                </Command.Group>
              </Command.List>
            </Command>
          </D.Content>
        </D.Portal>
      </D.Root>
    </>
  )
}
