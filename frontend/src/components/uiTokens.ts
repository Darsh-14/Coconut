/** Shared semantic colour mappings used by primitives and their consumers. */
export type Tone = 'win' | 'warn' | 'risk' | 'accent' | 'mute'

export const TONE_SOFT: Record<Tone, string> = {
  win: 'tone-win',
  warn: 'tone-warn',
  risk: 'tone-risk',
  accent: 'tone-accent',
  mute: '',
}

export const TONE_DOT: Record<Tone, string> = {
  win: 'bg-[var(--win)]',
  warn: 'bg-[var(--warn)]',
  risk: 'bg-[var(--risk)]',
  accent: 'bg-[var(--accent)]',
  mute: 'bg-[var(--fg-3)]',
}

export const toneDot = (tone: Tone) => TONE_DOT[tone]
