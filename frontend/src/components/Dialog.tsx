import { useCallback, useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'

/**
 * The shell every modal in the app shares.
 *
 * Rendered through a portal, deliberately. `position: fixed` resolves against the nearest
 * ancestor that establishes a containing block, and any ancestor carrying a transform does
 * so — including one whose animation merely *ends* at `transform: none`, because
 * fill-mode: both retains the computed identity matrix rather than the keyword. The case
 * page wraps its tab panel in `.rise`, which did exactly that and clipped a dialog to the
 * evidence column. Portalling to <body> makes a dialog independent of where it is mounted.
 */
export function Dialog({
  labelledBy,
  label,
  onClose,
  children,
  width = 'max-w-2xl',
}: {
  labelledBy?: string
  /** Fallback accessible name while a loading/error state has not rendered its title. */
  label?: string
  onClose: () => void
  children: React.ReactNode
  width?: string
}) {
  const panelRef = useRef<HTMLDivElement>(null)
  const onCloseRef = useRef(onClose)

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    const panel = panelRef.current
    const previousFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null

    const focusable = () =>
      panel
        ? Array.from(
            panel.querySelectorAll<HTMLElement>(
              'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
            ),
          ).filter(
            (element) =>
              element.getAttribute('aria-hidden') !== 'true' &&
              (element.offsetWidth > 0 || element.offsetHeight > 0 || element.getClientRects().length > 0),
          )
        : []

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.preventDefault()
        onCloseRef.current()
        return
      }
      if (e.key !== 'Tab' || !panel) return

      const controls = focusable()
      if (!controls.length) {
        e.preventDefault()
        panel.focus()
        return
      }

      const first = controls[0]
      const last = controls[controls.length - 1]
      const active = document.activeElement
      if (e.shiftKey && (active === panel || active === first || !panel.contains(active))) {
        e.preventDefault()
        last.focus()
      } else if (!e.shiftKey && (active === panel || active === last || !panel.contains(active))) {
        e.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    // Move focus into the dialog so keyboard users are not left behind on the page.
    // The panel itself is the fallback: a dialog that opens on a loading skeleton has no
    // control to focus yet, and without this focus stayed outside it entirely -- Escape
    // still worked, but Tab walked off into the page behind.
    ;(focusable()[0] ?? panel)?.focus()
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  }, [])

  const stop = useCallback((e: React.MouseEvent) => e.stopPropagation(), [])

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-8"
      style={{
        // Opaque enough that dense page content behind cannot compete with the dialog.
        background: 'color-mix(in srgb, var(--bg) 88%, transparent)',
        backdropFilter: 'saturate(140%) blur(6px)',
        WebkitBackdropFilter: 'saturate(140%) blur(6px)',
      }}
      onClick={onClose}
      role="presentation"
    >
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        aria-labelledby={labelledBy}
        aria-label={label}
        onClick={stop}
        className={`rise flex max-h-[86vh] w-full ${width} flex-col overflow-hidden rounded-[var(--radius-card)]`}
        style={{ background: 'var(--surface)', boxShadow: 'var(--shadow-pop)' }}
      >
        {children}
      </div>
    </div>,
    document.body,
  )
}

/** Title bar with a close control. Stays put while the body scrolls. */
export function DialogHeader({
  id,
  title,
  sub,
  onClose,
  aside,
}: {
  id: string
  title: string
  sub?: string
  onClose: () => void
  aside?: React.ReactNode
}) {
  return (
    <header
      className="flex shrink-0 items-start justify-between gap-4 border-b p-5"
      style={{ borderColor: 'var(--line)' }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h2 id={id} className="truncate text-[15px]" style={{ fontVariationSettings: "'wght' 590" }}>
            {title}
          </h2>
          {aside}
        </div>
        {sub && <p className="mt-1 text-[12px] text-[var(--fg-3)]">{sub}</p>}
      </div>
      <button
        type="button"
        onClick={onClose}
        aria-label="Close"
        className="focus-ring shrink-0 rounded-[var(--radius-inner)] px-2 py-1 text-[18px] leading-none text-[var(--fg-3)] transition hover:text-[var(--fg)]"
      >
        &times;
      </button>
    </header>
  )
}

/** The scrolling middle of a dialog. */
export function DialogBody({ children }: { children: React.ReactNode }) {
  return <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
}

/** Pinned foot, so actions stay reachable however long the body is. */
export function DialogFooter({ children }: { children: React.ReactNode }) {
  return (
    <footer
      className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t p-4"
      style={{ borderColor: 'var(--line)', background: 'var(--surface-2)' }}
    >
      {children}
    </footer>
  )
}
