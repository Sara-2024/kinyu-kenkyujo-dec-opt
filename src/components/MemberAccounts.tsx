// 管理者画面「会員」: お客様を 1 人 1 行に畳んで並べ、開くとその口座のぜんぶが見える。
//
//   畳んだ行 … お名前・口座番号・プラン・稼働の状態・残高・有効証拠金・本日の確定損益・含み損益・建玉の数
//   開いた中 … 稼働状況 ／ 資金状況 ／ 持っているポジション ／ 取引履歴 ／ 会員の設定
//
// 数字は作らない。パスポートが MT5 から読んで中継に預けた値（states）と、開いたときに
// その口座のパスポートへ問い合わせた取引履歴（query）だけを出す。稼働の様子を見るための画面で、
// 売買の良し悪しは言わない。
import { useEffect, useState, type ReactNode } from 'react'
import { memberLabel, type Member, type MemberRole, type MemberStatus } from '../data/auth'
import type { FleetAnswer, FleetCommand, FleetQuery, RoomState } from '../hooks/useFleet'
import { MEMBER_PLANS, PLAN_NAMES, isSubscriptionAccount, type MemberPlan } from '../data/subscription'
import { systemLabel } from '../data/fleet'
import { formatStamp } from '../data/setupFlow'
import type { TradeHistory as TradeHistoryData } from '../data/tradeReview'
import { TRADE_HISTORY } from '../data/characters'
import { Rows as TradeRows, Summary as TradeSummary } from './TradeHistory'

const GREEN = '#35f58a'
const RED = '#ff8484'
const YELLOW = '#ffd23e'
const LINE = 'rgba(94,204,255,0.12)'

/** 畳んだ行と見出しで同じ列幅を使う（数字の桁を縦にそろえる） */
const COLS = '24px minmax(130px,1.3fr) 104px 132px 76px repeat(4,minmax(104px,1fr)) 56px'

type Sort = 'name' | 'today' | 'open' | 'balance'
type Query = (room: string, command: FleetQuery, extra?: { days?: number; limit?: number }) => Promise<FleetAnswer>

export interface MemberAccountsProps {
  rows: Member[]
  states: Record<string, RoomState>
  /** ログイン中の管理者自身（「自分」と添える） */
  selfId?: string
  busyId: string | null
  /** 停止・稼働・全決済を送ったあとの一言（会員ID → 文） */
  sent: Record<string, string>
  query: Query
  onSend: (row: Member, command: FleetCommand) => void
  onPlan: (row: Member, plan: MemberPlan) => void
  onRole: (row: Member, role: MemberRole) => void
  onStatus: (row: Member, status: MemberStatus) => void
  onTrade: (row: Member, canTrade: boolean) => void
  onRemove: (row: Member) => void
  onPassword: (row: Member) => void
  /** パスワード変更の入力欄を出す会員と、その入力欄 */
  passwordTargetId?: string | null
  passwordForm?: ReactNode
}

const num = (v: unknown): number | null => (typeof v === 'number' && !Number.isNaN(v) ? v : null)

function money(v: unknown, currency?: string, sign = false): string {
  const n = num(v)
  if (n == null) return '—'
  const jpy = !currency || currency === 'JPY'
  const text = n.toLocaleString('ja-JP', jpy ? { maximumFractionDigits: 0 } : { maximumFractionDigits: 2, minimumFractionDigits: 2 })
  return `${sign && n > 0 ? '+' : ''}${text}${jpy ? ' 円' : ` ${currency}`}`
}

function pnlColor(v: unknown): string | undefined {
  const n = num(v)
  if (n == null || n === 0) return undefined
  return n > 0 ? GREEN : RED
}

/** その口座がいまどうなっているかの一言（畳んだ行に出す） */
function runState(st: RoomState | undefined): { label: string; color: string } {
  const s = st?.status
  if (!st?.online) return { label: '未接続', color: '#94a3b8' }
  if (s?.mt5_ready === false) return { label: 'MT5 待ち', color: YELLOW }
  if (typeof s?.value !== 'number') return { label: '接続中', color: '#cbd5e1' }
  return s.value !== 0 ? { label: '稼働中', color: GREEN } : { label: '停止中', color: YELLOW }
}

export function MemberAccounts(props: MemberAccountsProps) {
  const { rows, states } = props
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>('name')

  const q = query.trim().toLowerCase()
  const list = rows
    .filter((r) => !q || (r.name ?? '').toLowerCase().includes(q) || String(r.account ?? '').includes(q))
    .map((r) => ({ row: r, st: states[r.id] as RoomState | undefined }))
  const key = (x: (typeof list)[number]): number | string => {
    const s = x.st?.status
    if (sort === 'today') return num(s?.today?.today_profit) ?? -Infinity
    if (sort === 'open') return num(s?.today?.open_profit) ?? -Infinity
    if (sort === 'balance') return num(s?.balance) ?? -Infinity
    return x.row.name ?? ''
  }
  list.sort((a, b) => {
    const ka = key(a)
    const kb = key(b)
    if (typeof ka === 'string' || typeof kb === 'string') return String(ka).localeCompare(String(kb), 'ja')
    return kb - ka // 数字は大きい順
  })

  // 合計は通貨ごと（円とドルの口座を足さない）
  const totals = new Map<string, { balance: number; equity: number; today: number; open: number }>()
  for (const { st } of list) {
    const s = st?.status
    if (!s || num(s.balance) == null) continue
    const cur = s.currency ?? ''
    const t = totals.get(cur) ?? { balance: 0, equity: 0, today: 0, open: 0 }
    t.balance += num(s.balance) ?? 0
    t.equity += num(s.equity) ?? 0
    t.today += num(s.today?.today_profit) ?? 0
    t.open += num(s.today?.open_profit) ?? 0
    totals.set(cur, t)
  }
  const online = list.filter((x) => x.st?.online).length

  return (
    <div className="mt-5 rounded-[4px] border" style={{ borderColor: 'var(--panel-border)', background: 'var(--panel-bg)' }}>
      <div className="flex flex-wrap items-center gap-3 px-4 pt-4">
        <p className="text-[17px] font-bold">お客様の一覧</p>
        <span className="text-[14px] text-slate-400">
          {list.length} 件 ／ パスポート接続中 {online}
        </span>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="お名前・口座番号で探す"
          className="ml-auto h-11 w-60 rounded-[4px] border px-3 text-[15px]"
          style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
        />
        <select
          aria-label="並べ替え"
          value={sort}
          onChange={(e) => setSort(e.target.value as Sort)}
          className="h-11 rounded-[4px] border px-2 text-[14px]"
          style={{ background: 'rgba(8,14,26,0.9)', borderColor: 'var(--panel-border)' }}
        >
          <option value="name">お名前順</option>
          <option value="today">本日の確定損益が多い順</option>
          <option value="open">含み損益が多い順</option>
          <option value="balance">残高が多い順</option>
        </select>
      </div>
      <p className="px-4 pt-2 text-[14px] text-slate-400">
        行を押すと開いて、その口座の稼働状況・資金状況・持っているポジション・取引履歴が見られます。
        数字はお客様のパソコンのパスポートが MT5 から読んだ値です。薄い行はパスポートが切れていて、切れる前の値です。
      </p>

      <div className="mt-3 overflow-x-auto">
        <div className="min-w-[1000px]">
          <div
            className="grid items-center gap-x-3 border-b px-3 py-3 text-[14px] font-bold text-slate-400"
            style={{ gridTemplateColumns: COLS, borderColor: 'var(--panel-border)' }}
          >
            <span />
            <span>お名前</span>
            <span>口座番号</span>
            <span>プラン</span>
            <span>状態</span>
            <span className="text-right">残高</span>
            <span className="text-right">有効証拠金</span>
            <span className="text-right">本日の確定損益</span>
            <span className="text-right">含み損益</span>
            <span className="text-right">建玉</span>
          </div>

          {list.map(({ row, st }) => (
            <MemberRow key={row.id} {...props} row={row} st={st} />
          ))}
          {list.length === 0 && (
            <p className="px-3 py-8 text-center text-[15px] text-slate-500">{q ? '該当する口座がありません。' : 'まだアカウントがありません。'}</p>
          )}

          {[...totals.entries()].map(([cur, t]) => (
            <div
              key={cur}
              className="grid items-center gap-x-3 px-3 py-3 text-[15px] font-bold tabular-nums"
              style={{ gridTemplateColumns: COLS, background: 'rgba(94,204,255,0.06)' }}
            >
              <span />
              <span style={{ gridColumn: 'span 4' }}>合計{totals.size > 1 && cur ? `（${cur}）` : ''}</span>
              <span className="text-right">{money(t.balance, cur)}</span>
              <span className="text-right">{money(t.equity, cur)}</span>
              <span className="text-right" style={{ color: pnlColor(t.today) }}>{money(t.today, cur, true)}</span>
              <span className="text-right" style={{ color: pnlColor(t.open) }}>{money(t.open, cur, true)}</span>
              <span />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function MemberRow(props: MemberAccountsProps & { row: Member; st: RoomState | undefined }) {
  const { row, st, selfId } = props
  const [open, setOpen] = useState(false)
  const s = st?.status ?? null
  const cur = s?.currency
  const today = s?.today
  const state = runState(st)
  const sub = isSubscriptionAccount(row.plan, s)
  const plan = (row.plan ?? (sub ? 'subscription' : null)) as MemberPlan | null
  const count = today?.open_positions ?? (s?.positions ? s.positions.length : null)
  const panelId = `member-${row.id}`

  return (
    <div className="border-b" style={{ borderColor: LINE }}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
        className="grid min-h-[56px] w-full items-center gap-x-3 px-3 py-2 text-left text-[15px] transition hover:brightness-125"
        style={{ gridTemplateColumns: COLS, background: open ? 'rgba(94,204,255,0.08)' : 'transparent', opacity: st?.online || open ? 1 : 0.6 }}
      >
        <span aria-hidden className="text-[16px]" style={{ color: 'var(--accent)' }}>
          {open ? '▼' : '▶'}
        </span>
        <span className="font-bold">
          {row.name || row.email || '—'}
          {row.id === selfId && <span className="ml-2 text-[13px] font-normal text-slate-500">自分</span>}
          {row.role === 'admin' && <span className="ml-2 text-[13px] font-normal text-slate-400">管理者</span>}
          {row.status !== 'active' && <span className="ml-2 text-[13px]" style={{ color: RED }}>BAN中</span>}
        </span>
        <span className="font-mono">{row.account ?? s?.account ?? '—'}</span>
        <span className="text-[14px]" style={{ color: sub ? '#f4c46a' : row.plan === 'crystal' ? '#e8d8a8' : '#cbd5e1' }}>
          {plan ? PLAN_NAMES[plan] : '—'}
        </span>
        <span className="font-bold" style={{ color: state.color }}>{state.label}</span>
        <span className="text-right tabular-nums">{money(s?.balance, cur)}</span>
        <span className="text-right tabular-nums">{money(s?.equity, cur)}</span>
        <span className="text-right tabular-nums" style={{ color: pnlColor(today?.today_profit) }}>{money(today?.today_profit, cur, true)}</span>
        <span className="text-right tabular-nums" style={{ color: pnlColor(today?.open_profit) }}>{money(today?.open_profit, cur, true)}</span>
        <span className="text-right tabular-nums">{count != null ? `${count} 件` : '—'}</span>
      </button>
      {open && (
        <div id={panelId} className="px-4 pb-6 pt-2" style={{ background: 'rgba(4,8,16,0.55)' }}>
          <Detail {...props} />
        </div>
      )}
    </div>
  )
}

function SectionTitle({ children, note }: { children: string; note?: string }) {
  return (
    <div className="mb-2 mt-5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className="h-3 w-[3px] self-center" style={{ background: 'var(--accent)' }} />
      <p className="text-[16px] font-bold text-slate-100">{children}</p>
      {note && <p className="text-[13px] text-slate-500">{note}</p>}
    </div>
  )
}

function Fact({ label, value, color, note }: { label: string; value: ReactNode; color?: string; note?: string }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b py-2" style={{ borderColor: LINE }}>
      <span className="shrink-0 text-[15px] text-slate-400">{label}</span>
      <span className="text-right text-[16px] font-bold tabular-nums" style={{ color: color ?? '#e8edf5' }}>
        {value}
        {note && <span className="block text-[13px] font-normal text-slate-500">{note}</span>}
      </span>
    </div>
  )
}

function Detail(props: MemberAccountsProps & { row: Member; st: RoomState | undefined }) {
  const { row, st, busyId, sent, onSend } = props
  const s = st?.status ?? null
  const cur = s?.currency
  const today = s?.today
  const funds = s?.funds ?? null
  const online = !!st?.online
  const busy = busyId === row.id
  const state = runState(st)
  const positions = s?.positions ?? []
  const mismatch = online && s?.account != null && row.account != null && String(s.account) !== String(row.account)
  const pc = (s?.platform ?? row.platform) === 'mac' ? 'Mac' : (s?.platform ?? row.platform) === 'windows' ? 'Windows' : '—'

  return (
    <>
      {!online && (
        <p className="pt-3 text-[15px]" style={{ color: YELLOW }}>
          {s ? 'パスポートがつながっていません。下の数字は、切れる前に最後に届いた値です。' : 'パスポートがつながっていないので、口座の数字はまだ届いていません。'}
        </p>
      )}

      <div className="flex flex-wrap gap-x-10">
        <div className="min-w-[320px] flex-1">
          <SectionTitle>稼働状況</SectionTitle>
          <Fact label="自動売買" value={state.label} color={state.color} />
          <Fact
            label="パスポート"
            value={online ? '接続中' : '未接続'}
            color={online ? GREEN : '#94a3b8'}
            note={online && st?.since ? `${new Date(st.since).toLocaleString('ja-JP')} から` : undefined}
          />
          {online && (
            <Fact
              label="MT5"
              value={s?.mt5_ready === false ? '閉じている／ログインしていません' : s?.terminal_trade_allowed === false ? '「アルゴ取引」ボタンが OFF' : 'つながっています'}
              color={s?.mt5_ready === false || s?.terminal_trade_allowed === false ? YELLOW : undefined}
            />
          )}
          {online && s?.mt5_ready !== false && (
            <Fact
              label="チャートのシステム"
              value={s?.ea_alive ? '動いています' : '動いていません'}
              color={s?.ea_alive ? undefined : YELLOW}
              note={s?.ea_problem ?? (s?.ea_symbol ? `${s.ea_symbol} のチャート` : undefined)}
            />
          )}
          <Fact label="システム" value={systemLabel(s)} />
          <Fact
            label="つないでいる口座"
            value={s?.account != null ? `${s.account}${s.server ? ` ／ ${s.server}` : ''}` : row.connected_account ? `${row.connected_account}${row.server ? ` ／ ${row.server}` : ''}` : '—'}
            color={mismatch ? RED : undefined}
            note={mismatch ? `登録した口座（${row.account}）と違います` : undefined}
          />
          {typeof s?.intent === 'number' && (
            <Fact label="最後の指示" value={s.intent !== 0 ? '稼働' : '停止'} note={s.intent_at ? formatStamp(s.intent_at) : undefined} />
          )}
          <Fact label="パソコン" value={pc} note={s?.version ? `パスポートの版 ${s.version}` : undefined} />
          <Fact label="最終ログイン" value={row.last_login_at ? new Date(row.last_login_at).toLocaleString('ja-JP') : '—'} />

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <Mini disabled={!online || busy} onClick={() => onSend(row, 'stop_trading')}>停止（新規だけ止める）</Mini>
            <Mini disabled={!online || busy} onClick={() => onSend(row, 'start_trading')}>稼働</Mini>
            <Mini disabled={!online || busy} onClick={() => onSend(row, 'close_all')}>全決済</Mini>
          </div>
          {sent[row.id] && <p className="mt-2 text-[14px] text-slate-400">{sent[row.id]}</p>}
          {st?.ack && (
            <p className="mt-1 text-[14px]" style={{ color: st.ack.ok ? GREEN : RED }}>
              {st.ack.ok ? 'パスポートが実行しました' : `失敗: ${st.ack.error ?? ''}`}
            </p>
          )}
        </div>

        <div className="min-w-[320px] flex-1">
          <SectionTitle note={s?.server_time ? `ブローカーの時計で ${formatStamp(s.server_time)} 時点` : undefined}>資金状況</SectionTitle>
          <Fact label="残高" value={money(s?.balance, cur)} />
          <Fact label="有効証拠金" value={money(s?.equity, cur)} note="残高 ＋ 含み損益" />
          <Fact label="含み損益" value={money(today?.open_profit, cur, true)} color={pnlColor(today?.open_profit)} />
          <Fact
            label="本日の確定損益"
            value={money(today?.today_profit, cur, true)}
            color={pnlColor(today?.today_profit)}
            note={(today?.today_closed ?? 0) > 0 ? `決済 ${today?.today_closed} 回（勝ち ${today?.today_wins ?? 0}・負け ${today?.today_losses ?? 0}）` : undefined}
          />
          {funds ? (
            <>
              <Fact label="入金の合計" value={money(funds.deposit, cur)} />
              <Fact label="出金の合計" value={funds.withdrawal ? money(funds.withdrawal, cur) : 'なし'} />
              {(num(funds.credit) ?? 0) !== 0 && <Fact label="クレジット（ボーナス）" value={money(funds.credit, cur)} />}
              <Fact
                label="トータル損益"
                value={money(funds.total_profit, cur, true)}
                color={pnlColor(funds.total_profit)}
                note="有効証拠金 − クレジット − 入金 ＋ 出金"
              />
            </>
          ) : (
            s && <p className="pt-2 text-[14px] text-slate-500">入金・出金・トータル損益は、お客様のパスポートが新しい版になると出ます。</p>
          )}
        </div>
      </div>

      <SectionTitle note={positions.length > 0 ? `${positions.length} 件` : undefined}>持っているポジション</SectionTitle>
      {positions.length === 0 ? (
        <p className="text-[15px] text-slate-400">{s ? 'いま持っているポジションはありません。' : '—'}</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-left text-[15px]">
            <thead>
              <tr className="border-b text-[14px] text-slate-400" style={{ borderColor: 'rgba(94,204,255,0.18)' }}>
                <th className="py-2 pr-4 font-bold">建てた日時</th>
                <th className="py-2 pr-4 font-bold">銘柄</th>
                <th className="py-2 pr-4 font-bold">売買</th>
                <th className="py-2 pr-4 font-bold">ロット</th>
                <th className="py-2 pr-4 text-right font-bold">建値</th>
                <th className="py-2 pr-4 text-right font-bold">現在値</th>
                <th className="py-2 pr-4 text-right font-bold">損切り</th>
                <th className="py-2 pr-4 text-right font-bold">利確</th>
                <th className="py-2 pr-4 text-right font-bold">スワップ</th>
                <th className="py-2 text-right font-bold">含み損益</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((p) => {
                const price = (v: unknown) => (num(v) != null && (v as number) > 0 ? (v as number).toFixed(p.digits ?? 2) : '—')
                return (
                  <tr key={p.ticket} className="border-b font-mono tabular-nums" style={{ borderColor: LINE }}>
                    <td className="py-2.5 pr-4 text-slate-400">{formatStamp(p.opened_at) || '—'}</td>
                    <td className="py-2.5 pr-4 font-sans font-bold text-slate-100">{p.symbol}</td>
                    <td className="py-2.5 pr-4 font-sans font-bold" style={{ color: p.side === 'buy' ? GREEN : RED }}>
                      {p.side === 'buy' ? '買い' : '売り'}
                    </td>
                    <td className="py-2.5 pr-4">{num(p.volume) != null ? p.volume.toFixed(2) : '—'}</td>
                    <td className="py-2.5 pr-4 text-right text-slate-300">{price(p.price_open)}</td>
                    <td className="py-2.5 pr-4 text-right text-slate-300">{price(p.price_current)}</td>
                    <td className="py-2.5 pr-4 text-right text-slate-400">{price(p.sl)}</td>
                    <td className="py-2.5 pr-4 text-right text-slate-400">{price(p.tp)}</td>
                    <td className="py-2.5 pr-4 text-right text-slate-400">{num(p.swap) != null && p.swap !== 0 ? money(p.swap, cur, true) : '—'}</td>
                    <td className="py-2.5 text-right font-bold" style={{ color: pnlColor(p.profit) }}>{money(p.profit, cur, true)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      <History room={row.id} online={online} query={props.query} fallbackCurrency={cur} />

      <MemberSettings {...props} />
    </>
  )
}

const PERIODS = [7, 30, 90, 180] as const
/** 一度に出す件数。増やすと、お客様のパソコンの MT5 への問い合わせが重くなる */
const HISTORY_LIMIT = 200

/** その口座の取引履歴。開いたときと、期間を変えたとき、「最新にする」を押したときだけ読みに行く */
function History({ room, online, query, fallbackCurrency }: { room: string; online: boolean; query: Query; fallbackCurrency?: string }) {
  const [days, setDays] = useState<number>(30)
  const [history, setHistory] = useState<TradeHistoryData | null>(null)
  const [currency, setCurrency] = useState<string | undefined>(fallbackCurrency)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!online) return
    let alive = true
    setLoading(true)
    setFailed(null)
    void query(room, 'get_trades', { days, limit: HISTORY_LIMIT }).then((ack) => {
      if (!alive) return
      setLoading(false)
      const data = ack.trades as TradeHistoryData | undefined
      if (!ack.ok || !data || !Array.isArray(data.trades)) {
        setFailed(ack.error || TRADE_HISTORY.failed)
        return
      }
      setHistory(data)
      if (typeof ack.currency === 'string') setCurrency(ack.currency)
    })
    return () => {
      alive = false
    }
  }, [room, online, days, tick, query])

  return (
    <>
      <SectionTitle note="決済した取引。時刻はブローカーのサーバー時計">取引履歴</SectionTitle>
      <div className="flex flex-wrap items-center gap-2" role="group" aria-label="履歴の期間">
        {PERIODS.map((d) => (
          <button
            key={d}
            type="button"
            aria-pressed={days === d}
            disabled={!online}
            onClick={() => setDays(d)}
            className="h-11 rounded-full border px-4 text-[15px] disabled:opacity-40"
            style={{
              borderColor: days === d ? 'var(--accent)' : 'var(--panel-border)',
              color: days === d ? 'var(--accent)' : '#cbd5e1',
              background: 'rgba(8,14,26,0.7)',
            }}
          >
            過去 {d} 日
          </button>
        ))}
        <Mini disabled={!online || loading} onClick={() => setTick((n) => n + 1)}>
          {loading ? '読み取り中…' : TRADE_HISTORY.reload}
        </Mini>
      </div>

      {!online && <p className="mt-3 text-[15px] text-slate-400">取引履歴は、お客様のパスポートがつながっているときに読めます。{history ? '下は、さきほど読んだぶんです。' : ''}</p>}
      {online && loading && !history && <p className="mt-3 text-[15px] text-slate-400">{TRADE_HISTORY.loading}</p>}
      {failed && <p className="mt-3 text-[15px]" style={{ color: RED }}>⚠ {failed}</p>}
      {history &&
        (history.trades.length === 0 ? (
          <p className="mt-3 text-[15px] text-slate-400">{TRADE_HISTORY.empty.replace('{days}', String(history.days))}</p>
        ) : (
          <div className="mt-3 rounded-[4px] border" style={{ borderColor: LINE, opacity: loading ? 0.6 : 1 }}>
            <TradeSummary history={history} currency={currency} />
            <div className="max-h-[460px] overflow-y-auto pt-3">
              <TradeRows trades={history.trades} currency={currency} />
            </div>
          </div>
        ))}
    </>
  )
}

/** 会員そのものの設定（プラン・権限・BAN など）。口座の様子とは別なので、いちばん下に置く */
function MemberSettings(props: MemberAccountsProps & { row: Member }) {
  const { row, busyId, onPlan, onRole, onStatus, onTrade, onRemove, onPassword, passwordTargetId, passwordForm } = props
  const busy = busyId === row.id
  return (
    <>
      <SectionTitle note={`${row.role === 'admin' ? '管理者' : '一般'} ／ ${row.status === 'active' ? '利用中' : 'BAN中'} ／ お客様の操作は${row.can_trade ? '許可' : '不可'}`}>
        会員の設定
      </SectionTitle>
      <div className="flex flex-wrap items-center gap-2">
        {/* プランはここで直せる。ロイヤル（crystal）だけが同じ PC に 2 つ目の口座を足せる */}
        <label className="flex items-center gap-2 text-[15px] text-slate-300">
          プラン
          <select
            value={row.plan ?? ''}
            disabled={busy}
            onChange={(e) => {
              const next = e.target.value as MemberPlan | ''
              if (!next || next === row.plan) return
              if (!window.confirm(`${memberLabel(row)} のプランを「${PLAN_NAMES[next]}」にします。よろしいですか？`)) return
              onPlan(row, next)
            }}
            className="h-11 rounded-[4px] border px-2 text-[15px]"
            style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)', color: row.plan ? '#e2e8f0' : '#94a3b8' }}
          >
            <option value="">—（未設定）</option>
            {MEMBER_PLANS.map((p) => (
              <option key={p} value={p}>{PLAN_NAMES[p]}</option>
            ))}
          </select>
        </label>
        <Mini disabled={busy} onClick={() => onTrade(row, !row.can_trade)}>{row.can_trade ? 'お客様の操作を禁止' : 'お客様の操作を許可'}</Mini>
        <Mini disabled={busy} onClick={() => onPassword(row)}>パスワード変更</Mini>
        <Mini disabled={busy} onClick={() => onRole(row, row.role === 'admin' ? 'user' : 'admin')}>{row.role === 'admin' ? '一般にする' : '管理者にする'}</Mini>
        <Mini disabled={busy} onClick={() => onStatus(row, row.status === 'active' ? 'suspended' : 'active')}>{row.status === 'active' ? 'BAN' : 'BAN解除'}</Mini>
        <Mini disabled={busy} onClick={() => onRemove(row)}>削除</Mini>
      </div>
      {passwordTargetId === row.id && passwordForm}
    </>
  )
}

function Mini({ children, onClick, disabled }: { children: string; onClick: () => void; disabled?: boolean }) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="h-11 rounded-[4px] border px-4 text-[15px] font-bold text-slate-100 disabled:opacity-40"
      style={{ borderColor: 'var(--panel-border)', background: 'rgba(8,14,26,0.7)' }}
    >
      {children}
    </button>
  )
}
