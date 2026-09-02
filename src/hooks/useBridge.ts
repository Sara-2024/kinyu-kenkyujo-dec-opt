// 中継サーバー経由で、MT5のそばにいるブリッジとやり取りする。
// 接続に失敗した場合は黙ってモックに落とさず、エラーコードを返す。
import { useCallback, useEffect, useRef, useState } from 'react'
import type { BridgeError, BridgeErrorCode } from '../data/bridgeErrors'
import type { HistoryStats, PositionRow, TodayStats } from '../data/setupFlow'
import type { TradeHistory } from '../data/tradeReview'

export interface BridgeStatus {
  bridgeId: string
  account?: number | string
  server?: string
  balance?: number
  equity?: number
  currency?: string
  value?: number
  variable?: string
  mt5_ready?: boolean
  terminal_connected?: boolean
  terminal_trade_allowed?: boolean
  build?: number
  terminal_name?: string
  ea_installed?: boolean
  ea_found?: string[]
  ea_compiled?: string[]
  gate?: Record<string, number>
  today?: TodayStats
  /** ブリッジが数秒ごとに送ってくる建玉。画面はこれを見るだけでよい */
  positions?: PositionRow[]
  /** ブローカーのサーバー時刻 */
  server_time?: string
  /** 動いているブリッジの版 */
  version?: string
  /** MT5 のチャートに実際に出ている状態（EAが書き出したもの） */
  ea_state?: string | null
  ea_allowed?: string | null
  ea_state_at?: string | null
  ea_name?: string | null
  /** EA が生きているか（10秒ごとの書き込みが届いているか） */
  ea_alive?: boolean
  /** EA とブリッジが同じフォルダを見ているか */
  ea_same_folder?: boolean | null
  /** サイトから最後に指示された状態と、その時刻・出どころ */
  intent?: number
  intent_by?: string
  intent_at?: string
  gate_path?: string | null
}

type Ack = {
  type: 'ack'
  id?: string
  command?: string
  ok: boolean
  value?: number
  error?: string
  /** get_positions の応答 */
  positions?: PositionRow[]
  /** get_history の応答 */
  history?: HistoryStats
  /** get_trades の応答（添削のもと） */
  trades?: TradeHistory
} & Partial<BridgeStatus>

export type BridgeAck = Ack

export type BridgePhase = 'connecting' | 'live' | 'no_bridge' | 'error'

/** 接続先。未設定ならローカルの中継サーバー */
export const WS_URL = import.meta.env.VITE_RELAY_URL || 'ws://localhost:8080/app'

function appUrl(roomId?: string | null): string {
  if (!roomId) return WS_URL
  const sep = WS_URL.includes('?') ? '&' : '?'
  return `${WS_URL}${sep}room=${encodeURIComponent(roomId)}`
}

const STATUS_KEYS: (keyof BridgeStatus)[] = [
  'bridgeId',
  'account',
  'server',
  'balance',
  'equity',
  'currency',
  'value',
  'variable',
  'mt5_ready',
  'terminal_connected',
  'terminal_trade_allowed',
  'build',
  'terminal_name',
  'ea_installed',
  'ea_found',
  'ea_compiled',
  'gate',
  'today',
  'positions',
  'server_time',
  'version',
  'ea_state',
  'ea_allowed',
  'ea_state_at',
  'ea_name',
  'ea_alive',
  'ea_same_folder',
  'intent',
  'intent_by',
  'intent_at',
  'gate_path',
]

function definedFields(extra: Partial<BridgeStatus> & Record<string, unknown>): Partial<BridgeStatus> {
  const out: Partial<BridgeStatus> = {}
  for (const key of STATUS_KEYS) {
    if (extra[key] !== undefined) {
      ;(out as Record<string, unknown>)[key] = extra[key]
    }
  }
  return out
}

function mergeStatus(prev: BridgeStatus | null, extra: Partial<BridgeStatus> & { bridgeId?: string }): BridgeStatus {
  const patch = definedFields(extra)
  const bridgeId = String(extra.bridgeId ?? prev?.bridgeId ?? patch.bridgeId ?? '')
  return {
    ...(prev ?? { bridgeId }),
    ...patch,
    bridgeId,
  }
}

export function useBridge(roomId?: string | null) {
  const [phase, setPhase] = useState<BridgePhase>('connecting')
  const [error, setError] = useState<BridgeError | null>(null)
  const [status, setStatus] = useState<BridgeStatus | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const waiting = useRef(new Map<string, (ack: Ack) => void>())
  const seq = useRef(0)
  const hadLive = useRef(false)
  const offlineTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  const live = phase === 'live'

  const setErr = (code: BridgeErrorCode, detail?: string) => {
    setError({ code, detail })
    setPhase(code === 'E003' || code === 'E004' ? 'no_bridge' : 'error')
    if (detail) console.warn(`[bridge] ${code}`, detail)
  }

  useEffect(() => {
    if (!roomId) {
      setStatus(null)
      setErr('E003')
      return
    }

    let closed = false
    let retry: ReturnType<typeof setTimeout> | null = null

    const target = appUrl(roomId)

    const connect = () => {
      if (closed) return
      setPhase('connecting')
      setError(null)

      let ws: WebSocket
      try {
        ws = new WebSocket(target)
      } catch (e) {
        setErr('E001', `${target} — ${e instanceof Error ? e.message : 'open failed'}`)
        retry = setTimeout(connect, 5000)
        return
      }
      wsRef.current = ws

      ws.onopen = () => {
        if (closed) return
        // welcome メッセージ待ち。ブリッジ無しなら E003 は onmessage で判定
      }

      ws.onmessage = (event) => {
        let payload: Record<string, unknown>
        try {
          payload = JSON.parse(event.data)
        } catch {
          return
        }

        if (payload.type === 'welcome') {
          const list = ((payload.bridges as BridgeStatus[]) ?? []).filter((row) =>
            roomId ? String(row.bridgeId) === roomId : true,
          )
          if (list.length > 0) {
            setStatus(list[0])
            setPhase('live')
            setError(null)
            hadLive.current = true
          } else {
            setStatus(null)
            setErr('E003', `relay=${target}`)
          }
          return
        }

        if (roomId && payload.bridgeId && String(payload.bridgeId) !== roomId) return

        if (payload.type === 'bridge_online') {
          if (offlineTimer.current) {
            clearTimeout(offlineTimer.current)
            offlineTimer.current = null
          }
          setStatus({ ...(payload.status as BridgeStatus), bridgeId: String(payload.bridgeId ?? roomId ?? '') })
          setPhase('live')
          setError(null)
          hadLive.current = true
          return
        }

        if (payload.type === 'bridge_status') {
          if (offlineTimer.current) {
            clearTimeout(offlineTimer.current)
            offlineTimer.current = null
          }
          setStatus({ ...(payload.status as BridgeStatus), bridgeId: String(payload.bridgeId ?? roomId ?? '') })
          setPhase('live')
          setError(null)
          hadLive.current = true
          return
        }

        if (payload.type === 'bridge_offline') {
          // 二重起動の交代では一瞬切断になるので、すぐにはエラーにしない
          if (offlineTimer.current) clearTimeout(offlineTimer.current)
          offlineTimer.current = setTimeout(() => {
            setStatus(null)
            setErr('E004', String(payload.bridgeId ?? ''))
          }, 1500)
          return
        }

        if (payload.type === 'ack') {
          const ack = payload as unknown as Ack
          if (ack.id && waiting.current.has(ack.id)) {
            waiting.current.get(ack.id)?.(ack)
            waiting.current.delete(ack.id)
          }
          if (ack.ok) {
            setStatus((s) => mergeStatus(s, ack))
          } else if (typeof ack.value === 'number') {
            setStatus((s) => (s ? { ...s, value: ack.value } : s))
          }
        }
      }

      ws.onclose = (ev) => {
        if (wsRef.current !== ws) return
        setPhase(hadLive.current ? 'error' : 'connecting')
        setErr('E002', `code=${ev.code} relay=${target}`)
        wsRef.current = null
        if (!closed) retry = setTimeout(connect, 5000)
      }

      ws.onerror = () => {
        setErr('E001', target)
      }
    }

    connect()
    return () => {
      closed = true
      if (retry) clearTimeout(retry)
      if (offlineTimer.current) clearTimeout(offlineTimer.current)
      wsRef.current?.close()
    }
  }, [roomId])

  const send = useCallback(
    (command: string, extra: Record<string, unknown> = {}): Promise<Ack> =>
      new Promise((resolve) => {
        const ws = wsRef.current
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          resolve({ type: 'ack', ok: false, error: 'E005: WebSocket not open' })
          return
        }
        if (phase !== 'live') {
          resolve({ type: 'ack', ok: false, error: 'E003: bridge not live' })
          return
        }
        const id = `app-${++seq.current}`
        waiting.current.set(id, resolve)
        ws.send(JSON.stringify({ id, command, ...(roomId ? { bridgeId: roomId } : {}), ...extra }))
        setTimeout(() => {
          if (waiting.current.has(id)) {
            waiting.current.delete(id)
            resolve({ type: 'ack', ok: false, error: 'E006: timeout' })
          }
        }, 12000)
      }),
    [phase, roomId],
  )

  return { live, phase, status, error, wsUrl: appUrl(roomId), send }
}
