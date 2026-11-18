// Yumekku【サブスク版】の利用許可を、つないでいるパスポート（ブリッジ）へ配る係。
//
//   ・許可そのもの（期限と署名）は DB（subscription_licenses）が作る。中継は鍵を持たず、受け取って渡すだけ。
//   ・ブリッジが名乗った（hello）ときと、LICENSE_SWEEP_MS（既定 60 秒）ごとに、つないでいる部屋の分をまとめて取る。
//     変わったときだけ { type: 'license', until, sig, status } を送る（期限は 1 時間ごとに進むので、そのたびに届く）。
//   ・サブスクでない会員の部屋は DB が返さないので、何も送らない（ファースト等には関係しない）。
//   ・承認中でない部屋は、画面からの稼働・設定変更を断る（allowsWrite）。止める操作は通す。
//     EA も許可が無ければ新規を止めるが、画面で「稼働」を押せてしまうと分かりにくいので中継でも断る。
//   ・取れなかったとき（DB に届かない）は何も変えない。EA は手元の許可の期限まで動き、切れたら止まる。

export function createSubscriptions({ rooms, send, log, isMemberRoom, supabaseUrl, supabaseKey, fetchImpl = fetch }) {
  const enabled = Boolean(supabaseUrl && supabaseKey)
  /** roomId → { status, until, sig } 最後に送ったもの */
  const sent = new Map()
  /** roomId → status（pending / active / stopped）。サブスクの会員の部屋だけ */
  const statusOf = new Map()

  async function fetchLicenses(ids) {
    const wanted = [...new Set(ids)].filter((id) => isMemberRoom(id))
    if (!enabled || wanted.length === 0) return null
    try {
      const res = await fetchImpl(`${supabaseUrl}/rest/v1/rpc/subscription_licenses`, {
        method: 'POST',
        headers: { apikey: supabaseKey, authorization: `Bearer ${supabaseKey}`, 'content-type': 'application/json' },
        body: JSON.stringify({ p_ids: wanted }),
      })
      if (!res.ok) return null
      const data = await res.json()
      return Array.isArray(data) ? data : null
    } catch (err) {
      log(`サブスクの利用許可を取れませんでした: ${err.message}`)
      return null
    }
  }

  function deliver(roomId, lic, force = false) {
    const room = rooms.get(roomId)
    const until = Number(lic.until) || 0
    const sig = Number(lic.sig) || 0
    const status = String(lic.status || '')
    statusOf.set(roomId, status)
    if (!room?.bridge) return false
    const last = sent.get(roomId)
    if (!force && last && last.until === until && last.sig === sig && last.status === status) return false
    sent.set(roomId, { until, sig, status })
    send(room.bridge, { type: 'license', until, sig, status })
    if (!last || last.status !== status) log(`サブスクの利用許可を渡しました: ${String(roomId).slice(0, 8)}… ${status}${until ? '' : '（停止）'}`)
    return true
  }

  /** つないでいる（または指定した）部屋の許可を取って、変わったものを渡す */
  async function sweep(only = null, force = false) {
    const ids = only ?? [...rooms.entries()].filter(([, r]) => r.bridge).map(([id]) => id)
    const list = await fetchLicenses(ids)
    if (!list) return 0
    let n = 0
    const seen = new Set()
    for (const lic of list) {
      const id = String(lic.id || '')
      if (!id) continue
      seen.add(id)
      if (deliver(id, lic, force)) n += 1
    }
    // 申請が消えた（会員の削除など）部屋は、覚えている状態も忘れる
    for (const id of ids) if (!seen.has(id)) statusOf.delete(id)
    return n
  }

  return {
    enabled,
    sweep,
    /** ブリッジが名乗ったとき。前に送っていても、もう一度渡す（ブリッジは作り直されているかもしれない） */
    applyRoom: (roomId) => (isMemberRoom(roomId) ? sweep([roomId], true) : Promise.resolve(0)),
    /** 画面からの稼働・設定変更を通してよいか。サブスクの会員で、承認中でなければ断る */
    allowsWrite: (roomId) => {
      const status = statusOf.get(roomId)
      return status === undefined || status === 'active'
    },
    statusOf: (roomId) => statusOf.get(roomId) ?? null,
    forget: (roomId) => sent.delete(roomId),
  }
}
