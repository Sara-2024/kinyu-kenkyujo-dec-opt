// 中継サーバー経由で、MT5のそばにいるブリッジとやり取りする。
// 接続に失敗した場合は黙ってモックに落とさず、エラーコードを返す。
import { useCallback, useEffect, useRef, useState } from 'react'
import type { BridgeError, BridgeErrorCode } from '../data/bridgeErrors'

export interface BridgeStatus {
  bridgeId: string
  account?: number | string
  server?: string
  balance?: number
  equity?: number
  value?: number
  variable?: string
  mt5_ready?: boolean
  terminal_connected?: boolean
}

type Ack = {
  type: 'ack'
  id?: string
  command?: string
  ok: boolean
  value?: number
  error?: string
}

export type BridgePhase = 'connecting' | 'live' | 'no_bridge' | 'error'

/** 接続先。未設定ならローカルの中継サーバー */
export const WS_URL = import.meta.env.VITE_RELAY_URL || 'ws://localhost:8080/app'

export function useBridge() {
  const [phase, setPhase] = useState<BridgePhase>('connecting')
  const [error, setError] = useState<BridgeError | null>(null)
  const [status, setStatus] = useState<BridgeStatus | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const waiting = useRef(new Map<string, (ack: Ack) => void>())
  const seq = useRef(0)
  const hadLive = useRef(false)

  const live = phase === 'live'

  const setErr = (code: BridgeErrorCode, detail?: string) => {
    setError({ code, detail })
    setPhase(code === 'E003' || code === 'E004' ? 'no_bridge' : 'error')
  }

  useEffect(() => {
    let closed = false
    let retry: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (closed) return
      setPhase('connecting')
      setError(null)

      let ws: WebSocket
      try {
        ws = new WebSocket(WS_URL)
      } catch (e) {
        setErr('E001', `${WS_URL} — ${e instanceof Error ? e.message : 'open failed'}`)
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
          const list = (payload.bridges as BridgeStatus[]) ?? []
          if (list.length > 0) {
            setStatus(list[0])
            setPhase('live')
            setError(null)
            hadLive.current = true
          } else {
            setStatus(null)
            setErr('E003', `relay=${WS_URL}`)
          }
          return
        }

        if (payload.type === 'bridge_online') {
          setStatus({ ...(payload.status as BridgeStatus), bridgeId: String(payload.bridgeId) })
          setPhase('live')
          setError(null)
          hadLive.current = true
          return
        }

        if (payload.type === 'bridge_offline') {
          setStatus(null)
          setErr('E004', String(payload.bridgeId ?? ''))
          return
        }

        if (payload.type === 'ack') {
          const ack = payload as unknown as Ack
          if (ack.id && waiting.current.has(ack.id)) {
            waiting.current.get(ack.id)?.(ack)
            waiting.current.delete(ack.id)
          }
          if (typeof ack.value === 'number') {
            setStatus((s) => (s ? { ...s, value: ack.value } : s))
          }
        }
      }

      ws.onclose = (ev) => {
        if (wsRef.current !== ws) return
        setPhase(hadLive.current ? 'error' : 'connecting')
        setErr('E002', `code=${ev.code} relay=${WS_URL}`)
        wsRef.current = null
        if (!closed) retry = setTimeout(connect, 5000)
      }

      ws.onerror = () => {
        setErr('E001', WS_URL)
      }
    }

    connect()
    return () => {
      closed = true
      if (retry) clearTimeout(retry)
      wsRef.current?.close()
    }
  }, [])

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
        ws.send(JSON.stringify({ id, command, ...extra }))
        setTimeout(() => {
          if (waiting.current.has(id)) {
            waiting.current.delete(id)
            resolve({ type: 'ack', ok: false, error: 'E006: timeout' })
          }
        }, 8000)
      }),
    [phase],
  )

  return { live, phase, status, error, wsUrl: WS_URL, send }
}
