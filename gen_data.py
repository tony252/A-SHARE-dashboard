import sys,io,os,json
sys.stdout=io.TextIOWrapper(sys.stdout.buffer,encoding='utf-8')

import pandas as pd,numpy as np

def to_py(v):
    if isinstance(v,(np.integer,)): return int(v)
    if isinstance(v,(np.floating,np.float64)): return float(v)
    if isinstance(v,(np.bool_,)): return bool(v)
    return v

BASE=os.path.dirname(os.path.abspath(__file__))
df=pd.read_csv(os.path.join(BASE,'data','style_indices_v2.csv'),index_col=0,parse_dates=True)
STYLES=['大盘价值','大盘成长','中盘价值','中盘成长','小盘价值','小盘成长']
BENCHMARKS=['上证指数','沪深300','上证50','中证500','中证1000','创业板指','中证红利']

sz=df['上证指数']; sz_cur=sz.iloc[-1]
sz_ma20=sz.iloc[-20:].mean(); sz_ma60=sz.iloc[-60:].mean()
sz_ma120=sz.iloc[-120:].mean(); sz_ma250=sz.iloc[-250:].mean()
# 滚动 250 日高点: 全历史最高点会让回撤永久为负(2015 年后未创新高),
# GREEN 信号自 2015-06 起再未出现。滚动窗口才反映当前市场状态。
sz_dd=(sz/sz.rolling(250).max()-1).iloc[-1]
sz_dd_alltime=(sz/sz.expanding().max()-1).iloc[-1]

# 180d for chart
r180=df.iloc[-180:]
ts_180=[str(d)[:10] for d in r180.index]
sz_180=r180['上证指数'].tolist()

# YTD
ytd={}
year_start = f"{df.index[-1].year}-01-01"
for col in STYLES+['上证50','沪深300','中证500','中证1000','创业板指','中证红利']:
    s=df[col];m=s.index>=year_start;ytd[col]=round(s[m].iloc[-1]/s[m].iloc[0]-1,4)

# Value/Growth ratios (360d)
vg_data={}
for prefix in ['大盘','中盘','小盘']:
    r=df[f'{prefix}价值']/df[f'{prefix}成长']
    r=r.iloc[-360:]
    base=r.iloc[0]
    vg_data[prefix]={
        'ts':[str(d)[:10] for d in r.index],
        'vals':[round(v/base,4) for v in r.values]
    }

# Size rotation (720d)
ls_ratio=df['沪深300']/df['中证1000']
ls=ls_ratio.iloc[-720:]
ls_base=ls.iloc[0]
ls_data={'ts':[str(d)[:10] for d in ls.index],'vals':[round(v/ls_base,4) for v in ls.values]}

# 最近60日累计收益曲线 (从60日前=0%)
r60=df.iloc[-60:]
roll_data={}
for st in STYLES:
    base=r60[st].iloc[0]
    vals=[(r60[st].iloc[i]/base-1)*100 for i in range(len(r60))]
    roll_data[st]={'ts':[str(d)[:10] for d in r60.index],'vals':[round(v,2) for v in vals]}

# Signals
lv_vs_lg=round(r180['大盘价值'].iloc[-1]/r180['大盘价值'].iloc[-60]-1-(r180['大盘成长'].iloc[-1]/r180['大盘成长'].iloc[-60]-1),4)
rets_60={st:round(r180[st].iloc[-1]/r180[st].iloc[-60]-1,4) for st in STYLES}
rets_20={st:round(r180[st].iloc[-1]/r180[st].iloc[-20]-1,4) for st in STYLES}
best_20=max(rets_20,key=rets_20.get); worst_20=min(rets_20,key=rets_20.get)

# Risk flags (内生风险信号，不含国家队)
risk_flags=[]
if abs(sz_dd)>0.15: risk_flags.append(f"回撤{abs(sz_dd):.0%}超过15%阈值")
if sz_cur<sz_ma60: risk_flags.append("上证跌破MA60(季线)")
if sz_cur<sz_ma120: risk_flags.append("上证跌破MA120(半年线)")
if sz_cur<sz_ma250: risk_flags.append("上证跌破MA250(年线)")
# 价值/成长极端分化检测: 绝对值>10%触发
vg_spread = abs(lv_vs_lg)
if vg_spread > 0.10:
    direction = '价值跑赢' if lv_vs_lg > 0 else '成长跑赢'
    risk_flags.append(f"价值/成长极端分化({direction}{vg_spread:+.0%})→不稳定信号")

# Breakdown count v2
bd=0
if sz_cur<sz_ma20: bd+=1        # 跌破月线
if sz_cur<sz_ma60: bd+=2        # 跌破季线
if sz_cur<sz_ma120: bd+=3       # 跌破半年线
if sz_cur<sz_ma250: bd+=4       # 跌破年线
if not (sz_ma60>sz_ma120>sz_ma250): bd+=1  # 中期均线死叉
if abs(sz_dd)>0.15: bd+=2
if abs(sz_dd)>0.25: bd+=2
if vg_spread > 0.10: bd+=2      # 风格极端分化(绝对值)
rf_count=len(risk_flags)

# === 仓位评级 v2 ===
# 国家队信号独立计算，不影响颜色评级
national_team_active = False  # 由ETF段填充

if bd==0 and rf_count==0: overall='GREEN'
elif bd<=2 and rf_count<=1: overall='YELLOW'
elif bd<=4 and sz_cur>=sz_ma120: overall='ORANGE'
else: overall='RED'

status_labels={'GREEN':'牛市健康','YELLOW':'牛市调整','ORANGE':'中期走弱','RED':'熊市特征'}

# 仓位建议: 基础区间 + 国家队"降落伞"微调
position_base = {'GREEN':(80,100), 'YELLOW':(60,80), 'ORANGE':(30,50), 'RED':(0,30)}
p_lo, p_hi = position_base[overall]
# 安全阀: 若 bd>=4 且站上年线, 硬性截断上限至20%
if bd>=4 and sz_cur>=sz_ma250:
    p_hi = min(p_hi, 20)

def build_advice(overall, p_lo, p_hi, nt_active):
    advice = {
        'GREEN': f'仓位{p_lo}-{p_hi}%,持有强势风格,可适度追涨',
        'YELLOW': f'仓位降至{p_lo}-{p_hi}%,关注MA120支撑,减仓弱风格',
        'ORANGE': f'仓位降至{p_lo}-{p_hi}%,转防御(大盘价值),密切关注年线得失',
        'RED': f'仓位控制在{p_lo}-{p_hi}%,仅保留防御底仓,等待底部信号'
    }[overall]
    if nt_active:
        advice += ' [国家队托底中,可偏向区间上限]'
    return advice

status_desc = {level: build_advice(level, *position_base[level], False) for level in position_base}
# 初始值(ETF段会更新)

# ETF 国家队份额跟踪 @gen_data.py
etf_flow_path = os.path.join(BASE, 'data', 'etf_flow.csv')
etf_data = {'daily': [], 'summary': {}, 'alert': False, 'alert_msg': ''}
if os.path.exists(etf_flow_path):
    ef = pd.read_csv(etf_flow_path, index_col=0)
    ef.columns = pd.to_datetime(ef.columns)
    ef = ef.sort_index(axis=1)
    
    # Daily changes (亿份)
    ef_delta = ef.diff(axis=1).iloc[:, 1:] / 1e8
    last_dates = ef_delta.columns[-5:]
    etf_names = [str(i).split(' ', 1)[1] if ' ' in str(i) else str(i) for i in ef.index]
    etf_codes = [str(i).split(' ', 1)[0] for i in ef.index]
    
    # ETF NAV: 优先用抓取到的真实收盘价(腾讯), 缺失时才回退到硬编码表
    etf_nav = {}
    # Fallback: 仅当真实价格缺失时使用(历史值, 已明显偏离现价)
    FALLBACK_PRICE = {
        '510300': 4.8, '510310': 4.5, '510330': 4.8, '159919': 4.8,
        '510050': 3.0, '510500': 8.0,
        '512100': 3.2, '159845': 3.2,
        '159915': 2.4, '159949': 1.1,
        '588000': 1.9, '588080': 1.4,
        '510180': 4.0,
        '510880': 3.5, '512890': 1.7,
        '512880': 1.1,
    }
    price_path = os.path.join(BASE, 'data', 'etf_price.csv')
    price_lookup = {}
    if os.path.exists(price_path):
        try:
            p_df = pd.read_csv(price_path, index_col=0, parse_dates=True)
            for code in p_df.columns:
                s = p_df[code].dropna()
                if len(s):
                    price_lookup[str(code)] = float(s.iloc[-1])
        except Exception as e:
            print(f"price csv read error: {e}")
    print(f"real ETF prices loaded: {len(price_lookup)}")
    
    for i, code in enumerate(etf_codes):
        price = price_lookup.get(code, FALLBACK_PRICE.get(code, 1.0))
        etf_nav[code] = price
        row = {'code': code, 'name': etf_names[i], 'price': round(price, 2)}
        for d in last_dates:
            ds = str(d)[:10]
            # NaN = no data, keep as NaN (don't fill 0)
            if d in ef_delta.columns and not pd.isna(ef_delta.iloc[i][d]):
                sv = round(ef_delta.iloc[i][d], 2)
                mv = round(sv * price, 2)
                row[ds+'_s'] = sv
                row[ds+'_m'] = mv
            else:
                row[ds+'_s'] = None  # None → JS renders as '-'
                row[ds+'_m'] = None
        # d3/d5/d10: only use actual data points
        all_sv = ef_delta.iloc[i].dropna()
        if len(all_sv) >= 3:
            row['d3_s'] = round(float(all_sv.iloc[-3:].sum()), 2); row['d3_m'] = round(row['d3_s'] * price, 2)
        else: row['d3_s'] = row['d3_m'] = None
        if len(all_sv) >= 5:
            row['d5_s'] = round(float(all_sv.iloc[-5:].sum()), 2); row['d5_m'] = round(row['d5_s'] * price, 2)
        else: row['d5_s'] = row['d5_m'] = None
        if len(all_sv) >= 10:
            row['d10_s'] = round(float(all_sv.iloc[-10:].sum()), 2); row['d10_m'] = round(row['d10_s'] * price, 2)
        else: row['d10_s'] = row['d10_m'] = None
        etf_data['daily'].append(row)
    
    # Totals: skip None (missing data)
    totals = {}
    for d in last_dates:
        ds = str(d)[:10]
        s_vals = [r[ds+'_s'] for r in etf_data['daily'] if r.get(ds+'_s') is not None]
        m_vals = [r[ds+'_m'] for r in etf_data['daily'] if r.get(ds+'_m') is not None]
        totals[ds+'_s'] = round(sum(s_vals), 2) if s_vals else None
        totals[ds+'_m'] = round(sum(m_vals), 2) if m_vals else None
    for key in ['d3','d5','d10']:
        s_vals = [r[key+'_s'] for r in etf_data['daily'] if r.get(key+'_s') is not None]
        m_vals = [r[key+'_m'] for r in etf_data['daily'] if r.get(key+'_m') is not None]
        totals[key+'_s'] = round(sum(s_vals), 2) if s_vals else None
        totals[key+'_m'] = round(sum(m_vals), 2) if m_vals else None
    
    # 国家队信号 — 比率激增判定(动量+累计)
    total_d5_m = totals.get('d5_m') or 0
    total_d1_m = totals.get(str(last_dates[-1])[:10]+'_m') or 0 if len(last_dates) > 0 else 0
    
    # 计算前4日均值(去除当日，避免当日自身干扰)
    if len(last_dates) >= 2:
        prev_days = [totals.get(str(d)[:10]+'_m', 0) for d in last_dates[:-1]]
        avg_prev = sum(prev_days) / len(prev_days) if prev_days else 0
    else:
        avg_prev = 0
    
    # 比率: 当日 / 前4日均值
    ratio = total_d1_m / avg_prev if avg_prev > 0 else 0
    # 绝对底线: 当日至少5亿才值得关注
    has_floor = total_d1_m >= 5
    
    nt_level = 'none'
    
    if total_d5_m > 80 and has_floor and ratio > 0.3:
        # 仍在持续买入(比率>30% + 绝对底线) → 降落伞生效
        nt_level = 'active'
        etf_data['alert'] = True
        if total_d5_m > 200:
            etf_data['alert_msg'] = f"🪂 国家队5日+{total_d5_m:.0f}亿→持续托底(日{total_d1_m:.0f}亿,比率{ratio:.0%})"
        else:
            etf_data['alert_msg'] = f"🪂 国家队5日+{total_d5_m:.0f}亿→持续买入(日{total_d1_m:.0f}亿)"
        national_team_active = True
    elif total_d5_m > 80 and ratio <= 0.3:
        # 显著减速或已停 → 降落伞折叠
        nt_level = 'watch'
        etf_data['alert'] = True
        if total_d1_m < 5:
            etf_data['alert_msg'] = f"🪂 国家队5日+{total_d5_m:.0f}亿，但今日已暂停(仅{total_d1_m:.0f}亿)"
        else:
            etf_data['alert_msg'] = f"🪂 国家队5日+{total_d5_m:.0f}亿，但买入减速(日{total_d1_m:.0f}亿,比率{ratio:.0%})"
        national_team_active = False
    elif total_d5_m < -80:
        etf_data['alert'] = True
        etf_data['alert_msg'] = f"国家队5日净流出{abs(total_d5_m):.0f}亿→减持回收"
        national_team_active = False
    # 国家队独立标签加入显示(用🪂区分)
    if etf_data['alert']:
        risk_flags.append(etf_data['alert_msg'])
    
    # Check individual ETFs (based on money) — also 🪂
    for r in etf_data['daily']:
        dm = r.get('d3_m')
        if dm is not None and abs(dm) > 30:
            direction = '买入' if r['d3_m'] > 0 else '卖出'
            msg = f"🪂 {r['code']} {r['name']} 3日{direction}{abs(r['d3_m']):.0f}亿"
            if msg not in risk_flags:
                risk_flags.append(msg)
    
    etf_data['summary'] = totals
    etf_data['dates'] = [str(d)[:10] for d in last_dates]

# rf_count 只计内生风险(不含🪂国家队)
rf_count = len([f for f in risk_flags if not f.startswith('🪂')])

# 国家队降落伞修正仓位建议
if national_team_active:
    p_lo = max(p_lo, 10)  # 底线: 国家队托底中至少留10%
status_desc = {level: build_advice(level, *position_base[level], national_team_active) for level in position_base}
# 当前级别必须用截断后的 p_lo/p_hi 重建, 否则安全阀(上限20%)不会显示
status_desc[overall] = build_advice(overall, p_lo, p_hi, national_team_active)

# Latest values
last=df.iloc[-1]

data={
    'date':str(df.index[-1])[:10],
    'sh_index':round(sz_cur,0),
    'ma20':round(sz_ma20,0),'ma60':round(sz_ma60,0),'ma120':round(sz_ma120,0),'ma250':round(sz_ma250,0),
    'drawdown':round(sz_dd,4),
    'drawdown_alltime':round(sz_dd_alltime,4),
    'above_ma250':to_py(sz_cur>sz_ma250),'above_ma120':to_py(sz_cur>sz_ma120),'above_ma60':to_py(sz_cur>sz_ma60),
    'above_ma20':to_py(sz_cur>sz_ma20),'ma_bull':to_py(sz_ma60>sz_ma120>sz_ma250),
    'bdd_count':bd,'risk_flags':risk_flags,'rf_count':rf_count,
    'overall':overall,'overall_label':status_labels[overall],'overall_desc':status_desc[overall],
    'best_20':best_20,'worst_20':worst_20,'best_20_val':rets_20[best_20],'worst_20_val':rets_20[worst_20],
    'best_60':best_20,'worst_60':worst_20,'best_60_val':rets_20[best_20],'worst_60_val':rets_20[worst_20],
    'lv_vs_lg':lv_vs_lg,
    'benchmarks':{k:round(last[k],0) for k in BENCHMARKS},
    'ytd':ytd,'vg_data':vg_data,'ls_data':ls_data,'roll_data':roll_data,
    'ts_180':ts_180,'sz_180':sz_180,'rets_20':rets_20,'rets_60':rets_60,
    'etf_flow':etf_data,
}

with open(os.path.join(BASE,'dashboard_data.json'),'w',encoding='utf-8') as f:
    json.dump(data,f,ensure_ascii=False,indent=1)
print("JSON data generated: dashboard_data.json")
