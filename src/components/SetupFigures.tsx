// 接続ツールを受け取るときに Windows が出す確認画面の、簡単な絵。
//
// 未署名のプログラムなので、ブラウザと Windows がそれぞれ確認を出す。
// 文字だけで説明しても押す場所が伝わらないので、押すところに印をつけて見せる。
// （実物の写真ではなく、どこを押すかを示すための絵）
import type { CSSProperties } from 'react'

export type FigureKind = 'browserWarning' | 'smartScreen'

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
          <span className="block truncate text-[13px] font-bold">AITrader.exe</span>
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

export function SetupFigure({ kind }: { kind: FigureKind }) {
  if (kind === 'browserWarning') {
    return (
      <div className="mt-2">
        <BrowserWarning />
        <Caption>「…」を押すと「保存」が出ます</Caption>
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
