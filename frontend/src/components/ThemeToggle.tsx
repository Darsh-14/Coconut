import { Moon, Sun } from 'lucide-react'
import { useSyncExternalStore } from 'react'

type Theme = 'dark' | 'light'

const STORAGE_KEY = 'coconut.theme'
const THEME_EVENT = 'coconut:theme-change'

function currentTheme(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark'
}

/**
 * Both the desktop sidebar and the mobile bar stay mounted across the `lg` breakpoint.
 * A component-local useState therefore let the hidden toggle go stale: switch themes,
 * resize, and the newly visible button described the old theme. This tiny external store
 * makes the document's actual theme the single source of truth and also follows changes
 * made in another tab.
 */
function subscribeTheme(onChange: () => void) {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY) return
    document.documentElement.dataset.theme = event.newValue === 'light' ? 'light' : 'dark'
    onChange()
  }
  window.addEventListener(THEME_EVENT, onChange)
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(THEME_EVENT, onChange)
    window.removeEventListener('storage', onStorage)
  }
}

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme
  try {
    localStorage.setItem(STORAGE_KEY, theme)
  } catch {
    // A browser blocking site data should not stop the theme applying for this session.
  }
  window.dispatchEvent(new Event(THEME_EVENT))
}

/**
 * Lifted out of App.tsx when the landing and sign-in pages arrived: they render outside
 * the dashboard shell, and a theme control that only exists inside the sidebar would have
 * left the two public pages with no way to switch.
 */
export function ThemeToggle({ compact = false }: { compact?: boolean }) {
  const theme = useSyncExternalStore(subscribeTheme, currentTheme, () => 'dark')
  const isDark = theme === 'dark'
  return (
    <button
      type="button"
      onClick={() => applyTheme(isDark ? 'light' : 'dark')}
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
      className="grid shrink-0 place-items-center"
      style={{
        width: size,
        height: size,
      }}
    >
      <svg
        viewBox="0 0 64 64"
        style={{ width: size * 0.94, height: size * 0.94 }}
        fill="none"
        aria-hidden="true"
      >
        <defs>
          <clipPath id="coconut-cutout">
            <path d="M14 33C14 20 22 10 33 10c11 0 18 9 18 22 0 12-8 21-19 21-11 0-18-8-18-20Z" />
          </clipPath>
        </defs>
        <path d="M25 17C28 10 35 7 43 8c-2 6-7 11-14 12" fill="#111" />
        <path d="M14 33C14 20 22 10 33 10c11 0 18 9 18 22 0 12-8 21-19 21-11 0-18-8-18-20Z" fill="#111" />
        <g clipPath="url(#coconut-cutout)">
          <path d="M18 14h37v42H18z" fill="#000" opacity="0.15" />
          <path d="M22 12c-2 14-1 29 5 43M31 10c-1 17 1 32 6 45M41 11c-1 17 2 30 7 41" stroke="#fff" strokeWidth="1.5" opacity="0.3" />
          <path d="M15 35c7 4 15 5 23 3 6-1 11-4 16-8v21H15Z" fill="#000" opacity="0.45" />
        </g>
        <path d="M24 29c1-7 5-11 10-11 6 0 10 5 10 12 0 7-4 12-10 12-6 0-11-5-10-13Z" fill="#fff" />
      </svg>
    </span>
  )
}
