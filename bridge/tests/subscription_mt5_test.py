"""
Yumekku【サブスク版】の利用許可と、「閉じた MT5 を勝手に開かない」の試験。MT5 も Windows も要らない。

実行: python3 bridge/tests/subscription_mt5_test.py

確かめること
  1) 動いている MT5 が無ければ、mt5.initialize を一度も呼ばない（呼ぶと MT5 が起動してしまう）
  2) 動いている MT5 だけに繋ぎに行く（閉じている MT5 は名指しでも試さない）
  3) ブリッジの再接続（_attach_to / _initialize_any_blocking）も、閉じた MT5 を起こさない
  4) パスポートは MT5 が閉じていても MT5 を起動しない（connect_all に launch_mt5 が無い）
  5) 中継から来た利用許可を、指令ファイルの SUB_UNTIL / SUB_SIG に書く。変な値は受け取らない
  6) 署名の作り方が DB（migration）と EA で同じ文字列になっている
  7) サブスクの会員の口座には Yumekku【サブスク版】を置き、1 年版で代えない
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import pathlib
import re
import sys
import tempfile
import types

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
BRIDGE = ROOT / "bridge"
sys.path.insert(0, str(BRIDGE))

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


# ── MetaTrader5 の身代わり（initialize が呼ばれたら記録する）──
calls: list[dict] = []


class FakeMT5(types.ModuleType):
    def __init__(self) -> None:
        super().__init__("MetaTrader5")
        self.logged = False

    def initialize(self, **kwargs):  # noqa: D401
        calls.append(kwargs)
        return True

    def shutdown(self):
        return True

    def account_info(self):
        return types.SimpleNamespace(login=123456, server="HFM-Demo", balance=0, equity=0, currency="JPY")

    def terminal_info(self):
        return types.SimpleNamespace(data_path="", commondata_path=TMP, name="MT5", build=1, connected=True, trade_allowed=True)

    def last_error(self):
        return (0, "")


TMP = tempfile.mkdtemp(prefix="subtest-")
fake = FakeMT5()
sys.modules["MetaTrader5"] = fake

import mt5_terminal  # noqa: E402

mt5_terminal.mt5 = fake

# ── 1) 動いている MT5 が無ければ initialize を呼ばない ──
mt5_terminal.running_terminal_exes = lambda: []
calls.clear()
got = mt5_terminal.find_logged_in_terminal()
check("MT5 が全部閉じていれば、誰にも繋がず None", got is None)
check("MT5 が全部閉じていれば、initialize を呼ばない（起動させない）", calls == [], str(calls))

# ── 2) 動いている MT5 だけを試す ──
live = pathlib.Path(r"C:\MT5-A\terminal64.exe")
mt5_terminal.running_terminal_exes = lambda: [live]
calls.clear()
got = mt5_terminal.find_logged_in_terminal()
paths = [c.get("path") for c in calls]
check("動いている MT5 に繋ぐ", got is not None and got.get("account") == 123456, str(got))
check("試すのは動いている MT5 だけ（path 無しの initialize もしない）", paths == [str(live)], str(paths))

# Windows 以外（Mac は mt5_files。起動しない）は、これまでどおり
mt5_terminal.running_terminal_exes = lambda: None
check("調べられないとき（Windows 以外）は「動いている」扱い", mt5_terminal.terminal_is_running(r"C:\x\terminal64.exe") is True)

# ── 3) ブリッジの再接続も、閉じた MT5 を起こさない ──
try:
    import websockets.exceptions  # noqa: F401
except ImportError:

    def _stub(name: str, **attrs: object) -> None:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod

    async def _connect(*_a: object, **_k: object) -> None:
        raise RuntimeError("stub")

    _stub("websockets", exceptions=types.SimpleNamespace(WebSocketException=Exception))
    _stub("websockets.exceptions", WebSocketException=Exception)
    _stub("websockets.asyncio", client=types.SimpleNamespace(connect=_connect))
    _stub("websockets.asyncio.client", connect=_connect)

os.environ["LOCALAPPDATA"] = TMP
os.environ["APPDATA"] = TMP
import bridge as bridge_mod  # noqa: E402

bridge_mod.mt5 = fake
bridge_mod.terminal_is_running = lambda _exe=None: False
bridge_mod.running_terminal_exes = lambda: []
bridge_mod.find_logged_in_terminal = lambda *_a, **_k: None
cfg = bridge_mod.Config()
cfg.mt5_path = r"C:\MT5-A\terminal64.exe"
ctl = bridge_mod.MT5Controller(cfg)
calls.clear()
check("閉じた MT5 には _attach_to しない", bridge_mod._attach_to(pathlib.Path(cfg.mt5_path), 1000) is None and calls == [], str(calls))
ok = ctl._initialize_any_blocking()
check("MT5 が全部閉じていれば、ブリッジは initialize を呼ばない", ok is False and calls == [], str(calls))
check("閉じていることを理由として持つ（サイトに出す）", "閉じています" in ctl.mt5_error, ctl.mt5_error)

# 名指しの MT5 が閉じていて、別の MT5 が動いていれば、動いているほうを名指しにする（path 無しで起こさない）
other = pathlib.Path(r"C:\MT5-B\terminal64.exe")
bridge_mod.running_terminal_exes = lambda: [other]
bridge_mod.terminal_is_running = lambda exe=None: exe is None or pathlib.Path(str(exe)) == other
calls.clear()
ctl._initialize_any_blocking()
check("最後の手段の initialize も、動いている MT5 を名指しにする", calls and calls[-1].get("path") == str(other), str(calls))


# 再接続の待ちは、閉じているあいだ initialize を呼ばずに回る
async def _wait_closed() -> int:
    bridge_mod.terminal_is_running = lambda _exe=None: False
    bridge_mod.MT5_CLOSED_POLL_SEC = 0.01
    stop = asyncio.Event()
    calls.clear()
    task = asyncio.create_task(ctl.connect_with_retry(stop))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, 2)
    return len(calls)

check("MT5 が閉じているあいだ、再接続は MT5 を起こさずに待つ", asyncio.run(_wait_closed()) == 0)

# ── 4) パスポートは MT5 を起動しない ──
connect_src = (ROOT / "connect.py").read_text(encoding="utf-8")
body = connect_src[connect_src.index("def connect_all(") : connect_src.index("def _same_path(")]
check("connect_all は MT5 を起動しない（launch_mt5 を呼ばない）", "launch_mt5(" not in body)
check("MT5 が閉じていても、連携済みならブリッジだけ先に動かす", "start_bridge(None)" in body)
check("自動起動のときは MT5 を開くのを待たない", "if not ui:\n                return 0" in body)

# ── 5) 利用許可を指令ファイルへ ──
ctl2 = bridge_mod.MT5Controller(bridge_mod.Config())
ctl2.ready = True
bridge_mod.OWN_ACCOUNT = "123456"
ctl2._gate_dir = lambda: pathlib.Path(TMP)  # type: ignore[method-assign]
check("変な許可（署名が 48 ビットを超える）は受け取らない", ctl2.take_license({"until": 1, "sig": 2 ** 48}) is False)
check("変な許可（数でない）は受け取らない", ctl2.take_license({"until": "x", "sig": 1}) is False)
check("正しい許可は受け取る", ctl2.take_license({"until": 1800000000, "sig": 123456789012, "status": "active"}) is True)
asyncio.run(ctl2.apply_license())
gate = ctl2._load_gate()
check("指令ファイルに期限を書く", gate.get("SUB_UNTIL") == 1800000000.0, str(gate))
check("指令ファイルに署名を丸めずに書く", int(gate.get("SUB_SIG", 0)) == 123456789012, str(gate))
text = (pathlib.Path(TMP) / ctl2._gate_name()).read_text(encoding="utf-8")
check("宛先の口座番号も付く（ほかの口座の EA は読まない）", text.startswith("AI_ACCOUNT=123456"), text[:40])
ctl2.take_license({"until": 0, "sig": 0, "status": "stopped"})
asyncio.run(ctl2.apply_license())
check("停止したら期限 0 を書く（EA は新規を止める）", ctl2._load_gate().get("SUB_UNTIL") == 0.0)

# ── 6) 署名の作り方が DB と EA で同じ ──
mig = (ROOT / "supabase" / "migrations" / "20261118_subscription.sql").read_text(encoding="utf-8")
check("DB の署名は 'YMKSUB|口座|期限|鍵' の sha256 先頭 12 桁",
      "'YMKSUB|' || p_account::text || '|' || p_until::text || '|' || s.secret" in mig and "substr(encode(" in mig and ", 1, 12)" in mig)
ea_src_path = BRIDGE / "subscription" / "Yumekku【サブスク版】ver1.1.mq5"
if ea_src_path.is_file():   # ソースはこの Mac にしか無い（.gitignore）
    ea = ea_src_path.read_text(encoding="utf-8")
    check("EA の署名も同じ文字列", '"YMKSUB|" + IntegerToString(account) + "|" + IntegerToString(until) + "|" + YMK_SUB_SECRET' in ea)
    check("EA は先頭 6 バイト（＝16 進 12 桁）を使う", "for(int i = 0; i < 6; i++) v = (v << 8) | (long)hash[i];" in ea)
    check("EA は末尾の 0 を含めずに sha256 を取る", "ArrayResize(data, n - 1);" in ea and "CRYPT_HASH_SHA256" in ea)
    check("EA に固定の有効期限が無い（承認で決まる）", "EXPIRY_TIME" not in ea)
    check("新規の前に承認を確かめる", re.search(r"if\(!SubscriptionOK\(\)\)\s*\{", ea) is not None)
    check("ナンピン追加も承認が要る", 'hit && SpreadOK() && !SubscriptionOK()' in ea)
    check("期限はサーバー時計で見る（PC の時計を戻しても延びない）", "(long)TimeCurrent() - SUB_SERVER_SLACK_SEC > (long)until" in ea)
    check("マジックナンバーは添付のロット調整版と同じ（20261201/02/03）", all(f"= {m};" in ea for m in ("20261201", "20261202", "20261203")))
    check("鍵はソースに直接書かない（SubscriptionSecret.mqh から読む）", '#include "SubscriptionSecret.mqh"' in ea and not re.search(r"[0-9a-f]{64}", ea))
# 例：Python で同じ計算をすると 48 ビットに収まる（double で丸まらない）
digest = hashlib.sha256(b"YMKSUB|123456|1800000000|" + b"k" * 64).hexdigest()
check("署名は 48 ビット（double で正確に運べる）", int(digest[:12], 16) < 2 ** 48 <= 2 ** 53)

# ── 7) サブスクの会員には Yumekku【サブスク版】を置く ──
check("名前に Yumekku を含む（うちの EA として扱われる）", mt5_terminal.is_our_ea(mt5_terminal.SUB_EA_NAME))
src_body = connect_src[connect_src.index("def subscription_source(") : connect_src.index("def source_for_account(")]
check("サブスク版が無いときに 1 年版で代えない", "load_source(BRIDGE_DIR)" not in src_body.replace("include_dir=BRIDGE_DIR", ""))
sfa = connect_src[connect_src.index("def source_for_account(") :]
sfa = sfa[: sfa.index("\ndef ")]
check("サブスクの判定がいちばん先", sfa.index("is_subscription()") < sfa.index("is_second_account("))
check("合図の返事のプランを覚える", "remember_subscription()" in connect_src[connect_src.index("LAST_REDEEMED_PLAN = str(data.get"):][:400])
ex5 = BRIDGE / "subscription" / "Yumekku【サブスク版】ver1.1.ex5"
check("配布物（.ex5）がある", ex5.is_file())

# ── 8) サブスクの名前で配ったときは「ドリームランド・パスポート」と見せない ──
import installer_ui  # noqa: E402

installer_ui.SUB_BRAND = True
said = installer_ui.brand("ドリームランド・パスポートを開いてください。パスポートが自動でつながります")
check("サブスクの名前では「パスポート」を言い換える", "パスポート" not in said and "ドリームランド" not in said and "Yumekku Link" in said, said)
installer_ui.SUB_BRAND = False
check("ふだんの名前では言い換えない", installer_ui.brand("パスポート") == "パスポート")
check("サブスクの判定は同梱の目印か、ファイル名が Yumekku で始まるか", '(BRIDGE_DIR / "brand_subscription.txt").is_file()' in connect_src and 'Path(sys.executable).stem.lower().startswith("yumekku")' in connect_src)
check("名前を変えた exe のブリッジも止められる（connect.py のヒント）", '"yumekku"' in connect_src[connect_src.index("BRIDGE_IMAGE_HINTS = tuple("):][:300])
bsrc = (BRIDGE / "bridge.py").read_text(encoding="utf-8")
check("名前を変えた exe のブリッジも止められる（bridge.py のヒント）", '"yumekku"' in bsrc[bsrc.index("def _is_bridge_process"):][:800])
page = (ROOT / "dreamland" / "yumekku-sub" / "index.html").read_text(encoding="utf-8")
check("特別ゲートは YumekkuLink.exe を配る（ファイルそのものが別。名前の上書きに左右されない）", 'winFile: "/download/YumekkuLink.exe"' in page and 'const SUB_FILE_NAME = "YumekkuLink.exe"' in page)
check("特別ゲートの画面に「パスポート」と出さない", "パスポート" not in page)

# ── 9) 中継に届かなくても、合図の取りに行きで落ちない ──
rc = connect_src[connect_src.index("def relay_claim_with_slot("):]
rc = rc[: rc.index("\ndef ")]
check("中継に届かないときも、戻り値は 2 つ（合図・何番目か）", 'return "", 0, 0' not in rc and rc.count('return "", 0') >= 2)

bat = (ROOT / "tools" / "build-windows.bat").read_bytes().decode("cp932")
check("ビルドはサブスク版の exe（YumekkuLink.exe）も作る", "set \"PYI_NAME=YumekkuLink\"" in bat and "public\\download\\YumekkuLink.exe" in bat)
check("サブスク版の exe には目印と別の起動画像を入れる", "tools\\brand_subscription.txt;bridge" in bat and "tools\\splash-yumekku.png" in bat)
check("目印と起動画像のファイルがある", (ROOT / "tools" / "brand_subscription.txt").is_file() and (ROOT / "tools" / "splash-yumekku.png").is_file())
wf = (ROOT / ".github" / "workflows" / "build-exe.yml").read_text(encoding="utf-8")
check("自動ビルドはサブスク版の exe も commit する", "public/download/YumekkuLink.exe" in wf)

isb = connect_src[connect_src.index("def is_subscription("):]
isb = isb[: isb.index("\ndef ")]
check("Yumekku Link は連携済みの PC でもサブスク版を置く（いちばん先に SUB_BRAND を見る）", isb.index("if SUB_BRAND:") < isb.index("LAST_REDEEMED_PLAN"))

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
