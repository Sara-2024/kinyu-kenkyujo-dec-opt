#!/usr/bin/env bash
# ロビー（dreamland/index.html）を公開する前の確認。MT5 もサイトも要らない。
#   ・<script> の文法が通るか
#   ・HTML と JS で使っているクラスに、CSS の定義があるか（消し飛んだまま公開しないため）
set -u
cd "$(dirname "$0")/.."
node -e '
const fs=require("fs");const s=fs.readFileSync("dreamland/index.html","utf8");
const js=s.match(/<script>([\s\S]*)<\/script>/)[1];
try{new Function(js)}catch(e){console.log("  NG   JS の文法:",e.message);process.exit(1)}
const css=s.slice(s.indexOf("<style>")+7,s.indexOf("</style>"));
let d=0;for(const ch of css){d+=(ch==="{")-(ch==="}");if(d<0){console.log("  NG   CSS の波括弧が合わない");process.exit(1)}}
if(d!==0){console.log("  NG   CSS の波括弧が合わない");process.exit(1)}
const ignore=new Set(["idx","true","fly--first"]);
const names=new Set();
for(const m of s.matchAll(/class="([^"]+)"/g)) for(const c of m[1].split(/[\s$]+/)) if(/^[a-z][a-z0-9_-]*$/.test(c)&&!ignore.has(c)) names.add(c);
const missing=[...names].filter(c=>!css.includes("."+c)).sort();
if(missing.length){console.log("  NG   CSS の無いクラス:",missing.join(", "));process.exit(1)}
console.log("  ok   JS の文法・CSS の対応（"+names.size+" クラス）  1 ok / 0 NG");
'
