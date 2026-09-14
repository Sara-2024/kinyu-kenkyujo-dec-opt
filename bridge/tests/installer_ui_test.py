"""初回の設定画面が、お客様に見せてよい形になっているかを確かめる。

  ・専門用語（MQL5 / Experts / ブリッジ / API / Python …）を画面に出していないか
  ・ボタンの高さが 44px 以上あるか（老眼と手の震えを前提にする）
  ・本文の文字が小さすぎないか
  ・手順に ✓ が付くか

画面を開けない環境（CI・サーバー）では、何もせずに通す。
実行: python3 bridge/tests/installer_ui_test.py
"""
from __future__ import annotations

import pathlib
import sys

BRIDGE = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BRIDGE))

import installer_ui as ui  # noqa: E402

if ui.headless():
    print("  -- 画面を開けない環境なので省略します")
    raise SystemExit(0)

ok = fail = 0
def check(name, cond, extra=""):
    global ok, fail
    if cond: ok += 1; print(f"  ok   {name}")
    else: fail += 1; print(f"  NG   {name} {extra}")

w = ui.open_window()
check("窓を開ける", w is not None)
w.say("HFM が見つかりました。")
w.add_step("mt5", "MT5の確認"); w.mark("mt5", True)
w.add_step("ea", "AI Traderの設定"); w.mark("ea", True)
w.button("閉じる", lambda: None)
w.root.update_idletasks()

check("題名は MT5 Automatic", w.root.title() == "MT5 Automatic", w.root.title())
check("案内文が入る", "HFM" in w.message.cget("text"), w.message.cget("text"))
marks = [m.cget("text") for m, _ in w._steps]
check("手順に✓が付く", marks == ["✓", "✓"], str(marks))

btns = [c for c in w.buttons.winfo_children()]
check("ボタンがある", len(btns) == 1)
h = btns[0].winfo_reqheight()
check("ボタンの高さが44px以上", h >= 44, f"{h}px")
f = w.f["body"].actual()
check("本文の文字が12pt以上", f["size"] >= 12, str(f["size"]))

# 画面に技術用語を出していないか、窓の中の文字を全部集めて確かめる
words = []
def walk(widget):
    try: words.append(str(widget.cget("text")))
    except Exception: pass
    for c in widget.winfo_children(): walk(c)
walk(w.root)
blob = " ".join(words)
banned = ["MQL5", "Experts", "Terminal", "Bridge", "ブリッジ", "API", "Python", "Socket", "ex5", "mq5"]
hit = [b for b in banned if b.lower() in blob.lower()]
check("専門用語を出していない", not hit, str(hit))

# 選択画面: 台数が多くてもボタンが押せるか（画面の外に出ないか）
import tkinter as tk  # noqa: E402

w2 = ui.open_window()
many = [(f"d{i}", f"SomeBroker-Demo{i}（口座 {10000000 + i}）") for i in range(8)]
w2.clear_body()
w2.clear_buttons()
w2.say("設定するMT5を選んでください。")
need = 300 + 46 * len(many)
w2.root.update_idletasks()
ui._center(w2.root, 560, min(need, max(400, w2.root.winfo_screenheight() - 120)))
var = tk.StringVar(value=many[0][0])
for value, label in many:
    tk.Radiobutton(
        w2.body, text=label, variable=var, value=value, bg=ui.BG, fg=ui.TEXT,
        selectcolor=ui.PANEL, activebackground=ui.BG, activeforeground=ui.TEXT,
        font=w2.f["step"], anchor="w", justify="left", wraplength=460, padx=6, pady=6,
    ).pack(fill="x", anchor="w")
w2.button("これで設定する", lambda: None)
w2.root.update_idletasks()
w2.root.update()
btn2 = w2.buttons.winfo_children()[0]
bottom = btn2.winfo_rooty() - w2.root.winfo_rooty() + btn2.winfo_height()
check("8台あってもボタンが窓の中にある", bottom <= w2.root.winfo_height(), f"{bottom} > {w2.root.winfo_height()}")
check("ボタンは下に固定されている", btn2.winfo_rooty() > w2.body.winfo_rooty())
w2.close()

# はい／いいえの画面が作れるか（MT5 を開き直すかを聞く）
w4 = ui.open_window()
w4.clear_body()
w4.clear_buttons()
w4.say("MT5を開き直しますか？")
w4.button("開き直す（おすすめ）", lambda: None, primary=True)
w4.button("あとで自分でやる", lambda: None, primary=False)
w4.root.update_idletasks()
w4.root.update()
btns = w4.buttons.winfo_children()
check("はい／いいえの2つが出る", len(btns) == 2, str(len(btns)))
low = btns[-1].winfo_rooty() - w4.root.winfo_rooty() + btns[-1].winfo_height()
check("どちらも窓の中にある", low <= w4.root.winfo_height(), f"{low} > {w4.root.winfo_height()}")
w4.close()
check("閉じられていれば ask は いいえ", w4.ask("?", "はい", "いいえ") is False)

# ✕ で閉じられたあとに触っても落ちないか（実際に落ちていた）
w3 = ui.open_window()
w3._on_close()
check("閉じたあとは alive() が False", not w3.alive())
try:
    w3.say("なにか")
    w3.clear_body()
    w3.clear_buttons()
    w3.add_step("x", "手順")
    w3.mark("x", True)
    w3.button("押せない", lambda: None)
    w3.finish(["終わり"], ok=True)
    w3.fail("だめでした", "もう一度")
    w3.close()
    check("閉じたあとに触っても落ちない", True)
except Exception as exc:  # noqa: BLE001
    check("閉じたあとに触っても落ちない", False, f"{type(exc).__name__}: {exc}")

# 失敗の案内に技術的な原因を書いていないか
import inspect
src = inspect.getsource(ui)
check("失敗時の文面も日本語の案内だけ", "MQL5 Directory" not in src and "not found" not in src)
w.close()
print(f"\n{ok} ok / {fail} NG")
sys.exit(1 if fail else 0)
