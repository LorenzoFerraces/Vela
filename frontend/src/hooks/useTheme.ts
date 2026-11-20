import { useCallback, useEffect, useState } from 'react'

export type Theme = 'dark' | 'light'

const STORAGE_KEY = 'vela.theme'
// ponytail: hex literals only here and in index.html — meta theme-color cannot consume a CSS variable.
const THEME_COLORS: Record<Theme, string> = { dark: '#120e1e', light: '#f4f1f8' }

function getInitialTheme(): Theme {
  const fallback = window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY)
    if (stored === 'dark' || stored === 'light') return stored
  } catch {
    // storage unavailable
  }
  return fallback
}

export function useTheme(): { theme: Theme; toggle: () => void } {
  const [theme, setTheme] = useState<Theme>(getInitialTheme)

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', THEME_COLORS[theme])
    try {
      window.localStorage.setItem(STORAGE_KEY, theme)
    } catch {
      // private-mode/quota failures must not break theme switching; the read path is already guarded.
    }
  }, [theme])

  const toggle = useCallback(
    () => setTheme((current) => (current === 'dark' ? 'light' : 'dark')),
    [],
  )

  return { theme, toggle }
}
