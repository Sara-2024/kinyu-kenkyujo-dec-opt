# 金融研究所｜12月オプト

12月オプトインキャンペーン用の特設サイト。
横視点の2Dゲーム風「サイバーラボ」に研究員（AIキャラクター）を配置し、
クリックするとノベルゲーム風の会話ウィンドウが開く。

研究員は5人＋受付のユイ。それぞれ担当が決まっていて、担当のデータだけを見て答える。

| 研究員 | 担当 | 見ているもの |
| --- | --- | --- |
| ユイ | 受付・初期設定 | （定型文） |
| リン | チャート分析 | 大画面の銘柄のローソク足・高値安値・移動平均 |
| ジン | 経済指標・金利 | 経済指標カレンダー（`/api/calendar`）と主要レート。発表の1時間前・10分前に知らせる |
| アルゴ | 自動売買システム | MT5 の状態・本日の成績・建玉・システムの取引 |
| ミオ | トレード利益分析 | お客様の約定履歴の集計（7日・30日）と「トレードを添削して」 |
| ガンツ | システム開発 | （道具まわりの案内。AIには聞かない） |

自動売買担当「アルゴ」からは、MT5との**おまかせ接続**フローと、
接続後の**管理画面（停止・ロット等の設定変更）**に入れる。

---

## 動かす

```bash
npm install
npm run dev          # http://localhost:5181
```

| コマンド | 内容 |
| --- | --- |
| `npm run dev` | 開発サーバー（ポート5181。使用中なら `PORT` 環境変数で変更可） |
| `npm run build` | 本番ビルド（型チェック込み）|
| `npm run preview` | ビルド結果の確認 |
| `npm run typecheck` | 型チェックのみ |

## 技術構成

React 19 / TypeScript / Vite 6 / Tailwind CSS v4 / react-router-dom

ドット絵キャラクターは画像ではなく**CSSのブロックで描画**している（`PixelPerson.tsx`）。
差し替える場合はこのコンポーネントを `<img>` に置き換えるだけでよい。

## ディレクトリ

```
src/
├─ App.tsx                 ルーティング
├─ index.css               デザイントークンとアニメーション（全CSSはここ）
├─ pages/
│  ├─ Lab.tsx              研究所のメイン画面（1440×810の固定ステージ）
│  └─ Chat.tsx             ※ 未使用。/chat/:id の直リンク用に残置
├─ components/
│  ├─ PixelPerson.tsx      CSSで描くドット絵キャラ
│  ├─ Panels.tsx           チャート・サーバーラック・机などの什器
│  ├─ DialogueWindow.tsx   会話ウィンドウ（会話／接続フロー／管理画面の親）
│  └─ ControlPanel.tsx     接続後の管理画面（停止・EA設定）
├─ data/
│  ├─ characters.ts        研究員の人格・台詞・選択肢と受け答え
│  ├─ ai.ts                /api/chat の呼び出しと、研究員間の質問の引き継ぎ
│  ├─ aiContext.ts         研究員ごとに AI へ渡す「手元のデータ」
│  ├─ calendar.ts          経済指標カレンダーの読み込みと表示用の整形
│  ├─ setupFlow.ts         おまかせ接続の工程定義
│  ├─ eaSettings.ts        EA設定項目 ↔ MT5グローバル変数の対応
│  └─ connection.ts        接続状態の保存（localStorage）
└─ hooks/
   ├─ useMarket.ts         相場のライブ更新と急変動シミュレーション
   └─ useEconomicAlerts.ts 経済指標の発表前のお知らせ（ジン）
api/
├─ chat.ts / _lib/chat.ts        研究員の AI 回答（Gemini 3.5 Flash-Lite）
├─ calendar.ts / _lib/calendar.ts 経済指標カレンダー（ForexFactory）
└─ market.ts / _lib/market.ts     相場データ
```

## 画面の作り

- **ステージ方式** — 1440×810の固定キャンバスを画面サイズに合わせて拡縮する。
  ホイールで拡大縮小、ドラッグで移動、右下に大きな ＋ − ⟲ ボタン。
- **absoluteのみ** — カード型レイアウトは使わない。全要素を `absolute` + `%` で配置する。
- **デザイントークン** — 色・枠線・光彩は `index.css` の CSS変数（`--accent` 等）に集約。
  パネルを追加するときは `Panels.tsx` の `<Panel>` を使えば見た目が揃う。

## 状態の保存（localStorage）

会員ごとに分ける必要があるものは、キーの末尾に会員IDを付ける。

| キー | 内容 |
| --- | --- |
| `lab-tutorial-done:<会員ID>` | チュートリアルを見たか |
| `lab-guide-done:<会員ID>` | 案内を見たか |
| `lab-intro-done:<会員ID>` | メンバー紹介を見たか |
| `trelab-connection:<会員ID>` | 接続状態・口座情報・EA設定 |
| `trelab-session-token` | ログインの合言葉 |
| `trelab-site-settings` | 研究員の名前などの設定 |
| `trelab-econ-alerted` | 経済指標のお知らせを出したか |

商談で最初から見せ直すときは、管理画面右下の「この端末の連携を解除」を押す。

## いまの状態（重要）

**画面・中継・ブリッジ・AI までつながっている。**

- 接続ツールは「接続ツールをダウンロード」ボタンで配る（`public/download/MT5Automatic.exe`、Python 不要）
- 口座番号・稼働状況・成績はブリッジが MT5 から返した値だけを表示する
- 研究員の回答は Gemini（`GEMINI_API_KEY`）。鍵が無いときは `characters.ts` の定型文

## MT5ブリッジ

`bridge/` に、MT5が動くWindows環境で常駐させるPythonスクリプトがある。
WebSocketで指令を待ち受け、MT5のグローバル変数を書き換えてEAの売買可否を制御する。
詳細は [bridge/README.md](bridge/README.md)。

画面側のEA設定（`eaSettings.ts`）は、それぞれ MT5 のグローバル変数に対応している。

| 画面の項目 | グローバル変数 |
| --- | --- |
| ロット数 | `AI_LOT` |
| 同時に持つ数 | `AI_MAX_POSITIONS` |
| 1日の損失上限 | `AI_DAY_LOSS_LIMIT` |
| 稼働／停止 | `AI_TRADING_ALLOWED` |

## これから必要なもの

1. **AI の鍵** — Vercel の環境変数に `GEMINI_API_KEY` を入れる（下の「研究員の AI」参照）
2. **接続ツールの更新** — `connect.py` や `bridge/` を変えたら、Windows で `tools/build-windows.bat`
   を実行して `public/download/MT5Automatic.exe` を置き直す

中継サーバー（画面とブリッジをつなぐ WebSocket）は `server/` にあり、Render で動いている。
手順は [DEPLOY.md](DEPLOY.md)。

---

## GitHub 連携

```bash
# 1. GitHub CLI でログイン（ブラウザが開きます）
gh auth login

# 2. リポジトリ作成して push（プライベート）
gh repo create kinyu-kenkyujo-dec-opt --private --source=. --remote=origin --push
```

Cursor からはそのまま clone / push できます。Cloud Agent を使う場合も、GitHub 連携後に
リポジトリを指定すれば動きます。

---

## 研究員の AI（Gemini）

リン・ジン・アルゴ・ミオの受け答えは Gemini 3.5 Flash-Lite（いちばん安いモデル）に聞く。
費用を抑えるため、研究員ごとに担当を固定し、担当ぶんのデータだけを渡し、担当外の質問は
調べずに「▶ ○○に聞く」ボタンで担当へ案内する。1回の質問はおおむね 0.05 円前後。

1. [Google AI Studio](https://aistudio.google.com/apikey) で **Create API key**
2. Vercel → Project → **Settings → Environment Variables** に `GEMINI_API_KEY` を追加（Production）
3. **Deployments → Redeploy**（環境変数は再デプロイで効く）

ローカルで試すときは `.env` に `GEMINI_API_KEY=` を書く（`npm run dev` が読む）。
鍵が無い間は定型文で答え、画面に「準備中」は出ない。

## Supabase 連携（ログインに必須）

会員登録・ログイン・管理者画面は Supabase の関数だけで動かします（追加サーバーなし）。

1. [Supabase](https://supabase.com) でプロジェクトを作成
2. **SQL Editor** で [supabase/schema.sql](supabase/schema.sql) を実行
3. **Project Settings → API** から URL と `anon` key をコピー
4. ルートの `.env` に `VITE_SUPABASE_URL` と `VITE_SUPABASE_ANON_KEY` を記入
5. 初回登録の入場パスワードは `AITrader-dream`（最初に登録した人が管理者）
6. 管理者画面から入場パスワードを変更する

### デプロイ時

Vite のビルド時に `VITE_*` が埋め込まれるため、ホスティング先（Vercel / Netlify 等）の
環境変数にも同じキーを設定してください。
