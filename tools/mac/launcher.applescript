-- MT5 Automatic（Mac）の .app の中身。
--
-- 役割は 2 つだけ:
--   1. ダブルクリックされたら、同梱の本体（Resources/bin/MT5Automatic-<機種>）を起こす
--   2. サイトのボタン（aitrader://connect?token=…）で呼ばれたら、その URL を
--      本体に渡して起こす（Windows の exe が受け取るのと同じ引数）
--
-- 本体は Apple シリコン用（arm64）と Intel 用（x86_64）の 2 つを同梱していて、
-- `uname -m` でこの Mac の機種を見て使い分ける（お客様はどちらでも同じ ZIP）。
-- 本体は tkinter の窓を自分で出すので、ここでは画面を出さない。
-- Terminal.app も開かない（do shell script をバックグラウンドで）。
-- aitrader:// を受けられるのは Info.plist の CFBundleURLTypes のおかげ
--（tools/mac/build-mac.sh が書き足す）。

on binPath()
	set resDir to POSIX path of (path to resource "bin")
	-- 「machine」は AppleScript の予約語なので使わない
	set cpuType to do shell script "uname -m"
	set wanted to resDir & "/MT5Automatic-" & cpuType
	-- その機種用が無ければ、入っているものを使う（Rosetta があれば Intel 用も動く）
	set found to do shell script "if [ -x " & quoted form of wanted & " ]; then echo " & quoted form of wanted & "; else ls " & quoted form of resDir & "/MT5Automatic-* 2>/dev/null | head -1; fi"
	return found
end binPath

on launchWith(args)
	do shell script quoted form of binPath() & " " & args & " > /dev/null 2>&1 &"
end launchWith

on run
	launchWith("")
end run

on open location theURL
	launchWith("--silent --from-site " & quoted form of theURL)
end open location
