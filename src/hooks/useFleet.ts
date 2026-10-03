// 一斉制御の画面と中継（/fleet）をつなぐ。
//
// 1口座ずつの画面（useBridge）は自分の部屋に入って指令を出すが、こちらは
// 部屋を持たず、宛先の部屋を名指しして同じ指令を一度に流す。
// 口座の数字は中継が覚えている要約（hello / status_update）をそのまま使う。
import { useCallback, useEffect, useRef, useState } from 'react'
import { WS_URL, type BridgeStatus } from './useBridge'

export type FleetCommand = 'stop_trading' | 'close_all' | 'stop_system' | 'start_trading'

export interface RoomState {
  online: boolean
  since: number | null
  status: BridgeStatus | null
  /** ブリッジが居ないあいだに預かっている指令 */
  pending: string | null
  /** 最後に送った指令への応答 */
  ack?: { command: string; ok: boolean; error?: string; closed?: number; removed?: number; at: number }
}

export interface SendResult {
  id: string
  command: FleetCommand
  delivered: string[]
  waiting: string[]
  /** 本人が「受け付けない」と決めていたので、中継が外した部屋 */
  refused?: string[]
}

export type FleetPhase = 'connecting' | 'live' | 'denied' | 'error'

function fleetUrl(session: string): string {
  const base = WS_URL.replace(/\/app(\?.*)?$/, '/fleet')
  const sep = base.includes('?') ? '&' : '?'
  return `${base}${sep}session=${encodeURIComponent(session)}`
}

export function useFleet(session: string | null, rooms: string[]) {
  const [phase, setPhase] = useState<FleetPhase>('connecting')
  const [states, setStates] = useState<Record<string, RoomState>>({})
  const wsRef = useRef<WebSocket | null>(null)
  const seq = useRef(0)
  const pendingSend = useRef(new Map<string, (r: SendResult) => void>())
  const roomsKey = rooms.slice().sort().join(',')

  const patch = useCallback((room: string, fn: (prev: RoomState) => RoomState) => {
    setStates((prev) => {
      const base: RoomState = prev[room] ?? { online: false, since: null, status: null, pending: null }
      return { ...prev, [room]: fn(base) }
    })
  }, [])

  const watch = useCallback(() => {
    const ws = wsRef.current
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({ type: 'fleet_watch', id: `w${++seq.current}`, rooms: roomsKey ? roomsKey.split(',') : [] }))
  }, [roomsKey])

  useEffect(() => {
    if (!session) return
    let closed = false
    let retry: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (closed) return
      setPhase('connecting')
      let ws: WebSocket
      try {
        ws = new WebSocket(fleetUrl(session))
      } catch {
        setPhase('error')
        retry = setTimeout(connect, 5000)
        return
      }
      wsRef.current = ws
      let opened = false

      ws.onopen = () => {
        opened = true
        setPhase('live')
        watch()
      }
      ws.onmessage = (event) => {
        let payload: Record<string, unknown>
        try {
          payload = JSON.parse(event.data)
        } catch {
          return
        }
        if (payload.type === 'fleet_snapshot') {
          const summary = (payload.rooms as Record<string, Omit<RoomState, 'ack'>>) ?? {}
          setStates((prev) => {
            const next: Record<string, RoomState> = {}
            for (const [room, s] of Object.entries(summary)) next[room] = { ...s, ack: prev[room]?.ack }
            return next
          })
          return
        }
        if (payload.type === 'fleet_sent') {
          const r = payload as unknown as SendResult
          pendingSend.current.get(r.id)?.(r)
          pendingSend.current.delete(r.id)
          for (const room of r.waiting) patch(room, (p) => ({ ...p, pending: r.command }))
          return
        }
        if (payload.type === 'fleet_event') {
          const room = String(payload.room ?? '')
          const msg = (payload.message ?? {}) as Record<string, unknown>
          if (msg.type === 'bridge_online') {
            patch(room, (p) => ({ ...p, online: true, since: Date.now(), status: msg.status as BridgeStatus, pending: null }))
          } else if (msg.type === 'bridge_status') {
            patch(room, (p) => ({ ...p, online: true, status: msg.status as BridgeStatus }))
          } else if (msg.type === 'bridge_offline') {
            patch(room, (p) => ({ ...p, online: false, since: null }))
          } else if (msg.type === 'ack' && typeof msg.command === 'string') {
            const command = msg.command
            patch(room, (p) => ({
              ...p,
              ack: {
                command,
                ok: Boolean(msg.ok),
                error: msg.error ? String(msg.error) : undefined,
                closed: typeof msg.closed === 'number' ? msg.closed : undefined,
                removed: typeof msg.removed === 'number' ? msg.removed : undefined,
                at: Date.now(),
              },
            }))
          }
        }
      }
      ws.onclose = (ev) => {
        wsRef.current = null
        if (closed) return
        // 管理者でない／会員の確認が無い中継は 403 で断られ、開く前に閉じる
        setPhase(opened ? 'connecting' : 'denied')
        if (ev.code !== 1000) retry = setTimeout(connect, opened ? 3000 : 10000)
      }
      ws.onerror = () => {
        /* onclose で扱う */
      }
    }
    connect()
    return () => {
      closed = true
      if (retry) clearTimeout(retry)
      wsRef.current?.close(1000)
      wsRef.current = null
    }
  }, [session, watch, patch])

  // 見る部屋が変わったら、見直す
  useEffect(() => {
    watch()
  }, [watch])

  // 中継の要約は「変わったとき」しか届かないので、30秒に一度は取り直す
  useEffect(() => {
    const id = setInterval(watch, 30_000)
    return () => clearInterval(id)
  }, [watch])

  const send = useCallback(
    (command: FleetCommand, targets: string[], reason = '一斉制御'): Promise<SendResult> => {
      const ws = wsRef.current
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        return Promise.reject(new Error('中継につながっていません'))
      }
      const id = `f${Date.now()}-${++seq.current}`
      return new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          pendingSend.current.delete(id)
          reject(new Error('中継から返事がありません'))
        }, 8000)
        pendingSend.current.set(id, (r) => {
          clearTimeout(timer)
          resolve(r)
        })
        ws.send(JSON.stringify({ type: 'fleet_send', id, command, rooms: targets, reason }))
      })
    },
    [],
  )

  return { phase, states, send, refresh: watch }
}
