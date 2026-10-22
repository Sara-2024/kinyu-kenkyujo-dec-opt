"""サイトからの連携（Phase 2）を、サイトも MT5 も無いところで確かめる。

見たいのは4つ。

  ・aitrader://connect?token=... から合図を読めるか
  ・合図をサイトに確かめてもらい、その返事の部屋だけを採用するか
  ・確かめられなければ連携しない（＝通信も始めない）か
  ・アプリ単体では連携できない（合図を自分で作れない）か

実行: python3 bridge/tests/phase2_test.py
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
ROOT = BRIDGE.parent
WORK = tempfile.mkdtemp(prefix="aitrader-phase2-")
os.environ["LOCALAPPDATA"] = str(pathlib.Path(WORK) / "Local")
os.environ["APPDATA"] = str(pathlib.Path(WORK) / "Roaming")

sys.path.insert(0, str(BRIDGE))
sys.path.insert(0, str(ROOT))

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


import connect  # noqa: E402
import connect_state  # noqa: E402

GOOD = "a" * 64
MEMBER = "11111111-2222-4333-8444-555555555555"

# ── 1) URL から合図を読む ────────────────────────────
check("合図を読める", connect.connect_token_from_args([f"aitrader://connect?token={GOOD}"]) == GOOD)
check(
    "from が一緒でも読める",
    connect.connect_token_from_args([f"aitrader://connect?from=https://x.test&token={GOOD}"]) == GOOD,
)
check("短い合図は読まない", connect.connect_token_from_args(["aitrader://connect?token=abc"]) == "")
check("16進でない合図は読まない", connect.connect_token_from_args([f"aitrader://connect?token={'z' * 64}"]) == "")
check("合図が無ければ空", connect.connect_token_from_args(["aitrader://connect?room=" + MEMBER]) == "")
check("ファイル名の合図を読める（ダウンロード名）", connect.connect_token_from_exe_name(f"C:\\Users\\x\\Downloads\\DreamlandPassport-{GOOD}.exe") == GOOD)
check("ブラウザが (1) を付けても読める", connect.connect_token_from_exe_name(f"/tmp/DreamlandPassport-{GOOD} (1).exe") == GOOD)
check("合図の無い名前は空", connect.connect_token_from_exe_name("/tmp/DreamlandPassport.exe") == "")

# ── 追加口座（ロイヤルファーストクラスの 2 つ目）──
check("合図の URL から口座番号を読める", connect.account_from_args([f"aitrader://connect?token={GOOD}&account=135209731"]) == "135209731")
check("口座番号が無ければ空", connect.account_from_args([f"aitrader://connect?token={GOOD}"]) == "")
check("数字でない口座番号は読まない", connect.account_from_args([f"aitrader://connect?token={GOOD}&account=abc"]) == "")
_slot = connect.slot_dir("135209731")
check("追加口座の設定は accounts/<口座番号>/ に分かれる", _slot.name == "135209731" and _slot.parent.name == "accounts")
import json as _json
(_slot / "slot.json").write_text(_json.dumps({"account": "135209731", "room": MEMBER, "terminal": "/nowhere", "exe": ""}), encoding="utf-8")
check("追加口座の一覧を読める", any(x.get("account") == "135209731" for x in connect.list_slots()))
check("1 本目の口座番号が無ければ空（これまでどおり扱う）", connect.primary_account() == "" or connect.primary_account().isdigit())
check("短い・16進でない名前は空", connect.connect_token_from_exe_name("/tmp/DreamlandPassport-abc.exe") == "" and connect.connect_token_from_exe_name(f"/tmp/DreamlandPassport-{'z' * 64}.exe") == "")
import tempfile as _tf
_zdir = pathlib.Path(_tf.mkdtemp())
_zexe = _zdir / "DreamlandPassport.exe"; _zexe.write_bytes(b"MZ")
# Windows の Zone.Identifier（代替データストリーム）の代わりに、同じ名前のファイルで形だけ再現する
(_zdir / "DreamlandPassport.exe:Zone.Identifier").write_text(f"[ZoneTransfer]\r\nZoneId=3\r\nReferrerUrl=https://dreamland-lobby.vercel.app/\r\nHostUrl=https://dreamland-lobby.vercel.app/download/DreamlandPassport.exe?k={GOOD}\r\n", encoding="utf-8")
check("ダウンロード元の URL（Zone.Identifier）から合図を読める", connect.connect_token_from_exe_name(str(_zexe)) == GOOD)
(_zdir / "DreamlandPassport.exe:Zone.Identifier").write_text("[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://dreamland-lobby.vercel.app/download/DreamlandPassport.exe\r\n", encoding="utf-8")
check("URL に合図が無ければ空", connect.connect_token_from_exe_name(str(_zexe)) == "")
check("ただの引数は読まない", connect.connect_token_from_args(["--console", GOOD]) == "")

# ── 2) URL の room= は、もう読まない ────────────────
check("room= を読む処理は無い", not hasattr(connect, "site_room_from_args"))
check("room= からは合図を作らない", connect.connect_token_from_args([f"aitrader://connect?room={MEMBER}"]) == "")

# ── 3) 合図をサイトに確かめてもらう ──────────────────
sent: list[dict] = []


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *_a) -> None:  # noqa: ANN002
        return None


def fake_urlopen(payload):  # noqa: ANN001, ANN202
    def inner(req, timeout=0):  # noqa: ANN001, ANN202
        sent.append({"url": req.full_url, "body": json.loads(req.data.decode("utf-8"))})
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)

    return inner


real_urlopen = connect.urllib.request.urlopen

connect.urllib.request.urlopen = fake_urlopen({"ok": True, "room": MEMBER})
room = connect.redeem_connect_token(GOOD)
check("正しい合図なら部屋が返る", room == MEMBER, room)
check("問い合わせ先は /api/connect", sent and sent[0]["url"].endswith("/api/connect"), str(sent[:1]))
check("合図を送っている", sent and sent[0]["body"].get("token") == GOOD)
check("宛先は決め打ち（from= を当てにしない）", sent and sent[0]["url"].startswith("https://"), str(sent[:1]))

# 返事に部屋が無い／おかしい
connect.urllib.request.urlopen = fake_urlopen({"ok": True})
check("部屋が無ければ連携しない", connect.redeem_connect_token(GOOD) == "")
connect.urllib.request.urlopen = fake_urlopen({"ok": True, "room": "../../etc/passwd"})
check("おかしな部屋は受け取らない", connect.redeem_connect_token(GOOD) == "")

# サイトが断った／つながらない
connect.urllib.request.urlopen = fake_urlopen(
    connect.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
)
check("サイトが断れば連携しない", connect.redeem_connect_token(GOOD) == "")
connect.urllib.request.urlopen = fake_urlopen(OSError("network"))
check("つながらなければ連携しない", connect.redeem_connect_token(GOOD) == "")

# ── 4) 合図が通らないかぎり、状態は変わらない ────────────
check("まだ INSTALL_ONLY", connect_state.current() == connect_state.INSTALL_ONLY, connect_state.current())
check("つながっていない", not connect_state.is_connected())

# 合図が通ったときだけ CONNECTED になる（adopt_room を通す）
connect.write_env_key = lambda *a, **k: None  # .env は書かせない
connect.adopt_room(MEMBER)
check("連携すると CONNECTED", connect_state.is_connected())
check("部屋を覚えている", connect_state.read().get("room") == MEMBER)

# 連携が済めば、既存のブリッジが動かせるようになる（歯止めを通り抜ける）
reached = []
connect.bridge_already_running = lambda: (reached.append("見に行った"), False)[1]
connect.spawn_hidden = lambda *a, **k: reached.append("起動した")
connect.start_bridge(None)
check("連携後はブリッジが動かせる", "起動した" in reached, str(reached))

# 解除すれば、また止まる
connect_state.mark_install_only("試験")
reached.clear()
connect.start_bridge(None)
check("解除すると、また止まる", reached == [], str(reached))
connect_state.mark_connected(MEMBER)

# ── 5) アプリ単体では合図を作れない ──────────────────
src = (ROOT / "connect.py").read_text(encoding="utf-8")
# コメントに書いてある言葉ではなく、実際に呼んでいる処理で見る
import ast  # noqa: E402

tree = ast.parse(src)
called = set()
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        fn = node.func
        if isinstance(fn, ast.Attribute):
            base = fn.value.id if isinstance(fn.value, ast.Name) else ""
            called.add(f"{base}.{fn.attr}".lstrip("."))
        elif isinstance(fn, ast.Name):
            called.add(fn.id)
risky = {c for c in called if c.startswith(("secrets.", "random.")) or c in ("os.urandom", "uuid4")}
check("合図を自分で作らない", not risky, str(risky))
check("発行の関数を呼んでいない", "connect_token_issue" not in called and "connect_token_issue" not in src)
check("確かめるのもサイトに任せる（直接 DB を叩かない）", "connect_token_redeem" not in src)

# ── 6) 記録に合図そのものを残さない ──────────────────
log_text = ""
log_path = pathlib.Path(os.environ["LOCALAPPDATA"]) / "AITrader" / "connect.log"
if log_path.is_file():
    log_text = log_path.read_text(encoding="utf-8")
check("記録に合図を書いていない", GOOD not in log_text)

# ── 7) サイト側が room= を作っていないこと ───────────────
connector_ts = (ROOT / "src" / "data" / "connector.ts").read_text(encoding="utf-8")
check("サイトは room= を発行しない", "params.set('room'" not in connector_ts)
check("サイトは token= を発行する", "params.set('token'" in connector_ts)
check("サイトは会員IDを URL に載せない", "member?.id" not in connector_ts)

dialogue = (ROOT / "src" / "components" / "DialogueWindow.tsx").read_text(encoding="utf-8")
check("画面も会員IDを渡していない", "launchConnector(member?.id)" not in dialogue)

# ── 7-2) 使う MT5 を固定できるか（複数あるPCで、別の MT5 に入らないこと）──
import inspect  # noqa: E402

import mt5_terminal  # noqa: E402

sig = inspect.signature(mt5_terminal.find_logged_in_terminal)
check("MT5 を指定して探せる", "prefer_data_path" in sig.parameters)
src_connect = (ROOT / "connect.py").read_text(encoding="utf-8")
check("覚えている MT5 を優先して渡している", 'find_logged_in_terminal(chosen)' in src_connect)
check("使った MT5 を覚える", 'terminal=used' in src_connect)

# ── 8-0) 一斉制御の migration も schema.sql とずれていないか ──
fleet_mig = ROOT / "supabase" / "migrations" / "20261002_add_fleet.sql"
check("一斉制御の migration がある", fleet_mig.is_file())
if fleet_mig.is_file():
    fleet_sql = fleet_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("一斉制御の migration の中身が schema.sql と同じ", fleet_sql.strip() in schema_all)
    check("一斉制御の migration は追加だけ（既存を落とさない）", "drop " not in fleet_sql.lower().replace("do update", ""))
    # パスワードは暗号化して入れ、鍵のテーブルは外から読めない
    check("パスワードは暗号化して保存", "pgp_sym_encrypt" in fleet_sql)
    check("鍵のテーブルは外から読めない", "revoke all on table public.fleet_secret" in fleet_sql)
    check("一覧はパスワードを返さない", "password" not in fleet_sql[fleet_sql.index("_fleet_row_json(r public.fleet_accounts") : fleet_sql.index("fleet_register(")])

# ── 8-1) 「つながっている口座を登録する」migration も schema.sql とずれていないか ──
reg_mig = ROOT / "supabase" / "migrations" / "20261003_fleet_register_for.sql"
check("管理者登録の migration がある", reg_mig.is_file())
if reg_mig.is_file():
    reg_sql = reg_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("管理者登録の migration の中身が schema.sql と同じ", reg_sql.strip() in schema_all)
    check("管理者登録は管理者だけ", "_require_admin(p_token)" in reg_sql)
    check("管理者登録は追加だけ（既存を落とさない）", "drop " not in reg_sql.lower().replace("do update", ""))

# ── 8-2) 「一斉停止を受け付けない」migration も schema.sql とずれていないか ──
opt_mig = ROOT / "supabase" / "migrations" / "20261003_fleet_optout.sql"
check("受け付けないの migration がある", opt_mig.is_file())
if opt_mig.is_file():
    opt_sql = opt_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("受け付けないの migration の中身が schema.sql と同じ", opt_sql.strip() in schema_all)
    check("切り替えは本人だけ（セッションの会員）", "_session_member(p_token)" in opt_sql[opt_sql.index("fleet_optout_set") :])
    check("一覧は管理者だけ", "_require_admin(p_token)" in opt_sql[opt_sql.index("fleet_optouts(") :])
    check("記録のテーブルは外から読めない", "revoke all on table public.fleet_optout" in opt_sql)
    check("受け付けないの migration は追加だけ（既存を落とさない）", "drop " not in opt_sql.lower().replace("do update", ""))

# ── 8-3) 「会員の削除」と「BAN した会員のブリッジを切る」migration も schema.sql とずれていないか ──
ban_mig = ROOT / "supabase" / "migrations" / "20261003_admin_delete_and_bridges_blocked.sql"
check("削除・BAN の migration がある", ban_mig.is_file())
if ban_mig.is_file():
    ban_sql = ban_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("削除・BAN の migration の中身が schema.sql と同じ", ban_sql.strip() in schema_all)
    check("削除は管理者だけ", "_require_admin(p_token)" in ban_sql[ban_sql.index("admin_delete_member") :])
    check("自分自身は消せない", "SELF_DELETE" in ban_sql)
    check("最後の管理者は消せない", "LAST_ADMIN" in ban_sql)
    check("ブリッジの確認は「止められているか」だけ返す", "status = 'active'" in ban_sql[ban_sql.index("bridges_blocked") :])
    check("削除・BAN の migration は既存のテーブルを落とさない", "drop table" not in ban_sql.lower())

# ── 8-3b) 「合図の返事にプラン」「管理者が会員のプランを直す」migration も schema.sql とずれていないか ──
plan_mig = ROOT / "supabase" / "migrations" / "20261017_connect_plan_and_admin_set_plan.sql"
check("プランの migration がある", plan_mig.is_file())
if plan_mig.is_file():
    plan_sql = plan_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    # connect_token_redeem は 20261022 で書き換わった（口座番号も返す）ので、
    # この migration からは admin_set_member_plan のぶんだけを schema.sql と見比べる
    admin_part = plan_sql[plan_sql.index("create or replace function public.admin_set_member_plan") :]
    check("プランの migration の中身（admin_set_member_plan）が schema.sql と同じ", admin_part.strip() in schema_all)
    acct_mig = ROOT / "supabase" / "migrations" / "20261022_connect_token_account.sql"
    check("合図の返事に口座番号を足す migration がある", acct_mig.is_file())
    if acct_mig.is_file():
        acct_sql = acct_mig.read_text(encoding="utf-8")
        check("合図の返事に account が入る", "'account', v_member.account" in acct_sql)
        check("口座番号の migration は既存のテーブルを落とさない", "drop table" not in acct_sql.lower())
    slot_mig = ROOT / "supabase" / "migrations" / "20261022_connect_token_slot.sql"
    check("合図の返事に何番目の口座か（slot）を足す migration がある", slot_mig.is_file())
    if slot_mig.is_file():
        slot_sql = slot_mig.read_text(encoding="utf-8")
        fn = slot_sql[slot_sql.index("create or replace function public.connect_token_redeem") :]
        check("slot の migration の中身が schema.sql と同じ", fn.strip() in schema_all, "schema.sql の connect_token_redeem を 20261022_connect_token_slot と同じにする")
        check("合図の返事に slot が入る", "'slot', v_slot" in slot_sql)
        check("slot の migration は既存のテーブルを落とさない", "drop table" not in slot_sql.lower())
    check("合図の返事に plan が入る", "'plan', v_member.plan" in plan_sql[plan_sql.index("connect_token_redeem") :])
    check("プランを直せるのは管理者だけ", "_require_admin(p_token)" in plan_sql[plan_sql.index("admin_set_member_plan") :])
    check("プランは 3 つのどれか", "('first', 'crystal', 'premium')" in plan_sql[plan_sql.index("admin_set_member_plan") :])
    check("プランの migration は既存のテーブルを落とさない", "drop table" not in plan_sql.lower())

# ── 8-4) 「お使いのパソコン（Windows / Mac）の記録」migration も schema.sql とずれていないか ──
pf_mig = ROOT / "supabase" / "migrations" / "20261004_platform.sql"
check("OS の記録の migration がある", pf_mig.is_file())
if pf_mig.is_file():
    pf_sql = pf_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("OS の記録の migration の中身が schema.sql と同じ", pf_sql.strip() in schema_all)
    check("記録は本人だけ（セッションの会員）", "_session_member(p_token)" in pf_sql[pf_sql.index("member_platform_set") :])
    check("windows / mac 以外は受け付けない", "('windows', 'mac')" in pf_sql)
    check("管理者の一覧に OS が出る", "c.platform," in pf_sql)
    check("OS の記録の migration は既存のテーブルを落とさない", "drop table" not in pf_sql.lower())

# ── 8-5) ドリームランドの口座申込の migration も schema.sql とずれていないか ──
dl_mig = ROOT / "supabase" / "migrations" / "20261012_dreamland_applications.sql"
check("ドリームランドの申込の migration がある", dl_mig.is_file())
if dl_mig.is_file():
    dl_sql = dl_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("ドリームランドの申込の migration の中身が schema.sql と同じ", dl_sql.strip() in schema_all)
    check("パスワードは一斉制御と同じ鍵で暗号化する", "pgp_sym_encrypt(p_password, public._fleet_key())" in dl_sql)
    check("同意が無ければ預からない", "NO_CONSENT" in dl_sql)
    check("一覧と取り出しは管理者だけ", dl_sql.count("_require_admin(p_token)") >= 4)
    check("一覧はパスワードを返さない", "password" not in dl_sql[dl_sql.index("_dreamland_row_json(r public") : dl_sql.index("dreamland_apply(")].replace("password_enc", ""))
    check("同じ口座をもう一度送ったら回数を数える", "submissions = public.dreamland_applications.submissions + 1" in dl_sql)
    check("テーブルは直接読めない", "revoke all on table public.dreamland_applications" in dl_sql)
    check("ドリームランドの申込の migration は既存のテーブルを落とさない", "drop table" not in dl_sql.lower())

# ── 8-6) 「会員 ＝ 口座番号」の migration も schema.sql とずれていないか ──
acc_mig = ROOT / "supabase" / "migrations" / "20261012_member_account_login.sql"
check("口座番号ログインの migration がある", acc_mig.is_file())
if acc_mig.is_file():
    acc_sql = acc_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("口座番号ログインの migration の中身が schema.sql と同じ", acc_sql.strip() in schema_all)
    check("登録は口座番号・お名前・パスワード・入場パスワード", "auth_register(p_account bigint, p_name text, p_password text, p_entry text)" in acc_sql)
    check("ログインは口座番号とパスワード", "auth_login(p_account bigint, p_password text)" in acc_sql)
    check("メールでの登録・ログインは消す", "drop function if exists public.auth_register(text, text, text)" in acc_sql and "drop function if exists public.auth_login(text, text)" in acc_sql)
    check("口座番号は会員ごとに一つ（重複しない）", "members_account_idx" in acc_sql and "ACCOUNT_TAKEN" in acc_sql)
    check("ロビーの申込と会員を口座番号で結ぶ", "left join public.members m on m.account = r.account" in acc_sql)
    check("会員の表は落とさない", "drop table" not in acc_sql.lower())


# ── 8-7) 「プランごとの合言葉」の migration も schema.sql とずれていないか ──
plan_mig = ROOT / "supabase" / "migrations" / "20261013_plan_passwords.sql"
check("プランの合言葉の migration がある", plan_mig.is_file())
if plan_mig.is_file():
    plan_sql = plan_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("プランの合言葉の migration の中身が schema.sql と同じ", plan_sql.strip() in schema_all)
    check("合言葉はハッシュで持つ（crypt）", "crypt(p_entry, password_hash)" in plan_sql and "gen_salt('bf')" in plan_sql)
    check("登録で合ったプランを会員に記録する", "insert into public.members (account, name, password_hash, role, plan)" in plan_sql)
    check("これまでの入場パスワードはファーストクラスに引き継ぐ", "select 'first', entry_password_hash from public.app_settings" in plan_sql)
    check("合言葉の確認は総当たりを遅らせる", "pg_sleep" in plan_sql)
    check("合言葉を決められるのは管理者だけ", "_require_admin(p_token)" in plan_sql)
    check("合言葉の表は直接読めない", "revoke all on table public.plan_passwords" in plan_sql)
    check("プランの合言葉の migration は既存のテーブルを落とさない", "drop table" not in plan_sql.lower())


# ── 8-8) 「管理サイトの合言葉」の migration も schema.sql とずれていないか ──
adm_mig = ROOT / "supabase" / "migrations" / "20261014_admin_site.sql"
check("管理サイトの migration がある", adm_mig.is_file())
if adm_mig.is_file():
    adm_sql = adm_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("管理サイトの migration の中身が schema.sql と同じ", adm_sql.strip() in schema_all)
    check("合言葉はハッシュで持つ", "crypt(p_password, v_hash)" in adm_sql)
    check("運営の会員は admin で作る", "'operator@dreamland.local', '運営'" in adm_sql and "'admin')" in adm_sql)
    check("合言葉の確認は総当たりを遅らせる", "pg_sleep" in adm_sql)
    check("合言葉を変えられるのは管理者だけ", "_require_admin(p_token)" in adm_sql)
    check("管理サイトの migration は既存のテーブルを落とさない", "drop table" not in adm_sql.lower())


# ── 8-9) プレミアムプラン（渡航なし）の migration も schema.sql とずれていないか ──
pm_mig = ROOT / "supabase" / "migrations" / "20261015_premium_plan.sql"
check("プレミアムプランの migration がある", pm_mig.is_file())
if pm_mig.is_file():
    pm_sql = pm_mig.read_text(encoding="utf-8")
    schema_all = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
    check("プレミアムプランの migration の中身が schema.sql と同じ", pm_sql.strip() in schema_all)
    check("会員・合言葉・申込の 3 つの制約に premium が入る", pm_sql.count("('first', 'crystal', 'premium')") >= 5)
    check("合言葉を決めるのは管理者だけ", "_require_admin(p_token)" in pm_sql[pm_sql.index("admin_set_plan_password") :])
    check("プレミアムプランの migration は既存のテーブルを落とさない", "drop table" not in pm_sql.lower())

# ── 8) DB の追加分（migration）と schema.sql がずれていないか ──
mig_path = ROOT / "supabase" / "migrations" / "20260912_add_connect_tokens.sql"
schema_path = ROOT / "supabase" / "schema.sql"
check("migration がある", mig_path.is_file())
if mig_path.is_file():
    mig = mig_path.read_text(encoding="utf-8")
    schema = schema_path.read_text(encoding="utf-8")
    body = mig[mig.index("create table if not exists public.connect_tokens") :]
    # 合図の期限は 20261014_connect_token_ttl.sql で 5 分 → 60 分にした。schema.sql は新しいほう
    body = body.replace("now() + interval '5 minutes'", "now() + interval '24 hours'").replace("'expires_in', 300", "'expires_in', 86400")
    check("migration の中身が schema.sql と同じ（期限だけ 24 時間）", body.strip() in schema)
    ttl_path = ROOT / "supabase" / "migrations" / "20261014_connect_token_ttl.sql"
    check("期限を延ばす migration がある", ttl_path.is_file())
    if ttl_path.is_file():
        ttl = ttl_path.read_text(encoding="utf-8")
        fn = ttl[ttl.index("create or replace function public.connect_token_issue") :]
        check("期限を延ばす migration の関数が schema.sql と同じ", fn.strip() in schema)
        check("期限は 24 時間", "interval '24 hours'" in ttl and "'expires_in', 86400" in ttl)
    for name in ("connect_tokens", "connect_token_issue", "connect_token_redeem"):
        check(f"migration に {name} が入っている", name in mig)
    check("索引も入っている", "connect_tokens_member_idx" in mig and "connect_tokens_expires_idx" in mig)
    check("権限も入っている", mig.count("grant execute") == 2, str(mig.count("grant execute")))
    # 実行される行（コメントを除いたもの）が、既存のものに触っていないこと
    lines = [ln.split("--")[0].strip() for ln in mig.splitlines()]
    sql = " ".join(ln for ln in lines if ln)
    import re as _re

    bad = [
        m
        for m in _re.findall(r"(?:alter|drop)\s+(?:table|function|index)\s+[\w.]+", sql, _re.I)
        if "connect_token" not in m
    ]
    check("既存のテーブル・関数に触らない", not bad, str(bad))
    check("members や sessions を書き換えない", "alter table public.members" not in sql and "public.sessions" not in sql)

# ══════════════════════════════════════════════════
# 9) 通しで確かめる。CONNECTED になれる入口は合図だけ
# ══════════════════════════════════════════════════
connect_state.mark_install_only("通しの試験の前に戻す")

# にせの MT5 と配布物（EA を置くところまでは動かせるようにする）
import hashlib  # noqa: E402

mt5_dir = pathlib.Path(os.environ["APPDATA"]) / "MetaQuotes" / "Terminal" / ("C" * 32)
(mt5_dir / "MQL5" / "Experts").mkdir(parents=True, exist_ok=True)
(mt5_dir / "MQL5" / "Include").mkdir(parents=True, exist_ok=True)
install_dir = pathlib.Path(WORK) / "PF" / "HFM MetaTrader 5"
install_dir.mkdir(parents=True, exist_ok=True)
(install_dir / "terminal64.exe").write_text("")
(mt5_dir / "origin.txt").write_text(str(install_dir), encoding="utf-16")

assets = pathlib.Path(WORK) / "assets"
assets.mkdir(exist_ok=True)
BODY = b"EX5-FOR-PHASE2"
(assets / "3YumekkuEA_win.ex5").write_bytes(BODY)
(assets / "TradingGate.mqh").write_text("// 共通部品", encoding="utf-8")
(assets / "ea_manifest.json").write_text(
    json.dumps({"ea": "3YumekkuEA_win", "file": "3YumekkuEA_win.ex5", "version": "6.10",
                "sha256": hashlib.sha256(BODY).hexdigest()}), encoding="utf-8")
connect.BRIDGE_DIR = assets
connect.installer_ui.open_window = lambda: None


def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
    raise AssertionError(f"起動・通信してはいけない場面で呼ばれた: {a[:1]}")


connect.spawn_hidden = boom
connect.run_hidden = boom
connect.urllib.request.urlopen = boom
connect.write_env_key = lambda *a, **k: None

calls: list[str] = []
# show= は「手で開いたときだけ画面を出す」ための引数。ここでは画面を出さない
connect.connect_all = lambda room="", show=False: (calls.append(room), 0)[1]


def run_main(*argv: str) -> int:
    sys.argv = ["connect.py", *argv]
    return connect.main()


# (A) INSTALL_ONLY の PC に room= を投げても、連携させない
connect_state.mark_install_only("試験")
calls.clear()
code = run_main(f"aitrader://connect?room={MEMBER}")
check("room= を渡しても失敗にはしない（EA は置く）", code == 0, f"code={code}")
check("room= では CONNECTED にならない", not connect_state.is_connected(), connect_state.current())
check("room= では連携の処理に進まない", calls == [], str(calls))
check("room= ではブリッジも通信も起きない", True)  # boom が呼ばれたらここまで来ない
check("room= でも EA は置かれる", (mt5_dir / "MQL5" / "Experts" / "3YumekkuEA_win.ex5").is_file())

# (B) 会員IDを知っていても、部屋を名乗るだけでは連携できない
calls.clear()
run_main(f"aitrader://connect?room={MEMBER}&from=https://example.test")
check("from が付いていても同じ", not connect_state.is_connected() and calls == [])

# (C) 形だけ token に似せても、サイトが確かめないかぎり連携しない
calls.clear()
connect.urllib.request.urlopen = fake_urlopen(
    connect.urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)  # type: ignore[arg-type]
)
code = run_main(f"aitrader://connect?token={GOOD}")
check("サイトが断れば失敗で終わる", code == 1, f"code={code}")
check("断られたら CONNECTED にならない", not connect_state.is_connected())
check("断られたら連携の処理に進まない", calls == [])
connect.urllib.request.urlopen = boom

# (D) 正しい合図のときだけ INSTALL_ONLY → CONNECTED
calls.clear()
connect.urllib.request.urlopen = fake_urlopen({"ok": True, "room": MEMBER})
code = run_main(f"aitrader://connect?token={GOOD}")
check("正しい合図なら成功", code == 0, f"code={code}")
check("正しい合図で連携の処理に進む", calls == [MEMBER], str(calls))
connect.urllib.request.urlopen = boom

# (E) すでに使っているお客様は、URL ではなく手元の設定から引き継ぐ
connect_state.state_path().unlink(missing_ok=True)
calls.clear()
connect.env_value = lambda key: MEMBER if key == "BRIDGE_ID" else ""
code = run_main()
check("既存のお客様は引き継げる", connect_state.is_connected(), connect_state.current())
check("引き継いだらこれまでどおり動く", calls == [""], str(calls))

# (E2) つなぎ直しの URL（合図なし）。サイトの管理画面から開かれるもの
#      条件: 正式な連携情報があるときだけ再接続する／未連携は CONNECTED にならない／
#            合図なしで新しい紐付けはできない
RELAUNCH = "aitrader://connect"
check("つなぎ直しの URL からは合図を読まない", connect.connect_token_from_args([RELAUNCH]) == "")

#   連携済みの PC → これまでどおりつなぎ直す
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: MEMBER if key == "BRIDGE_ID" else ""
calls.clear()
code = run_main(RELAUNCH)
check("連携済みなら、つなぎ直しに進む", calls == [""], str(calls))
check("連携済みのままでいる", connect_state.is_connected())

#   未連携の PC → EA を置くだけ。部屋も持たない
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: ""
calls.clear()
code = run_main(RELAUNCH)
check("未連携なら CONNECTED にならない", not connect_state.is_connected(), connect_state.current())
check("未連携ならつなぎ直しにも進まない", calls == [], str(calls))
check("未連携でもブリッジも通信も起きない", True)  # boom が呼ばれたらここまで来ない
check("合図なしでは新しい紐付けができない", connect_state.read().get("room") in (None, ""), str(connect_state.read()))

# (E3) Windows の起動時（--startup）。古い版が登録した自動起動が残っている PC で、
#      毎回ログインのたびに設定画面が開かないこと
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: ""
calls.clear()
opened = []
connect.installer_ui.open_window = lambda: (opened.append(1), None)[1]
code = run_main("--silent", "--startup")
check("未連携なら自動起動で何もしない", code == 0 and calls == [] and opened == [], f"code={code} calls={calls} 画面={opened}")
check("未連携の自動起動では CONNECTED にならない", not connect_state.is_connected())

#      連携済みなら、これまでどおり裏でつなぎ直す
connect_state.state_path().unlink(missing_ok=True)
connect.env_value = lambda key: MEMBER if key == "BRIDGE_ID" else ""
calls.clear()
opened.clear()
code = run_main("--silent", "--startup")
check("連携済みなら自動起動でつなぎ直す", calls == [""], str(calls))
check("自動起動では画面を出さない", opened == [], str(opened))
connect.installer_ui.open_window = lambda: None

# (F) 引き継ぐ材料が無い PC は、EA を置くだけ
connect_state.state_path().unlink(missing_ok=True)
calls.clear()
connect.env_value = lambda key: "vps-01" if key == "BRIDGE_ID" else ""
code = run_main()
check("既定の部屋では引き継がない", not connect_state.is_connected(), connect_state.current())
check("EA を置くだけで終わる", calls == [], str(calls))

connect.urllib.request.urlopen = real_urlopen
shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
