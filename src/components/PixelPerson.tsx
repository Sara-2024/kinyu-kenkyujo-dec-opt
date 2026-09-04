// ドット絵の研究員。16×26 のマス目にパーツを描き、外側に1マスの輪郭を付ける。
// 髪型・服・持ち物の組み合わせは characters.ts の look で決める。
// 描画は SVG（shape-rendering: crispEdges）なので、拡大してもにじまない。
import { useMemo } from 'react'
import type { Look } from '../data/characters'

const COLS = 16
const ROWS = 26
const OUTLINE = '#10141c'
const EYE = '#151a24'
const SHOE = '#1a1f2b'

/** 色を明るく／暗くする（k<1 で暗く） */
function shade(hex: string, k: number): string {
  const n = parseInt(hex.replace('#', ''), 16)
  const ch = (v: number) => Math.max(0, Math.min(255, Math.round(v * k)))
  const r = ch((n >> 16) & 255)
  const g = ch((n >> 8) & 255)
  const b = ch(n & 255)
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`
}

type Grid = (string | null)[][]

function blank(): Grid {
  return Array.from({ length: ROWS }, () => Array<string | null>(COLS).fill(null))
}

function rect(g: Grid, x: number, y: number, w: number, h: number, color: string) {
  for (let yy = y; yy < y + h; yy++) {
    for (let xx = x; xx < x + w; xx++) {
      if (yy >= 0 && yy < ROWS && xx >= 0 && xx < COLS) g[yy][xx] = color
    }
  }
}

function px(g: Grid, x: number, y: number, color: string) {
  rect(g, x, y, 1, 1, color)
}

/** 見た目の定義からマス目を描く */
function paint(look: Look, surprised: boolean): Grid {
  const g = blank()
  const skin = look.skin
  const skinS = shade(skin, 0.82)
  const hair = look.hair
  const hairH = shade(hair, 1.35)
  const cloth = look.clothes
  const clothS = shade(cloth, 0.72)
  const inner = look.inner ?? '#f2f4f7'
  const accent = look.accent ?? '#ffd23e'
  const pants = look.pants
  const pantsS = shade(pants, 0.7)
  const acc = look.accessoryColor ?? '#c22f3d'

  // ── 顔 ──
  rect(g, 4, 3, 8, 7, skin)
  rect(g, 4, 9, 8, 1, skinS) // あご影
  px(g, 4, 3, skinS)
  px(g, 11, 3, skinS)
  // 首
  rect(g, 7, 10, 2, 1, skinS)

  // ── 髪 ──
  switch (look.hairStyle) {
    case 'short':
      rect(g, 4, 1, 8, 3, hair)
      rect(g, 3, 2, 1, 3, hair)
      rect(g, 12, 2, 1, 3, hair)
      // 前髪
      px(g, 5, 4, hair)
      px(g, 6, 4, hair)
      px(g, 9, 4, hair)
      rect(g, 5, 1, 3, 1, hairH)
      break
    case 'bob':
      rect(g, 4, 1, 8, 3, hair)
      rect(g, 3, 2, 2, 8, hair)
      rect(g, 11, 2, 2, 8, hair)
      px(g, 4, 9, hair)
      px(g, 11, 9, hair)
      // 前髪（ぱっつん）
      rect(g, 5, 4, 6, 1, hair)
      px(g, 8, 4, skin)
      rect(g, 5, 1, 4, 1, hairH)
      break
    case 'ponytail':
      rect(g, 4, 1, 8, 3, hair)
      rect(g, 3, 2, 1, 4, hair)
      rect(g, 12, 2, 1, 3, hair)
      px(g, 5, 4, hair)
      px(g, 6, 4, hair)
      px(g, 10, 4, hair)
      // 横に垂らした尻尾
      rect(g, 13, 3, 2, 8, hair)
      px(g, 14, 11, hair)
      px(g, 13, 4, hairH)
      rect(g, 6, 1, 3, 1, hairH)
      break
    case 'slick':
      // 撫でつけた髪。額が広く見える
      rect(g, 4, 1, 8, 2, hair)
      rect(g, 3, 2, 1, 3, hair)
      rect(g, 12, 2, 1, 3, hair)
      rect(g, 4, 3, 2, 1, hair)
      rect(g, 10, 3, 2, 1, hair)
      rect(g, 6, 1, 5, 1, hairH)
      px(g, 12, 3, hairH)
      px(g, 3, 3, hairH)
      break
    case 'bandana':
      rect(g, 4, 1, 8, 2, acc)
      rect(g, 3, 2, 1, 2, acc)
      rect(g, 12, 2, 1, 2, acc)
      rect(g, 5, 1, 3, 1, shade(acc, 1.3))
      // 結び目（後ろ）
      rect(g, 12, 3, 2, 1, acc)
      px(g, 14, 4, acc)
      px(g, 13, 4, shade(acc, 0.7))
      // バンダナの下からのぞく髪
      rect(g, 4, 3, 8, 1, hair)
      px(g, 8, 3, skin)
      break
  }

  // ── 目・口 ──
  if (surprised) {
    rect(g, 5, 6, 2, 2, EYE)
    rect(g, 9, 6, 2, 2, EYE)
    rect(g, 7, 9, 2, 1, EYE)
  } else {
    rect(g, 6, 6, 1, 2, EYE)
    rect(g, 9, 6, 1, 2, EYE)
    rect(g, 7, 9, 2, 1, skinS)
    px(g, 8, 9, shade(skin, 0.72))
  }

  // ── 小物（頭） ──
  switch (look.accessory) {
    case 'glasses': {
      const rim = acc
      rect(g, 5, 6, 1, 2, rim)
      rect(g, 7, 6, 2, 1, rim)
      rect(g, 10, 6, 1, 2, rim)
      px(g, 5, 8, rim)
      px(g, 7, 8, rim)
      px(g, 8, 8, rim)
      px(g, 10, 8, rim)
      break
    }
    case 'headset': {
      rect(g, 4, 0, 8, 1, acc)
      px(g, 3, 1, acc)
      px(g, 12, 1, acc)
      rect(g, 2, 5, 2, 3, acc)
      rect(g, 12, 5, 2, 3, acc)
      px(g, 2, 6, '#35f58a')
      px(g, 13, 6, '#35f58a')
      // マイク
      px(g, 3, 8, acc)
      px(g, 4, 9, acc)
      px(g, 5, 10, acc)
      break
    }
    case 'goggles': {
      // 額に上げたゴーグル
      rect(g, 3, 3, 10, 1, OUTLINE)
      rect(g, 4, 3, 2, 1, '#7fe7ff')
      rect(g, 10, 3, 2, 1, '#7fe7ff')
      px(g, 5, 3, '#c9f6ff')
      px(g, 11, 3, '#c9f6ff')
      break
    }
    case 'ribbon': {
      rect(g, 12, 2, 2, 1, acc)
      rect(g, 12, 3, 1, 1, shade(acc, 0.75))
      px(g, 14, 2, acc)
      px(g, 14, 3, acc)
      px(g, 11, 1, acc)
      break
    }
  }

  // ── 胴体 ──
  const sleeve = look.outfit === 'vest' ? inner : cloth
  const sleeveS = shade(sleeve, 0.75)
  rect(g, 4, 11, 8, 8, cloth)
  rect(g, 2, 11, 2, 6, sleeve) // 左腕
  rect(g, 12, 11, 2, 6, sleeve) // 右腕
  px(g, 3, 11, sleeveS)
  px(g, 12, 11, sleeveS)
  rect(g, 2, 17, 2, 2, skin) // 手
  rect(g, 12, 17, 2, 2, skin)
  rect(g, 4, 18, 8, 1, clothS) // 裾の影

  switch (look.outfit) {
    case 'blazer':
      rect(g, 7, 11, 2, 3, inner)
      px(g, 7, 14, inner)
      rect(g, 6, 11, 1, 3, clothS)
      rect(g, 9, 11, 1, 3, clothS)
      px(g, 5, 12, accent) // ブローチ
      px(g, 8, 16, clothS) // ボタン
      break
    case 'suit':
      rect(g, 7, 11, 2, 2, inner)
      rect(g, 7, 12, 2, 4, accent) // ネクタイ
      px(g, 7, 15, shade(accent, 0.7))
      rect(g, 5, 11, 2, 3, clothS) // 襟
      rect(g, 9, 11, 2, 3, clothS)
      px(g, 4, 11, cloth)
      px(g, 11, 11, cloth)
      px(g, 10, 13, inner) // ポケットチーフ
      break
    case 'vest':
      rect(g, 4, 11, 8, 8, inner)
      rect(g, 5, 11, 6, 8, cloth)
      rect(g, 7, 11, 2, 2, inner)
      rect(g, 5, 12, 1, 6, accent) // 光る縁取り
      rect(g, 10, 12, 1, 6, accent)
      px(g, 8, 15, accent)
      px(g, 8, 17, accent)
      rect(g, 5, 18, 6, 1, clothS)
      break
    case 'work':
      rect(g, 8, 11, 1, 8, clothS) // ファスナー
      rect(g, 5, 11, 2, 1, clothS) // 襟
      rect(g, 9, 11, 2, 1, clothS)
      rect(g, 5, 15, 2, 2, clothS) // ポケット
      rect(g, 9, 15, 2, 2, clothS)
      rect(g, 2, 14, 2, 3, skin) // 袖をまくった腕
      rect(g, 12, 14, 2, 3, skin)
      rect(g, 2, 13, 2, 1, clothS)
      rect(g, 12, 13, 2, 1, clothS)
      px(g, 10, 12, accent) // 胸のワッペン
      break
    case 'uniform':
      rect(g, 6, 11, 4, 1, accent) // スカーフ
      rect(g, 7, 12, 2, 2, accent)
      px(g, 7, 13, shade(accent, 0.7))
      px(g, 8, 14, clothS)
      px(g, 8, 16, clothS)
      rect(g, 4, 11, 1, 8, clothS)
      break
  }

  // ── 脚 ──
  if (look.skirt) {
    rect(g, 3, 19, 10, 3, pants)
    rect(g, 3, 21, 10, 1, pantsS)
    rect(g, 5, 22, 2, 2, skin)
    rect(g, 9, 22, 2, 2, skin)
  } else {
    rect(g, 4, 19, 8, 5, pants)
    rect(g, 7, 19, 1, 5, pantsS)
    px(g, 8, 19, pantsS)
  }
  // 靴
  rect(g, 3, 24, 5, 2, SHOE)
  rect(g, 8, 24, 5, 2, SHOE)
  px(g, 7, 24, shade(SHOE, 1.6))
  px(g, 3, 24, shade(SHOE, 1.4))
  px(g, 12, 24, shade(SHOE, 1.4))

  // ── 持ち物（右手） ──
  switch (look.item) {
    case 'tablet':
      rect(g, 12, 14, 4, 6, '#0e1524')
      rect(g, 13, 15, 2, 4, look.screen ?? '#5eccff')
      px(g, 13, 16, shade(look.screen ?? '#5eccff', 0.55))
      px(g, 14, 18, shade(look.screen ?? '#5eccff', 0.55))
      break
    case 'clipboard':
      rect(g, 12, 13, 4, 7, '#f2f4f7')
      rect(g, 13, 13, 2, 1, '#8895ab')
      rect(g, 13, 15, 2, 1, '#8895ab')
      rect(g, 13, 17, 2, 1, '#8895ab')
      px(g, 13, 18, '#2fbf62')
      px(g, 14, 18, '#e04b4b')
      break
    case 'wrench':
      rect(g, 13, 12, 2, 9, '#a9b4c6')
      rect(g, 12, 11, 4, 2, '#a9b4c6')
      px(g, 13, 11, '#0e1524')
      px(g, 14, 11, '#0e1524')
      px(g, 14, 14, '#7d8799')
      px(g, 14, 18, '#7d8799')
      break
  }

  return g
}

/** 外側1マスの輪郭を足す。描かれたマスに隣接する透明マスを輪郭色にする */
function outline(g: Grid): Grid {
  const out: Grid = Array.from({ length: ROWS + 2 }, () => Array<string | null>(COLS + 2).fill(null))
  for (let y = 0; y < ROWS; y++) for (let x = 0; x < COLS; x++) out[y + 1][x + 1] = g[y][x]
  const filled = (x: number, y: number) => y >= 0 && y < ROWS && x >= 0 && x < COLS && g[y][x] != null
  for (let y = -1; y <= ROWS; y++) {
    for (let x = -1; x <= COLS; x++) {
      if (filled(x, y)) continue
      if (filled(x - 1, y) || filled(x + 1, y) || filled(x, y - 1) || filled(x, y + 1)) out[y + 1][x + 1] = OUTLINE
    }
  }
  return out
}

/** 横に続く同じ色をひとつの rect にまとめる */
function toRects(g: Grid): Array<{ x: number; y: number; w: number; color: string }> {
  const rects: Array<{ x: number; y: number; w: number; color: string }> = []
  for (let y = 0; y < g.length; y++) {
    let x = 0
    while (x < g[y].length) {
      const color = g[y][x]
      if (!color) {
        x++
        continue
      }
      let w = 1
      while (x + w < g[y].length && g[y][x + w] === color) w++
      rects.push({ x, y, w, color })
      x += w
    }
  }
  return rects
}

/** s は「1マスの基準サイズ」。マス目が細かくなったぶん 0.82 倍する（s=5.4 で背丈 約 125px） */
export function PixelPerson({ look, s = 5, surprised = false }: { look: Look; s?: number; surprised?: boolean }) {
  const cell = s * 0.82
  const rects = useMemo(() => toRects(outline(paint(look, surprised))), [look, surprised])
  const w = (COLS + 2) * cell
  const h = (ROWS + 2) * cell
  return (
    <div className="pix-idle relative" style={{ width: w, height: h + cell }}>
      <svg
        width={w}
        height={h}
        viewBox={`0 0 ${COLS + 2} ${ROWS + 2}`}
        shapeRendering="crispEdges"
        style={{ display: 'block' }}
        aria-hidden
      >
        {rects.map((r, i) => (
          <rect key={i} x={r.x} y={r.y} width={r.w} height={1} fill={r.color} />
        ))}
      </svg>
      {/* 足元の影 */}
      <div
        className="absolute left-1/2 -translate-x-1/2 rounded-full"
        style={{ bottom: 0, width: w * 0.8, height: cell * 1.2, background: 'rgba(0,0,0,0.3)', filter: 'blur(1.5px)' }}
      />
    </div>
  )
}
