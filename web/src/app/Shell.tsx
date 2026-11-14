import { NavLink, Outlet } from 'react-router-dom'
import { Moon, ShieldAlert, ShieldCheck, Sun, ShieldX } from 'lucide-react'
import { useSystemStatus } from '../api/hooks'
import { Tag } from '../ui/Chip'
import { Tip } from '../ui/Tooltip'
import { cn } from '../ui/cn'
import { Button } from '../ui/Button'
import { CommandPalette } from './CommandPalette'
import { HaltControl } from './HaltDialog'
import { NAV } from './nav'
import { useTheme } from './theme'

const ago = (s: number | null | undefined) => {
  if (s == null) return null
  const m = Math.floor(s / 60)
  if (m < 1) return 'just now'
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  return h < 48 ? `${h} h ago` : `${Math.floor(h / 24)} d ago`
}

function Rail() {
  const { data } = useSystemStatus()
  return (
    <aside className="flex w-14 shrink-0 flex-col border-r border-line bg-surface lg:w-52">
      <div className="flex h-12 items-center gap-2 border-b border-line px-3.5">
        <img src="/proef-mark.png" alt="" width={22} height={22} />
        <span className="hidden text-[15px] font-semibold tracking-tight lg:inline">proef<span aria-hidden className="text-[#ff8a1f]">.</span></span>
      </div>
      <nav className="flex flex-col gap-0.5 p-2" aria-label="Sections">
        {NAV.map(({ to, label, icon: Icon, ...rest }) => (
          <NavLink key={to} to={to} end={'end' in rest}
            className={({ isActive }) => cn(
              'flex h-9 items-center gap-2.5 rounded-md px-2.5 text-sm text-muted hover:bg-sunken hover:text-ink',
              isActive && 'bg-accent-soft font-medium text-accent hover:bg-accent-soft hover:text-accent')}>
            <Icon size={16} aria-hidden />
            <span className="hidden lg:inline">{label}</span>
            {label === 'Inbox' && !!data?.pending_approvals && (
              <span className="num ml-auto hidden rounded-full bg-warn-soft px-1.5 text-[11px] font-semibold text-warn lg:inline">
                {data.pending_approvals}
              </span>
            )}
          </NavLink>
        ))}
      </nav>
    </aside>
  )
}

function TrustStrip() {
  const { data } = useSystemStatus()
  if (!data) return <footer className="h-8 border-t border-line bg-surface" />
  const { chain, anchor, eval: ev } = data
  return (
    <footer className="flex h-8 shrink-0 items-center gap-4 border-t border-line bg-surface px-4 text-xs text-muted">
      <Tip label={chain.verified
        ? 'Every record was re-hashed and its link to the previous record checked just now.'
        : `${chain.problems.length} record(s) fail verification — the ledger was altered.`}>
        <span className={cn('flex items-center gap-1.5', !chain.verified && 'font-medium text-bad')}>
          {chain.verified ? <ShieldCheck size={13} className="text-ok" /> : <ShieldX size={13} />}
          {chain.verified ? 'Chain verified' : 'Chain integrity failed'}
          <span className="num text-faint">· {chain.records.toLocaleString()} records</span>
        </span>
      </Tip>
      <Tip label={anchor ? 'Merkle root of the ledger. An anchor protects you only once it is published somewhere you do not control.'
        : 'No anchor yet — run `proef anchor` and publish the root to make the record externally checkable.'}>
        <span className="flex items-center gap-1.5">
          {anchor ? <>Anchored <span className="num">{ago(anchor.age_s)}</span>{anchor.published === false && <Tag tone="warn">unpublished</Tag>}</>
            : <Tag tone="warn">not anchored</Tag>}
        </span>
      </Tip>
      {ev && (
        <Tip label="Deterministic eval suite (proef eval). Scores below 1.0 are honest deductions, not hidden.">
          <span>Graded <span className="num">{ev.mean.toFixed(3)}</span> · <span className="num">{ev.tasks}</span> tasks{ev.all_pass ? '' : ' · failing'}</span>
        </Tip>
      )}
    </footer>
  )
}

export default function Shell() {
  const { theme, toggle } = useTheme()
  const { data } = useSystemStatus()
  return (
    <div className="flex h-full bg-canvas text-ink">
      <Rail />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line bg-surface px-4">
          <CommandPalette dark={theme === 'dark'} onToggleTheme={toggle} />
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={toggle} aria-label="Toggle theme">
              {theme === 'dark' ? <Sun size={16} /> : <Moon size={16} />}
            </Button>
            <HaltControl />
          </div>
        </header>
        {data?.halted && (
          <div role="alert" className="flex items-center gap-2 bg-bad-soft px-4 py-2 text-sm font-medium text-bad">
            <ShieldAlert size={16} /> All agents are halted{data.halt_reason ? ` — ${data.halt_reason}` : ''}. Nothing new will be submitted to the lab until a human resumes.
          </div>
        )}
        <main className="min-h-0 flex-1 overflow-auto"><Outlet /></main>
        <TrustStrip />
      </div>
    </div>
  )
}
