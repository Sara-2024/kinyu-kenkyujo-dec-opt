// 実データを出すときの共通の見た目。
// カードで区切らず、1pxシアンの枠の中に行を積む。
import type { ReactNode } from 'react'

export const GREEN = '#35f58a'
export const RED = '#ff8484'

/** 損益の色。プラスは緑、マイナスは赤 */
export function tone(n: number): string {
  if (n > 0) return GREEN
  if (n < 0) return RED
  return '#cbd5e1'
}

export function Heading({ title, note }: { title: string; note?: string }) {
  return (
    <div className="mb-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="h-3 w-[2px]" style={{ background: 'var(--accent)', boxShadow: '0 0 6px var(--accent)' }} />
      <p className="text-[14px] font-bold text-slate-200">{title}</p>
      {note && <p className="font-mono text-[12px] text-slate-500">{note}</p>}
    </div>
  )
}

export function Row({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div
      className="flex items-baseline justify-between gap-4 border-b py-2 last:border-b-0"
      style={{ borderColor: 'rgba(94,204,255,0.12)' }}
    >
      <span className="text-[14px] text-slate-400">{label}</span>
      <span className="font-mono text-[16px] font-bold" style={{ color: color ?? '#e8edf5' }}>
        {value}
      </span>
    </div>
  )
}

export function Frame({ children }: { children: ReactNode }) {
  return (
    <div
      className="step-in rounded-[6px] border px-5 py-4"
      style={{ borderColor: 'rgba(94,204,255,0.28)', background: 'rgba(9,17,31,0.6)' }}
    >
      {children}
    </div>
  )
}

/** 割合を横棒で見せる。数字の隣に置く前提の細い棒 */
export function Bar({ ratio, color }: { ratio: number; color: string }) {
  return (
    <span
      className="h-2 min-w-[2px] rounded-full"
      style={{
        width: `${Math.max(2, Math.min(1, Math.abs(ratio)) * 58)}%`,
        background: color,
        boxShadow: `0 0 8px ${color}55`,
      }}
    />
  )
}
