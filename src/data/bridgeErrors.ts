/** 中継サーバー／ブリッジ接続のエラーコード */
export const BRIDGE_ERRORS = {
  E001: '中継サーバーに接続できません',
  E002: '中継サーバーとの接続が切断されました',
  E003: '中継サーバーは応答していますが、ブリッジ（MT5側）が未接続です',
  E004: 'ブリッジがオフラインになりました',
  E005: 'WebSocket が未接続のため指令を送れません',
  E006: 'ブリッジから応答がありません（タイムアウト）',
  E007: 'ブリッジがエラーを返しました',
  E008: 'MT5 連携なしでは接続を完了できません',
} as const

export type BridgeErrorCode = keyof typeof BRIDGE_ERRORS

export interface BridgeError {
  code: BridgeErrorCode
  detail?: string
}

export function formatBridgeError(err: BridgeError): string {
  const base = BRIDGE_ERRORS[err.code]
  return err.detail ? `${err.code}: ${base} — ${err.detail}` : `${err.code}: ${base}`
}
