/**
 * The primitive layer. Everything visual in the app is built from these, so tone,
 * radius and density stay consistent without each page re-deciding them.
 */

type Tone = 'win' | 'warn' | 'risk' | 'accent' | 'mute'

const TONE_SOFT: Record<Tone, string> = {
  win: 'tone-win',
  warn: 'tone-warn',
  risk: 'tone-risk',
  accent: 'tone-accent',
  mute: '',
}

const TONE_DOT: Record<Tone, string> = {
  win: 'bg-[var(--win)]',
  warn: 'bg-[var(--warn)]',
  risk: 'bg-[var(--risk)]',
  accent: 'bg-[var(--accent)]',
  mute: 'bg-[var(--fg-3)]',
}

export const toneDot = (tone: Tone) => TONE_DOT[tone]

/** Small status chip. `mute` renders as plain neutral text — colour means state only. */
export function Badge({
  tone = 'mute',
  dot = false,
  children,
  title,
  className = '',
}: {
  tone?: Tone
  dot?: boolean
  children: React.ReactNode
  title?: string
  className?: string
}) {
  const muted = tone === 'mute'
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1.5 rounded-md px-1.5 py-0.5 text-[11.5px] font-medium ${
        muted ? 'text-[var(--fg-2)]' : TONE_SOFT[tone]
      } ${muted ? 'bg-[var(--surface-2)]' : ''} ${className}`}
      style={{ fontVariationSettings: "'wght' 510" }}
    >
      {dot && <span className={`size-1.5 rounded-full ${TONE_DOT[tone]}`} />}
      {children}
    </span>
  )
}

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: 'primary' | 'secondary' | 'ghost'
  size?: 'sm' | 'md'
}

const VARIANTS = {
  primary:
    'bg-[var(--fg)] text-[var(--bg)] hover:opacity-90 disabled:opacity-40 shadow-[var(--shadow-line)]',
  secondary:
    'bg-[var(--surface)] text-[var(--fg)] shadow-[var(--shadow-line)] hover:bg-[var(--surface-2)] disabled:opacity-40',
  ghost: 'text-[var(--fg-2)] hover:bg-[var(--surface-2)] hover:text-[var(--fg)] disabled:opacity-40',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  className = '',
  ...props
}: ButtonProps) {
  return (
    <button
      {...props}
      className={`inline-flex items-center justify-center gap-1.5 rounded-[var(--radius-control)] font-medium transition duration-[160ms] ease-[var(--ease-out)] focus-visible:focus-ring disabled:cursor-not-allowed ${
        size === 'sm' ? 'px-2.5 py-1.5 text-xs' : 'px-3 py-2 text-[13px]'
      } ${VARIANTS[variant]} ${className}`}
      style={{ fontVariationSettings: "'wght' 510" }}
    />
  )
}

export function Surface({
  className = '',
  children,
}: {
  className?: string
  children: React.ReactNode
}) {
  return <div className={`surface ${className}`}>{children}</div>
}

/** A labelled figure. The one number someone came for, plus its unit. */
export function Metric({
  label,
  value,
  sub,
  tone,
  loading,
}: {
  label: string
  value: string
  sub?: string
  tone?: Tone
  loading?: boolean
}) {
  return (
    <Surface className="p-4">
      <p className="text-[11px] uppercase tracking-[0.06em] text-[var(--fg-3)]">{label}</p>
      {loading ? (
        <div className="skeleton mt-2 h-7 w-24" />
      ) : (
        <p
          className={`num mt-1.5 text-[27px] leading-none tracking-[-0.02em] ${
            tone && tone !== 'mute' ? `text-[var(--${tone})]` : 'text-[var(--fg)]'
          }`}
          style={{ fontVariationSettings: "'wght' 560" }}
        >
          {value}
        </p>
      )}
      {sub && <p className="mt-1.5 text-[11.5px] text-[var(--fg-3)]">{sub}</p>}
    </Surface>
  )
}

/** A determinate or indeterminate progress line. */
export function Progress({ value }: { value?: number }) {
  return (
    <div className="h-[3px] w-full overflow-hidden rounded-full bg-[var(--surface-3)]">
      {value == null ? (
        <div className="breathe h-full w-1/3 rounded-full bg-[var(--accent)]" />
      ) : (
        <div
          className="h-full rounded-full bg-[var(--fg)] transition-[width] duration-300 ease-[var(--ease-out)]"
          style={{ width: `${Math.min(100, Math.max(0, value * 100))}%` }}
        />
      )}
    </div>
  )
}

/** Confidence as a proportion bar. */
export function Meter({ value, tone = 'mute' }: { value: number; tone?: Tone }) {
  return (
    <div className="h-1 w-full overflow-hidden rounded-full bg-[var(--surface-3)]">
      <div
        className={`h-full rounded-full transition-[width] duration-500 ease-[var(--ease-out)] ${TONE_DOT[tone]}`}
        style={{ width: `${Math.max(2, Math.min(100, value * 100))}%` }}
      />
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`skeleton ${className}`} />
}

/** Table skeleton: the layout is known, so show its shape rather than a spinner. */
export function TableSkeleton({ rows = 8 }: { rows?: number }) {
  return (
    <div className="divide-y" style={{ borderColor: 'var(--line)' }}>
      {Array.from({ length: rows }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-3.5">
          <Skeleton className="h-3.5 w-14" />
          <Skeleton className="h-3.5 flex-1" />
          <Skeleton className="h-3.5 w-20" />
          <Skeleton className="h-3.5 w-16" />
          <Skeleton className="h-5 w-24 rounded-md" />
        </div>
      ))}
    </div>
  )
}

export function EmptyState({
  title,
  action,
}: {
  title: string
  action?: React.ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
      <p className="text-[13px] text-[var(--fg-3)]">{title}</p>
      {action}
    </div>
  )
}

/**
 * Sticky page header on the material layer, so the page title and its primary action stay
 * reachable while a long table scrolls under them.
 */
export function PageHeader({
  title,
  sub,
  action,
}: {
  title: string
  sub?: string
  action?: React.ReactNode
}) {
  return (
    <header className="material -mx-4 mb-6 flex flex-wrap items-end justify-between gap-4 px-4 pb-4 pt-2 sm:-mx-8 sm:px-8 lg:sticky lg:top-0 lg:z-10">
      <div>
        <h1
          className="text-[26px] leading-none tracking-[-0.028em]"
          style={{ fontVariationSettings: "'wght' 600" }}
        >
          {title}
        </h1>
        {sub && <p className="mt-2 text-[13px] text-[var(--fg-2)]">{sub}</p>}
      </div>
      {action}
    </header>
  )
}

/** Apple-style segmented control: one visible selection, sliding rather than blinking. */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
}: {
  options: Array<{ key: T; label: string; count?: number }>
  value: T
  onChange: (key: T) => void
}) {
  return (
    <div
      className="inline-flex gap-0.5 rounded-[var(--radius-control)] p-0.5"
      style={{ background: 'var(--surface-2)' }}
      role="tablist"
    >
      {options.map((o) => {
        const active = o.key === value
        return (
          <button
            key={o.key}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(o.key)}
            className={`pressable rounded-[var(--radius-inner)] px-3 py-1.5 text-[12.5px] ${
              active
                ? 'bg-[var(--surface)] text-[var(--fg)] shadow-[var(--shadow-line)]'
                : 'text-[var(--fg-2)] hover:text-[var(--fg)]'
            }`}
            style={{ fontVariationSettings: active ? "'wght' 560" : "'wght' 480" }}
          >
            {o.label}
            {o.count != null && <span className="num ml-1.5 opacity-55">{o.count}</span>}
          </button>
        )
      })}
    </div>
  )
}

/** A display-scale figure. Negative tracking is what makes large numerals look composed. */
export function BigFigure({
  value,
  label,
  tone,
  loading,
}: {
  value: string
  label: string
  tone?: 'win' | 'warn' | 'risk' | 'accent'
  loading?: boolean
}) {
  return (
    <div>
      {loading ? (
        <div className="skeleton h-11 w-40" />
      ) : (
        <p
          className="num text-[44px] leading-[0.95] tracking-[-0.035em]"
          style={{
            fontVariationSettings: "'wght' 590",
            color: tone ? `var(--${tone})` : 'var(--fg)',
          }}
        >
          {value}
        </p>
      )}
      <p className="mt-2 text-[12px] text-[var(--fg-3)]">{label}</p>
    </div>
  )
}

/** A compact row linking to a case. Used by Overview's shortlists. */
export function CaseRow({
  id,
  title,
  meta,
  right,
  onClick,
}: {
  id: string
  title: string
  meta: React.ReactNode
  right: React.ReactNode
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="pressable flex w-full items-center justify-between gap-4 rounded-[var(--radius-inner)] px-2.5 py-2 text-left hover:bg-[var(--surface-2)]"
    >
      <span className="min-w-0">
        <span className="flex items-center gap-2">
          <span className="text-[13px]" style={{ fontVariationSettings: "'wght' 510" }}>
            {title}
          </span>
          <span className="num text-[11px] text-[var(--fg-3)]">{id}</span>
        </span>
        <span className="mt-0.5 block text-[11.5px] text-[var(--fg-3)]">{meta}</span>
      </span>
      <span className="shrink-0 text-right">{right}</span>
    </button>
  )
}
