# このリポジトリで作業するときの約束

Cursor / Claude Code などのAIアシスタント向けの指示。人間が読んでも構わない。

## このサイトの性格

40〜50代の投資家に向けた**営業用の特設サイト**。
商談の場で見せて「こういうものを売ります」と伝えるのが目的なので、
**本物のサービスに見えること**を最優先する。

- 画面に「デモ」「サンプル」「準備中」といった文言を**出さない**
- ただし金融サービスとして自然な注記（表示レートの断り書き等）は**残す**

## デザインの決まり（崩さないこと）

1. **カード型レイアウト禁止。** Grid や Flex で画面を四角い箱に区切らない。
   1枚の絵の上に `position: absolute` と `%` で配置する。
2. **視点は真横。** 見下ろしでも斜めでもない、横スクロールゲームの画面。
3. **色は `index.css` の CSS変数から取る。** `--accent`（シアン）、`--panel-bg`、
   `--panel-border`、`--panel-glow`。個別に色を決め打ちしない。
4. **パネルは `Panels.tsx` の `<Panel>` を使う。** 半透明ダークネイビー＋1pxシアン枠。
5. **文字は大きめに。** 本文15〜17px、ボタンの高さは44px以上。老眼を前提にする。
6. **アニメーションは translateY / scale のみ。**
   Tailwind v4 の `-translate-x-1/2` は `translate` プロパティなので、
   keyframes で `translate(-50%, …)` を使うと二重に効いて位置がずれる。

## 内容についての決まり

- **投資助言をさせない。** キャラクターに「買いです」「上がります」と言わせない。
  「こういう形なので、判断の境目はここです」という説明にとどめる。
- **MT5のパスワードは扱わない。** 仕組み上も不要（すでにログイン済みの
  ターミナルに接続ツールが横から繋ぐため）。ここは商品の売りでもある。
- キャラクターの台詞・選択肢・受け答えは `src/data/characters.ts` に集約する。
  コンポーネント内に台詞を直書きしない。
- **数字は作らない。** 成績・建玉・履歴・添削は、すべてブリッジが MT5 から
  返した値だけを使う。それらしい数字を画面側で用意しない。

## 研究員の AI（Gemini）の決まり

- **担当を固定する。** リン＝チャート、ジン＝経済指標・金利、アルゴ＝自動売買システム、
  ミオ＝お客様のトレードの利益分析。担当の定義は `api/_lib/chat.ts` の `ROLE_SPEC`。
- **AI に渡すのは担当ぶんのデータだけ。** 画面側が `src/data/aiContext.ts` で
  「その担当が見る手元のデータ」を組み立てて送る。サーバーは何も調べに行かない。
  担当外のデータを混ぜない（AI が余計なことまで調べて、費用が増える）。
- **担当外の質問は調べない。** `redirect` だけ返し、画面は「▶ ○○に聞く」ボタンを出す。
  押すと質問を持ったまま担当の研究員に切り替わる（`setPendingQuestion`）。
- **AI を使わずに済むものは使わない。** 「次の指標はいつ？」「今週の重要指標は？」は
  カレンダーを読むだけ、「トレードを添削して」は `reviewTrades()` で画面側が答える。
- **鍵が無ければ定型文。** `GEMINI_API_KEY` 未設定のときは `characters.ts` の
  `answers` / `fallback` で返し、画面に「準備中」を出さない。
- 経済指標は `/api/calendar`（ForexFactory の今週ぶん JSON）だけを使う。
  来週ぶんは週明けまで届かない。取れないときも予定を作らない。

## 研究員の AI（Gemini）の決まり

- **担当を固定する。** リン＝チャート、ジン＝経済指標・金利、アルゴ＝自動売買システム、
  ミオ＝お客様のトレードの利益分析。担当の定義は `api/_lib/chat.ts` の `ROLE_SPEC`。
- **AI に渡すのは担当ぶんのデータだけ。** 画面側が `src/data/aiContext.ts` で
  「その担当が見る手元のデータ」を組み立てて送る。サーバーは何も調べに行かない。
  担当外のデータを混ぜない（AI が余計なことまで調べて、費用が増える）。
- **担当外の質問は調べない。** `redirect` だけ返し、画面は「▶ ○○に聞く」ボタンを出す。
  押すと質問を持ったまま担当の研究員に切り替わる（`setPendingQuestion`）。
- **AI を使わずに済むものは使わない。** 「次の指標はいつ？」「今週の重要指標は？」は
  カレンダーを読むだけ、「トレードを添削して」は `reviewTrades()` で画面側が答える。
- **鍵が無ければ定型文。** `GEMINI_API_KEY` 未設定のときは `characters.ts` の
  `answers` / `fallback` で返し、画面に「準備中」を出さない。
- 経済指標は `/api/calendar`（ForexFactory の今週ぶん JSON）だけを使う。
  来週ぶんは週明けまで届かない。取れないときも予定を作らない。

## MT5 を読むときの決まり

- **時刻はブローカーのサーバー時計。** MT5 の約定時刻は「サーバー時計を
  そのまま UNIX 秒にしたもの」で、日本時間ではない。
  `datetime.now()` や `datetime.fromtimestamp()` を履歴の問い合わせや表示に
  使わない（時差のぶん窓がずれて、直近の売買が丸ごと抜ける）。
  `_server_now()` / `_server_dt()` / `_deals_between()` を通すこと。
- **履歴は「決済ぶん」を一件も落とさない。** 数え方を変えるときは
  `_closing_entries()`（OUT / OUT_BY / INOUT）を通す。ドテンの損益は INOUT に載るので、
  ここを外すとその取引の損益がまるごと画面から消える。
  取引一覧（`_trades_blocking`）は、窓の外で建てた取引も落とさない
  （建てた側が無ければ `_entry_deals_for()` で名指しに取り、それでも無ければ
  建値を空にして損益だけ載せる）。窓の上限では切らない（`open_end=True`）。
  サーバー時計との差は最大15分ぶん粗く、10分間は取り直さないので、
  上限で切ると「たったいまの決済」が落ちる。
- **売買フラグを動かしてよいのは「サイトからの指示」だけ。**
  指示は `%LOCALAPPDATA%\AITrader\intent.json` に持つ。ブリッジは起動時も
  再接続時も、この意思に MT5 を合わせるだけ。記録が無ければ「停止」から始める
  （`GV_DEFAULT` で勝手に稼働させない）。稼働に変わるのは、お客様がアルゴの
  管理画面で「自動売買をはじめる」を押したときだけ。ユイの初期設定は
  「つなぐ」までで、稼働には入れない。
- **作り直した exe は、古いブリッジを止めてから動く。** 同じ版だと入れ替わらないので、
  exe 版は実行ファイルの更新時刻を版に足して、毎回別の版として扱う（`bridge.py` の `VERSION`）。
- **ブリッジを二重に動かさない。** 二つ動くと売買フラグを取り合い、
  MT5 の表示が勝手に入れ替わる。起動時に `takeover_old_bridges()` で
  古い版を終了させてからロックを取る。ロック名を変えるときは、
  古い名前も `LOCK_NAMES` に残すこと（残さないと二重に動ける）。
  ロックに番号を書いていない古い版も居るので、止めるときはロック頼みにせず
  「`bridge.py` を実行中の python」をコマンドラインから探す
  （`connect.py list_bridge_processes()` / `bridge.py _list_bridge_processes()`）。
- **手動の売買も同じように扱う。** magic の有無で拾う・拾わないを決めない
  （`by_system` は表示の区別に使うだけ）。

## AIリスク監督（新規注文の見張り）の決まり

- **止めるのは新規注文だけ。** 決済・SL/TP・トレーリング・ロットには一切触らない。
  停止中も `ManageM1Basket()` の決済管理は動き続ける。ナンピンの追加も新規注文として
  同じゲートを通す（`bridge/OrbitGoldEA_v6.mq5` の `OpenTrade` と ナンピン追加の2か所）。
- **買いと売りは別々に止める。** 高値が近いことを理由に売りを止めない。逆も同じ。
- **原則は許可。** 「レンジっぽい」「自信がない」では止めない。止めるときは、
  入力に実在する数値と理由コード（`api/_lib/risk.ts` の `REASON_CODES`）が必ず要る。
- **EA は通信を待たない。** 判定はブリッジが取りに行き、指令ファイルに数字で書く
  （`AI_GATE_MODE` / `AI_BUY_ALLOWED` / `AI_SELL_ALLOWED` / `AI_GATE_UNTIL` / `AI_GATE_SEQ`）。
  EA はそれを読むだけ。`TradingGate.mqh` の `AiAllowsEntry()` が唯一の判定入口。
- **AI に期限・口座・銘柄・連番・モデル名を作らせない。** すべて `api/_lib/risk.ts` が付ける。
  AI の evidence は入力の項目名と値に一致するものだけ採用し、合わなければ捨てて停止も取り消す。
- **迷いと故障を区別する。** 有効なデータでの INSUFFICIENT_DATA は新しい停止の理由にしない。
  通信障害は前の判定を期限まで使う。期限が切れたら（反映モードのときだけ）新規注文を止める。
- **一度止めたら時間切れでは戻さない。** 最新のデータで連続 `RISK_UNBLOCK_CONFIRM` 回
  問題なしになり、かつ `RISK_MIN_BLOCK_SEC` を過ぎたときだけ再開する。
- **本番口座では自動で反映しない。** デモは `on`、本番は `shadow`（記録のみ）で始まる。
  切り替えは管理画面の「反映 / 記録のみ / 切」だけ。切でも既存の安全装置は働く。
- **試験の走らせ方**（MT5 も鍵も要らない）:
  `python3 bridge/tests/risk_features_test.py` … 水準・突破・リテストの計算
  `python3 bridge/tests/risk_gate_test.py` … 停止と再開、通信断、古い応答、重複呼び出し
  `node --experimental-strip-types api/_lib/risk.test.mjs` … 根拠の検証と方向別の理由コード
  `python3 bridge/tests/wiring_test.py` … Bridge の配線（未定義の名前・属性違いを捕まえる）
  `python3 bridge/tests/symbol_test.py` … 金の銘柄選び（GOLD を採り、XAUEUR/XAUJPY を弾く）
  `python3 bridge/tests/settings_restore_test.py` … 指令ファイルが消えたときの設定の書き戻し
  `python3 bridge/tests/history_test.py` … 口座履歴の取りこぼし（ドテン・長期保有・時計のズレ）
  `python3 bridge/tests/phase1_test.py` … MT5の検出・EAの状態判定・連携状態
  `python3 bridge/tests/phase1_offline_test.py` … 初回の設定が通信しないこと（通し）
  `python3 bridge/tests/installer_ui_test.py` … 初回の設定画面（専門用語・文字の大きさ）
  `python3 bridge/tests/phase2_test.py` … サイトからの連携（合図の読み取り・検証・状態）
  `node --experimental-strip-types api/_lib/connect.test.mjs` … 合図を確かめる所
- **AI に聞くのは「入りうる場面」だけ。** EA はブレイク後のリテスト成立でしか入らないので、
  水準から遠く伸びも小さい時間帯に聞いても、その判定は使われない（費用だけ増える）。
  条件は `RiskGate._entry_possible`：重要水準まで ATR 1個以内／直近15本で ATR 4個以上動いた／
  水準を抜けて `retest_bars` 本以内。ゴールドの実データで聞く回数は全体の 27%。
  聞かなかったときは判定の期限だけ延ばし、EA は止めない（原則は許可）。
- **有効にする設定**: Vercel に `TRELAB_RISK_TOKEN`（と `GEMINI_API_KEY`）、
  手元に `bridge/risk_secret.py`（`risk_secret.py.example` をコピーして同じ文字列）。
  `tools\build-windows.bat` がこれを exe に同梱するので、**お客様は何も入力しない**。
  どちらか欠けていれば「切」のまま動かない（`/api/risk` は 503 を返す）。
  `risk_secret.py` はコミットしない。配布物からは取り出せるので、サイト側で
  1台あたりの呼び出し回数を制限している（`api/_lib/risk.ts` の `RATE_LIMIT`）。
- 戦略プロフィールは EA が自分の設定を状態ファイルへ書き出したものを使う
  （`GateProfile`）。ここを増やしたら `bridge/bridge.py` の `DEFAULT_PROFILE` も合わせる。

## AI Trader Connect（お客様に配る Windows アプリ）

配るのは1つの exe（`AITrader.exe`／表示名は AI Trader Connect）。
中身は接続ツールとブリッジで、**状態で動きが変わる**。

- **状態は2つだけ。** `bridge/connect_state.py` の `INSTALL_ONLY` / `CONNECTED`。
  記録は `%LOCALAPPDATA%\AITrader\state.json`。
  - `INSTALL_ONLY` … MT5 を探して EA を置くところまで。**サイトとは一切通信しない。**
    配った直後はここから始まる。サイトの存在をお客様に見せない。
  - `CONNECTED` … サイトから正式に連携されたあと。これまでどおりブリッジが動く。
- **通信の歯止めは `start_bridge()` の先頭1か所。** 連携前は必ずそこで止まる。
  呼び出し口を増やしても漏れないよう、判定はここに集約する。
- **すでに使っているお客様は引き継ぐ。** `state.json` が無く `bridge.env` の
  `BRIDGE_ID` が会員ID なら CONNECTED とみなす（`connect_state.adopt_legacy`）。
  これが無いと、更新した瞬間に既存のお客様が「EAを置くだけ」に戻る。
- **初回は EA を置くだけ。** `setup_phase1()`。MT5 の検出はログインも起動も要らない
  （`bridge/mt5_detect.py` が AppData のデータフォルダを数えるだけ）。
  MT5 が複数あるときだけ選択画面を出す。
- **EA の置き場と名前は変えない。** `MQL5/Experts/OrbitGoldEA_v6.mq5` のまま。
  すでに使っているお客様のチャート設定を動かさないため。
  状態判定と配置は `bridge/ea_manager.py` に集約し、`NOT_INSTALLED` /
  `INSTALLED` / `UPDATE_AVAILABLE` / `LATEST` / `ERROR` を返す。
  **無条件に上書き・削除しない。** 中身（SHA-256）が同じなら触らない。
- **配るのはコンパイル済み（`.ex5`）だけ。** お客様の PC で MetaEditor を起動しない、
  コンパイルもしない、ソース（`.mq5`）も配らない。
  `.ex5` から版は読めないので、同梱の `ea_manifest.json` に版と SHA-256 を書く。
  作り方は Windows で MetaEditor コンパイル →
  `py -3 tools\make-ea-manifest.py` → `.ex5` と `ea_manifest.json` をコミット。
  `tools\build-windows.bat` は、この2つが無ければ exe を作らずに止まる。
- **同梱物の SHA-256 は置く前に確かめる。** manifest と食い違っていたら置かない
  （`Source.ok`）。置いたあとも、置いたファイルを取り直して確かめる。
- **お客様の PC に入っている版は `ea_installed.json` に控える。**
  `.ex5` は中身から版を読めないため、置いたときの版と SHA-256 を覚えておき、
  次回それと見比べて「更新が要るか」を決める。
- **画面に技術用語を出さない。** `bridge/installer_ui.py`。MQL5・Experts・
  ブリッジ・API・Python・Socket は書かない。失敗しても原因ではなく
  「次に何をすればいいか」だけを出す。ボタンは高さ 44px 以上。
- **インストーラーは `tools/AITraderConnect.iss`**（Inno Setup 6）。
  管理者権限を要求せず、`aitrader://` の登録とアンインストールまで面倒を見る。

### サイトとの連携（Phase 2）

- **連携はサイトからしか始められない。** 接続ツール単体では合図を作れない。
  `supabase/schema.sql` の `connect_token_issue` はログイン中のセッションが要る。
- **URL に載せるのは短命の合図だけ。** `aitrader://connect?token=<64桁>`。
  会員IDそのもの・パスワード・API キー・永続トークンは載せない。
  合図は 32バイトの乱数、5分で失効、一度使ったら無効（`connect_tokens`）。
- **確かめるのはサイトのサーバー関数。** `/api/connect`（`api/_lib/connect.ts`）が
  Supabase の `connect_token_redeem` に取り次ぎ、会員IDを返す。
  接続ツールは Supabase を直接叩かない（鍵を配らないため）。
  宛先は `PRODUCTION_SITE` の決め打ち。`aitrader://` の `from=` は当てにしない。
- **新しい環境変数は要らない。** すでにある `VITE_SUPABASE_URL` /
  `VITE_SUPABASE_ANON_KEY` をそのまま使う。
- **合図は記録に残さない。** ログにも応答にも、伏せた形でしか出さない。
- **`aitrader://connect?room=...` は受け付けない。** 会員IDを知っているだけの
  相手に連携されてしまうため、URL から部屋を受け取る処理そのものを廃止した。
  外から CONNECTED にできる入口は合図（token）ただ1つ。
- **すでに使っているお客様の引き継ぎは、URL ではなく手元の設定から。**
  その PC の `bridge.env` に会員IDが入っていれば CONNECTED とみなす
  （`connect_state.adopt_legacy`）。
- **DB の追加は migration で流す。** すでに動いている環境には
  `supabase/migrations/20260912_add_connect_tokens.sql` だけを流す。
  新しい環境は `schema.sql` でよい（同じ内容が入っている。ずれていないことは
  `phase2_test.py` が見ている）。

## お客様のPCで動くもの（接続ツール）

- **`.bat` は Shift-JIS（CP932）で保存する。** 日本語版 Windows のコマンド画面は
  既定が CP932 なので、UTF-8 で書くと文字化けして読めなくなる（`chcp 65001` に頼らない）。
- **黒い画面（コンソール）を出さない。** お客様は「何か怖いものが動いた」と感じる。
  - 押すファイルは2つだけ。増やさない。
  - `はじめる.bat` … 自分が確認するとき（画面つき。初回の準備もここ）
  - `AITrader.vbs` / `AITrader.exe` … お客様が使うもの（画面なし。表示名は AIトレーダー）
  - 個別のスクリプトは `tools/` に置く。プロジェクト直下に増やさない。
  - `connect.py` から他のプログラムを呼ぶときは `run_hidden` / `spawn_hidden` を使う。
    直に `subprocess.Popen` を書かない（ウィンドウが出る）。
  - 経過は画面ではなく `%LOCALAPPDATA%\AITrader\connect.log` に残す。
  - 例外は MT5 公式インストーラだけ（本人の操作が要るため）。
- サイトからの起動は `aitrader://` プロトコル。接続ツールが初回に自分を登録する。
  呼び出し時に会員ID（部屋）を渡し、中継はその部屋以外へ指令を流さない。
  ブラウザは登録なしにPCのソフトを起動できないので、**初回だけツールを一度開いてもらう**
  導線は残しておく。配り方はサイトの「接続ツールをダウンロード」ボタン
  （既定は `public/download/AITrader.exe`。Windows で `tools/build-windows.bat` を実行して
  できたものを置いて**コミットする**。Python 不要で、ユイの手順は「開くだけ」）。
  Python 版の ZIP は `tools/pack-connector.sh` で作り、`VITE_CONNECTOR_URL=/download/AITrader.zip`
  で差し替えられる。`connect.py` や `bridge/` を変えたら exe を作り直して置き直すこと。
  メールで送る導線は廃止した。
- **MT5 に送る EA は `bridge/OrbitGoldEA_v6.mq5` の1つだけ**（Orbit GOLD 2軸エンジン、
  XAUUSD 専用）。v6 はトレンド方向を UP/DOWN の二択にし、ナンピンを既定 OFF にしたもの。
  前の版 `bridge/OrbitGoldEA_v5.mq5` は参照用に残してあるだけで、配りも読み込みもしない
  （`EA_NAMES` に入っていない。お客様の MT5 にあれば `OLD_EA_NAMES` で片づける）。名前は `bridge/mt5_terminal.py` の `EA_NAMES` が唯一の定義で、
  connect.py の配置・bridge.py の有無報告・古い EA の片づけ（`OLD_EA_NAMES`）が全部そこを見る。
  EA を差し替えるときは、`TradingGate.mqh` を include して
  `IsTradingAllowedRaw()` / `GateNumber("AI_LOT")` などをエントリー前に見ることと、
  `OnTimer` で `SyncGateFileToGlobals()` を呼ぶこと（これが無いと `ea_alive` が立たず、
  サイトの「稼働／停止」も効かない）。売買ロジックそのものは触らない。
- **役割分担。** MT5との連携（初期設定・ダウンロード案内・メンバー紹介）は受付のユイ、
  稼働・停止・ロット変更（管理画面）はアルゴ。アルゴの「自動売買をはじめる」は
  未連携ならユイへ案内するだけ。台詞は `characters.ts` の `SETUP` / `TOUR`。

## 動作確認

変更したら、必ずブラウザで確認すること。

```bash
npm run dev        # http://localhost:5181
npm run build      # 型チェック込み。コミット前に通す
```

確認する導線:
1. ユイをクリック → チュートリアル解除 → 初回は「メンバーの紹介」→「初期設定をはじめる」
2. ユイ → 初期設定 → **接続ツールを呼び出す**（`aitrader://`）。
   ツールが入っていれば数秒で接続まで進む。入っていなければ30秒で
   「接続ツールをダウンロード」に切り替わる（手順はユイが案内、起動を検知して自動で先へ）。
   つながっても EA がチャートに無い／アルゴ取引ボタンが OFF なら、その操作をユイが案内し、
   ブリッジの `ea_alive` / `terminal_trade_allowed` を見て自動で進む（外からは自動化できない）。
   済むと「アルゴのところへ」で管理画面に引き継ぐ
3. アルゴ → 「今日の成績」「過去の成績」「いまのポジション」→ MT5の実データが出る
4. リン → 「トレードを添削して」→ 履歴（既定180日）からクセを出す
5. 管理画面 → ロットの ＋ − → 「変更を反映する」
6. 「この端末の連携を解除」で最初の状態に戻せる

## 触るときに気をつける場所

- `Lab.tsx` は 1440×810 の固定ステージ。座標は `%` かステージ内px。
  画面サイズに合わせた拡縮は `base * zoom` で行っているので、
  新しい要素もステージの中に置くこと（画面直下に置くと拡縮から外れる）。
- `useMarket.ts` は 450ms ごとに再描画する。重い処理を足さない。
- `pages/Chat.tsx` は現在どこからもリンクされていない（旧実装の名残）。
