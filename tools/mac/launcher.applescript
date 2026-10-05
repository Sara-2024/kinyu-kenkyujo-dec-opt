-- MT5 Automatic（Mac）の .app の中身。
--
-- 役割は 2 つだけ:
--   1. ダブルクリックされたら、同梱の本体（Resources/bin/MT5Automatic）を起こす
--   2. サイトのボタン（aitrader://connect?token=…）で呼ばれたら、その URL を
--      本体に渡して起こす（Windows の exe が受け取るのと同じ引数）
--
-- 本体は tkinter の窓を自分で出すので、ここでは画面を出さない。
-- Terminal.app も開かない（do shell script をバックグラウンドで）。
-- aitrader:// を受けられるのは Info.plist の CFBundleURLTypes のおかげ
--（tools/mac/build-mac.sh が書き足す）。

on binPath()
	set resDir to POSIX path of (path to resource "bin")
	return resDir & "/MT5Automatic"
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
