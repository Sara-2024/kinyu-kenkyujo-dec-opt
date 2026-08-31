# 本番環境の起動手順

## 構成

| 役割 | ホスト | URL |
|------|--------|-----|
| 画面（React） | Vercel | https://kinyu-kenkyujo-dec-opt.vercel.app |
| 中継（WebSocket） | Render | https://kinyu-relay.onrender.com |
| ブリッジ + MT5 | お客様の Windows | `start-connect.bat` |

```
ブラウザ ──wss──► Render（中継）◄──wss── bridge.py ──► MT5
```

## 1. 中継サーバー（Render）— 初回のみ

1. [Render Dashboard](https://dashboard.render.com/) にログイン
2. **New → Blueprint**
3. GitHub リポジトリ `Sara-2024/kinyu-kenkyujo-dec-opt` を選択
4. `render.yaml` の **kinyu-relay** をデプロイ（Starter 推奨。Free はスリープします）
5. デプロイ完了後、**https://kinyu-relay.onrender.com/health** が `{"ok":true,...}` を返すことを確認

## 2. 画面（Vercel）

環境変数（Production）:

| キー | 値 |
|------|-----|
| `VITE_RELAY_URL` | `wss://kinyu-relay.onrender.com/app` |
| `VITE_SUPABASE_URL` | （任意）Supabase Project URL |
| `VITE_SUPABASE_ANON_KEY` | （任意）Supabase anon key |

```bash
vercel env add VITE_RELAY_URL production
# → wss://kinyu-relay.onrender.com/app

vercel --prod
```

## 3. Windows（MT5 の横）

`bridge/.env`（接続ツールが `MT5_PATH` を自動で書き込みます）:

```env
TRELAB_WS_URL=wss://kinyu-relay.onrender.com/bridge
```

1. MT5 を起動してログイン
2. `install-ea.bat` → EA を配置
3. `start-connect.bat` → 中継 + ブリッジ起動
4. チャートに SiteTestEA を載せ、自動売買 ON

## 動作確認

1. https://kinyu-kenkyujo-dec-opt.vercel.app を開く
2. アルゴ → 接続フロー
3. 画面上部に **● MT5と接続中** と **口座番号**（MT5 と同じ）が出る
4. 管理画面で停止 → MT5 パネルが赤になる
