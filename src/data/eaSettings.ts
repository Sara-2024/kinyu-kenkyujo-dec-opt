// EAの設定項目。
//
// 各項目はMT5のグローバル変数1つに対応する。
// 画面で変更 → ブリッジ(bridge.py)の set_variable → MT5のグローバル変数 → EAが毎Tick読む、
// という流れなので、EAを載せ直したりMT5を触ったりせずに反映できる。

export interface EaSetting {
  key: string
  label: string
  /** 何のための設定かを一言で */
  hint: string
  unit: string
  min: number
  max: number
  step: number
  defaultValue: number
  decimals: number
  /** 対応するMT5グローバル変数 */
  gv: string
}

export const EA_SETTINGS: EaSetting[] = [
  {
    key: 'lot',
    label: 'ロット数',
    hint: '1回の注文の大きさ',
    unit: 'Lot',
    min: 0.01,
    max: 5,
    step: 0.01,
    defaultValue: 0.1,
    decimals: 2,
    gv: 'AI_LOT',
  },
  {
    key: 'maxPositions',
    label: '同時に持つ数',
    hint: 'これ以上はポジションを増やしません',
    unit: '件',
    min: 1,
    max: 10,
    step: 1,
    defaultValue: 3,
    decimals: 0,
    gv: 'AI_MAX_POSITIONS',
  },
  {
    key: 'dayLossLimit',
    label: '1日の損失上限',
    hint: 'ここに達したら、その日は自動で止まります',
    unit: '円',
    min: 5000,
    max: 200000,
    step: 5000,
    defaultValue: 30000,
    decimals: 0,
    gv: 'AI_DAY_LOSS_LIMIT',
  },
]

export function formatValue(setting: EaSetting, value: number): string {
  const fixed = value.toFixed(setting.decimals)
  return setting.decimals === 0 ? Number(fixed).toLocaleString('ja-JP') : fixed
}

export function defaultSettings(): Record<string, number> {
  return Object.fromEntries(EA_SETTINGS.map((s) => [s.key, s.defaultValue]))
}

/** 指令ファイル（ゲート）に書いてある値だけを画面の設定キーへ写す */
export function settingsFromGate(gate?: Record<string, number> | null): Record<string, number> {
  if (!gate) return {}
  const out: Record<string, number> = {}
  for (const setting of EA_SETTINGS) {
    const raw = gate[setting.gv]
    if (typeof raw === 'number' && Number.isFinite(raw)) {
      out[setting.key] = Number(raw.toFixed(setting.decimals))
    }
  }
  return out
}
