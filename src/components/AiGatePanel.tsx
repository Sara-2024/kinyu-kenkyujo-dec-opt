// AIリスク監督の表示（管理画面の中）。
//
// 出しているのは、ブリッジが返した判定そのもの。画面側では何も計算しない。
// 触れるのは「反映 / 記録のみ / 切」の切り替えだけで、ロットや決済には関わらない。
import { useState } from 'react'
import {
  MODE_LABEL,
  MODE_NOTE,
  levelText,
  reasonText,
  remainSec,
  shortTime,
  type AiGateMode,
  type AiGateSide,
  type AiGateState,
} from '../data/aiGate'
import type { useBridge } from '../hooks/useBridge'

const MODES: AiGateMode[] = ['on', 'shadow', 'off']

function SideRow({ label, side, enforced }: { label: string; side: AiGateSide; enforced: boolean }) {
  const blocked = side.blocked
  const color = blocked ? '#ff8484' : '#35f58a'
  return (
    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="flex items-center gap-2">
        <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: color }} />
        <span className="text-[15px] font-bold text-white">
          {label} {blocked ? (enforced ? '停止中' : '停止（記録のみ）') : '許可'}
        </span>
      </span>
      {blocked && (
        <>
          <span className="text-[13px]" style={{ color: '#ffd23e' }}>
            {reasonText(side.reasons) || '理由なし'}
          </span>
          {side.level_name && <span className="font-mono text-[13px] text-slate-400">{levelText(side)}</span>}
          {side.held_sec != null && (
            <span className="font-mono text-[12px] text-slate-500 tabular-nums">{Math.round(side.held_sec)}秒経過</span>
          )}
        </>
      )}
    </div>
  )
}

export function AiGatePanel({ gate, bridge }: { gate: AiGateState; bridge: ReturnType<typeof useBridge> }) {
  const [busy, setBusy] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  const enforced = gate.mode === 'on'
  const left = remainSec(gate.expires_at)
  const expired = enforced && gate.decided_at != null && left == null
  const commsBad = gate.comms === 'error'
  const skipped = gate.metrics?.skipped ?? {}

  const setMode = async (mode: AiGateMode) => {
    if (mode === gate.mode || busy) return
    setBusy(true)
    setFailed(null)
    const ack = await bridge.send('set_ai_gate', { mode })
    if (!ack.ok) setFailed(ack.error ?? 'E007: 切り替えに失敗しました')
    setBusy(false)
  }

  return (
    <div
      className="mb-4 rounded-[6px] border px-5 py-4"
      style={{
        borderColor: expired || commsBad ? 'rgba(250,204,21,0.5)' : 'rgba(94,204,255,0.28)',
        background: expired || commsBad ? 'rgba(250,204,21,0.06)' : 'rgba(9,17,31,0.6)',
      }}
    >
      <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="h-4 w-[2px] shrink-0" style={{ background: 'var(--accent)' }} />
        <span className="text-[15px] font-bold text-white">AIの見張り</span>
        <span className="text-[12px] text-slate-400">危ない形のときだけ、その向きの新規注文を見送ります</span>
        <div className="ml-auto flex items-center gap-1.5">
          {MODES.map((mode) => (
            <button
              key={mode}
              type="button"
              disabled={busy}
              onClick={() => void setMode(mode)}
              className="rounded-[5px] border px-3 py-2 text-[13px] font-bold transition hover:brightness-110 disabled:opacity-50"
              style={
                gate.mode === mode
                  ? { borderColor: 'var(--accent)', background: 'rgba(94,204,255,0.16)', color: '#fff' }
                  : { borderColor: 'rgba(148,163,184,0.35)', background: 'rgba(10,18,32,0.8)', color: '#94a3b8' }
              }
            >
              {MODE_LABEL[mode]}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        <SideRow label="買い" side={gate.buy} enforced={enforced} />
        <SideRow label="売り" side={gate.sell} enforced={enforced} />
      </div>

      {gate.summary && <p className="mt-3 text-[14px] leading-relaxed text-slate-200">{gate.summary}</p>}

      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-slate-400">
        <span>{MODE_NOTE[gate.mode]}</span>
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 font-mono text-[12px] text-slate-500 tabular-nums">
        <span>最終判定 {shortTime(gate.decided_at)}</span>
        <span>{left != null ? `有効期限まで ${left}秒` : gate.decided_at ? '有効期限ぎれ' : '判定なし'}</span>
        <span>
          通信 {gate.comms === 'ok' ? '正常' : gate.comms === 'error' ? '不通' : '停止中'}
          {gate.comms_error ? `（${gate.comms_error.slice(0, 40)}）` : ''}
        </span>
        {gate.symbol && <span>{gate.symbol}</span>}
        {gate.model && <span>{gate.model}</span>}
        {gate.metrics?.evaluations != null && <span>判定 {gate.metrics.evaluations}回</span>}
        {(skipped.ai_skip_buy != null || skipped.ai_skip_sell != null) && (
          <span>
            見送り 買い{skipped.ai_skip_buy ?? 0} / 売り{skipped.ai_skip_sell ?? 0}
          </span>
        )}
        {(skipped.ai_shadow_buy != null || skipped.ai_shadow_sell != null) && (
          <span>
            記録のみ 買い{skipped.ai_shadow_buy ?? 0} / 売り{skipped.ai_shadow_sell ?? 0}
          </span>
        )}
      </div>

      {expired && (
        <p className="mt-2 text-[13px] font-bold" style={{ color: '#ffd23e' }}>
          ⚠ 判定が期限切れです。新規注文は止まりますが、保有中の決済とSL/TPの管理は続いています
        </p>
      )}
      {failed && (
        <p className="mt-2 text-[13px] font-bold" style={{ color: '#ff8484' }}>
          {failed}
        </p>
      )}

      {gate.history && gate.history.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-[13px] text-slate-400 underline-offset-4 hover:underline"
          >
            {open ? '判断の履歴を閉じる' : `判断の履歴を見る（${gate.history.length}件）`}
          </button>
          {open && (
            <ul className="mt-2 space-y-1.5">
              {gate.history.map((h, i) => (
                <li key={`${h.at}-${i}`} className="flex flex-wrap items-baseline gap-x-3 text-[13px]">
                  <span className="font-mono text-[12px] text-slate-500 tabular-nums">{shortTime(h.at)}</span>
                  <span className="text-slate-300">
                    買い {h.buy === 'BLOCK' ? '停止' : h.buy === 'ALLOW' ? '許可' : '材料不足'} / 売り{' '}
                    {h.sell === 'BLOCK' ? '停止' : h.sell === 'ALLOW' ? '許可' : '材料不足'}
                  </span>
                  {!h.enforced && <span className="text-[12px] text-slate-500">記録のみ</span>}
                  <span className="text-[12px] text-slate-500">
                    {reasonText([...(h.reason_codes?.buy ?? []), ...(h.reason_codes?.sell ?? [])])}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  )
}
