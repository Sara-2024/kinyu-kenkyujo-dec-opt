"""MT5 Automatic の画面（初回の設定だけ）。

40〜60代のお客様が迷わないことを最優先にする。

  ・専門用語を出さない（MQL5 / Experts / ブリッジ / API / Python は書かない）
  ・文字は大きめ、ボタンは高さ 44px 以上
  ・失敗しても「何をすればいいか」だけを出す

黒い画面（コンソール）は出さない。ここはウィンドウなので、お客様には
「アプリが開いた」としか見えない。

tkinter は Python に同梱されているので、追加の部品は要らない。
画面が開けない環境（サーバー等）では headless() が True を返すので、
呼び出し側は画面なしで進めてよい。
"""
from __future__ import annotations

import os
import sys

from typing import Any, Callable, Sequence

try:
    import tkinter as tk
    from tkinter import font as tkfont
except Exception:  # noqa: BLE001 - 画面が無い環境
    tk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]

APP_NAME = "MT5 Automatic"

BG = "#0b1220"
PANEL = "#111c31"
TEXT = "#e8edf5"
MUTED = "#94a3b8"
ACCENT = "#5eccff"
OK = "#35f58a"
WARN = "#ffd23e"
NG = "#ff8484"


def close_splash() -> None:
    """起動中に出している画像（PyInstaller の --splash）を消す。

    exe は開くのに数秒かかるので、そのあいだ「開いています…」の画像を出している。
    本当の窓が出たら、こちらは要らない。exe でないとき（.py のまま）は何も無い。
    """
    try:
        import pyi_splash  # type: ignore  exe に --splash を付けたときだけ存在する

        pyi_splash.close()
    except Exception:  # noqa: BLE001
        pass


def message_box(text: str, title: str = APP_NAME) -> bool:
    """窓を作れなかったときの、最後の知らせ方。

    tkinter を積み忘れた exe を作ってしまっても、「押しても何も起きない」
    だけは避ける。Windows が必ず持っているものなので、何も足さずに出せる。
    Windows 以外では何もしない（False を返す）。
    """
    if os.name != "nt":
        return False
    close_splash()
    try:
        import ctypes

        # 0x40 = 情報アイコン付きの「OK」だけの画面
        ctypes.windll.user32.MessageBoxW(0, str(text), str(title), 0x40)
        return True
    except Exception:  # noqa: BLE001
        return False


def headless() -> bool:
    """画面を開けるか。開けないときは True。"""
    if tk is None:
        return True
    try:
        root = tk.Tk()
        root.destroy()
        return False
    except Exception:  # noqa: BLE001
        return True


def _fonts() -> dict[str, Any]:
    return {
        "title": tkfont.Font(family="Meiryo UI", size=18, weight="bold"),
        "body": tkfont.Font(family="Meiryo UI", size=12),
        "step": tkfont.Font(family="Meiryo UI", size=13),
        "button": tkfont.Font(family="Meiryo UI", size=12, weight="bold"),
        "small": tkfont.Font(family="Meiryo UI", size=10),
    }


def _center(win: Any, width: int, height: int) -> None:
    win.update_idletasks()
    x = (win.winfo_screenwidth() - width) // 2
    y = (win.winfo_screenheight() - height) // 3
    win.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")


class SetupWindow:
    """「確認しています → 見つかりました → 設定しています → 完了」だけを見せる窓。"""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.configure(bg=BG)
        self.root.resizable(False, False)
        self.f = _fonts()
        self._steps: list[tuple[Any, str]] = []
        self._choice: str | None = None
        # ✕ で閉じられたあとに触ると落ちるので、閉じたことを覚えておく
        self._alive = True
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        tk.Label(self.root, text=APP_NAME, bg=BG, fg=ACCENT, font=self.f["title"]).pack(pady=(22, 2))
        tk.Frame(self.root, bg=ACCENT, height=2, width=60).pack(pady=(0, 14))

        self.message = tk.Label(
            self.root, text="MT5を確認しています…", bg=BG, fg=TEXT, font=self.f["body"], wraplength=440, justify="center"
        )
        self.message.pack(pady=(0, 12))

        # ボタンを先に下へ固定する。あとから中身が増えても、画面の外に出ない
        self.buttons = tk.Frame(self.root, bg=BG)
        self.buttons.pack(side="bottom", fill="x", padx=28, pady=(6, 20))

        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(side="top", fill="both", expand=True, padx=28)

        _center(self.root, 520, 400)

    # ── 表示 ───────────────────────────────────
    def _on_close(self) -> None:
        """お客様が ✕ を押した。ここから先は何もしない。"""
        self._alive = False
        try:
            self.root.quit()
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass

    def alive(self) -> bool:
        """窓がまだ開いているか。閉じられていれば False。"""
        if not self._alive:
            return False
        try:
            self.root.winfo_exists()
        except Exception:  # noqa: BLE001
            self._alive = False
        return self._alive

    def pump(self) -> None:
        """待ち時間のあいだに呼ぶ。呼ばないと Windows が「応答なし」と出す。"""
        if not self.alive():
            return
        try:
            self.root.update()
        except Exception:  # noqa: BLE001
            self._alive = False

    def say(self, text: str) -> None:
        if not self.alive():
            return
        try:
            self.message.configure(text=text)
            self.root.update()
        except Exception:  # noqa: BLE001
            self._alive = False

    def clear_body(self) -> None:
        if not self.alive():
            return
        try:
            for child in self.body.winfo_children():
                child.destroy()
        except Exception:  # noqa: BLE001
            self._alive = False
            return
        self._steps = []

    def clear_buttons(self) -> None:
        if not self.alive():
            return
        try:
            for child in self.buttons.winfo_children():
                child.destroy()
        except Exception:  # noqa: BLE001
            self._alive = False
            return

    def add_step(self, key: str, text: str) -> None:
        if not self.alive():
            return
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=3, anchor="w")
        mark = tk.Label(row, text="…", bg=BG, fg=MUTED, font=self.f["step"], width=2)
        mark.pack(side="left")
        tk.Label(row, text=text, bg=BG, fg=TEXT, font=self.f["step"], anchor="w").pack(side="left")
        self._steps.append((mark, key))
        self.root.update()

    def mark(self, key: str, ok: bool = True) -> None:
        if not self.alive():
            return
        for widget, name in self._steps:
            if name == key:
                widget.configure(text="✓" if ok else "×", fg=OK if ok else NG)
        self.root.update()

    def button(self, text: str, command: Callable[[], None], primary: bool = True) -> None:
        if not self.alive():
            return
        btn = tk.Button(
            self.buttons,
            text=text,
            command=command,
            font=self.f["button"],
            bg=ACCENT if primary else PANEL,
            # Mac の Tk はボタンの背景色を変えられない（薄い灰色のまま）ので、文字は濃い色にする。
            # 薄い文字（TEXT）だと、2つ目のボタンの文字が見えなくなる（実機で起きた）
            fg="#04121f" if (primary or sys.platform == "darwin") else TEXT,
            activebackground=ACCENT if primary else PANEL,
            relief="flat",
            bd=0,
            height=2,
            pady=6,  # 老眼と、手の震えを前提に。高さは 44px 以上にする
            cursor="hand2",
        )
        btn.pack(fill="x", pady=4)
        self.root.update()

    # ── 画面のかたち ────────────────────────────
    def choose_terminal(self, items: Sequence[tuple[str, str]]) -> str | None:
        """複数の MT5 があるときだけ出す選択画面。items は (値, 見せる名前)。

        ✕ で閉じられたら None を返す。呼び出し側は、そこでやめること
        （勝手に1台目を選んで、意図しない MT5 に入れてしまわないため）。
        """
        if not self.alive():
            return None
        self.clear_body()
        self.clear_buttons()
        self.say("設定するMT5を選んでください。")
        # 台数ぶん窓を高くする。画面に収まらないときは、そこで打ち止め
        need = 300 + 46 * len(items)
        self.root.update_idletasks()
        height = min(need, max(400, self.root.winfo_screenheight() - 120))
        self.root.resizable(False, True)
        _center(self.root, 560, height)
        var = tk.StringVar(value=items[0][0])
        for value, label in items:
            tk.Radiobutton(
                self.body,
                text=label,
                variable=var,
                value=value,
                bg=BG,
                fg=TEXT,
                selectcolor=PANEL,
                activebackground=BG,
                activeforeground=TEXT,
                font=self.f["step"],
                anchor="w",
                justify="left",
                wraplength=460,
                padx=6,
                pady=6,
            ).pack(fill="x", anchor="w")

        def pick() -> None:
            self._choice = var.get()
            self.root.quit()

        self.button("これで設定する", pick)
        try:
            self.root.mainloop()
        except Exception:  # noqa: BLE001
            self._alive = False
        return self._choice if self._alive else None

    def menu(
        self,
        title: str,
        lines: Sequence[str] = (),
        options: Sequence[tuple[str, str]] = (),
    ) -> str | None:
        """いまの状態を見せて、やることを選んでもらう。

        options は (返す値, ボタンの文字)。先頭が目立つ色になる。
        ✕ で閉じられたら None（呼び出し側は、そこでやめること）。

        ダブルクリックして何も起きないと、お客様は不安になる。
        すでに設定が済んでいるときも、この画面で「いま入っているもの」を見せる。
        """
        if not self.alive():
            return None
        self.clear_body()
        self.clear_buttons()
        self.say(title)
        # 行数とボタンの数で窓を高くする。画面に収まらないときは、そこで打ち止め
        need = 260 + 26 * len(lines) + 58 * len(options)
        self.root.update_idletasks()
        height = min(need, max(400, self.root.winfo_screenheight() - 120))
        self.root.resizable(False, True)
        _center(self.root, 560, height)
        for line in lines:
            tk.Label(
                self.body,
                text=line,
                bg=BG,
                fg=TEXT if line and not line.startswith("（") else MUTED,
                font=self.f["small"],
                wraplength=480,
                justify="left",
            ).pack(anchor="w", pady=2)

        picked: dict[str, str | None] = {"key": None}

        def pick(key: str) -> None:
            picked["key"] = key
            try:
                self.root.quit()
            except Exception:  # noqa: BLE001
                self._alive = False

        for i, (key, label) in enumerate(options):
            self.button(label, lambda k=key: pick(k), primary=(i == 0))
        try:
            self.root.mainloop()
        except Exception:  # noqa: BLE001
            self._alive = False
        return picked["key"] if self.alive() else None

    def ask(self, question: str, yes: str, no: str, lines: Sequence[str] = ()) -> bool:
        """はい／いいえを聞く。閉じられたら「いいえ」扱い。"""
        if not self.alive():
            return False
        self.clear_body()
        self.clear_buttons()
        self.say(question)
        for line in lines:
            tk.Label(
                self.body, text=line, bg=BG, fg=MUTED, font=self.f["small"], wraplength=440, justify="left"
            ).pack(anchor="w", pady=2)

        answer = {"value": False}

        def pick(value: bool) -> None:
            answer["value"] = value
            try:
                self.root.quit()
            except Exception:  # noqa: BLE001
                self._alive = False

        self.button(yes, lambda: pick(True), primary=True)
        self.button(no, lambda: pick(False), primary=False)
        try:
            self.root.mainloop()
        except Exception:  # noqa: BLE001
            self._alive = False
        return answer["value"] and self.alive()

    def ask_or_wait(
        self,
        question: str,
        yes: str,
        no: str,
        lines: Sequence[str] = (),
        check: Callable[[], bool] | None = None,
        every_ms: int = 2000,
    ) -> str:
        """はい／いいえを聞きながら、条件が整うのを待つ。

        返り値は "yes" / "no" / "ready"（check が真になった）/ "closed"（✕ で閉じられた）。
        Mac で「EA を載せると自動で先へ進む」ために使う。
        """
        if not self.alive():
            return "closed"
        self.clear_body()
        self.clear_buttons()
        self.say(question)
        for line in lines:
            tk.Label(
                self.body, text=line, bg=BG, fg=MUTED, font=self.f["small"], wraplength=440, justify="left"
            ).pack(anchor="w", pady=2)

        answer = {"value": "closed", "done": False}

        def pick(value: str) -> None:
            if answer["done"]:
                return
            answer["done"] = True
            answer["value"] = value
            try:
                self.root.quit()
            except Exception:  # noqa: BLE001
                self._alive = False

        def tick() -> None:
            if answer["done"] or not self.alive():
                return
            try:
                if check is not None and check():
                    pick("ready")
                    return
            except Exception:  # noqa: BLE001
                pass
            try:
                self.root.after(every_ms, tick)
            except Exception:  # noqa: BLE001
                self._alive = False

        self.button(yes, lambda: pick("yes"), primary=True)
        self.button(no, lambda: pick("no"), primary=False)
        if check is not None:
            try:
                self.root.after(every_ms, tick)
            except Exception:  # noqa: BLE001
                self._alive = False
        try:
            self.root.mainloop()
        except Exception:  # noqa: BLE001
            self._alive = False
        answer["done"] = True
        return answer["value"] if self.alive() or answer["value"] != "closed" else "closed"

    def finish(self, lines: Sequence[str], ok: bool = True) -> None:
        if not self.alive():
            return
        self.clear_buttons()
        self.say("設定が完了しました。" if ok else "設定が終わりませんでした。")
        for line in lines:
            tk.Label(
                self.body, text=line, bg=BG, fg=MUTED if ok else WARN, font=self.f["small"], wraplength=440, justify="left"
            ).pack(anchor="w", pady=2)
        self.button("閉じる", self._on_close)
        try:
            self.root.mainloop()
        except Exception:  # noqa: BLE001
            self._alive = False

    def fail(self, message: str, hint: str = "") -> None:
        """技術的な理由は出さない。次にやることだけを書く。"""
        if not self.alive():
            return
        self.clear_body()
        self.clear_buttons()
        self.say(message)
        if hint:
            tk.Label(self.body, text=hint, bg=BG, fg=MUTED, font=self.f["small"], wraplength=440, justify="left").pack(
                anchor="w", pady=4
            )
        self.button("閉じる", self._on_close)
        try:
            self.root.mainloop()
        except Exception:  # noqa: BLE001
            self._alive = False

    def close(self) -> None:
        self._alive = False
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass


def open_window() -> SetupWindow | None:
    """窓を開く。開けない環境では None（呼び出し側は画面なしで進める）。"""
    if tk is None:
        close_splash()
        return None
    try:
        win = SetupWindow()
    except Exception:  # noqa: BLE001
        close_splash()
        return None
    close_splash()  # 本当の窓が出たので、起動中の画像は消す
    return win
