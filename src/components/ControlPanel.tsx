// 接続後の管理画面。
// 一度つないだお客様が次に開くのはここ。停止・再開と、EAの設定変更ができる。
//
// 設定の変更は「MT5のグローバル変数を書き換える」だけなので、
// EAを載せ直す必要も、MT5を触っていただく必要もない。
import { useState } from 'react'
import { BridgeStatusBar } from './BridgeStatusBar'
import type { Connection } from '../data/connection'
import { formatBridgeError } from '../data/bridgeErrors'
import { EA_SETTINGS, formatValue } from '../data/eaSettings'
import type { useBridge } from '../hooks/useBridge'

export function ControlPanel({
  conn,
  onChange,
  onReset,
  onReconnect,
  bridge,
}: {
  conn: Connection
  onChange: (next: Connection) => void
  onReset: () => void
  onReconnect?: () => void
  bridge: ReturnType<typeof useBridge>
}) {
  const [draft, setDraft] = useState<Record<string, number>>(conn.settings)
  const [sending, setSending] = useState(false)
  const [savedAt, setSavedAt] = useState<number | null>(null)
  const [failed, setFailed] = useState<string | null>(null)

  const dirty = EA_SETTINGS.some((s) => draft[s.key] !== conn.settings[s.key])

  const bump = (key: string, dir: 1 | -1) => {
    const setting = EA_SETTINGS.find((s) => s.key === key)
    if (!setting) return
    setSavedAt(null)
    setDraft((d) => {
      const raw = (d[key] ?? setting.defaultValue) + dir * setting.step
      const clamped = Math.min(setting.max, Math.max(setting.min, raw))
      // 0.01刻みの誤差を丸める
      return { ...d, [key]: Number(clamped.toFixed(setting.decimals)) }
    })
  }

  const apply = async () => {
    setSending(true)
    setFailed(null)

    if (!bridge.live) {
      setSending(false)
      if (onReconnect) {
        onReconnect()
        return
      }
      setFailed(bridge.error ? formatBridgeError(bridge.error) : 'E008: MT5 未接続')
      return
    }

    const changed = EA_SETTINGS.filter((s) => draft[s.key] !== conn.settings[s.key])
    for (const setting of changed) {
      const ack = await bridge.send('set_variable', { name: setting.gv, value: draft[setting.key] })
      if (!ack.ok) {
        setSending(false)
        setFailed(ack.error ?? `E007: ${setting.label}の反映に失敗しました`)
        return
      }
    }
    onChange({ ...conn, settings: draft })
    setSending(false)
    setSavedAt(Date.now())
  }

  const running =
    bridge.live && typeof bridge.status?.value === 'number' ? Number(bridge.status.value) !== 0 : conn.running

  // MT5 のチャートに出ている状態と、この画面の状態が食い違っていないか。
  // 食い違うのは、EAが止まっている・別のフォルダを見ている・誰かが書き換えた、のいずれか。
  const mt5Mismatch =
    bridge.live &&
    bridge.status?.ea_alive === true &&
    bridge.status?.ea_allowed != null &&
    (bridge.status.ea_allowed === '1') !== running

  const health = (() => {
    if (!bridge.live) return 'MT5との接続を確認できません'
    if (bridge.status?.terminal_connected === false) return 'ターミナルが相場サーバーとつながっていません'
    if (bridge.status?.terminal_trade_allowed === false) return 'MT5の自動売買ボタンがオフです'
    return running ? 'MT5は取引可能な状態です' : '停止中です。再開はボタンから行えます'
  })()

  const engineLabel =
    bridge.live && bridge.status?.build != null
      ? `build ${bridge.status.build}`
      : bridge.status?.terminal_name
        ? String(bridge.status.terminal_name)
        : '—'

  return (
    <div className="border-t px-6 py-4" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
      <BridgeStatusBar bridge={bridge} onReconnect={onReconnect} />
      {/* ── 稼働状態 ── */}
      <div
        className="mb-4 flex flex-wrap items-center gap-4 rounded-[6px] border px-5 py-4"
        style={{
          borderColor: running ? 'rgba(53,245,138,0.45)' : 'rgba(224,75,75,0.5)',
          background: running ? 'rgba(53,245,138,0.07)' : 'rgba(224,75,75,0.08)',
        }}
      >
        <span
          className={`h-3.5 w-3.5 shrink-0 rounded-full ${running ? 'live-dot' : ''}`}
          style={{ background: running ? '#35f58a' : '#e04b4b' }}
        />
        <div className="min-w-0">
          <p className="text-[17px] font-bold text-white">自動売買 {running ? '稼働中' : '停止中'}</p>
          <p className="text-[12px] text-slate-400">
            {health}
          </p>
        </div>
        <button
          type="button"
          onClick={async () => {
            const next = !running
            if (!bridge.live) {
              if (onReconnect) {
                onReconnect()
                return
              }
              setFailed(bridge.error ? formatBridgeError(bridge.error) : 'E008: MT5 未接続')
              return
            }
            const ack = await bridge.send(next ? 'start_trading' : 'stop_trading', {
              reason: next ? '' : '画面から停止',
            })
            if (!ack.ok) {
              setFailed(ack.error ?? 'E007: 切り替えに失敗しました')
              return
            }
            setFailed(null)
            const confirmed = typeof ack.value === 'number' ? Number(ack.value) !== 0 : next
            onChange({ ...conn, running: confirmed })
          }}
          className="ml-auto whitespace-nowrap rounded-[5px] border px-6 py-3 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px"
          style={
            running
              ? { background: 'rgba(224,75,75,0.9)', borderColor: '#7f1d1d', color: '#fff' }
              : { background: 'rgba(53,245,138,0.9)', borderColor: '#166534', color: '#04120a' }
          }
        >
          {running ? '■ いますぐ停止' : '▶ 再開する'}
        </button>
      </div>

      {/* ── MT5側が実際に出している状態（表示のズレをその場で見つける） ── */}
      {bridge.live && bridge.status?.ea_state && (
        <div
          className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[5px] border px-4 py-2.5 text-[13px]"
          style={
            mt5Mismatch
              ? { borderColor: 'rgba(250,204,21,0.5)', background: 'rgba(250,204,21,0.08)' }
              : { borderColor: 'rgba(94,204,255,0.25)', background: 'rgba(94,204,255,0.05)' }
          }
        >
          <span className="font-bold text-slate-400">MT5の表示</span>
          <span className="font-bold text-slate-100">{bridge.status.ea_state}</span>
          {bridge.status.ea_state_at && (
            <span className="font-mono text-[12px] text-slate-500">{bridge.status.ea_state_at}</span>
          )}
          {mt5Mismatch && (
            <span className="w-full font-bold text-[#ffd23e]">
              ⚠ サイトと違う状態が出ています。指示どおりに戻しています（数十秒で揃います）。
            </span>
          )}
          {bridge.status.ea_alive === false && (
            <span className="w-full font-bold text-[#ffd23e]">
              ⚠ チャートにシステムが載っていません。MT5のチャートへドラッグしてください。
            </span>
          )}
          {bridge.status.ea_same_folder === false && (
            <span className="w-full font-bold text-[#ff8484]">
              ⚠ MT5と接続ツールが別のフォルダを見ています。接続ツールを開き直してください。
            </span>
          )}
        </div>
      )}

      {/* ── 口座 ── */}
      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-1 text-[13px]">
        <span className="text-slate-400">
          口座{' '}
          <span className="font-mono ml-1 font-bold text-slate-200">
            {bridge.live && bridge.status?.account != null ? bridge.status.account : conn.account}
          </span>
        </span>
        <span className="text-slate-400">
          サーバー{' '}
          <span className="font-mono ml-1 font-bold text-slate-200">
            {bridge.live && bridge.status?.server ? bridge.status.server : conn.server}
          </span>
        </span>
        <span className="text-slate-400">
          エンジン{' '}
          <span className="font-mono ml-1 font-bold text-slate-200">{engineLabel}</span>
        </span>
      </div>

      {/* ── EAの設定 ── */}
      <div className="mb-3 flex items-baseline gap-3">
        <span className="h-3.5 w-[2px]" style={{ background: 'var(--accent)', boxShadow: '0 0 6px var(--accent)' }} />
        <p className="text-[15px] font-bold text-slate-100">売買の設定</p>
        <p className="text-[12px] text-slate-400">変更はすぐに反映されます。MT5を触る必要はありません。</p>
      </div>

      <div className="space-y-2.5">
        {EA_SETTINGS.map((s) => {
          const value = draft[s.key] ?? s.defaultValue
          const changed = value !== conn.settings[s.key]
          return (
            <div
              key={s.key}
              className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-[6px] border px-4 py-3"
              style={{
                borderColor: changed ? 'rgba(250,204,21,0.5)' : 'rgba(94,204,255,0.18)',
                background: changed ? 'rgba(250,204,21,0.06)' : 'rgba(9,17,31,0.5)',
              }}
            >
              <div className="min-w-0 flex-1">
                <p className="text-[15px] font-bold text-white">{s.label}</p>
                <p className="text-[12px] text-slate-400">{s.hint}</p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => bump(s.key, -1)}
                  disabled={value <= s.min}
                  aria-label={`${s.label}を減らす`}
                  className="flex h-11 w-11 items-center justify-center rounded-[5px] border text-[22px] font-bold text-slate-100 transition hover:brightness-150 disabled:opacity-30"
                  style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.8)' }}
                >
                  −
                </button>
                <p className="w-28 text-center">
                  <span className="font-mono text-[20px] font-bold tabular-nums text-white">
                    {formatValue(s, value)}
                  </span>
                  <span className="ml-1 text-[12px] text-slate-400">{s.unit}</span>
                </p>
                <button
                  type="button"
                  onClick={() => bump(s.key, 1)}
                  disabled={value >= s.max}
                  aria-label={`${s.label}を増やす`}
                  className="flex h-11 w-11 items-center justify-center rounded-[5px] border text-[22px] font-bold text-slate-100 transition hover:brightness-150 disabled:opacity-30"
                  style={{ borderColor: 'rgba(148,163,184,0.4)', background: 'rgba(10,18,32,0.8)' }}
                >
                  ＋
                </button>
              </div>
            </div>
          )
        })}
      </div>

      {/* ── 反映 ── */}
      <div className="mt-4 flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={apply}
          disabled={!dirty || sending}
          className="whitespace-nowrap rounded-[5px] border px-6 py-3 text-[15px] font-bold transition hover:brightness-110 active:translate-y-px disabled:opacity-35"
          style={{ background: 'rgba(250,204,21,0.92)', borderColor: '#a16207', color: '#1c1607' }}
        >
          {sending ? 'MT5に送信しています…' : '変更を反映する ▶'}
        </button>

        {sending && (
          <span className="spin h-5 w-5 rounded-full"
                style={{ border: '2px solid rgba(94,204,255,0.2)', borderTopColor: 'var(--accent)' }} />
        )}
        {!sending && savedAt && !dirty && (
          <span className="check-pop text-[14px] font-bold text-[#35f58a]">✓ MT5に反映しました</span>
        )}
        {!sending && dirty && !failed && <span className="text-[13px] text-slate-400">変更された項目があります</span>}
        {failed && <span className="text-[13px] font-bold text-[#ff8484]">⚠ {failed}</span>}

        <button
          type="button"
          onClick={onReset}
          className="font-mono ml-auto text-[12px] text-slate-500 underline-offset-4 hover:underline"
        >
          この端末の連携を解除
        </button>
      </div>
    </div>
  )
}
