# PDF から書き出した各ページ（img/pNN.webp）を、ロビーと同じ装いの 1 枚のウェブページに組む
import html, sys, re
from pathlib import Path
ROOT = Path("/Users/mao/金融研究所｜12月オプト/dreamland")
BASE_CSS = (ROOT / "manual" / "index.html").read_text()
css = BASE_CSS[BASE_CSS.index("<style>") + 7 : BASE_CSS.index("</style>")]
EXTRA = """
.slide{background:rgba(255,255,255,.78);border:1px solid #fff;border-radius:18px;padding:18px 20px 20px;margin:0 0 16px;box-shadow:0 10px 40px rgba(139,122,154,.1)}
.slide__head{display:flex;gap:14px;align-items:center;margin-bottom:12px}
.slide__head h3{margin:0;font-family:var(--serif);font-weight:600;font-size:20px;letter-spacing:.06em;line-height:1.4}
.slide__head .chip{margin-left:auto;flex:0 0 auto;font-size:12px;color:var(--teal-b);background:#e6f3f3;border-radius:20px;padding:4px 12px;white-space:nowrap}
.slide__img{margin:0;border-radius:12px;overflow:hidden;border:1px solid var(--line);background:#dbe5f2}
.slide__img img{display:block;width:100%;height:auto}
.flow--auto{grid-template-columns:repeat(auto-fit,minmax(170px,1fr))}
@media (max-width:720px){.slide{padding:12px 12px 14px}.slide__head h3{font-size:17px}.slide__head .chip{display:none}}
"""
def page(key, title, en, lead, cover_img, parts, done_items, back_href, back_label, next_block="", intro_pages=()):
    out = []
    out.append(f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}｜ドリームランド渡航手続き</title>
<meta name="description" content="{html.escape(lead)}">
<meta name="robots" content="noindex, nofollow">
<meta name="theme-color" content="#d1e4ee">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='32' fill='%23789ea7'/%3E%3Cpath d='M32 12l4.4 13.6L50 30l-13.6 4.4L32 48l-4.4-13.6L14 30l13.6-4.4z' fill='%23fff6dc'/%3E%3C/svg%3E">
<style>{css}{EXTRA}</style>
</head>
<body>
<header class="cover">
  <img src="../assets/clouds.webp" alt="" decoding="async">
  <div class="wrap cover__in">
    <div><span class="brand">DREAMLAND · {html.escape(en)}</span>
      <h1>{html.escape(title)}</h1>
      <p>{html.escape(lead)}</p></div>
  </div>
</header>
<nav class="toc" aria-label="目次"><div class="wrap">
  <a href="#top">はじめに</a>{"".join(f'<a href="#part-{i+1}" data-part="{i+1}">{html.escape(p["code"])}　{html.escape(p["name"])}</a>' for i, p in enumerate(parts))}<a href="#done">最後に</a>
</div></nav>
<main class="wrap">
<section class="intro" id="top">
  <div class="card">
    <h2>全体の流れ</h2><p class="lead">画面の写真を見ながら、1ページずつ同じように進めてください。</p>
    <ol class="flow flow--auto">{"".join(f'<li><a href="#part-{i+1}"><small>{html.escape(p["code"])}</small><b>{html.escape(p["name"])}</b><span>{html.escape(p["desc"])}</span></a></li>' for i, p in enumerate(parts))}</ol>
  </div>''')
    for n, t in intro_pages:
        out.append(f'''
  <div class="slide" style="margin-top:16px"><div class="slide__head"><span class="step__no">{n:02d}</span><h3>{html.escape(t)}</h3></div>
    <figure class="slide__img"><img src="img/p{n:02d}.webp" alt="{html.escape(t)}" width="1600" height="900" decoding="async"></figure></div>''')
    out.append("\n</section>")
    for i, p in enumerate(parts):
        out.append(f'''
<div class="part" id="part-{i+1}"><div class="sign"><span class="sign__wire"></span><span class="sign__wire"></span><div class="sign__panel"><span class="sign__code">{html.escape(p["code"])}</span><span class="sign__jp">{html.escape(p["name"])}</span></div></div><p class="part__desc">{html.escape(p["desc"])}</p>''')
        for entry in p["pages"]:
            n, t = entry[0], entry[1]
            extra = entry[2] if len(entry) > 2 else ""
            out.append(f'''<section class="slide" id="p{n:02d}">
  <div class="slide__head"><span class="step__no">{n:02d}</span><h3>{html.escape(t)}</h3><span class="chip">{html.escape(p["name"])}</span></div>
  <figure class="slide__img"><img src="img/p{n:02d}.webp" alt="{html.escape(t)}" width="1600" height="900" loading="lazy" decoding="async"></figure>
  {extra}
</section>''')
        out.append("</div>")
    out.append(f'''
<section class="done" id="done">
  <div class="card">
    <h2>最後に、チェックしましょう</h2>
    <ul>{"".join(f"<li>{html.escape(x)}</li>" for x in done_items)}</ul>
    {next_block}
    <a class="back" href="{back_href}">‹ {html.escape(back_label)}</a>
  </div>
</section>
</main>
<footer class="foot">DREAMLAND INTERNATIONAL · {html.escape(en)}</footer>
<script>
(() => {{
  const links=[...document.querySelectorAll('.toc a[data-part]')];
  const parts=[...document.querySelectorAll('.part')];
  const io=new IntersectionObserver((es)=>{{es.forEach(e=>{{if(!e.isIntersecting)return;const k=e.target.id.slice(5);links.forEach(a=>a.classList.toggle('is-on',a.dataset.part===k));}});}},{{rootMargin:'-30% 0px -60% 0px'}});
  parts.forEach(p=>io.observe(p));
}})();
</script>
</body>
</html>''')
    (ROOT / key / "index.html").write_text("".join(out))
    print("wrote", key, len("".join(out)), "bytes")

# HFM の Windows 版 MT5（公式の配布元）。変わったらここだけ直す
MT5_DOWNLOAD_URL = "https://download.terminal.free/cdn/web/12018/mt5/hfmarketsglobal5setup.exe"
MT5_DOWNLOAD_CTA = (
    f'<a class="cta" href="{MT5_DOWNLOAD_URL}" target="_blank" rel="noopener noreferrer">'
    '<span>Windows 版の MT5 をダウンロード</span><small>HFM 公式 · hfmarketsglobal5setup.exe</small></a>'
    '<p class="tip">ダウンロードが終わったら、次のページ（セットアップを開く）へ進んでください。</p>'
)

page("manual-login", "MT5 ログインマニュアル", "MT5 LOGIN MANUAL",
     "Windows 版の MT5 を入れて、リアル口座にログインするまでの手順です。ログインできたら、パスポートと EA の設置マニュアルへ進みます。",
     None,
     [
       {"code": "PART 1", "name": "MT5 をダウンロード", "desc": "HFM の Windows 版 MT5 を手に入れる", "pages": [(3, "Windows 版の MT5 をダウンロード", MT5_DOWNLOAD_CTA)]},
       {"code": "PART 2", "name": "MT5 をインストール", "desc": "セットアップを開いて「次へ」→「完了」", "pages": [(4, "ダウンロードしたセットアップを開く"), (5, "内容を確認し、「次へ」を押す"), (6, "終わったら、「完了」を押す")]},
       {"code": "PART 3", "name": "リアル口座にログイン", "desc": "会社を選び、口座番号・パスワード・サーバーを入れる", "pages": [(7, "利用する会社を選ぶ"), (8, "会社を選べたら、「次へ」"), (9, "「既存の取引口座」を選ぶ"), (10, "リアル口座の口座番号を入力する"), (11, "リアル口座の取引用パスワードを入力する"), (12, "リアル口座のサーバーを選ぶ"), (13, "入力できたら、「完了」を押す")]},
     ],
     ["Windows 版の MT5 を入れた", "リアル口座の口座番号・取引用パスワード・サーバー名でログインできた", "口座番号とサーバー名を、ロビーの「口座の登録」と同じものにそろえた"],
     "../#service", "渡航手続きロビーにもどる（パスポートの発行へ）",
     next_block='<p class="fin">ログインできたら、次はパスポートと EA の設置です。</p><a class="cta" href="../manual-setup/"><span>パスポートと EA の設置マニュアルへ</span><small>DREAMLAND · PASSPORT &amp; EA SETUP MANUAL</small></a>',
     intro_pages=[(2, "ログインに必要な3つを用意します")])

page("manual-setup", "パスポートと EA の設置マニュアル", "PASSPORT & EA SETUP MANUAL",
     "ドリームランド・パスポート（DreamlandPassport.exe）で EA を MT5 に配置し、チャートに載せて稼働の準備を整えるまでの手順です。同じパソコンで MT5 にログインしてから始めてください。",
     None,
     [
       {"code": "PART 1", "name": "パスポートで EA を配置", "desc": "DreamlandPassport.exe を開き、対象の MT5 を選ぶ", "pages": [(3, "ダウンロードが止まったら、詳細を開く"), (4, "ツールのダウンロードを続ける"), (5, "保護画面が出たら「詳細情報」を開く"), (6, "アプリ名を確認し、「実行」を押す"), (7, "パスポートが開くまで待つ"), (8, "対象の MT5 を選び、EA を自動配置する")]},
       {"code": "PART 2", "name": "ナビゲータで「更新」", "desc": "EA の一覧に出るまで", "pages": [(9, "EA 一覧がないときは「ナビゲータ」"), (10, "EA 一覧を右クリックして「更新」"), (11, "一覧に EA が出れば OK")]},
       {"code": "PART 3", "name": "チャートへ設置", "desc": "XAUUSD のチャートを開いて EA を載せ、設定を確認", "pages": [(12, "気配値がないときは「気配値表示」"), (13, "銘柄が見つからなければ「全て表示」"), (14, "XAUUSD のチャートを開く"), (15, "指定された時間足を選ぶ"), (16, "EA をチャートへ動かす"), (17, "「アルゴリズム取引を許可」にチェック"), (18, "2つのチェックを確認し、「OK」を押す")]},
       {"code": "PART 4", "name": "稼働の準備", "desc": "取引ボタンを ON にして、開いたままにする", "pages": [(19, "MT5 上部の取引ボタンも ON に"), (20, "右上に EA があれば OK"), (21, "動かしている間は、開いたまま")]},
       {"code": "HELP", "name": "困ったとき", "desc": "ログインできない・EA が動かないとき", "pages": [(22, "ログインできないときは"), (23, "EA が動かないときは")]},
     ],
     ["リアル口座でログインできた", "指定のチャートに EA がある", "2か所の取引許可が ON になった", "エラーログが出ていない"],
     "../#service", "渡航手続きロビーにもどる（搭乗ゲートへ）",
     next_block='<p class="fin">ここまでできたら、稼働準備完了です。ロビーに戻って、パスポートの発行を終わらせてください。</p>',
     intro_pages=[(2, "パスポートで、EA を MT5 に自動配置します")])
