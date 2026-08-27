// CSSブロックだけで組む仮のドット絵キャラ。
// 単位 s(px) を敷き詰めて描く。あとで本物のドット絵PNGに差し替える前提。
import type { CSSProperties } from 'react'
import type { Look } from '../data/characters'

const DARK = '#1b2028' // ズボン
const SHOE = '#10141a'
const LINE = '#141922' // 輪郭がわりの影色

function px(n: number, s: number) {
  return `${n * s}px`
}

export function PixelPerson({ look, s = 5, surprised = false }: { look: Look; s?: number; surprised?: boolean }) {
  const b = (l: number, t: number, w: number, h: number, bg: string, extra?: CSSProperties) =>
    ({
      position: 'absolute',
      left: px(l, s),
      top: px(t, s),
      width: px(w, s),
      height: px(h, s),
      background: bg,
      ...extra,
    }) as CSSProperties

  return (
    <div
      className="pix-idle relative"
      style={{ width: px(14, s), height: px(16, s), imageRendering: 'pixelated' }}
    >
      {/* ───── 頭 ───── */}
      <div style={b(3, 2, 8, 5, look.skin)} />
      {/* 前髪 */}
      <div style={b(3, 1, 8, 1.6, look.hair)} />
      <div style={b(3, 2.6, 1.2, 1, look.hair)} />
      <div style={b(9.8, 2.6, 1.2, 1, look.hair)} />
      {look.hairStyle === 'bob' && (
        <>
          {/* おかっぱのサイド */}
          <div style={b(2.2, 2, 1, 4.6, look.hair)} />
          <div style={b(10.8, 2, 1, 4.6, look.hair)} />
        </>
      )}
      {/* 目（驚くと見開く） */}
      <div style={b(surprised ? 4.7 : 5, surprised ? 3.9 : 4.2, surprised ? 1.5 : 1, surprised ? 1.9 : 1.4, LINE)} />
      <div style={b(surprised ? 7.8 : 8, surprised ? 3.9 : 4.2, surprised ? 1.5 : 1, surprised ? 1.9 : 1.4, LINE)} />
      {surprised && <div style={b(6.4, 5.9, 1.2, 0.8, LINE)} />}
      {/* あご影 */}
      <div style={b(3, 6.6, 8, 0.4, 'rgba(0,0,0,0.18)')} />

      {/* ───── アクセサリー ───── */}
      {look.accessory === 'headphones' && (
        <>
          <div style={b(3.4, 0.4, 7.2, 0.8, '#c22f3d')} />
          <div style={b(2.2, 2.4, 1.2, 2.4, '#c22f3d')} />
          <div style={b(10.6, 2.4, 1.2, 2.4, '#c22f3d')} />
        </>
      )}
      {look.accessory === 'headband' && <div style={b(2.8, 2.2, 8.4, 1, '#ffd23e')} />}

      {/* ───── 胴体（白ベース＋ベスト） ───── */}
      <div style={b(2.5, 7, 9, 4.6, '#f2f4f7')} />
      <div style={b(4.4, 7, 5.2, 4.6, look.shirt)} />
      {look.accent && <div style={b(6.3, 8.2, 1.4, 1.4, look.accent)} />}
      {/* 襟の影 */}
      <div style={b(4.4, 7, 5.2, 0.5, 'rgba(0,0,0,0.22)')} />

      {/* 手 */}
      <div style={b(2.5, 11, 1.4, 1.4, look.skin)} />
      <div style={b(10.1, 11, 1.4, 1.4, look.skin)} />

      {/* ───── 持ち物（タブレット） ───── */}
      {look.item && (
        <div style={b(9.6, 9.4, 3.6, 4.2, '#0e1524', { border: `${Math.max(1, s * 0.3)}px solid ${LINE}` })}>
          {look.item === 'tablet' ? (
            <span
              className="font-mono font-bold text-white"
              style={{ fontSize: px(1.8, s), lineHeight: px(3.4, s), display: 'block', textAlign: 'center' }}
            >
              A
            </span>
          ) : (
            <div style={{ position: 'absolute', inset: `${s * 0.5}px`, display: 'flex', alignItems: 'flex-end', gap: `${s * 0.25}px` }}>
              <div style={{ flex: 1, height: '45%', background: '#2fbf62' }} />
              <div style={{ flex: 1, height: '75%', background: '#e04b4b' }} />
              <div style={{ flex: 1, height: '60%', background: '#2fbf62' }} />
            </div>
          )}
        </div>
      )}

      {/* ───── 脚と靴 ───── */}
      <div style={b(4.4, 11.6, 2.2, 2.8, DARK)} />
      <div style={b(7.4, 11.6, 2.2, 2.8, DARK)} />
      <div style={b(4.2, 14.4, 2.6, 1.2, SHOE)} />
      <div style={b(7.2, 14.4, 2.6, 1.2, SHOE)} />

      {/* 足元の影 */}
      <div
        style={b(2.6, 15.4, 8.8, 0.8, 'rgba(0,0,0,0.25)', { borderRadius: '9999px', filter: 'blur(1px)' })}
      />
    </div>
  )
}
