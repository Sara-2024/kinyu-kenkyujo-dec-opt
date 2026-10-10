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

-- 本体は .app の中から直接は起こさない。
-- ブラウザで落とした .app の中身には「隔離」の印が付いていて、外側の .app を
-- システム設定の「このまま開く」で許可しても、中の本体を起こした瞬間に macOS が
-- もう一度止めて強制終了させる（macOS 15 で確認。「ゴミ箱に入れる」まで勧めてくる）。
-- しかも Downloads から開いた .app は読み取り専用の仮の場所で動くので、
-- 印をその場で外すこともできない。
-- なので本体を ~/Library/Application Support/MT5Automatic/bin/ に印を付けずに写し
--（cp -X は拡張属性を写さない）、そちらを起こす。写しは本体が変わったときだけ作り直す。
-- 自動起動（LaunchAgent）もこの写しを指すので、.app を消されても朝の起動は生きる。

on binPath()
	set resDir to POSIX path of (path to resource "bin")
	-- 「machine」は AppleScript の予約語なので使わない
	set cpuType to do shell script "uname -m"
	set wanted to resDir & "/MT5Automatic-" & cpuType
	-- その機種用が無ければ、入っているものを使う（Rosetta があれば Intel 用も動く）
	set src to do shell script "if [ -x " & quoted form of wanted & " ]; then echo " & quoted form of wanted & "; else ls " & quoted form of resDir & "/MT5Automatic-* 2>/dev/null | head -1; fi"
	set dstDir to (POSIX path of (path to application support folder from user domain)) & "MT5Automatic/bin"
	set dst to dstDir & "/" & (do shell script "basename " & quoted form of src)
	set tmp to dst & ".new"
	-- 動いている写しを上書きしないよう、別名に写してから差し替える
	do shell script "mkdir -p " & quoted form of dstDir & " && if ! cmp -s " & quoted form of src & " " & quoted form of dst & "; then cp -X " & quoted form of src & " " & quoted form of tmp & " && chmod +x " & quoted form of tmp & " && mv -f " & quoted form of tmp & " " & quoted form of dst & "; fi; xattr -d com.apple.quarantine " & quoted form of dst & " 2>/dev/null; true"
	return dst
end binPath

on launchWith(args)
	do shell script quoted form of binPath() & " " & args & " > /dev/null 2>&1 &"
end launchWith

-- 同じ .app が何個も残っていると（Downloads に「MT5 Automatic 2.app」「3.app」…）、
-- サイトのボタン（aitrader://）がどれに届くか分からない。古い版に届くと、中の本体が
-- Gatekeeper に止められて何も起きない（実機で起きた）。
-- 開かれた .app を登録し直して、以後の aitrader:// はこちらに来るようにする。
-- 作るときに CFBundleVersion を毎回新しくしているので、同じ名前なら新しいほうが選ばれる。
on registerSelf()
	try
		do shell script "/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f " & quoted form of (POSIX path of (path to me))
	end try
end registerSelf

on run
	registerSelf()
	launchWith("")
end run

on open location theURL
	registerSelf()
	launchWith("--silent --from-site " & quoted form of theURL)
end open location
