// 一斉制御（管理者）。自社のデモ口座を1画面で見て、一度に止める。
//
// 口座ごとに「対象にする／対象外にする」を持ち、ボタンは対象の口座にだけ流す。
// 口座の数字は中継が覚えている要約を使う（1口座ずつ取りに行かない）。
import { useEffect, useMemo, useState } from 'react'
import { Link, Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/AuthContext'
import { useFleet, type FleetCommand, type RoomState } from '../hooks/useFleet'
import {
  fleetDelete,
  fleetErrorMessage,
  fleetList,
  fleetOptouts,
  fleetRegisterFor,
  fleetReveal,
  fleetSetIncluded,
  type FleetAccount,
} from '../data/fleet'

/** 一覧の1行。登録簿に無い「連携だけの口座」は virtual（中継の要約から作る） */
type Row = FleetAccount & { virtual?: boolean }

const COMMAND_LABEL: Record<FleetCommand, string> = {
  stop_trading: 'エントリーのみ停止',
  close_all: '一斉全決済',
  stop_system: 'システム停止',
  start_trading: '一斉再開',
}

const COMMAND_NOTE: Record<FleetCommand, string> = {
  stop_trading: '新しい注文だけ止めます。持っているポジションはそのまま（決済・SL/TP は今までどおり動きます）。',
  close_all: '持っているポジションと待機注文をすべて閉じます。新しい注文は止めないので、システムがまた入ることがあります。元に戻せません。',
  stop_system: '新しい注文を止めたうえで、持っているポジションと待機注文をすべて閉じます。口座を空にして止めます。元に戻せません。',
  start_trading: '止めていた新規注文を再開します。',
}

/** 元に戻せない操作（確認の枠を赤くする） */
const DESTRUCTIVE: ReadonlySet<FleetCommand> = new Set<FleetCommand>(['close_all', 'stop_system'])

export function Fleet() {
  const { member, token, ready } = useAuth()
  const [rows, setRows] = useState<FleetAccount[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirm, setConfirm] = useState<FleetCommand | null>(null)
  const [report, setReport] = useState<{ command: FleetCommand; delivered: string[]; waiting: string[]; refused: string[]; at: number } | null>(null)
  const [revealed, setRevealed] = useState<Record<string, string>>({})
  const [optouts, setOptouts] = useState<string[]>([])

  useEffect(() => {
    const prev = document.body.style.overflow
    document.body.style.overflow = 'auto'
    return () => {
      document.body.style.overflow = prev
    }
  }, [])

  const reload = async () => {
    if (!token) return
    try {
      setRows(await fleetList(token))
      // 「受け付けない」の一覧は別に取る（まだ DB に入っていなくても一覧は出す）
      setOptouts(await fleetOptouts(token).catch(() => []))
      setError(null)
    } catch (err) {
      setError(fleetErrorMessage(err))
    }
  }

  useEffect(() => {
    if (ready && member?.role === 'admin' && token) void reload()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, member, token])

  // 1会員 = 1部屋。同じ会員が複数口座を登録していても、部屋は1つ
  const rooms = useMemo(() => [...new Set(rows.map((r) => r.member_id))], [rows])
  const fleet = useFleet(ready && member?.role === 'admin' ? token : null, rooms)

  if (ready && !member) return <Navigate to="/login" replace />
  if (ready && member && member.role !== 'admin') return <Navigate to="/" replace />

  // つながっているのに登録簿に無い部屋（中継は登録前の部屋も要約に入れて返す）。
  // 連携した時点で同意とみなすので、登録簿に無くても「対象」として一覧に出す
  const registeredRooms = new Set(rows.map((r) => r.member_id))
  const unregistered = Object.entries(fleet.states).filter(([room, st]) => st.online && !registeredRooms.has(room))
  const allRows: Row[] = [
    ...rows,
    ...unregistered.map(([room, st]) => {
      const s = st.status as (Record<string, unknown> & { account?: unknown; server?: unknown }) | null
      return {
        id: `room:${room}`,
        member_id: room,
        email: '',
        account: Number(s?.account) || 0,
        server: String(s?.server ?? ''),
        included: true,
        note: '',
        created_at: '',
        updated_at: '',
        virtual: true,
      }
    }),
  ]
  // 本人が「受け付けない」と決めた口座には流さない（中継側でも同じ確認をする）
  const optedOut = new Set(optouts)
  const targets = allRows.filter((r) => r.included && !optedOut.has(r.member_id))
  const targetRooms = [...new Set(targets.map((r) => r.member_id))]
  const onlineCount = targetRooms.filter((room) => fleet.states[room]?.online).length
  const refusedCount = allRows.filter((r) => optedOut.has(r.member_id)).length

  const addConnected = async (room: string, st: RoomState) => {
    if (!token) return
    const s = st.status as (Record<string, unknown> & { account?: unknown; server?: unknown }) | null
    const account = Number(s?.account)
    const server = String(s?.server ?? '')
    if (!account || !server) {
      setError('この口座の番号がまだ届いていません。少し待ってから「いまの状況を取り直す」を押してください。')
      return
    }
    setBusy(true)
    try {
      await fleetRegisterFor(token, room, account, server)
      await reload()
      setError(null)
    } catch (err) {
      setError(fleetErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const toggleIncluded = async (row: Row) => {
    if (!token) return
    setBusy(true)
    try {
      if (row.virtual) {
        // 登録簿に無い口座を「対象外」にするには、まず登録簿に入れる
        const created = await fleetRegisterFor(token, row.member_id, row.account, row.server)
        await fleetSetIncluded(token, created.id, false)
      } else {
        await fleetSetIncluded(token, row.id, !row.included)
      }
      await reload()
    } catch (err) {
      setError(fleetErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (row: FleetAccount) => {
    if (!token) return
    if (!window.confirm(`${row.account} / ${row.server} を登録簿から消しますか？`)) return
    setBusy(true)
    try {
      await fleetDelete(token, row.id)
      await reload()
    } catch (err) {
      setError(fleetErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  const reveal = async (row: FleetAccount) => {
    if (!token) return
    if (revealed[row.id]) {
      setRevealed((prev) => {
        const next = { ...prev }
        delete next[row.id]
        return next
      })
      return
    }
    try {
      const data = await fleetReveal(token, row.id)
      setRevealed((prev) => ({ ...prev, [row.id]: data.password }))
    } catch (err) {
      setError(fleetErrorMessage(err))
    }
  }

  const fire = async (command: FleetCommand) => {
    setConfirm(null)
    setBusy(true)
    setError(null)
    try {
      const result = await fleet.send(command, targetRooms, COMMAND_LABEL[command])
      setReport({ command, delivered: result.delivered, waiting: result.waiting, refused: result.refused ?? [], at: Date.now() })
    } catch (err) {
      setError(err instanceof Error ? err.message : '送れませんでした')
    } finally {
      setBusy(false)
    }
  }

  const relayNote =
    fleet.phase === 'denied'
      ? '中継に入れませんでした（管理者のログインか、中継の会員確認の設定を確かめてください）。'
      : fleet.phase === 'connecting'
        ? '中継につないでいます…'
        : null

  return (
    <div className="min-h-screen px-6 py-6" style={{ background: '#070b14', color: '#e8edf5' }}>
      <div className="mx-auto max-w-[1280px]">
        <div className="flex flex-wrap items-center gap-4">
          <span className="h-4 w-[3px]" style={{ background: 'var(--accent)' }} />
          <h1 className="text-[22px] font-bold">一斉制御</h1>
          <span className="text-[14px] text-slate-400">
            連携 {allRows.length} 口座 ／ 対象 {targets.length} 口座 ／ 受け付けない {refusedCount} 口座 ／ つながっている {onlineCount} 台
          </span>
          <Link to="/admin" className="ml-auto text-[15px] font-bold" style={{ color: 'var(--accent)' }}>
            管理者画面へ
          </Link>
          <Link to="/" className="text-[15px] font-bold" style={{ color: 'var(--accent)' }}>
            研究所へ戻る
          </Link>
        </div>
        <p className="mt-2 text-[15px] text-slate-400">
          サイトと連携した口座は、その時点で一斉制御を受け付けたものとして、この一覧に「対象」で出ます（お客様の入力は要りません）。
          お客様が管理画面で「受け付けない」にした口座には流しません。「対象外」はこちらで外すときに使います。
          パスワードまで預かる場合だけ
          <Link to="/fleet/join" className="mx-1 font-bold" style={{ color: 'var(--accent)' }}>
            口座の登録ページ
          </Link>
          を使います。
        </p>

        {(error || relayNote) && (
          <p className="mt-4 text-[15px]" style={{ color: error ? '#ff8484' : '#94a3b8' }}>
            {error ?? relayNote}
          </p>
        )}

        {/* ── 一斉操作 ── */}
        <div className="mt-5 rounded-[4px] border px-5 py-5" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
          <div className="flex flex-wrap gap-3">
            <Big onClick={() => setConfirm('stop_trading')} disabled={busy || targetRooms.length === 0} tone="warn">
              {COMMAND_LABEL.stop_trading}
            </Big>
            <Big onClick={() => setConfirm('close_all')} disabled={busy || targetRooms.length === 0} tone="danger">
              {COMMAND_LABEL.close_all}
            </Big>
            <Big onClick={() => setConfirm('stop_system')} disabled={busy || targetRooms.length === 0} tone="danger">
              {COMMAND_LABEL.stop_system}
            </Big>
            <Big onClick={() => setConfirm('start_trading')} disabled={busy || targetRooms.length === 0} tone="ok">
              {COMMAND_LABEL.start_trading}
            </Big>
            <button
              type="button"
              onClick={() => {
                void reload()
                fleet.refresh()
              }}
              className="ml-auto h-11 rounded-[4px] border px-4 text-[14px] font-bold text-slate-100"
              style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' }}
            >
              いまの状況を取り直す
            </button>
          </div>

          {confirm && (
            <div className="mt-4 rounded-[4px] border px-4 py-4" style={{ borderColor: DESTRUCTIVE.has(confirm) ? '#ff8484' : 'var(--panel-border)' }}>
              <p className="text-[17px] font-bold">
                {COMMAND_LABEL[confirm]} — 対象 {targets.length} 口座（{targetRooms.length} 台、つながっている {onlineCount} 台）
              </p>
              <p className="mt-1 text-[15px] text-slate-300">{COMMAND_NOTE[confirm]}</p>
              {onlineCount < targetRooms.length && (
                <p className="mt-1 text-[14px]" style={{ color: '#ffd23e' }}>
                  つながっていない {targetRooms.length - onlineCount} 台には、次にその PC の MT5 Automatic がつながった瞬間に渡します。
                </p>
              )}
              <div className="mt-3 flex flex-wrap gap-3">
                <Big onClick={() => void fire(confirm)} disabled={busy} tone={DESTRUCTIVE.has(confirm) ? 'danger' : 'ok'}>
                  実行する
                </Big>
                <Big onClick={() => setConfirm(null)} disabled={busy} tone="plain">
                  やめる
                </Big>
              </div>
            </div>
          )}

          {report && (
            <div className="mt-4 text-[15px]">
              <p className="font-bold">
                {new Date(report.at).toLocaleTimeString('ja-JP')} に {COMMAND_LABEL[report.command]} を送りました：
                届いた {report.delivered.length} 台 ／ 待たせている {report.waiting.length} 台
                {report.refused.length > 0 ? ` ／ 受け付けない口座 ${report.refused.length} 台には流していません` : ''}
              </p>
              <p className="mt-1 text-slate-400">
                各口座の「返事」の欄で、実際に止まったかを確かめてください（数秒で返ってきます）。
              </p>
            </div>
          )}
        </div>

        {/* ── 口座一覧（登録簿の口座と、連携だけの口座を同じ表に出す） ── */}
        <div className="mt-5 overflow-x-auto rounded-[4px] border" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
          <table className="w-full min-w-[1100px] text-left text-[14px]">
            <thead>
              <tr className="border-b text-slate-400" style={{ borderColor: 'var(--panel-border)' }}>
                <th className="px-3 py-3 font-bold">対象</th>
                <th className="px-3 py-3 font-bold">登録した口座</th>
                <th className="px-3 py-3 font-bold">登録者</th>
                <th className="px-3 py-3 font-bold">接続</th>
                <th className="px-3 py-3 font-bold">つながっている口座</th>
                <th className="px-3 py-3 font-bold">自動売買</th>
                <th className="px-3 py-3 font-bold text-right">残高</th>
                <th className="px-3 py-3 font-bold text-right">有効証拠金</th>
                <th className="px-3 py-3 font-bold text-right">建玉</th>
                <th className="px-3 py-3 font-bold text-right">含み損益</th>
                <th className="px-3 py-3 font-bold">返事</th>
                <th className="px-3 py-3 font-bold">操作</th>
              </tr>
            </thead>
            <tbody>
              {allRows.map((row) => {
                const st: RoomState | undefined = fleet.states[row.member_id]
                const s = st?.status
                const refused = optedOut.has(row.member_id)
                const liveAccount = s?.account != null ? String(s.account) : ''
                const mismatch = st?.online && liveAccount && liveAccount !== String(row.account)
                const running = s?.value != null ? Number(s.value) !== 0 : null
                return (
                  <tr key={row.id} className="border-b" style={{ borderColor: 'rgba(94,204,255,0.12)', opacity: refused ? 0.45 : row.included ? 1 : 0.55 }}>
                    <td className="px-3 py-3">
                      {refused ? (
                        <span className="text-[13px] font-bold" style={{ color: '#ffd23e' }}>
                          本人が拒否
                        </span>
                      ) : (
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => void toggleIncluded(row)}
                        className="h-11 rounded-[4px] border px-3 text-[13px] font-bold"
                        style={{
                          borderColor: row.included ? 'var(--accent)' : 'var(--panel-border)',
                          background: row.included ? 'rgba(94,204,255,0.15)' : 'rgba(8,14,26,0.7)',
                          color: row.included ? 'var(--accent)' : '#94a3b8',
                        }}
                      >
                        {row.included ? '対象' : '対象外'}
                      </button>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <div className="font-bold">{row.account}</div>
                      <div className="text-[12px] text-slate-400">{row.server}</div>
                    </td>
                    <td className="px-3 py-3 text-slate-300">{row.virtual ? <span className="text-slate-500">連携のみ</span> : row.email}</td>
                    <td className="px-3 py-3">
                      {st?.online ? (
                        <span style={{ color: '#35f58a' }}>● つながっている</span>
                      ) : st?.pending ? (
                        <span style={{ color: '#ffd23e' }}>○ 切断中（指令を預かり中）</span>
                      ) : (
                        <span className="text-slate-500">○ 切断中</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {liveAccount ? (
                        <span style={{ color: mismatch ? '#ffd23e' : undefined }}>
                          {liveAccount}
                          {mismatch ? '（登録と違う）' : ''}
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {running == null ? (
                        <span className="text-slate-500">—</span>
                      ) : running ? (
                        <span style={{ color: '#35f58a' }}>稼働</span>
                      ) : (
                        <span style={{ color: '#ffd23e' }}>停止</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-right tabular-nums">{money(s?.balance, s?.currency)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{money(s?.equity, s?.currency)}</td>
                    <td className="px-3 py-3 text-right tabular-nums">{s?.today?.open_positions ?? s?.positions?.length ?? '—'}</td>
                    <td className="px-3 py-3 text-right tabular-nums" style={{ color: signColor(s?.today?.open_profit) }}>
                      {money(s?.today?.open_profit, s?.currency, true)}
                    </td>
                    <td className="px-3 py-3 text-[13px]">
                      {st?.ack ? (
                        <span style={{ color: st.ack.ok ? '#35f58a' : '#ff8484' }}>
                          {COMMAND_LABEL[st.ack.command as FleetCommand] ?? st.ack.command}：{st.ack.ok ? '完了' : '失敗'}
                          {DESTRUCTIVE.has(st.ack.command as FleetCommand) && st.ack.ok ? `（決済 ${st.ack.closed ?? 0}・取消 ${st.ack.removed ?? 0}）` : ''}
                          {st.ack.error ? ` ${st.ack.error}` : ''}
                          <span className="ml-1 text-slate-500">{new Date(st.ack.at).toLocaleTimeString('ja-JP')}</span>
                        </span>
                      ) : (
                        <span className="text-slate-500">—</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-2">
                        {row.virtual ? (
                          <Mini
                            onClick={() => {
                              if (st) void addConnected(row.member_id, st)
                            }}
                            disabled={busy || !st}
                          >
                            登録簿に入れる
                          </Mini>
                        ) : (
                          <>
                            <Mini onClick={() => void reveal(row)}>{revealed[row.id] ? '隠す' : 'パスワード'}</Mini>
                            <Mini onClick={() => void remove(row)} disabled={busy}>
                              消す
                            </Mini>
                          </>
                        )}
                      </div>
                      {revealed[row.id] && <div className="mt-1 font-mono text-[13px] text-slate-300">{revealed[row.id]}</div>}
                    </td>
                  </tr>
                )
              })}
              {allRows.length === 0 && (
                <tr>
                  <td colSpan={12} className="px-3 py-8 text-center text-slate-500">
                    まだ口座がありません。口座の PC で MT5 Automatic がサイトと連携すると、ここに「対象」として出ます。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}

function money(v: unknown, currency?: string, sign = false): string {
  if (typeof v !== 'number' || Number.isNaN(v)) return '—'
  const text = v.toLocaleString('ja-JP', { maximumFractionDigits: 2, minimumFractionDigits: 2 })
  return `${sign && v > 0 ? '+' : ''}${text}${currency ? ` ${currency}` : ''}`
}

function signColor(v: unknown): string | undefined {
  if (typeof v !== 'number') return undefined
  if (v > 0) return '#35f58a'
  if (v < 0) return '#ff8484'
  return undefined
}

function Big({
  children,
  onClick,
  disabled,
  tone,
}: {
  children: string
  onClick: () => void
  disabled?: boolean
  tone: 'ok' | 'warn' | 'danger' | 'plain'
}) {
  const color = tone === 'danger' ? '#ff8484' : tone === 'warn' ? '#ffd23e' : tone === 'ok' ? 'var(--accent)' : 'var(--panel-border)'
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="h-12 rounded-[4px] border px-5 text-[15px] font-bold text-slate-100 disabled:opacity-40"
      style={{ borderColor: color, background: 'rgba(8,14,26,0.7)' }}
    >
      {children}
    </button>
  )
}

function Mini({ children, onClick, disabled }: { children: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="h-11 rounded-[4px] border px-3 text-[13px] font-bold text-slate-100 disabled:opacity-40"
      style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' }}
    >
      {children}
    </button>
  )
}
