// 中継サーバー経由で、MT5のそばにいるブリッジとやり取りする。
//
// サーバーが動いていなければ黙って諦める（そのまま営業用の見せ方で動く）。
// つながっているときだけ live=true になり、画面は本物の口座情報を映す。
import { useCallback, useEffect, useRef, useState } from 'react'

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

/** 接続先。未設定ならローカルの中継サーバー */
const WS_URL = import.meta.env.VITE_RELAY_URL || 'ws://localhost:8080/app'

export function useBridge() {
  const [live, setLive] = useState(false)
  const [status, setStatus] = useState<BridgeStatus | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const waiting = useRef(new Map<string, (ack: Ack) => void>())
  const seq = useRef(0)

  useEffect(() => {
    let closed = false
    let retry: ReturnType<typeof setTimeout> | null = null

    const connect = () => {
      if (closed) return
      let ws: WebSocket
      try {
        ws = new WebSocket(WS_URL)
      } catch {
        retry = setTimeout(connect, 5000)
        return
      }
      wsRef.current = ws

      ws.onmessage = (event) => {
        let payload: Record<string, unknown>
        try {
          payload = JSON.parse(event.data)
        } catch {
          return
        }

        // 接続直後：いまつながっているブリッジ
        if (payload.type === 'welcome') {
          const list = (payload.bridges as BridgeStatus[]) ?? []
          if (list.length > 0) {
            setStatus(list[0])
            setLive(true)
          }
          return
        }

        if (payload.type === 'bridge_online') {
          setStatus({ ...(payload.status as BridgeStatus), bridgeId: String(payload.bridgeId) })
          setLive(true)
          return
        }

        if (payload.type === 'bridge_offline') {
          setLive(false)
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

      ws.onclose = () => {
        // 自分より新しい接続ができている場合、それを巻き添えにしない。
        // （開発モードの二重マウントや再接続時に、有効な接続を消してしまうため）
        if (wsRef.current !== ws) return
        setLive(false)
        wsRef.current = null
        if (!closed) retry = setTimeout(connect, 5000)
      }
      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      closed = true
      if (retry) clearTimeout(retry)
      wsRef.current?.close()
    }
  }, [])

  /** 指令を送り、ブリッジからの応答を待つ */
  const send = useCallback(
    (command: string, extra: Record<string, unknown> = {}): Promise<Ack> =>
      new Promise((resolve) => {
        const ws = wsRef.current
        if (!ws || ws.readyState !== WebSocket.OPEN) {
          resolve({ type: 'ack', ok: false, error: 'サーバーにつながっていません' })
          return
        }
        const id = `app-${++seq.current}`
        waiting.current.set(id, resolve)
        ws.send(JSON.stringify({ id, command, ...extra }))
        // 応答が来ない場合の保険
        setTimeout(() => {
          if (waiting.current.has(id)) {
            waiting.current.delete(id)
            resolve({ type: 'ack', ok: false, error: '応答がありません' })
          }
        }, 8000)
      }),
    [],
  )

  return { live, status, send }
}
