import { Moon, Sun } from 'lucide-react'
import { useEffect, useState } from 'react'

/**
 * Lifted out of App.tsx when the landing and sign-in pages arrived: they render outside
 * the dashboard shell, and a theme control that only exists inside the sidebar would have
 * left the two public pages with no way to switch.
 */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme ?? 'dark')

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    try {
      localStorage.setItem('recourse.theme', theme)
    } catch {
      // A browser blocking site data should not stop the theme applying for this session.
    }
  }, [theme])

  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={() => setTheme(isDark ? 'light' : 'dark')}
      className={`pressable focus-ring flex items-center gap-2.5 rounded-[var(--radius-control)] text-[13px] text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)] ${
        compact ? 'p-2' : 'w-full px-2.5 py-2'
      }`}
      style={{ fontVariationSettings: "'wght' 510" }}
      aria-label="Toggle colour theme"
    >
      <span className="text-[var(--fg-3)]">
        {isDark ? (
          <Sun size={16} strokeWidth={1.6} aria-hidden="true" />
        ) : (
          <Moon size={16} strokeWidth={1.6} aria-hidden="true" />
        )}
      </span>
      {!compact && (isDark ? 'Light' : 'Dark')}
    </button>
  )
}

/**
 * The product mark. Bespoke on purpose: it is the product's identity rather than a UI
 * affordance, so it is not something to source from an icon set.
 */
export function Mark({ size = 32 }: { size?: number }) {
  return (
    <span
      className="grid shrink-0 place-items-center rounded-[9px]"
      style={{
        width: size,
        height: size,
        background:
          'linear-gradient(160deg, var(--fg) 0%, color-mix(in srgb, var(--fg) 78%, var(--accent)) 100%)',
        color: 'var(--bg)',
      }}
    >
      <svg viewBox="0 0 24 24" style={{ width: size * 0.56, height: size * 0.56 }} fill="none" aria-hidden="true">
        <path
          d="M12 3.2l6.8 2.9v5.2c0 4-2.8 7.4-6.8 8.7-4-1.3-6.8-4.7-6.8-8.7V6.1L12 3.2z"
          stroke="currentColor"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
        <path
          d="M9.2 12.1l2.1 2.1 4.1-4.3"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </span>
  )
}
