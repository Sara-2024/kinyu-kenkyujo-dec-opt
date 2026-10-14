// パスポートを受け取るときに Windows / Mac が出す確認画面の、簡単な絵。
//
// 署名の無いプログラムなので、ブラウザと OS がそれぞれ確認を出す。
// 文字だけで説明しても押す場所が伝わらないので、押すところに印をつけて見せる。
// （実物の写真ではなく、どこを押すかを示すための絵）
//
// Mac は macOS 15 から「右クリック→開く」の抜け道が無くなり、
// 「完了」→ システム設定の「このまま開く」の 2 段になった。
// 最初の画面に「ゴミ箱に入れる」が並ぶので、そこを押さないよう絵で示す。
import type { CSSProperties } from 'react'
import type { UserStep } from '../data/setupFlow'

export type FigureKind = NonNullable<UserStep['figure']>

const frame: CSSProperties = {
  background: '#f4f5f7',
  color: '#1b1f2a',
  borderRadius: 8,
  border: '1px solid rgba(0,0,0,0.18)',
  boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
  maxWidth: 380,
  overflow: 'hidden',
}

const hit: CSSProperties = {
  outline: '2px solid var(--accent)',
  outlineOffset: 2,
  borderRadius: 6,
  boxShadow: '0 0 0 6px rgba(94,204,255,0.18)',
}

function Caption({ children }: { children: string }) {
  return (
    <div className="mt-1.5 text-[13px]" style={{ color: 'var(--accent)' }}>
      ▲ {children}
    </div>
  )
}

/** ブラウザ（Chrome / Edge）のダウンロード欄に出る確認 */
function BrowserWarning() {
  return (
    <div style={frame}>
      <div className="px-3 py-2 text-[12px]" style={{ background: '#e8eaee', color: '#555c6b' }}>
        ダウンロード
      </div>
      <div className="flex items-center gap-2.5 px-3 py-2.5">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded" style={{ background: '#dfe3ea', fontSize: 14 }}>
          ⚠
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate text-[13px] font-bold">MT5 Automatic.exe</span>
          <span className="block text-[12px]" style={{ color: '#6b7280' }}>
            一般的にダウンロードされていません
          </span>
        </span>
        <span className="shrink-0 px-2 py-1 text-[15px] font-bold" style={hit}>
          …
        </span>
      </div>
      <div className="px-3 pb-2.5">
        <div className="inline-block rounded px-3 py-1.5 text-[13px]" style={{ background: '#ffffff', border: '1px solid rgba(0,0,0,0.15)' }}>
          <span className="font-bold" style={hit}>
            保存
          </span>
          <span style={{ color: '#9aa1ad' }} className="ml-3">
            削除
          </span>
        </div>
      </div>
    </div>
  )
}

/** ファイルを開いたときに Windows が出す確認 */
function SmartScreen() {
  return (
    <div style={frame}>
      <div className="px-3.5 pt-3 pb-2">
        <div className="text-[14px] font-bold">WindowsによってPCが保護されました</div>
        <div className="mt-1 text-[12px]" style={{ color: '#6b7280' }}>
          Microsoft Defender SmartScreen は認識されないアプリの起動を停止しました。
        </div>
        <div className="mt-2 inline-block text-[13px] font-bold" style={hit}>
          詳細情報
        </div>
      </div>
      <div className="flex justify-end gap-2 px-3.5 pb-3">
        <span className="rounded px-3 py-1.5 text-[13px] font-bold" style={{ ...hit, background: '#ffffff', border: '1px solid rgba(0,0,0,0.2)' }}>
          実行
        </span>
        <span className="rounded px-3 py-1.5 text-[13px]" style={{ background: '#ffffff', border: '1px solid rgba(0,0,0,0.15)', color: '#6b7280' }}>
          実行しない
        </span>
      </div>
    </div>
  )
}

const macFrame: CSSProperties = { ...frame, borderRadius: 12, background: '#ececf0' }

const macButton: CSSProperties = {
  background: '#ffffff',
  border: '1px solid rgba(0,0,0,0.15)',
  borderRadius: 6,
  padding: '5px 14px',
  fontSize: 13,
}

/** ダブルクリックしたときに macOS 15 以降が出す画面（「開く」の選択肢が無い） */
function MacNotOpened() {
  return (
    <div style={macFrame}>
      <div className="px-4 pt-3 pb-2 text-center">
        <div className="text-[14px] font-bold">“MT5 Automatic”は開けません。</div>
        <div className="mt-1 text-[12px]" style={{ color: '#6b7280' }}>
          Appleは、このアプリにMacに損害を与える可能性のあるマルウェアが含まれていないことを確認できませんでした。
        </div>
      </div>
      <div className="flex justify-center gap-2 px-4 pb-3">
        <span style={{ ...macButton, ...hit, fontWeight: 700 }}>完了</span>
        <span style={{ ...macButton, color: '#9aa1ad', textDecoration: 'line-through' }}>ゴミ箱に入れる</span>
      </div>
    </div>
  )
}

/** システム設定 → プライバシーとセキュリティ の下のほうに出る許可 */
function MacOpenAnyway() {
  return (
    <div style={macFrame}>
      <div className="px-3 py-2 text-[12px] font-bold" style={{ background: '#e0e2e8', color: '#555c6b' }}>
        プライバシーとセキュリティ
      </div>
      <div className="px-4 py-3">
        <div className="text-[12px] font-bold" style={{ color: '#6b7280' }}>
          セキュリティ
        </div>
        <div className="mt-2 flex items-center gap-3">
          <span className="min-w-0 flex-1 text-[12px]">
            “MT5 Automatic”は、Macを保護するためにブロックされました。
          </span>
          <span className="shrink-0" style={{ ...macButton, ...hit, fontWeight: 700 }}>
            このまま開く
          </span>
        </div>
      </div>
    </div>
  )
}

export function SetupFigure({ kind }: { kind: FigureKind }) {
  if (kind === 'browserWarning') {
    return (
      <div className="mt-2">
        <BrowserWarning />
        <Caption>「…」を押すと「保存」が出ます</Caption>
      </div>
    )
  }
  if (kind === 'macNotOpened') {
    return (
      <div className="mt-2">
        <MacNotOpened />
        <Caption>「完了」を押します（「ゴミ箱に入れる」は押さない）</Caption>
      </div>
    )
  }
  if (kind === 'macOpenAnyway') {
    return (
      <div className="mt-2">
        <MacOpenAnyway />
        <Caption>「このまま開く」→ パスワード → もう一度「このまま開く」</Caption>
      </div>
    )
  }
  return (
    <div className="mt-2">
      <SmartScreen />
      <Caption>「詳細情報」を押すと「実行」が出ます</Caption>
    </div>
  )
}
