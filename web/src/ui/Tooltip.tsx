import * as T from '@radix-ui/react-tooltip'

export function Tip({ label, children }: { label: React.ReactNode; children: React.ReactNode }) {
  return (
    <T.Provider delayDuration={250}>
      <T.Root>
        <T.Trigger asChild>{children}</T.Trigger>
        <T.Portal>
          <T.Content sideOffset={6}
            className="z-50 max-w-xs rounded-md bg-ink px-2.5 py-1.5 text-xs text-canvas shadow-lg">
            {label}
          </T.Content>
        </T.Portal>
      </T.Root>
    </T.Provider>
  )
}
