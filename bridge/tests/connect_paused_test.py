"""新しいMT5連携の受付を止めているあいだ、危ない道が塞がっているかを確かめる。

    python3 bridge/tests/connect_paused_test.py

止めている理由: サイトは合図（token）方式になったが、配っている接続ツールはまだ古い。
古いツールは合図を読めず、そのまま既定の部屋（vps-01）でブリッジを動かしてしまう。
新しいツールを配り終えるまで、新規の連携を受け付けない。

見たいのは4つ。
  ・新規の連携が始まらない（aitrader:// を開かない）
  ・古い接続ツールを配らない
  ・30秒後のダウンロード案内へ落ちない
  ・すでに連携済みのお客様の「つなぎ直し」は塞がない

再開するときは connector.ts の CONNECT_PAUSED を false に戻す。
そのときは、この試験の期待も「受付中」に変わる（下の PAUSED で切り替わる）。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
CONNECTOR = ROOT / "src" / "data" / "connector.ts"
DIALOGUE = ROOT / "src" / "components" / "DialogueWindow.tsx"
CHARACTERS = ROOT / "src" / "data" / "characters.ts"

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


connector = CONNECTOR.read_text(encoding="utf-8")
dialogue = DIALOGUE.read_text(encoding="utf-8")
characters = CHARACTERS.read_text(encoding="utf-8")

# いま受付を止めているか
found = re.search(r"export const CONNECT_PAUSED = (true|false)", connector)
check("停止スイッチがある", found is not None)
if found is None:
    print(f"\n{PASS} ok / {FAIL+1} NG")
    sys.exit(1)
PAUSED = found.group(1) == "true"
print(f"  --   いまの設定: {'受付を止めている' if PAUSED else '受付中'}")


def body_of(src: str, name: str) -> str:
    """関数の中身をざっくり取り出す（次の空行までではなく、閉じ括弧まで）"""
    start = src.index(name)
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    return src[start:]


launch = body_of(connector, "export async function launchConnector")
download = body_of(connector, "export function downloadConnector")
relaunch = body_of(connector, "export function relaunchConnector")

# ── 1) スイッチがちゃんと効く配線になっているか ──
#     （スイッチの値がどちらでも、この配線は残っていること）
check("新規の連携はスイッチを見ている", "if (CONNECT_PAUSED) return false" in launch, launch[:120])
check("画面側の入口もスイッチを見ている", "if (CONNECT_PAUSED) {" in dialogue)
check("止めるときは準備中の案内を出す", "SETUP.paused" in dialogue)
check("準備中の文言がある", "paused:" in characters)

# 止めるのは「呼び出し中」の画面へ進む前。ここで引き返すので、
# 接続ツールの呼び出しも、30秒後のダウンロード案内も出ない
m = re.search(
    r"if \(CONNECT_PAUSED\) \{\s*\n\s*setAiText\(t\(SETUP\.paused\)\)\s*\n\s*return\s*\n\s*\}\s*\n\s*setPhase\('launching'\)",
    dialogue,
)
check("『呼び出し中』の画面へ進む前で止める配線になっている", m is not None)

# ── 2) ダウンロードもスイッチを見ているか ──
check("ダウンロードもスイッチを見ている", "if (CONNECT_PAUSED) return" in download, download[:160])

# ── 2-2) いまの設定で、実際にどうなるか ──
if PAUSED:
    print("  --   いまは新規の連携を受け付けません（お客様には「準備中」と出ます）")
else:
    print("  --   いまは新規の連携を受け付けます")

# ── 3) つなぎ直しは塞がない（すでに連携済みのお客様） ──
check("つなぎ直しの入口がある", "export function relaunchConnector" in connector)
check("つなぎ直しは止めていない", "CONNECT_PAUSED" not in relaunch, relaunch[:160])
check("つなぎ直しは合図を付けない", "token" not in relaunch, relaunch[:160])
check("つなぎ直しは部屋も付けない", "room" not in relaunch, relaunch[:160])
check(
    "つなぎ直しの URL に問い合わせが付かない",
    "connect`" in relaunch and "?" not in relaunch.split("CONNECTOR_SCHEME")[-1][:60],
    relaunch[:200],
)

# 管理画面からのつなぎ直しが、合図方式の呼び出しに戻っていないこと
check("つなぎ直しは2か所とも relaunchConnector を使う", dialogue.count("relaunchConnector()") == 2,
      str(dialogue.count("relaunchConnector()")))
reconnect_fn = body_of(dialogue, "const reconnect = () =>")
# relaunchConnector の中にも launchConnector という並びが入っているので、単語として見る
check("つなぎ直しの中で launchConnector を呼ばない",
      re.search(r"\blaunchConnector\(", reconnect_fn) is None, reconnect_fn[:160])
# 残っている launchConnector は、どれも「これから連携する人」の道。
# 受付を止めているあいだは launchConnector 自身が false を返して止まる。
check("launchConnector を呼ぶのは新規の連携の道だけ",
      dialogue.count("launchConnector(sessionToken)") == 3,
      str(dialogue.count("launchConnector(sessionToken)")))

# ── 4) 止めていても、既存のお客様の画面は壊れていない ──
check("管理画面の再接続の受け口は残っている", "onReconnect" in dialogue)
check("ダウンロードの案内文はそのまま残っている", "needDownload" in dialogue)

print(f"\n{PASS} ok / {FAIL} NG")
sys.exit(1 if FAIL else 0)
