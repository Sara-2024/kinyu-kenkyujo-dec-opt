"""水準・突破・リテストの判定を、決め打ちの足で確かめる。"""
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import risk_features as rf

P=F=0
def check(name, cond, extra=""):
    global P,F
    if cond: P+=1; print(f"  ok   {name}")
    else: F+=1; print(f"  NG   {name} {extra}")

def bar(t,o,h,l,c): return {"time":t,"open":o,"high":h,"low":l,"close":c}

# 山と谷：右側の足がそろっていないものは採らない（未来を見ない）
bars=[bar(i,10,10+ (5 if i==5 else 0),9,10) for i in range(10)]
bars.append(bar(10,10,99,9,10))     # 最後の足は右側が無いので山にならない
hs,ls=rf.swing_points(bars,left=2,right=2)
check("右側が無い足は山にしない", all(b["high"]!=99 for b in hs))
check("確定した山は拾う", any(b["high"]==15 for b in hs))

# 突破 → リテスト → 再突破
level=100.0
m1=[]
t=0
for c in (95,96,97,98,99):            # 水準の下
    m1.append(bar(t,c,c+0.2,c-0.2,c)); t+=60
for c in (101,102,103):               # 上抜け
    m1.append(bar(t,c,c+0.2,c-0.2,c)); t+=60
m1.append(bar(t,101,101.2,99.9,100.4)); t+=60   # 戻って水準に触れる
for c in (102,104):                   # 再び上へ
    m1.append(bar(t,c,c+0.2,c-0.2,c)); t+=60
st=rf._break_state(m1, level, +1, tol=0.2)
check("上抜けを検出", st["broken"]==1)
check("リテストを検出", st["retest_seen"]==1)
check("リテスト成立を検出", st["retest_confirmed"]==1)
check("突破からの本数を数える", st["bars_since_break"]==5, str(st))  # 抜けた足=index5、窓は11本

# 触っただけで戻らない＝未成立
m2=m1[:9]
st2=rf._break_state(m2, level, +1, tol=0.2)
check("戻りだけでは成立にしない", st2["retest_seen"]==1 and st2["retest_confirmed"]==0, str(st2))

# 一度も抜けていない
st3=rf._break_state(m1[:5], level, +1, tol=0.2)
check("未突破は broken=0", st3["broken"]==0)

# 前日・前週は「1本前の確定した足」
d1=[bar(0,1,110,90,100), bar(86400,1,120,80,110)]
w1=[bar(0,1,150,50,100), bar(604800,1,160,40,110)]
f=rf.build_features(bid=99.9,ask=100.1,m1=m1*40,h1=m1*40,h4=m1*20,d1=d1,w1=w1,
                    profile={"ema_period":5,"atr_period":5,"retest_tolerance_atr":0.12,"h1_sl_atr_mult":1.5})
check("前日の高値は1本前の足", f["prev_day_high"]==110.0, str(f["prev_day_high"]))
check("前週の高値は1本前の足", f["prev_week_high"]==150.0, str(f["prev_week_high"]))
check("窓の最高値は window_high という名前", "window_high" in f and "all_time_high" not in f)
check("窓の開始時刻を持つ", f["window_start"] is not None)
check("足りない値は None のまま", rf.build_features(bid=1,ask=1.1,m1=[],h1=[],h4=[],d1=[],w1=[],profile={})["atr_m1"] is None)
check("データ不足を判定できる", rf.data_is_usable({"atr_m1":1,"atr_h1":1,"price_mid":1,"ema200_h1":1}) and not rf.data_is_usable({"atr_m1":None}))

print(f"\n{P} ok / {F} NG")
sys.exit(1 if F else 0)
