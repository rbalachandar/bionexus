import { useEffect, useState } from 'react'

export type Theme = 'light' | 'dark'

const read = (): Theme => {
  const q = new URLSearchParams(location.search).get('theme')
  if (q === 'dark' || q === 'light') return q
  const saved = localStorage.getItem('bn_theme') as Theme | null
  if (saved) return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(read)
  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem('bn_theme', theme)
  }, [theme])
  return { theme, toggle: () => setTheme((t) => (t === 'dark' ? 'light' : 'dark')) }
}
