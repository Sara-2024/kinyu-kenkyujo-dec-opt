import type { useBridge } from '../hooks/useBridge'
import { formatBridgeError } from '../data/bridgeErrors'

/** 中継サーバー／ブリッジの接続状態（エラーコード付き） */
export function BridgeStatusBar({ bridge }: { bridge: ReturnType<typeof useBridge> }) {
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
      ? `接続中… relay=${bridge.wsUrl}`
      : 'MT5 未接続'

  return (
    <div
      className="mb-2 rounded-[5px] border px-4 py-2.5 text-[13px] font-bold leading-relaxed"
      style={{ borderColor: 'rgba(224,75,75,0.55)', background: 'rgba(224,75,75,0.1)', color: '#ff8484' }}
    >
      ⚠ {message}
    </div>
  )
}
