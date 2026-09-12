"""AI Trader Connect の画面（初回の設定だけ）。

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

from typing import Any, Callable, Sequence

try:
    import tkinter as tk
    from tkinter import font as tkfont
except Exception:  # noqa: BLE001 - 画面が無い環境
    tk = None  # type: ignore[assignment]
    tkfont = None  # type: ignore[assignment]

APP_NAME = "AI Trader Connect"

BG = "#0b1220"
PANEL = "#111c31"
TEXT = "#e8edf5"
MUTED = "#94a3b8"
ACCENT = "#5eccff"
OK = "#35f58a"
WARN = "#ffd23e"
NG = "#ff8484"


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

        tk.Label(self.root, text=APP_NAME, bg=BG, fg=ACCENT, font=self.f["title"]).pack(pady=(22, 2))
        tk.Frame(self.root, bg=ACCENT, height=2, width=60).pack(pady=(0, 14))

        self.message = tk.Label(
            self.root, text="MT5を確認しています…", bg=BG, fg=TEXT, font=self.f["body"], wraplength=440, justify="center"
        )
        self.message.pack(pady=(0, 12))

        self.body = tk.Frame(self.root, bg=BG)
        self.body.pack(fill="both", expand=True, padx=28)

        self.buttons = tk.Frame(self.root, bg=BG)
        self.buttons.pack(fill="x", padx=28, pady=(6, 20))

        _center(self.root, 520, 400)

    # ── 表示 ───────────────────────────────────
    def say(self, text: str) -> None:
        self.message.configure(text=text)
        self.root.update()

    def clear_body(self) -> None:
        for child in self.body.winfo_children():
            child.destroy()
        self._steps = []

    def clear_buttons(self) -> None:
        for child in self.buttons.winfo_children():
            child.destroy()

    def add_step(self, key: str, text: str) -> None:
        row = tk.Frame(self.body, bg=BG)
        row.pack(fill="x", pady=3, anchor="w")
        mark = tk.Label(row, text="…", bg=BG, fg=MUTED, font=self.f["step"], width=2)
        mark.pack(side="left")
        tk.Label(row, text=text, bg=BG, fg=TEXT, font=self.f["step"], anchor="w").pack(side="left")
        self._steps.append((mark, key))
        self.root.update()

    def mark(self, key: str, ok: bool = True) -> None:
        for widget, name in self._steps:
            if name == key:
                widget.configure(text="✓" if ok else "×", fg=OK if ok else NG)
        self.root.update()

    def button(self, text: str, command: Callable[[], None], primary: bool = True) -> None:
        btn = tk.Button(
            self.buttons,
            text=text,
            command=command,
            font=self.f["button"],
            bg=ACCENT if primary else PANEL,
            fg="#04121f" if primary else TEXT,
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
        """複数の MT5 があるときだけ出す選択画面。items は (値, 見せる名前)。"""
        self.clear_body()
        self.clear_buttons()
        self.say("設定するMT5を選んでください。")
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
                padx=6,
                pady=6,
            ).pack(fill="x", anchor="w")

        def pick() -> None:
            self._choice = var.get()
            self.root.quit()

        self.button("これで設定する", pick)
        self.root.mainloop()
        return self._choice

    def finish(self, lines: Sequence[str], ok: bool = True) -> None:
        self.clear_buttons()
        self.say("設定が完了しました。" if ok else "設定が終わりませんでした。")
        for line in lines:
            tk.Label(
                self.body, text=line, bg=BG, fg=MUTED if ok else WARN, font=self.f["small"], wraplength=440, justify="left"
            ).pack(anchor="w", pady=2)
        self.button("閉じる", self.root.destroy)
        self.root.mainloop()

    def fail(self, message: str, hint: str = "") -> None:
        """技術的な理由は出さない。次にやることだけを書く。"""
        self.clear_body()
        self.clear_buttons()
        self.say(message)
        if hint:
            tk.Label(self.body, text=hint, bg=BG, fg=MUTED, font=self.f["small"], wraplength=440, justify="left").pack(
                anchor="w", pady=4
            )
        self.button("閉じる", self.root.destroy)
        self.root.mainloop()

    def close(self) -> None:
        try:
            self.root.destroy()
        except Exception:  # noqa: BLE001
            pass


def open_window() -> SetupWindow | None:
    """窓を開く。開けない環境では None（呼び出し側は画面なしで進める）。"""
    if tk is None:
        return None
    try:
        return SetupWindow()
    except Exception:  # noqa: BLE001
        return None
