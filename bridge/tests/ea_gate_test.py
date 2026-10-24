"""配る EA に、サイト連携がちゃんと入っているかを確かめる。

    python3 bridge/tests/ea_gate_test.py

MetaEditor はここでは動かせないので、ソースを読んで
「無いと動かないもの」が揃っているかだけを見る。

これが欠けると何が起きるか:
  include が無い            … そもそもコンパイルが通らない
  OnTimer が無い            … ea_alive が立たず、サイトが EA を見つけられない。
                               ユイの初期設定がそこで止まる
  IsTradingAllowedRaw が無い … 管理画面の「停止」を押しても止まらない
  SiteLot が無い             … 管理画面でロットを変えても反映されない

見るのは Windows 用（bridge/<EA_NAMES[0]>.mq5）と Mac 用（bridge/mac/*Yumekku*.mq5）、
追加口座用（bridge/growth/<GROWTH_EA_NAME>.mq5。ロイヤルファーストクラスの 2 つ目に置く「安定低月利ver」）。
Mac 用には、接続ツールが口座を読むためのファイル書き出し（docs/mac-ea-files.md）も要る。
追加口座用には、設定画面の順（ロット → ユメックAIの制御）と、1 取引のリスク上限・月次ストップが要る。
ソースが無いとき（配るのは .ex5 だけなので、普通は無い）は何もせず通す。
"""
from __future__ import annotations

import pathlib
import re
import sys

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE))

from mt5_terminal import EA_NAMES, GROWTH_EA_DIRNAME, GROWTH_EA_NAME  # noqa: E402

GROWTH_DIR = BRIDGE / GROWTH_EA_DIRNAME
SOURCES = [
    p
    for p in (
        BRIDGE / f"{EA_NAMES[0]}.mq5",
        *sorted((BRIDGE / "mac").glob("*Yumekku*.mq5")),
        GROWTH_DIR / f"{GROWTH_EA_NAME}.mq5",
    )
    if p.is_file()
]

PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ok   {name}")
    else:
        FAIL += 1
        print(f"  NG   {name} {extra}")


def body_of(src: str, name: str) -> str:
    """関数の中身を、波かっこの対応で取り出す。"""
    m = re.search(rf"\b{name}\s*\([^)]*\)\s*\n?\s*{{", src)
    if m is None:
        return ""
    start = m.end() - 1
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return src[start:]


def py_body_of(src: str, name: str) -> str:
    """python の関数の中身（次の top-level def/class まで）。"""
    m = re.search(rf"^def {name}\b.*?$", src, re.M)
    if m is None:
        return ""
    rest = src[m.end():]
    n = re.search(r"^(def |class |[A-Za-z_])", rest, re.M)
    return rest[: n.start()] if n else rest


def run_checks(source: pathlib.Path) -> None:
    src = source.read_text(encoding="utf-8", errors="ignore")
    is_mac = source.parent.name == "mac"
    is_growth = source.parent.name == GROWTH_EA_DIRNAME

    # ── 1) 連携部品を読んでいるか ──
    check("TradingGate.mqh を include している", "#include <TradingGate.mqh>" in src)

    # ── 2) 生存を知らせているか（これが無いとサイトは EA を見つけられない）──
    on_timer = body_of(src, "OnTimer")
    check("OnTimer がある", bool(on_timer))
    check("OnTimer で状態ファイルを書いている", "SyncGateFileToGlobals" in on_timer, on_timer[:80])

    on_init = body_of(src, "OnInit")
    check("OnInit でタイマーを起こしている", "EventSetMillisecondTimer" in on_init)
    check("OnInit でも一度だけ状態を書いている", "SyncGateFileToGlobals" in on_init)

    on_deinit = body_of(src, "OnDeinit")
    check("OnDeinit でタイマーを止めている", "EventKillTimer" in on_deinit)
    check("OnDeinit で画面の表示を片づけている", "RemoveGateStatus" in on_deinit)

    # ── 3) 新規注文の前に、サイトと AI の判断を見ているか ──
    open_trade = body_of(src, "OpenTrade")
    check("OpenTrade がある", bool(open_trade))
    check("サイトの稼働／停止を見ている", "SiteAllowsEntry" in open_trade, "")
    check("AI 判定（廃止済み）を見ていない", "AiAllowsEntry" not in src and "AiCountSkip" not in src and "GateProfile" not in src)
    check("入ったら回数を記録している", "MarkSiteEntry" in open_trade)

    # 停止の判断は、実際に発注する前でなければ意味がない
    if open_trade:
        order = re.search(r"g_trade\.(Buy|Sell)\s*\(", open_trade)
        gate = open_trade.find("SiteAllowsEntry")
        check(
            "判断は発注より前にある",
            order is not None and 0 <= gate < order.start(),
            f"停止={gate} 発注={order.start() if order else '無し'}",
        )

    # ── 4) ロットはサイトの設定を使うか ──
    calc_lot = body_of(src, "CalcLot")
    check("ロットはサイトの設定から取る", "SiteLot" in calc_lot, calc_lot[:80])

    # ── 4-2) 設定画面の順（一番上がロット、その下に「ユメックAIの制御を受ける」、連携部品は入力の後ろ）──
    groups = [m.start() for m in re.finditer(r'input group "', src)]
    first_group = re.search(r'input group "([^"]*)"', src)
    check("設定画面の一番上のグループは「ロット」", first_group is not None and "ロット" in first_group.group(1),
          first_group.group(1) if first_group else "無し")
    site_ctl = src.find("input bool    InpSiteControl")
    check("「ユメックAIの制御を受ける」はロットのグループの中にある",
          site_ctl > 0 and len(groups) >= 2 and groups[0] < site_ctl < groups[1], f"位置={site_ctl}")
    inc = src.find("#include <TradingGate.mqh>")
    check("TradingGate.mqh は入力の後ろで読む（中の入力が一番上に出ないように）", inc > 0 and all(g < inc for g in groups))

    # ── 5) この EA の建玉を、取りこぼさず数えているか ──
    magic = body_of(src, "IsOrbitMagic")
    for axis in ("InpM1Magic", "InpH1Magic", "InpM30Magic"):
        check(f"{axis} を自分のものと数える", axis in magic, magic[:120])

    # ── 6) ナンピンを使うときも同じ関門を通るか ──
    basket = body_of(src, "ManageM1Basket")
    check("ナンピン追加もサイトの指示を見る", "SiteAllowsEntry" in basket)

    # ── 7) 売買ロジックに手を入れていないか（触ってよいのは連携だけ）──
    check("エントリー条件（リテスト）はそのまま", "retestBuy" in src and "retestSell" in src)
    check("トレールはそのまま", "ManageTrail" in src)
    check("日次損失リミットはそのまま", "TodayRealizedPnL" in src)

    if is_growth:
        # ── 9) 追加口座用（安定低月利ver）: 安全装置がサイト連携のあとも残っているか ──
        check("安定低月利ver: 1 取引のリスク上限を発注の前に見る",
              "RiskAmount" in open_trade and 0 <= open_trade.find("RiskAmount") < (re.search(r"g_trade\.(Buy|Sell)\s*\(", open_trade) or re.search("$", open_trade)).start())
        check("安定低月利ver: 月次損失ストップがある", "MonthRealizedPnL" in open_trade)
        check("安定低月利ver: 複利ロットがある", bool(body_of(src, "CompoundLot")))
        site_lot = body_of(src, "SiteLot")
        check("安定低月利ver: サイトのロットが無ければ複利に戻る", "AI_LOT" in site_lot and "CompoundLot" in site_lot, site_lot[:120])
        check("安定低月利ver: サイトのロットにも上限（InpMaxLotCap）が効く", "InpMaxLotCap" in site_lot)
        check("安定低月利ver: 月次の集計も決済ぶんを落とさない（INOUT / OUT_BY）",
              "DEAL_ENTRY_INOUT" in body_of(src, "RealizedPnLSince") and "DEAL_ENTRY_OUT_BY" in body_of(src, "RealizedPnLSince"))
        check("安定低月利ver: 名前は mt5_terminal.GROWTH_EA_NAME と同じ", source.stem == GROWTH_EA_NAME, source.stem)
        main_src = BRIDGE / f"{EA_NAMES[0]}.mq5"
        if main_src.is_file():
            exp = lambda t: (re.search(r"#define EXPIRY_TIME\s+D'([^']+)'", t) or re.search("$", t)).group(0)
            check("安定低月利ver: 有効期限は 1 年版と同じ", exp(src) == exp(main_src.read_text(encoding="utf-8", errors="ignore")), exp(src))
        return

    if not is_mac:
        return

    # ── 8) Mac 用: 接続ツールが読むファイルを書いているか（docs/mac-ea-files.md）──
    #   Mac 版 MT5 は外から読めないので、これが無いと「ログインしていない」扱いのまま
    for name in ("trelab_account.ini", "trelab_positions.ini", "trelab_orders.ini", "trelab_deals.ini", "trelab_cmd_ack.ini"):
        check(f"Mac: {name} を書く", f'"{name}"' in src)
    for name in ("trelab_request.ini", "trelab_cmd.ini"):
        check(f"Mac: {name} を読んで消す", f'"{name}"' in src and f'FileDelete("{name}", FILE_COMMON)' in src)
    for key in ("login=", "server=", "balance=", "equity=", "terminal_trade_allowed=", "symbol=", "at="):
        check(f"Mac: 口座の控えに {key} がある", f'"{key}"' in src)
    check("Mac: 共通フォルダ（FILE_COMMON）に書く", "FILE_COMMON" in src)
    check("Mac: 毎回まるごと上書きする（別名に書いて差し替え）", "FileMove(" in src and "FILE_REWRITE" in src)
    check("Mac: 閉じる指令は magic を見ない（PositionSelectByTicket だけ）", "PositionSelectByTicket" in body_of(src, "TbHandleCommand"))
    check("Mac: OnTimer でファイルのやり取りをしている", "TbTimer" in on_timer)
    check("Mac: 建玉が変わったら書き直す（OnTradeTransaction）", "OnTradeTransaction" in src)
    deals = body_of(src, "TbWriteDeals")
    check("Mac: 履歴は INOUT（ドテン）を落とさない（entry で絞らない）", "DEAL_ENTRY_OUT" not in deals and "entry=" in deals)
    check("Mac: 入出金は履歴に入れない", "DEAL_TYPE_BUY" in deals and "DEAL_TYPE_SELL" in deals)
    check("Mac: ロット固定の縛りが無い（上限は InpMaxLot の入力）", "input double  InpMaxLot" in src)
    for word in ("推奨資金", "検証", "破綻", "月利", "勝率"):
        check(f"Mac: 説明文に「{word}」が無い", word not in src)


# ── TradingGate.mqh（配る部品。リポジトリにあるので必ず見る）──
GATE = (BRIDGE / "TradingGate.mqh").read_text(encoding="utf-8", errors="ignore")
print("── bridge/TradingGate.mqh ──")
check("パネルの表記は「ユメックAIと連携済み」", "ユメックAIと連携済み" in GATE)
check("パネルの表記は「ユメックAIと未接続」", "ユメックAIと未接続" in GATE)
check("「判定が期限切れ」は出さない", "判定が期限切れ" not in GATE)
check("AI 判定（廃止済み）が残っていない", "AiAllowsEntry" not in GATE and "AI_GATE_MODE" not in GATE)
check("接続ツールの合図（AI_BRIDGE_AT）で生きているかを見る", "AI_BRIDGE_AT" in GATE and "GateBridgeAlive" in GATE)
check("合図は読むたびに 0 へ戻す（古い合図が居座らない）", 'GlobalVariableSet("AI_BRIDGE_AT", 0.0)' in GATE)
check("指令ファイルは口座番号付き（trelab_gate_<口座>.ini）があればそちらを読む", "GateFileName()" in GATE and 'trelab_gate_" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN))' in GATE)
check("控えも口座番号付きで書く（同じ PC の別口座と混ざらない）", "StateFileName()" in GATE and "trelab_state_" in GATE)
check("口座番号付きが無ければこれまでの名前（1 口座の PC・古い接続ツール）", '"trelab_gate.ini"' in GATE and '"trelab_state.ini"' in GATE)
check("生きているかは「変化を最後に見た時刻」で決める（PC の時計と更新時刻を直接比べない）", "g_gate_changed_at" in GATE and "now - beat" not in GATE and "now - g_gate_mtime" not in GATE)

# ── 追加口座（2 つ目の口座）には「安定低月利ver」を置く配線（connect.py）──
CONNECT = (BRIDGE.parent / "connect.py").read_text(encoding="utf-8", errors="ignore")
print("── connect.py（追加口座に置く EA）──")
slot_body = py_body_of(CONNECT, "connect_slot")
check("connect_slot は 1 本目の配布物ではなく growth_source() を置く", "growth_source()" in slot_body and "load_source(BRIDGE_DIR)" not in slot_body)
growth_body = py_body_of(CONNECT, "growth_source")
check("growth_source は bridge/growth/ から読む（Include は 1 本目と共有）",
      "GROWTH_EA_DIR" in growth_body and "include_dir=BRIDGE_DIR" in growth_body)
check("置いた EA の名前を slot.json に控える", '"ea": source.ea_path.stem' in slot_body)
check("追加口座のブリッジに「載せるべき EA」を渡す（BRIDGE_EA_NAME）", 'env["BRIDGE_EA_NAME"]' in py_body_of(CONNECT, "start_slot_bridge"))
route_body = py_body_of(CONNECT, "maybe_connect_second_account")
claim_body = py_body_of(CONNECT, "try_connect_from_claim")
main_body = CONNECT[CONNECT.index("def main(") :] if "def main(" in CONNECT else CONNECT
check("2 本目を足す／替える判断は maybe_connect_second_account に集約する",
      "return connect_slot(room, wanted)" in route_body and "second_account_allowed()" in route_body)
check("ロイヤル以外で別の口座が来たら、元の口座を「停止」にしてから替える（stop_old_account）",
      "stop_old_account(mine)" in route_body)
check("ロイヤルは MT5 が見つからなくても 1 本目を切り替えない（connect_slot に任せて止まる）",
      "terminal_for_account(wanted) is not None" not in route_body)
check("ロビーからその場でつなぐ経路も 2 本目の判断を通す（1 年版の置き直しを防ぐ）",
      "maybe_connect_second_account(room, acct)" in claim_body)
check("サイトのボタン経路も同じ判断を通す",
      "maybe_connect_second_account(room, wanted)" in main_body)
pick_body = py_body_of(CONNECT, "source_for_account")
check("置く EA は口座で分ける（1 本目は 1 年版、2 つ目は安定低月利ver）",
      "is_second_account(account)" in pick_body and "growth_source()" in pick_body)
check("2 つ目かはサイトの slot を優先する（手元の 1 本目が空でも同じでも）",
      "site_says_second()" in route_body and "remember_slot(" in CONNECT)
check("設置もつなぎ直しも source_for_account で置く",
      "source_for_account(" in py_body_of(CONNECT, "setup_phase1")
      and "source_for_account(" in py_body_of(CONNECT, "copy_ea_files"))
stop_body = py_body_of(CONNECT, "stop_old_account")
check("停止は元の口座あての指令ファイル（trelab_gate_<口座>.ini）に書く", 'trelab_gate_{account}.ini' in stop_body and 'AI_TRADING_ALLOWED' in stop_body)
check("この PC の意思（intent.json）も停止に戻す", 'intent.json' in stop_body and '"allowed": 0.0' in stop_body)
check("プランは合図の返事（/api/connect の plan）から取る", 'data.get("plan")' in py_body_of(CONNECT, "redeem_connect_token"))
check("何番目の口座かも合図の返事（slot）から取る", 'data.get("slot")' in py_body_of(CONNECT, "redeem_connect_token"))
check("配布物（bridge/growth/<名前>.ex5）がリポジトリにある", (GROWTH_DIR / f"{GROWTH_EA_NAME}.ex5").is_file())
check("bridge/ 直下に安定低月利ver の .ex5 を置いていない（1 本目として配られる）", not (BRIDGE / f"{GROWTH_EA_NAME}.ex5").exists())
BRIDGE_PY = (BRIDGE / "bridge.py").read_text(encoding="utf-8", errors="ignore")
check("ブリッジは載せるべき EA（EXPECTED_EA）を状態に返す", '"ea_expected": EXPECTED_EA' in BRIDGE_PY and 'os.environ.get("BRIDGE_EA_NAME"' in BRIDGE_PY)
check("「○○を載せてください」は EXPECTED_EA で出す", "{EXPECTED_EA} を載せてください" in BRIDGE_PY)
LOBBY = (BRIDGE.parent / "dreamland" / "index.html").read_text(encoding="utf-8", errors="ignore")
check("ロビーの手順は ea_expected（無ければ何番目の口座か）で EA 名を出す", "Bridge.status.ea_expected" in LOBBY and "${eaName()}" in LOBBY)
check("ロビーの EA 名は mt5_terminal と同じ", f'"{GROWTH_EA_NAME}"' in LOBBY and f'"{EA_NAMES[0]}"' in LOBBY)
check("ロビーは 2 つ目の手続きで slot=2 を合図に付ける", "slot: memberSlot(m)" in LOBBY and "memberSlot" in LOBBY)
check("2 つ目は合図を待つだけでなくパスポートを呼び出す（slot=2 を URL に載せる）",
      "memberSlot(m) === 2) issueAndLaunch()" in LOBBY)
# ── 別の口座の EA が動かないこと（1 つ目の操作で 2 つ目が稼働／停止した事故から）──
_gate_src = (BRIDGE / "TradingGate.mqh").read_text(encoding="utf-8")
_bridge_src = (BRIDGE / "bridge.py").read_text(encoding="utf-8")
_connect_src = (BRIDGE.parent / "connect.py").read_text(encoding="utf-8")
check("EA は宛先の口座番号（AI_ACCOUNT）を見て、別の口座あての指令に従わない",
      '"AI_ACCOUNT"' in _gate_src and "ACCOUNT_LOGIN" in _gate_src and "MathAbs(addressed - mine)" in _gate_src)
check("ブリッジは指令に自分の口座番号を必ず付ける", 'f"AI_ACCOUNT={OWN_ACCOUNT}' in _bridge_src)
check("ブリッジは担当と違う口座の MT5 に繋がったら繋ぎ直す", "担当の MT5 を探します" in _bridge_src)
check("パスポートはサイトの口座の MT5 だけを使い、お客様に選ばせない", "site_acct = LAST_REDEEMED_ACCOUNT" in _connect_src)
check("2 つ目の口座は見つからなければ止める（ほかの MT5 を選ばせない）", "heading=pick_heading(2)" not in _connect_src)
check("ブリッジに担当の口座番号を渡す", 'env["BRIDGE_ACCOUNT"]' in _connect_src)

check("連携済みでもロビーの合図を先に取る（1 年版の置き直しを防ぐ）",
      "take_all_claims()" in main_body)
check("「2つ同時に」の 2 つ目は、もう 1 つのパスポートに渡す", "hand_over_claim(" in main_body)

if not SOURCES:
    print("  --   EA のソース（.mq5）が無いので省略します（配るのは .ex5 だけ）")
    raise SystemExit(1 if FAIL else 0)

for source in SOURCES:
    print(f"── {source.relative_to(BRIDGE.parent)} ──")
    run_checks(source)

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
