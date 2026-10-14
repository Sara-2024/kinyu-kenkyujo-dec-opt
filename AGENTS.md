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
- 経済指標は `/api/calendar` だけを使う（ForexFactory の今週ぶん・来週ぶんの2本。
  `api/_lib/calendar.ts` の `SOURCES`）。取れないときも予定を作らない。

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
  **exe の名前を変えたら `BRIDGE_IMAGE_HINTS`（connect.py）と `_is_bridge_process`（bridge.py）
  にも足す。** 足し忘れると古いブリッジを「触らない」と判定して止められず、
  新しいブリッジも起動しないまま「接続完了」になる（MT5Automatic への改名で実際に起きた）。
- **手動の売買も同じように扱う。** magic の有無で拾う・拾わないを決めない
  （`by_system` は表示の区別に使うだけ）。

## AIリスク監督（新規注文の見張り）の決まり

- **廃止（2026-10-14）。** EA は AI の判定を見ない（`TradingGate.mqh` から `AiAllowsEntry` を外した）、
  ブリッジは `RiskGate` を動かさない、中継の `set_ai_gate` / `get_ai_gate` も無い、画面の「AIの見張り」も無い。
  `api/_lib/risk.ts`・`bridge/risk_gate.py`・`risk_features.py` とその試験、exe への合言葉の同梱は残っているが、
  どこからも呼ばれない（消してよい）。以下は当時の決まり（参考）。
- **EA のパネルの最下行は「ユメックAIと連携済み／ユメックAIと未接続」。** 接続ツールが 30 秒ごとに
  指令ファイルへ `AI_BRIDGE_AT`（PC の時計の UNIX 秒）を書き（`bridge.py` の `touch_gate`。`watchdog` から）、
  EA はそれが 3 分より古ければ「未接続」と出す（`GateBridgeAlive`）。古い接続ツールは合図を書かないので、
  指令ファイルの更新時刻でも見る。新規注文を止める判断には使わない（表示だけ）。
  **合図は中継（サイト）とつながっているときだけ書く**（`_active_ws`）。中継に断られている（削除・BAN した会員の部屋）
  のに「連携済み」と出て、一斉制御もロビーも効かないのに正常に見えた事故から。
- **止めるのは新規注文だけ。** 決済・SL/TP・トレーリング・ロットには一切触らない。
  停止中も `ManageM1Basket()` の決済管理は動き続ける。ナンピンの追加も新規注文として
  同じゲートを通す（`bridge/YumekkuEA-1年版.mq5` の `OpenTrade` と ナンピン追加の2か所）。
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
- **試験は `npm test` でぜんぶ走る**（MT5 も AI の鍵も要らない）。
  一覧と実体は `tools/run-tests.sh`。新しい試験を足したらここにも足すこと
  （足さないと誰も走らせない）。`npm run check` なら型チェックも一緒に通る。
- **AI に聞くのは「入りうる場面」だけ。** EA はブレイク後のリテスト成立でしか入らないので、
  水準から遠く伸びも小さい時間帯に聞いても、その判定は使われない（費用だけ増える）。
  条件は `RiskGate._entry_possible`：重要水準まで ATR 1個以内／直近15本で ATR 4個以上動いた／
  水準を抜けて `retest_bars` 本以内。ゴールドの実データで聞く回数は全体の 27%。
  聞かなかったときは判定の期限だけ延ばし、EA は止めない（原則は許可）。
  **ただし、いま止めている最中は必ず聞く。** 聞かないと「連続で問題なし」が積み上がらず、
  危険が去っても永久に止まったままになる（再開は最新のデータでしか起きない）。
- **有効にする設定**: Vercel に `TRELAB_RISK_TOKEN`（と `GEMINI_API_KEY`）、
  手元に `bridge/risk_secret.py`（`risk_secret.py.example` をコピーして同じ文字列）。
  `tools\build-windows.bat` がこれを exe に同梱するので、**お客様は何も入力しない**。
  どちらか欠けていれば「切」のまま動かない（`/api/risk` は 503 を返す）。
  `risk_secret.py` はコミットしない。
  **ただし、この合言葉は配布物（exe）から取り出せる。** PyInstaller の同梱物を展開すれば
  数分で復元できるので、`public/download/DreamlandPassport.exe` を公開している以上、
  「誰でも取れる」前提で扱うこと。`api/_lib/risk.ts` の `RATE_LIMIT` は
  1インスタンスのメモリで数えているだけなので、サーバーレスでは悪用の歯止めにならない
  （事故で叩きすぎるのを止めるためのもの）。実際の歯止めは AI 提供元の予算上限で作る。
  中長期では、配布物に共有の合言葉を焼き込む方式をやめて、
  会員セッションに紐づく1台ごとのトークン（失効・台数管理ができるもの）に置き換える。
- 戦略プロフィールは EA が自分の設定を状態ファイルへ書き出したものを使う
  （`GateProfile`）。ここを増やしたら `bridge/bridge.py` の `DEFAULT_PROFILE` も合わせる。
- **費用のほとんどはここ。** 会話（研究員）はお客様が話しかけたときだけだが、見張りは
  相場が開いているあいだ動き続ける。1台あたり月およそ 4,000 回（120秒ごとに見て、
  実際に聞くのはその 27%）。人数ぶん増えるので、100人なら月 40万回になる。
  100万トークンあたりの単価（2026-09 時点）:

  | モデル | 入力 | 出力 |
  | --- | --- | --- |
  | `gemini-3.5-flash`（既定） | $1.50 | $9.00 |
  | `gemini-3.5-flash-lite` | $0.30 | $2.50 |
  | `deepseek-flash` | $0.15 | $0.60（協定時間帯は倍） |

  安い側に替えると費用は数分の一になるが、**判定の質は安全に直結する**ので、
  いきなり本番の既定を替えない。手順は「`RISK_LIVE_MODE=shadow`（記録のみ）で
  `GEMINI_RISK_MODEL` / `RISK_PROVIDER` を替えて走らせ、`risk_gate` が残す判定履歴を
  いまのモデルと突き合わせる」。止める・止めないが一致することを確かめてから替える。
  どのモデルで判定したかは `decision.model` に必ず残る（黙って別のモデルに落とさない）。
- **DeepSeek のモデル名は `deepseek-flash`。** 旧称 `deepseek-chat` は DeepSeek 側の
  料金表・モデル一覧から消えているので、既定にはしない（`DEEPSEEK_DEFAULT_MODEL`）。
- **AI へ送る JSON は詰めて書く。** `buildUserPrompt` で整形（インデント）すると、
  改行と空白のぶんだけ入力トークンが増える。呼ぶ回数が多いので効いてくる。

## ドリームランド・パスポート（お客様に配る接続ツール。旧称 MT5 Automatic）

配るのは1つの exe（`DreamlandPassport.exe`／表示名は「ドリームランド・パスポート」。2026-10-14 に MT5Automatic から改名。
PyInstaller の `--name` と `public/download/` の名前だけ変え、保存先（`%LOCALAPPDATA%\AITrader`、`~/Library/Application Support/MT5Automatic`）・
ロック名・Mac の本体名（`MT5Automatic-<機種>`）・bundle id は変えていない。既存の PC では新しい exe を一度開くと
`aitrader://` の登録と自動起動が新しい名前に切り替わる。`LEGACY_APP_NAMES` に「MT5 Automatic」を足してある）。
中身は接続ツールとブリッジで、**状態で動きが変わる**。

- **ルートは2つ（Windows / Mac）。** サイト・中継・一斉制御・会員・BAN は共通で、
  違うのはお客様のパソコンで動く部分だけ。初期設定の「接続ツールのダウンロード」で
  お客様がどちらかを選ぶ（`DialogueWindow` の `platform`。ブラウザから推定し、選び直せる。
  `localStorage` の `mt5automatic.platform` に覚える）。配るものは `connector.ts` の
  `CONNECTOR_DOWNLOADS`（windows = `DreamlandPassport.exe`、mac = `DreamlandPassport-mac.zip`、
  `VITE_CONNECTOR_URL_MAC` で差し替え）。手順は `installSteps('mac')`。
  **誰がどちらを使っているかは2か所に残す**：サイトが初期設定を始めた／選んだときに
  `member_platform_set`（`member_connections.platform`、管理者画面と一斉制御の「OS」列）、
  ブリッジが名乗るときに `status.platform`（動いている側の事実。一斉制御はこちらを優先）。
  `supabase/migrations/20261004_platform.sql`。Mac 版ツールそのものは次の項。
- **Mac 版ツールは「Windows 版の本体 ＋ OS 依存の差し替え」。** 入口は `connect_mac.py`。
  `connect.py` をそのまま読み込み、MT5 の探し方・ログイン済みの判定・MT5 の開き直し・
  自動起動（`~/Library/LaunchAgents/jp.trelab.mt5automatic.plist`）・プロセスの見つけ方・
  ブリッジの起こし方・MessageBox（osascript）だけを差し替える（`_patch()`）。
  初回の設定・合図（token）・`start_bridge()` の歯止め・一斉制御の指令は Windows と同じコード。
  - **MT5 は Wine の中**：`~/Library/Application Support/<アプリ>/drive_c/users/<user>/AppData/Roaming/
    MetaQuotes/Terminal/<ID>/`（`bridge/mt5_detect_mac.py`）。選んだら `point_appdata_at()` で
    **APPDATA をその Wine の Roaming に向ける**。これで `mt5_terminal` / `ea_manager`（控えの場所・
    EA の置き場）が Mac でもそのまま使える。設定と記録は `~/Library/Application Support/MT5Automatic/`
    （LOCALAPPDATA に見せる）。
    **Mac 公式の MT5 はポータブルモード**（`portable.txt`）で、AppData 側には `origin.txt` と
    `config` しか無く、MQL5 と logs は `origin.txt` が指す本体フォルダ（`drive_c/Program Files/
    MetaTrader 5` や `drive_c/MT5-Test`）にある。`resolve_data_dir()` が C:\ を drive_c に読み替えて
    MQL5 がある側を `data_path` にする（AppData 側だけ見ると 1 台も見つからない。実機で起きた）。
    Common/Files（EA の控え）は変わらず Roaming の下。同じ本体を Wine の別ユーザー
    （`users/mao` と `users/user`）から見ている重複は 1 台にまとめ、Roaming は Common/Files が
    新しいほうを採る。`terminal_id` は AppData 側のフォルダ名のまま。
  - **MetaTrader5 の代わりは `bridge/mt5_files.py`**：EA が共通フォルダに書くファイルを読み、
    閉じる・取り消すは `trelab_cmd.ini` → `trelab_cmd_ack.ini` の往復（`docs/mac-ea-files.md`）。
    `sys.modules["MetaTrader5"] = mt5_files` と差し込むので `bridge.py` は変えない。
    EA が控えを書いていなければ「ログインしていない」扱いになる（`initialize()` が False）。
  - **Mac 用の EA は `bridge/mac/YumekkuEA-1年版.mq5` → `bridge/mac/YumekkuEA-1年版.ex5`。**
    Windows 用（`bridge/YumekkuEA-1年版`。同じ名前）と売買の判断は同じで、違いは「接続ツールとのファイルの
    やり取り（`Tb*` の関数。`docs/mac-ea-files.md` の形式）」と、ロットが入力（固定／残高％・上限）
    になっていること。**bridge/ 直下に置かない**：Windows の `3_リリースする.bat` が直下の
    「別名の Yumekku .ex5」を片づけるので消される。ソース（`.mq5`）は `.gitignore`（配らない・
    リポジトリに入れない）。`.ex5` だけコミットする。
    **コンパイルはこの Mac でできる**：`bash tools/mac/compile-ea.sh` が
    `/Applications/MetaTrader 5.app` の中の Wine で MetaEditor64.exe を黙って動かし、
    `.ex5` と `bridge/mac/ea_manifest.json` を作る（Windows も MetaEditor の画面も要らない）。
    `build-mac.sh` は `bridge/mac/` の `.ex5` と控えだけを `.app` に入れ、Windows 用の `.ex5` と
    `bridge/ea_manifest.json` は入れない（入れると `ea_manager` が Windows 用を優先して置く）。
    連携の配線（`SiteAllowsEntry` / `AiAllowsEntry` / `SiteLot` / `OnTimer`）と Mac のファイル
    書き出しが揃っているかは `bridge/tests/ea_gate_test.py` が見る（ソースがある手元だけ）。
    `TodayRealizedPnL` は M30 軸も数える。
    **Windows 用の EA は、この Mac 版から起こしたもの**（2026-10-14 から。それまでの Windows 版 v1.00 は
    サイト連携が無く、ロット 0.01 固定・有効期限 2026-10-15 だった）。Mac 版を直したら Windows 版
    （`bridge/YumekkuEA-1年版.mq5`）も同じように直し、`bash tools/mac/compile-ea.sh all` で両方作る。
    違いは `Tb*`（ファイルのやり取り）と `OnTradeTransaction` が無いことと、`GateProfile` の名前だけ。
  - **配るのは `ドリームランド・パスポート.app` を ZIP にしたもの**（`public/download/DreamlandPassport-mac.zip`）。
    **Apple シリコン用（arm64）と Intel 用（x86_64）の本体を両方同梱**し、
    `tools/mac/launcher.applescript` が `uname -m` で使い分ける（お客様はどちらでも同じ ZIP）。
    `tools/mac/build-mac.sh --binary` が PyInstaller で動かしている機種の本体を作り、
    `--assemble` が `dist/MT5Automatic-*` を集めて `.app` に包み、Info.plist に `aitrader://` を書く。
    `.github/workflows/build-mac.yml` は `macos-15`（arm64）と `macos-15-intel`（x86_64）で本体を
    1 つずつ作ってからまとめる。手元の Apple シリコンでは Rosetta ＋ universal2 の Python があれば
    引数なしで両方できる。
  - **Gatekeeper の通し方（買う署名は無い）。** macOS 15 以降は右クリック→「開く」の抜け道が無く、
    お客様は初回だけ「開けません」→「完了」→ システム設定 →「プライバシーとセキュリティ」→
    「このまま開く」を通す（`installSteps('mac')` と `SetupFigures` の絵）。それを通せる形に
    しておくため、作り方に 2 つ決まりがある（どちらも macOS 15 で実際に踏んだ）：
    ① `--assemble` の最後で **アドホック署名し直す**（`codesign --force --deep --sign -`）。
    osacompile の .app は署名付きなので、Info.plist を書き換えて bin/ を足したままだと
    「壊れているため開けません。ゴミ箱に入れてください」になり、「このまま開く」が出ない。
    ② **launcher は本体を .app の中から直接起こさない。** 外側を許可しても、隔離の印が付いた
    中の本体はその場で強制終了される（しかも Downloads から開いた .app は読み取り専用の仮の
    場所で動くので印を外せない）。`~/Library/Application Support/MT5Automatic/bin/` に
    `cp -X`（拡張属性なし）で写し、そちらを起こす。自動起動の LaunchAgent もその写しを指す。
    ③ **`aitrader://` の受け手は、開かれた .app に寄せる。** Downloads に「MT5 Automatic 2.app」
    「3.app」…と古い `.app` が残ると、LaunchServices がどれに届けるか分からず、古い版に届くと
    中の本体が止められて何も起きない（実機で 8 個登録されていた）。launcher が開かれるたびに
    `lsregister -f` で自分を登録し直し、`--assemble` は `CFBundleVersion` を毎回新しくする。
  - **Mac では別名の Yumekku EA を片づけない**（`connect_mac._patch` が `cleanup_other_versions` を
    無効にする）。手で置いた Mac 用の EA を「前の版」として消してしまった実機の事故から。
    Mac は台数が少なく、手で置いた検証用の EA が並んでいることがあるので、消さずに残す
    （どれを載せるかは案内文の名前 `YumekkuEA-1年版` で分かる）。
    ソース（`.mq5`）はどちらの OS でも消さない（`cleanup_other_versions` は `.ex5` だけ）。
    Mac の Python は HTTPS の証明書を持たないので certifi を同梱し `SSL_CERT_FILE` で使う
    （無いと中継にもサイトにもつながらない）。
  - 試験：`bridge/tests/mt5_files_test.py`（EA のふりをして往復）、`bridge/tests/connect_mac_test.py`
    （差し替え・MT5 探し・自動起動・配布の定義）。どちらも Mac も MT5 も要らない。
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
- **自動起動（`--startup`）は、連携済みのときだけ働く。** 未連携なら何もしないで終わる。
  ここで初回の設定を始めると、古い版が登録した自動起動が残っている PC で、
  ログインのたびに画面が開いてしまう。
- **古い自動起動の登録は片づける。** 古い版は「そのときの exe の置き場」を指したまま
  登録しているので、残っていると Windows が古い exe を起こし続ける。
  インストーラーが入れるときに消し（`MT5Automatic.iss` の `[Registry]`）、
  初回の設定でも残っていれば消す（`unregister_startup`）。
  連携が済めば、新しい版が自分の場所で登録し直す。
- **ブリッジは「初回に選んだ MT5」に繋ぐ。** 接続ツールが `MT5_PATH` で渡した
  terminal64.exe を、`bridge.py` の `_initialize_blocking` が最初に名指しで試す
  （`_attach_to`）。path 無しの `initialize()` は「どれか」に繋ぐので、MT5 が何台もある
  PC では EA を載せたのと別のターミナルに繋がり、そちらの「アルゴ取引」が OFF だと
  サイトが「ON にしてください」から進まなくなる（`terminal_trade_allowed` は繋いだ側の値）。
- **連携後のつなぎ直しも、覚えている MT5 にしか繋がない**（`choose_session`）。
  別の MT5 にログインしていても黙って乗り換えず、「選んだ MT5 にログインしていません」と
  出して「別のMT5を選ぶ」を用意する。覚えていなくて複数あれば、そこで選んでもらう。
- **EA の控え（`trelab_state.ini`）は PC 内の全 MT5 で1つ**（`FILE_COMMON`）。
  だから「生きているか」は鮮度だけで決めず、控えの `account=` / `ea=` / `symbol=` を
  いまつないでいる口座・Yumekku・ゴールド（`is_gold_symbol`：XAUUSD か GOLD を含む）と
  突き合わせる（`_ea_state_blocking` の `ea_alive` / `ea_ready` / `ea_problem`、
  アプリ側は `ea_manager.heartbeat(account=…)`）。別の MT5 に載せた EA を「動いている」と
  数えたり、USDJPY のチャートで手順が「済み」になったりしないため。
  サイトの手順（`mt5StepIndex`）は `ea_alive` と `ea_symbol_ok` を見て、
  違うときは `ea_problem` の文をそのまま画面に出す。
- **初回は EA を置くだけ。** `setup_phase1()`。MT5 の検出はログインも起動も要らない
  （`bridge/mt5_detect.py` が AppData のデータフォルダを数えるだけ）。
  選択画面は MT5 が1台でも出す（口座番号を見て「どこに入れるか」を確かめてもらう）。
  画面を出せないときだけ、最後に使った MT5 を自動で選ぶ。
- **EA の置き場と名前は、軽々しく変えない。** いまは `MQL5/Experts/YumekkuEA-1年版.ex5`
  （Windows・Mac とも同じ名前。2026-10-14 に `YumekkuEA_win` / `YumekkuEA_mac` から改名）。
  変えると、すでに使っているお客様はチャートに新しい名前の EA を載せ直すことになる
  （旧名は `OLD_EA_NAMES` で片づける。Mac は片づけない）。
  状態判定と配置は `bridge/ea_manager.py` に集約し、`NOT_INSTALLED` /
  `INSTALLED` / `UPDATE_AVAILABLE` / `LATEST` / `ERROR` を返す。
  **無条件に上書き・削除しない。** 中身（SHA-256）が同じなら触らない。
- **配るのはコンパイル済み（`.ex5`）だけ。** お客様の PC で MetaEditor を起動しない、
  コンパイルもしない、ソース（`.mq5`）も配らない。
  `.ex5` から版は読めないので、同梱の `ea_manifest.json` に版と SHA-256 を書く。
  作り方は **この Mac で `bash tools/mac/compile-ea.sh all`**（Windows 用・Mac 用の両方。
  `.ex5` は OS に依らないので Windows は要らない）→ `.ex5` をコミット（`ea_manifest.json` は
  自動ビルドが作り直す）。Windows で MetaEditor コンパイル → `py -3 tools\make-ea-manifest.py` でもよい。
  `tools\build-windows.bat` は、この2つが無ければ exe を作らずに止まる。
- **同梱物の SHA-256 は置く前に確かめる。** manifest と食い違っていたら置かない
  （`Source.ok`）。置いたあとも、置いたファイルを取り直して確かめる。
- **お客様の PC に入っている版は `ea_installed.json` に控える。**
  `.ex5` は中身から版を読めないため、置いたときの版と SHA-256 を覚えておき、
  次回それと見比べて「更新が要るか」を決める。
- **窓の名前と装いはロビーに合わせる。** 題名は「ドリームランド｜パスポート」（`installer_ui.APP_NAME`）、
  クリーム地・金の罫・明朝の見出し・ティールの主ボタン（ロビーの CSS 変数と同じ色）。起動画像は `tools/splash.png`。
  ファイル名は DreamlandPassport.exe / ドリームランド・パスポート.app、ブラウザの「開きますか？」も
  「ドリームランド・パスポート」（`connect.PRODUCT_NAME`）。本体サイトの文言も「接続ツール」ではなく「パスポート」。
  Mac の Tk はボタンの背景色を変えられないので、文字は濃い色にする（薄いと消える）。
- **画面に技術用語を出さない。** `bridge/installer_ui.py`。MQL5・Experts・
  ブリッジ・API・Python・Socket は書かない。失敗しても原因ではなく
  「次に何をすればいいか」だけを出す。ボタンは高さ 44px 以上。
- **インストーラーは `tools/DreamlandPassport.iss`**（Inno Setup 6）。
  管理者権限を要求せず、`aitrader://` の登録とアンインストールまで面倒を見る。

### サイトとの連携（Phase 2）

- **いま新規の連携は止めてある。** `src/data/connector.ts` の `CONNECT_PAUSED`。
  サイトは合図（token）方式になったが、配っている接続ツールがまだ古く、
  古いツールは合図を読めずに既定の部屋（vps-01）でブリッジを動かしてしまうため。
  止まるのは「これから連携する人」だけ。すでに連携済みのお客様のブリッジは
  サイトと関係なく動き続け、つなぎ直し（`relaunchConnector`）も使える。
  **再開の手順**: 新しい接続ツールを配り終え、Supabase の migration を当ててから、
  `CONNECT_PAUSED = false` に戻すだけ。順番を逆にしないこと
  （migration を先に当てると、古いツールが合図で起動してしまう）。
- **つなぎ直しの URL に合図は付けない。** `aitrader://connect`（問い合わせ無し）。
  新しいツールは、連携済みならつなぎ直し、未連携なら EA を置くだけで終わる。
  この URL で新しく連携されることはない。

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
  - `MT5Automatic.vbs` / `DreamlandPassport.exe` … お客様が使うもの（画面なし。表示名は ドリームランド・パスポート）
  - 個別のスクリプトは `tools/` に置く。プロジェクト直下に増やさない。
  - `connect.py` から他のプログラムを呼ぶときは `run_hidden` / `spawn_hidden` を使う。
    直に `subprocess.Popen` を書かない（ウィンドウが出る）。
  - 経過は画面ではなく `%LOCALAPPDATA%\AITrader\connect.log` に残す。
  - 例外は MT5 公式インストーラだけ（本人の操作が要るため）。
- サイトからの起動は `aitrader://` プロトコル。接続ツールが初回に自分を登録する。
  呼び出し時に会員ID（部屋）を渡し、中継はその部屋以外へ指令を流さない。
  **この URL はどのページからでも開かせられる。** そのまま信じるとお客様のブリッジを
  他人の部屋へ移せてしまうので、`connect.py` は「会員IDの形（UUID）であること」と
  「`from=` が自分たちのサイトであること」の両方を確かめてからしか受け取らない
  （`TRUSTED_SITES`）。サイトのドメインを増やしたらここに足す。
  ブラウザは登録なしにPCのソフトを起動できないので、**初回だけツールを一度開いてもらう**
  導線は残しておく。配り方はサイトの「接続ツールをダウンロード」ボタン
  （既定は `public/download/DreamlandPassport.exe`。**exe は GitHub Actions が自動で作る**：
  `connect.py` / `bridge/` / `tools/build-windows.bat` を main に push すると
  `.github/workflows/build-exe.yml` が Windows で `build-windows.bat` を回し、
  できた exe を `[skip ci]` 付きで commit する。手元の Windows で
  `3_リリースする.bat` を押しても同じものができる。AIの見張りの合言葉は
  リポジトリの Secrets `TRELAB_RISK_TOKEN` から入る。Python 不要で、ユイの手順は「開くだけ」）。
  Python 版の ZIP は `tools/pack-connector.sh` で作り、`VITE_CONNECTOR_URL=/download/DreamlandPassport.zip`
  で差し替えられる。`connect.py` や `bridge/` を変えたら exe を作り直して置き直すこと。
  メールで送る導線は廃止した。
- **MT5 に送る EA は `bridge/YumekkuEA-1年版.mq5` の1つだけ**（Orbit GOLD 2軸エンジン、
  XAUUSD 専用）。v6 はトレンド方向を UP/DOWN の二択にし、ナンピンを既定 OFF にしたもの。
  配るのはコンパイル済みの `bridge/YumekkuEA-1年版.ex5` だけ。ソース（`.mq5`）は
  配らないし、リポジトリにも入れない（`.gitignore`）。**ソースはこの Mac にしか無い**
  （`bridge/YumekkuEA-1年版.mq5` と `bridge/mac/YumekkuEA-1年版.mq5`）。消さないこと。
  - **設定画面の一番上は「ロット」。** `#include <TradingGate.mqh>` は入力の**後ろ**に置く
    （この中にも `input` があり、先頭に置くとそれが一番上に出る）。
  - **使用期限は 1 年。起算日は 2026-11-01**（`EXPIRY_TIME` = 2027-10-31 23:59:59）。過ぎると新規だけ止め、
    保有分は通常どおり決済。次の年に配り直すときは起算日の 1 年後の前日へ書き換える。切れる前に配り直すこと。
  - **ロットの上限は既定で無し**（`InpMaxLot = 0` ＝ 口座の上限まで）。サイトの管理画面で決めた
    ロット（`AI_LOT`、ブリッジの `ALLOWED_VARIABLES` で 0.01〜5.0）がそのまま効く。
  `bridge/OrbitGoldEA_v6.mq5` は**検証用に残してある**（トレンドを UP/DOWN の
  二択にして、中間で止まらないようにした版）。配りも読み込みもしない。
  消さないこと。`EA_NAMES` に入っていないので、お客様には届かない。
  お客様の MT5 に v6 が残っていれば `OLD_EA_NAMES` で片づける。いま配る EA の名前は `bridge/mt5_terminal.py` の `EA_NAMES` が唯一の定義で、
  connect.py の配置と bridge.py の有無報告がそこを見る。片づける旧 EA の名前は
  `connect.py` の `OLD_EA_NAMES`（別のリスト。EA を上げたら旧名をこちらへ足す）。
  EA を差し替えるときは、`TradingGate.mqh` を include して
  `IsTradingAllowedRaw()` / `GateNumber("AI_LOT")` などをエントリー前に見ることと、
  `OnTimer` で `SyncGateFileToGlobals()` を呼ぶこと（これが無いと `ea_alive` が立たず、
  サイトの「稼働／停止」も効かない）。売買ロジックそのものは触らない。
- **役割分担。** MT5との連携（初期設定・ダウンロード案内・メンバー紹介）は受付のユイ、
  稼働・停止・ロット変更（管理画面）はアルゴ。アルゴの「自動売買をはじめる」は
  未連携ならユイへ案内するだけ。台詞は `characters.ts` の `SETUP` / `TOUR`。

## 一斉制御（自社デモ口座をまとめて止める）の決まり

既存の画面・連携とは**別枠**。画面は `/fleet`（管理者）と `/fleet/join`（口座の登録）。

- **止める仕組みは、1口座ずつの画面と同じ。** 口座の PC で動く MT5 Automatic が、
  会員IDの部屋で中継につながっている前提。一斉制御はその部屋へ、同じ指令
  （`stop_trading` / `close_all` / `start_trading`）を一度に流すだけ（中継の `/fleet`、
  `handleFleet`）。ブリッジ側の歯止め（`ALLOWED_VARIABLES` など）はそのまま効く。
- **`/fleet` に入れるのは管理者だけ。** 中継が `auth_me` で `role = 'admin'` を確かめる。
  会員の確認（`SUPABASE_URL` / `SUPABASE_ANON_KEY`）が無い中継では入口ごと閉じる。
  流せる指令は `FLEET_COMMANDS` の3つだけ。ロット変更などは1口座ずつの画面で。
- **口座の数字は中継が覚えている要約を使う**（`room.status`）。100口座ぶんを
  1口座ずつ取りに行かない。一斉制御の画面も「画面1枚」と数えて（`notifyWatchers`）、
  見ているあいだだけブリッジに数字を送らせる。
- **届かなかった部屋は預かる。** ブリッジが居ない部屋への指令は `room.pending` に置き、
  名乗った（hello）瞬間に渡す。覚えるのは最後の1つだけ、中継を再起動すると消える。
  画面は「届いた／預かっている」を分けて出す。
- **止め方は3つ。** `stop_trading`（エントリーのみ停止＝新規だけ止める）、
  `close_all`（一斉全決済＝建玉と待機注文を全部閉じる。**新規は止めない**ので EA が
  また入りうる）、`stop_system`（システム停止＝新規を止めてから全部閉じる）。
  閉じるのは手動・EA を問わずその口座の全部（`_close_all_blocking`）。1件失敗しても
  最後まで回し、失敗した番号を返す。全決済だけの応答に売買フラグ（value）は混ぜない。
- **パスワードは預かるだけ。停止には使わない。** 登録簿（`fleet_accounts`）は
  `pgp_sym_encrypt` で暗号化し、鍵（`fleet_secret`）は関数の中からしか読めない。
  一覧（`fleet_list`）はパスワードを返さず、取り出すのは `fleet_reveal`（管理者）だけ。
  「MT5のパスワードは扱わない」はお客様向けの商品の話で、こちらは自社口座の台帳。
- **連携した時点で「受け付けた」とみなす。** 中継の `fleet_watch` は、頼まれた部屋に加えて
  「ブリッジがつながっている部屋」も要約に入れて返すので、画面は登録簿に無い部屋も
  そのまま「対象」の行として出す（`Row.virtual`）。お客様の入力は要らない。
  登録簿に入れるのは、管理者が「対象外」にするときか「登録簿に入れる」を押したとき
  （`fleet_register_for`。管理者だけ。パスワードは預からない。
  `supabase/migrations/20261003_fleet_register_for.sql`）。
- **お客様は自分で拒否できる。** アルゴの管理画面（`ControlPanel`）の
  「運営による一斉停止：受け付ける／受け付けない」。記録は `fleet_optout`
  （`fleet_optout_set` / `fleet_my_optout` / `fleet_optouts`、
  `supabase/migrations/20261003_fleet_optout.sql`）。
  **拒否は画面だけでなく中継でも効かせる。** `fleet_send` は流す直前に
  `fleet_optouts` を引いて、拒否した部屋を宛先から外す（`refusingRooms`、応答の `refused`）。
  画面を迂回して中継に直接つないでも、拒否した口座には届かない。
- **対象にする／対象外にする**は口座ごと（`included`）。一斉操作は対象の口座の部屋にだけ流す。
  同じ会員が複数口座を登録していても部屋は1つなので、画面は会員IDで束ねて送る。
- DB は `supabase/migrations/20261002_add_fleet.sql`（`schema.sql` にも同じものが入っている。
  ずれていないことは `phase2_test.py` が見ている）。

## ドリームランド渡航手続き（`dreamland/`）の決まり

営業用の特設サイトとは**別の静的ページ**（`dreamland/index.html` 1枚。Vite も React も使わない）。
お客様に渡す URL で、ロビーの係員 3 人（ユイ・ソラ・ミナト。パスポートカウンターのハルは 2026-10-14 に廃止）が「口座開設 → MT5 口座の登録 → ドリームランド・パスポート（接続ツール）の発行 → 搭乗」を案内し、
最後にドリームランド本体へ飛ばす。リンク・台詞・プラン名は `index.html` の `LINKS` / `SCRIPT` / `PLANS` だけで直す。

- **入った瞬間にユイ（インフォメーション）が開く。** 受付済みの端末なら「おかえりなさい」と続きを案内する
  （`localStorage` の `dreamland.application`。パスワードは覚えない）。
  URL の末尾 `#service` `#connect`（接続ツールの設置）`#tool` `#gate` `#first` `#crystal` で、その窓口から始められる（LINE で直接送る用）。
- **MT5 のパスワードは、ここでは預かる。** 「MT5のパスワードは扱わない」は接続ツールの話。ロビーのサービス
  カウンターでは、運用システム（EA）を納品するために口座番号・サーバー・パスワード・プラン・お名前を記入してもらう
  （メールは聞かない）。本体サイトの会員とは口座番号で結びつき、管理者画面の一覧に「会員」として出る。
  送り先はサイトの `/api/dreamland`（`api/_lib/dreamland.ts`）→ Supabase の `dreamland_apply`。
  一斉制御の登録簿と同じ鍵（`_fleet_key()`）で暗号化し、取り出せるのは管理者画面の
  「ドリームランドの口座申込」（`DreamlandApplications.tsx`、`dreamland_reveal`）だけ。
  ロビーは Supabase を直接叩かない。`supabase/migrations/20261012_dreamland_applications.sql`。
- **同意が無ければ預からない。** 注意書き（会員登録はおひとり一回・何度も登録した人は会員権を取り消す・
  記入して送った時点で承認）と、2 つの確認チェックが要る（画面でもサーバーでも `NO_CONSENT`）。
  **パスポートの発行（口座をつなぐ）の前にも、同じ注意書きを必ず通す**（`service.terms`。文面は `NOTICE` の 1 か所）。
  2 つのチェックを入れるまで「確認しました」が押せず、読まずに `signup` / `login` へ来ても `terms` に回す（ページを開いているあいだに一度）。
  同じ口座をもう一度送ったら上書きして `submissions` を数える（消さない。管理者が見て判断する）。
- **搭乗口はプランごとに 2 つ。** `first`＝ファーストクラス（搭乗口 1・DL-001）、
  `crystal`＝ロイヤルファーストクラス（搭乗口 2・DL-002。紺×金の装い。MT5 の口座を **2 つ**つなぐ）。
  行き先は `LINKS.dreamlandFirst` / `LINKS.dreamlandCrystal`。違う搭乗口に来たらミナトが正しい搭乗口へ案内する。
- **プランは「合言葉」で決まる。** サービスカウンターの「接続ツールの設置」で、お客様がご契約時の合言葉を打つ。
  合言葉はプランごとに 1 つ（`plan_passwords`。管理者画面の「プランの合言葉」か
  `supabase/migrations/20261013_set_plan_passwords.sql` で決める。これまでの入場パスワードはファーストクラスに引き継がれる）。
  ロビーは `/api/lobby`（`api/_lib/lobby.ts`）の `plan` で確かめ、合ったプランの案内にしか進めない
  （ロイヤルの人がファーストへ、ファーストの人がロイヤルへ行けない）。決まったプランは `localStorage` の
  `dreamland.plan`、合言葉そのものは登録に要るので `sessionStorage`（タブを閉じるまで）に置く。
  `supabase/migrations/20261013_plan_passwords.sql`（`members.plan` もここで足す。`phase2_test.py` 8-7 が schema.sql と見比べる）。
- **パスポートは「ダウンロードして開くだけ」で口座に紐づく（2026-10-14 から。Windows）。**
  ロビーは Windows 用を同じドメイン（`/download/…` を `dreamland/vercel.json` の rewrite で本体サイトへ）から
  **「DreamlandPassport-<合図>.exe」** という名前で配る（`startDownload`。押した瞬間に `connect_token` を発行して
  ダウンロード名に付ける）。パスポートは引数なしで開かれ、まだ連携していなければ、自分のファイル名の合図で
  連携する（`connect.py` の `connect_token_from_exe_name`。連携済み・`--startup` などの引数ありでは見ない）。
  だからロビーの「設置が終わった（つなぐ）」は **呼び出さずに名乗りを待つだけ**（`startConnect(idx, "wait")` →
  `waiting`）。`aitrader://` で呼ぶ（ブラウザに「開きますか？」が出る）のは、「それでもつながらない（呼び出す）」と
  「もう入れてある（呼び出す）」（`"launch"`）、Mac、以前つないだことのある端末だけ。戻ってきたときに勝手に呼び出さない。
  合図の期限は 24 時間（`supabase/migrations/20261014_connect_token_ttl.sql`。流すまでは 5 分）。
  同じ口座で「登録直後」は、この端末で一度もつないでいなければダウンロードの案内から始める（お客様は最初は持っていない）。
- **「設置が終わった（つなぐ）」は、サイトからパスポートを呼び出して（`aitrader://connect?token=`。ブラウザに
  「開きますか？」が出る）紐づけたうえで、名乗ってきたかを 30 秒確かめて結果を出す**（`startConnect(idx, "wait")` →
  `waiting` → `verifyInstalled` → 次へ／`notyet`／`stuck`）。ダウンロード時の合図（URL の `?k=`）で先に紐づいていれば、
  呼び出しは同じ部屋へのつなぎ直しになるだけ。呼び出しを外して合図だけに頼った日（2026-10-14）に紐づかなくなったので、
  呼び出しは外さない。
- **ブリッジは MT5 につながるのを待たずに中継へ名乗る**（`bridge.py` の `run()`。MT5 は `bring_up_mt5` で裏で待つ）。
  `get_status` は `mt5_ready=false` と理由 `mt5_error` を返し、ロビーは「パスポートが MT5 に接続できていません（理由）」と出す。
  以前は MT5 につながるまで中継に出なかったので、MT5 側でこけるとサイトからは「来ない」としか見えなかった。
- **お客様はサイトのパスワードを持たない。** パスポートの発行（口座をつなぐ）で聞くのは口座番号とお名前だけ。
  会員のパスワードはロビーが口座番号と合言葉から同じものを作って使う（`derivedPassword`。別の端末でも同じ会員に入れる）。
  サーバー（`auth_register` / `auth_login`）は変えていない。以前にパスワード付きで登録した口座だけ `loginpw`（入力）に回す。
- **接続ツールの設置は、サービスカウンターの中で本物の連携をする。** 本体サイトの初期設定（ユイ）と同じ仕組みを
  ロビーの JS に移したもの：合言葉 → 口座をつなぐ（`/api/lobby` の `register`。会員 ＝ 口座番号なので、
  口座ごとに会員ができる。登録済みなら `login`）→ 合図を発行（`connect_token`）して `aitrader://connect?token=`
  → 中継（`RELAY`）に会員の部屋で入り、ブリッジが名乗るのを待つ → 30 秒で来なければダウンロード案内
  （OS 別の手順。既定の部屋 `vps-01` を `/health` で見張り、初回起動を検知したら合図を付けて呼び直す）
  → `get_status` で口座を確かめる → `mt5StepIndex`（EA が載ったか・アルゴ取引が ON か）をブリッジの状態で見張る → 完了。
  つながっている口座が登録した口座と違えば止める（別の MT5 にログインしている）。
  つないだ会員は `dreamland.members`（セッションの合言葉を含む。サイトのパスワードは覚えない）。
  チェック（tool / ea / algo）は、この流れで自動で付く。
- **ロイヤルファーストクラスは 1 つ目を必ず、2 つ目は「今から／あとで」。** 1 つ目の連携が済むとソラが
  「2 つ目を今から設置する／あとで設置する」を出す（`service.done`）。「あとで」は `dreamland.second = "later"`。
  2 つ目はいつでも「2 つ目の口座をつなぐ」から（同じ合言葉で、別の口座番号の会員を作る）。
  搭乗は 1 つ目が済んでいればできる（搭乗券にその旨を添える）。
- **お客様向けの呼び名。** 接続ツール（MT5 Automatic）はロビーでは**「ドリームランド・パスポート」**（台詞の中では「パスポート」）、
  つなぐことは「パスポートの発行」、ミナトの窓口は**「搭乗ゲート」**。
  MT5 のパスワードや合言葉と紛れないよう、「パスポート」は接続ツールのことにしか使わない。パソコン上のファイル名・OS の確認ダイアログは MT5 Automatic のままなので、
  ダウンロードと呼び出しの台詞には「パソコン上の名前は MT5 Automatic」と添える（名前が違って戸惑わないため）。
- **スマホでは発行しない。** MT5 もパスポートもパソコンにしか入らないので、スマホ・タブレット（`isPhone`。iPad は
  Mac を名乗るので `maxTouchPoints` で見分ける）から「パスポートの発行」に進むと `service.pc`：「パソコンで開いて」と
  リンクを自分に送るボタン（`navigator.share`、無ければコピー）。口座の登録・マニュアル・搭乗ゲートはスマホでも使える。
  スマホの窓は下から出るシート（立ち絵は名前の横に小さく、台詞と資料は横幅いっぱい）。
- **パスポートカウンター（ハル）は無い。** ファイルの受け取り・手順・マニュアルはすべてサービスカウンター（ソラ）にある。
- **搭乗口は、搭乗ゲートを押してから選ぶ。** 地図のピンは「搭乗ゲート」1 つ（`pin--gate`）。押すとミナトが
  搭乗口 1・2 のカード（`DOCS.gates`）を出す。合言葉が済んでいれば自分の搭乗口だけ押せて、もう一方は
  「OTHER PLAN」で押せない。ピンには「あなたの搭乗口：N 番」が付く（`renderGates`）。
- **窓口へは「移動」してから話す。** `goTo(spot)`：絵とピン（`#world`）をその窓口に向けて寄せ（`transform-origin`
  をピンの位置にして `scale(1.14)`）、真ん中に「○○へ」のリボン（`#travel`）を 0.75 秒出してから係員の窓が開く。
  別の係員へ送る `@service` なども同じ。閉じると元の引きに戻る。`prefers-reduced-motion` では寄せも待ちもしない。
  搭乗券の有効期間の注記は `VALID_NOTE`（原則 1 年、半年プランは半年で AI の紐付けをやり直す）。
- **窓口が使えないときも「準備中」を出さない。** `LINKS.register` が `#TODO` のとき・サーバーが 5xx のときは
  「窓口が立て込んでいる」と言ってサポート LINE を出す（`service.busy`）。
- **MT5 ログインマニュアルと、パスポート＋EA の設置マニュアルもロビーの中**（`dreamland/manual-login/`、
  `dreamland/manual-setup/`。どちらも Windows 向け）。依頼者が作った PDF（スライド 1600×900、ロビーと同じ装い）を
  1 ページ 1 枚の WebP（`img/pNN.webp`）にして、ロビーの見た目のページに並べたもの。文面は PDF のまま。
  作り直すときは、新しい PDF を `~/Downloads` に置いて `scratchpad/make_manual.py` 相当の手順（PyMuPDF で描画 →
  `make_manual.py` のページ一覧を直す）。ロビーからの入口は `LINKS.loginManual` / `LINKS.winPdf`
  （ソラの「口座開設の案内」「設置マニュアル」、ダウンロード画面の下）。Mac 用の設置マニュアルは無い。
  動画の置き場は 2026-10-14 に外した。
- **口座開設マニュアルはロビーの中（`dreamland/manual/`）。** HFM 配布の PDF（42 ページ）を、ロビーと同じ装いの
  1 枚のウェブページに組み直したもの（画面写真は `manual/img/`、PDF から取り出した WebP）。文面は PDF と同じ。
  HFM 側の画面が変わって作り直すときは、新しい PDF から文章と画像を取り出して `manual/index.html` を組み直す
  （元の PDF は Google Drive。リンクは `LINKS.accountManual` = `manual/`）。
- **公開先は Vercel の別プロジェクト `dreamland-lobby`**（https://dreamland-lobby.vercel.app）。`dreamland/` を
  そのまま静的に出す（`dreamland/vercel.json` で noindex ヘッダー）。更新は `cd dreamland && vercel deploy --prod --yes`
  （`dreamland/.vercel` に紐付けがある。無ければ `vercel link --yes --project dreamland-lobby`）。本体サイトとは別なので、
  `/api/lobby` `/api/dreamland` の変更は本体サイト（kinyu-kenkyujo-dec-opt）の push で出す。
- **出発の演出は「搭乗口の光に包まれて雲の上へ」**（`.fly`）。飛行機の絵は使わない。金の輪が広がり、光が満ちて白に
  溶けてから本体へ移動する（3.5 秒）。ロイヤルは紺×金の色味（`fly--crystal`）。
- 動かすには、migration を流し、サイト側に `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` があればよい
  （新しい環境変数は要らない）。ロビーを置くドメインを `DREAMLAND_ORIGIN` に書けば、CORS をそこだけに絞れる。
- 試験は `api/_lib/dreamland.test.mjs` と `api/_lib/lobby.test.mjs`（`npm test` に入っている）。
  **公開の前に `tools/check-lobby.sh` を通す**：JS の文法と、HTML/JS で使っているクラスが CSS に揃っているかを見る
  （記入欄・搭乗口のカードの CSS がまとめて消えたまま公開され、文字化けのように見えた事故から）。
  ロビーの接続の流れは、偽のサイト（fetch）と偽のブリッジ（WebSocket）を iframe に差し込んで headless Chrome で通す。ロビーの通し確認は headless Chrome で行う
  （手元の 8765 番は別のアプリが使っているので、別の番号で `python3 -m http.server` を立てる）。

## サイトの分け方（2026-10-14 から）

- **お客様に見せる顔はロビー（dreamland-lobby.vercel.app）だけ。** 本体サイト（kinyu-kenkyujo-dec-opt）のトップ `/` と
  知らない URL はロビーへ飛ばす（`App.tsx` の `ToLobby`、`VITE_LOBBY_URL` で差し替え）。研究所の顔は出さない。
  本体に残すのは仕組みだけ：`/api/*`（窓口）、`/download/*`（接続ツール）、`/login`、`/control`（旧・管制室。
  稼働／停止・ロット。`Lab`）、`/admin`、`/fleet`、`/fleet/join`。`/chat` は廃止。
  `Lab` では AI の研究員（リン・ジン・ミオ）を出さない（`HIDDEN_STAFF`）。残るのはユイ・アルゴ・ガンツ。
- **管理サイトは別の Vercel プロジェクト `dreamland-admin`**（https://dreamland-admin-green.vercel.app）。同じリポジトリを
  `VITE_SITE_MODE=admin` で動かす（`App.tsx` の `ADMIN_SITE`）。入口は `/`（`AdminGate`）で、口座番号ではなく
  **管理サイトの合言葉 1 つ**で入る（`admin_login` → 運営用の会員 `operator@dreamland.local`、role = admin）。
  中は `/admin` と `/fleet` だけ。合言葉は `app_settings.admin_password_hash`（`supabase/migrations/20261014_admin_site.sql`、
  初期値は `20261014_set_admin_password.sql`、管理画面の「管理サイトの合言葉」からも変えられる）。
  知っている人は誰でも管理者になれるので、合言葉は外に出さない。
  更新は `VERCEL_ORG_ID=… VERCEL_PROJECT_ID=prj_qU83tud01kRJnqr9aGCLpmWu7uPR vercel deploy --prod --yes`
  （リポジトリ直下から。`.vercel` は本体に紐付いているので環境変数で上書きする）。環境変数は Vercel 側に
  `VITE_SITE_MODE` / `VITE_SUPABASE_URL` / `VITE_SUPABASE_ANON_KEY` / `VITE_RELAY_URL`。

## 部屋（会員ごとの分離）の決まり

- **会員 ＝ MT5 の口座番号。** 会員登録は「入場パスワード → 口座番号 → お名前 → パスワード」で、
  メールは聞かない（`auth_register(p_account, p_name, …)` / `auth_login(p_account, …)`、
  `supabase/migrations/20261012_member_account_login.sql`）。口座が2つある人は会員を2つ作る
  （それぞれに自分のサイトがある）。
  入場パスワードはプランの合言葉（`plan_passwords`）で受け、合ったプランが `members.plan` に入る
  （ロイヤルファーストクラスの 2 口座は、同じ合言葉で登録した 2 つの会員）。画面の呼び名は `memberLabel()`（お名前（口座番号））。
  `members.email` は残してあるが空（メールで登録した会員は居ない）。
- **部屋 = 会員のUUID。** 画面は `useBridge(member.id, token)`、ブリッジは `BRIDGE_ID`。
  中継（`server/index.js`）は同じ部屋の中だけを行き来させる。
- **BAN（管理者画面の「BAN」＝ `status = 'suspended'`）はブリッジも切る。** ブリッジは合言葉を
  持たず部屋（会員ID）だけで入ってくるので、中継が `bridges_blocked`（匿名で呼べる。返すのは
  「止められているか」だけ）を接続時に引いて断り、つないでいる間も `BLOCK_SWEEP_MS`（既定 60 秒）
  ごとに見回って 4003 `banned` で切る。削除（`admin_delete_member`）も同じ扱いになる
  （会員が無ければ「止められている」）。新しい版のブリッジは 4003 で終了する。
  自分自身と最後の管理者は消せない。
  `supabase/migrations/20261003_admin_delete_and_bridges_blocked.sql`。
- **同じ部屋に2台目のブリッジが来たら、名乗り（口座番号）を聞いてから決める**（`handleBridge`）。
  同じ口座なら「同じ PC の繋ぎ直し」として新しいほうに入れ替える（古いほうは 4001）。
  別の口座なら、動いているほうを守って新しいほうを断る（4002 `busy`）。
  返事（pong）が 75 秒無いブリッジは死んだものとして待たずに入れ替える。
  これが無いと、1つの会員で2台の MT5 を連携したとき、23 秒おきに追い出し合いが永久に続く
  （古い版の exe は 4001 で終了せず、ただ繋ぎ直すため。中継側でしか止められない）。
  新しい版のブリッジは 4002 を受けたら `BUSY_WAIT_SEC` 待ってから確かめ直す。
- **中継は「本人か」を確かめる。** 画面から来たセッションの合言葉を、画面と同じ
  `auth_me` で確かめ、その会員のIDを部屋にする。自己申告の部屋名は使わない。
  `SUPABASE_URL` / `SUPABASE_ANON_KEY` を中継に設定していないとこの確認が動かず、
  部屋の名前を知っている人は誰でも入れてしまう（起動ログで警告が出る）。
- **画面から来る指令はホワイトリスト。** `READ_COMMANDS` / `WRITE_COMMANDS` /
  `STOP_COMMANDS` に無いものはブリッジへ流さない。ブリッジは届いた指令を実行するので、
  ここが最後の関所になる。
- **`can_trade` はサーバー側で効かせる。** 管理画面で「売買を止める」にした会員は、
  中継が稼働・設定変更を断る。止める操作だけは通す（安全側にしか動かないため）。
  画面のボタンを消すだけでは、中継に直接つないだ相手を止められない。
- **書き換えてよい変数と範囲は、お客様のPC側でも確かめる**（`bridge.py` の
  `ALLOWED_VARIABLES`）。画面の `eaSettings.ts` と同じ値を置く。片方だけ変えない。
- **ログに会員IDと口座番号をそのまま残さない。** 中継のログは第三者の手にも渡りうる。
- **止めた会員のブリッジは HTTP 403 で門前払いしない。** ブリッジは 403 を
  「中継に繋がらない」としか読めず、60 秒おきに叩き直してログが毎分増える。
  最初の 1 回は WebSocket を開いてから 4003（利用停止）で閉じ、ブリッジに自分から
  終了させる（`rejectBannedBridge`）。4003 を知らない古い版が叩き直してくるあいだは、
  会員の確認だけして黙って 403 を返す（ログは部屋ごとに 1 時間に 1 行）。

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
4. ミオ → 「トレードを添削して」→ 履歴（既定180日）からクセを出す
5. 管理画面 → ロットの ＋ − → 「変更を反映する」
6. 「この端末の連携を解除」で最初の状態に戻せる

## 触るときに気をつける場所

- `Lab.tsx` は 1440×810 の固定ステージ。座標は `%` かステージ内px。
  画面サイズに合わせた拡縮は `base * zoom` で行っているので、
  新しい要素もステージの中に置くこと（画面直下に置くと拡縮から外れる）。
- `useMarket.ts` は 450ms ごとに再描画する。重い処理を足さない。
- `pages/Chat.tsx` は画面のどこからもリンクされていないが、`/chat/:id` は
  `App.tsx` で現役のルートとして生きている（直リンク用）。
