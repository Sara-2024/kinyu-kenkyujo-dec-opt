import type { useBridge } from '../hooks/useBridge'
import { formatBridgeError } from '../data/bridgeErrors'

/** 中継サーバー／ブリッジの接続状態（エラーコード付き） */
export function BridgeStatusBar({
  bridge,
  onReconnect,
}: {
  bridge: ReturnType<typeof useBridge>
  onReconnect?: () => void
}) {
  if (bridge.live && bridge.status?.account != null) {
    return (
      <div
        className="mb-2 rounded-[5px] border px-4 py-2.5 text-[13px] font-bold"
        style={{ borderColor: 'rgba(53,245,138,0.45)', background: 'rgba(53,245,138,0.08)', color: '#35f58a' }}
      >
        ● MT5と接続中
        <span className="font-mono ml-3 font-normal text-slate-300">
          口座 {bridge.status.account} / {bridge.status.server ?? ''}
        </span>
        {bridge.status.terminal_name && (
          <span className="font-mono ml-3 font-normal text-slate-500">
            {bridge.status.terminal_name}
          </span>
        )}
      </div>
    )
  }

  const message = bridge.error
    ? formatBridgeError(bridge.error)
    : bridge.phase === 'connecting'
      ? '中継サーバーに接続しています…'
      : 'MT5 未接続'

  const canRetry = Boolean(onReconnect) && (bridge.phase === 'no_bridge' || bridge.phase === 'error')

  return (
    <div
      className="mb-2 flex flex-wrap items-center gap-3 rounded-[5px] border px-4 py-2.5 text-[13px] font-bold leading-relaxed"
      style={{ borderColor: 'rgba(224,75,75,0.55)', background: 'rgba(224,75,75,0.1)', color: '#ff8484' }}
    >
      <span className="min-w-0 flex-1">⚠ {message}</span>
      {canRetry && (
        <button
          type="button"
          onClick={onReconnect}
          className="h-11 shrink-0 rounded-[5px] border px-5 text-[14px] font-bold text-slate-100 transition hover:brightness-125 active:translate-y-px"
          style={{ borderColor: 'rgba(148,163,184,0.45)', background: 'rgba(10,18,32,0.75)', color: '#e2e8f0' }}
        >
          つなぎ直す
        </button>
      )}
    </div>
  )
}
