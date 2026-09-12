# 本番環境の起動手順

## 構成

| 役割 | ホスト | URL |
|------|--------|-----|
| 画面（React） | Vercel | https://kinyu-kenkyujo-dec-opt.vercel.app |
| 中継（WebSocket） | Render | https://kinyu-relay.onrender.com |
| ブリッジ + MT5 | お客様の Windows | `AITrader.exe`（自分の確認は `はじめる.bat`） |

```
ブラウザ ──wss──► Render（中継）◄──wss── bridge.py ──► MT5
          room=会員ID                    id=会員ID
```

サイトは1つ。中継も1台。会員ごとに部屋を分けて、他人の口座・停止/再開が混ざらない。

## 1. 中継サーバー（Render）— 初回のみ

1. [Render Dashboard](https://dashboard.render.com/) にログイン
2. **New → Blueprint**
3. GitHub リポジトリ `Sara-2024/kinyu-kenkyujo-dec-opt` を選択
4. `render.yaml` の **kinyu-relay** をデプロイ（Starter 推奨。Free はスリープします）
5. **環境変数を設定する（重要）**

   | キー | 要否 | 値 |
   |------|------|-----|
   | `SUPABASE_URL` | **必須** | Supabase Project URL |
   | `SUPABASE_ANON_KEY` | **必須** | Supabase anon key |
   | `TRELAB_TOKEN` | 任意 | 設定しない（設定すると画面側も同じ値を送る必要がある） |

   この2つを入れないと、中継は「会員の確認なし」で動きます。その状態では、
   部屋の名前（＝会員のUUID）を知っている人は誰でもその部屋に入れてしまい、
   他人の口座を見たり、停止・ロット変更を送れます。起動ログに警告が出るので、
   デプロイ後に **Logs で「会員の確認 : 有効」と出ていること**を必ず確認してください。
6. デプロイ完了後、**https://kinyu-relay.onrender.com/health** が `{"ok":true,...}` を返すことを確認

## 2. 画面（Vercel）

環境変数（Production）:

| キー | 要否 | 値 |
|------|------|-----|
| `VITE_RELAY_URL` | 必須 | `wss://kinyu-relay.onrender.com/app` |
| `VITE_SUPABASE_URL` | 必須 | Supabase Project URL。ログインだけでなく **`/api/chat` の会員確認にも使う**（サーバー側でも読む） |
| `VITE_SUPABASE_ANON_KEY` | 必須 | Supabase anon key。`eyJ` で始まるもの（新形式の `sb_publishable_…` は画面側が受け付けない） |
| `GEMINI_API_KEY` | 必須 | Google AI Studio の API キー。未設定なら研究員は定型文、`/api/risk` は 503 |
| `TRELAB_RISK_TOKEN` | **AIの見張りに必須** | ブリッジだけが `/api/risk` を呼べるようにする合言葉。`bridge/risk_secret.py` と同じ文字列。空だと見張りは「切」のまま動かない |
| `GEMINI_CHAT_MODEL` | 任意 | 研究員の会話のモデル（未設定なら `gemini-3.5-flash-lite`） |
| `GEMINI_RISK_MODEL` | 任意 | 見張りのモデル（未設定なら `gemini-3.5-flash`）。**費用のほとんどはここ**（AGENTS.md 参照） |
| `GEMINI_RISK_API_KEY` | 任意 | 見張り専用のキー。分けておくと、商談中の会話が見張りの枠を食い潰さない |
| `RISK_PROVIDER` | 任意 | `deepseek` にすると見張りだけ DeepSeek で判定する。**未指定でも `DEEPSEEK_API_KEY` があれば DeepSeek に倒れる** |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_RISK_MODEL` | 任意 | DeepSeek を使うとき（モデル未指定なら `deepseek-flash`） |
| `RISK_TIMEOUT_MS` | 任意 | 見張りの応答待ち（既定 12000） |

> MT5連携（`/api/connect`）は、上の Supabase の2つをそのまま使う。新しい環境変数は要らない。
> ただし、すでに動いている環境には
> **`supabase/migrations/20260912_add_connect_tokens.sql` だけ**を流すこと
> （Supabase ダッシュボード → SQL Editor に貼り付け）。
> 追加だけの内容で、既存のテーブル・関数・権限には触れない。
> 新しく環境を作るときは、これまでどおり `supabase/schema.sql` を流せばよい。

```bash
vercel env add VITE_RELAY_URL production
# → wss://kinyu-relay.onrender.com/app
vercel env add GEMINI_API_KEY production
# → AIza... （https://aistudio.google.com/apikey で作る）

vercel --prod
```

## 3. Windows（MT5 の横）

設定ファイルの場所は、exe 版と開発機で違います。

| 使うもの | 設定ファイル |
|---|---|
| `AITrader.exe`（お客様に配るもの） | `%LOCALAPPDATA%\AITrader\bridge.env` |
| `.py` / `.vbs`（開発機） | `bridge/.env` |

中身（接続ツールが `MT5_PATH` を自動で書き込みます）:

```env
TRELAB_WS_URL=wss://kinyu-relay.onrender.com/bridge
```

お客様に渡すのは **1本だけ**（`tools\build-windows.bat` で作る `dist\AITrader.exe`）。
開発機で試すときは `AITrader.vbs` でも同じ処理が動く。

1. MT5 を起動してログイン
2. `AITrader.exe`（または `AITrader.vbs`）を**一度だけ**開く
   - 黒い画面は出ない。中では EA 配置 → ブリッジ起動まで進む（EA はコンパイル済みを配るので、お客様のPCではコンパイルしない）
   - あわせて `aitrader://` とスタートアップを登録するので、
     次回からは**サイトのボタン1つ**、PC再起動後は**自動**でつながる
3. ゴールド（XAUUSD）のチャートに OrbitGoldEA_v6 を載せ、自動売買 ON
4. うまくいかないときは `%LOCALAPPDATA%\AITrader\connect.log` と `bridge.log` を見る
   （画面付きで追うなら `はじめる.bat` か `tools\start-connect.bat`）

解除するときは `python connect.py --uninstall`（`aitrader://` と自動起動の登録を消す）。

## 4. お客様への渡し方

渡すものは2つだけ。

1. 本番サイトのURL（ログイン用アカウントも渡す）
2. `AITrader.exe`（サイトの「接続ツールをダウンロード」ボタンで配る）

Windows で `tools/build-windows.bat` を実行して `dist/AITrader.exe` ができたら、
`public/download/AITrader.exe` に置いてコミットする（サイトの既定はこれ）。
`connect.py` や `bridge/` を変えたら作り直す。
Python 版の ZIP は `bash tools/pack-connector.sh` で `public/download/AITrader.zip` にできる
（`VITE_CONNECTOR_URL=/download/AITrader.zip` で差し替え）。

お客様側の手順:

1. サイトにログイン
2. 受付のユイ → 初期設定 → 「接続ツールをダウンロード」→ 一度開く（初回だけ）
   → その会員の部屋で MT5 とつながる
3. アルゴ → 管理画面 → 「自動売買をはじめる」

中継は **Render を再デプロイ** して、部屋分けのコードが入っていることを確認する。

## 動作確認

1. https://kinyu-kenkyujo-dec-opt.vercel.app を開く
2. ユイ → 初期設定 → 接続フロー → 「アルゴのところへ」
3. 画面上部に **● MT5と接続中** と **口座番号**（MT5 と同じ）が出る
4. 管理画面で停止 → MT5 パネルが赤になる
