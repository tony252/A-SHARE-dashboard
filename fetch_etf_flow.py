"""国家队ETF份额跟踪 - 数据抓取脚本"""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import akshare as ak
import requests
from datetime import datetime, timedelta

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE, 'data', 'etf_flow.csv')
PRICE_PATH = os.path.join(BASE, 'data', 'etf_price.csv')

# 国家队常用宽基ETF
TARGET_ETFS = {
    # 沪深300系列
    '510300': ('沪深300ETF华泰柏瑞', 'SSE'),
    '510310': ('沪深300ETF易方达', 'SSE'),
    '510330': ('沪深300ETF华夏', 'SSE'),
    '159919': ('沪深300ETF嘉实', 'SZSE'),
    # 上证50
    '510050': ('上证50ETF', 'SSE'),
    # 中证500
    '510500': ('中证500ETF', 'SSE'),
    # 中证1000
    '512100': ('中证1000ETF南方', 'SSE'),
    '159845': ('中证1000ETF华夏', 'SZSE'),
    # 创业板
    '159915': ('创业板ETF', 'SZSE'),
    '159949': ('创业板50ETF', 'SZSE'),
    # 科创50
    '588000': ('科创50ETF', 'SSE'),
    '588080': ('科创50ETF易方达', 'SSE'),
    # 上证180
    '510180': ('上证180ETF', 'SSE'),
    # 红利
    '510880': ('红利ETF', 'SSE'),
    '512890': ('中证红利ETF', 'SSE'),
    # 证券（国家队护盘常用）
    '512880': ('证券ETF', 'SSE'),
}
RETRY_COUNT = 3
RETRY_DELAY = 10  # seconds

class NoDataError(Exception):
    """该日期无数据(非交易日/数据未发布) —— 不值得重试"""

def _retry(func, name, *args, **kwargs):
    """重试包装: 失败后指数退避"""
    for attempt in range(RETRY_COUNT):
        try:
            return func(*args, **kwargs)
        except NoDataError as e:
            print(f"  {name} 无数据(非交易日或未发布), 跳过")
            return None
        except Exception as e:
            if attempt < RETRY_COUNT - 1:
                wait = RETRY_DELAY * (2 ** attempt)
                print(f"  {name} retry {attempt+1}/{RETRY_COUNT} in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  {name} FAILED after {RETRY_COUNT} tries: {e}")
                return None

def fetch_sse(date_str):
    """获取上交所ETF某日份额"""
    def _do():
        df = ak.fund_etf_scale_sse(date=date_str)
        if df is None or len(df) == 0:
            raise NoDataError(f"SSE {date_str} 无数据")
        df = df[['基金代码', '基金份额']].copy()
        df['日期'] = pd.to_datetime(date_str)
        df.columns = ['code', 'shares', 'date']
        return df
    return _retry(_do, f"SSE {date_str}")

def fetch_szse(date_str):
    """获取深交所ETF某日份额

    注意: ak.fund_etf_scale_szse() 在 akshare 1.19.x 已失效(bytes TypeError),
    改用 fund_scale_daily_szse(start_date, end_date, symbol='ETF'),
    该接口支持按日查询, 可直接拿到指定交易日的份额。
    """
    def _do():
        df = ak.fund_scale_daily_szse(
            start_date=date_str, end_date=date_str, symbol='ETF'
        )
        if df is None or len(df) == 0:
            raise NoDataError(f"SZSE {date_str} 无数据")
        df = df[['基金代码', '基金份额']].copy()
        df['日期'] = pd.to_datetime(date_str)
        df.columns = ['code', 'shares', 'date']
        df['code'] = df['code'].astype(str).str.zfill(6)
        return df
    return _retry(_do, f"SZSE {date_str}")

def get_trading_dates(n=15):
    """获取最近n个真实交易日(用新浪交易日历, 排除法定节假日)"""
    try:
        cal = ak.tool_trade_date_hist_sina()
        cal['trade_date'] = pd.to_datetime(cal['trade_date'])
        today = pd.Timestamp.now().normalize()
        past = cal[cal['trade_date'] < today]['trade_date'].sort_values(ascending=False)
        return [d.strftime('%Y%m%d') for d in past.head(n).tolist()]
    except Exception as e:
        print(f"交易日历获取失败, 回退到近似算法: {e}")
    dates = []
    d = datetime.now() - timedelta(days=1)  # 从昨天开始，不含今天(数据未出)
    while len(dates) < n:
        if d.weekday() < 5:  # Mon-Fri
            dates.append(d.strftime('%Y%m%d'))
        d -= timedelta(days=1)
    return dates

def _tx_symbol(code):
    """ETF 代码 -> 腾讯行情代码"""
    return ('sh' if code[0] == '5' else 'sz') + code

def fetch_prices(codes, start, end):
    """抓取 ETF 日线收盘价(腾讯), 返回 DataFrame[code][date] = close

    用途: 金额 = 份额变化 x 价格, 用真实收盘价而非硬编码净值,
    避免因净值过期导致金额系统性高估。
    """
    prices = {}
    for code in codes:
        sym = _tx_symbol(code)
        url = (
            'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get'
            f'?param={sym},day,{start},{end},60,qfq'
        )
        try:
            r = requests.get(url, timeout=20)
            j = r.json()
            node = j.get('data', {}).get(sym, {})
            rows = node.get('qfqday') or node.get('day') or []
            if not rows:
                continue
            ser = pd.Series(
                {str(row[0]): float(row[2]) for row in rows if len(row) > 2},
                name=code,
            )
            prices[code] = ser
            print(f"  price {code}: {len(ser)} rows")
        except Exception as e:
            print(f"  price {code} error: {e}")
        time.sleep(0.15)
    if not prices:
        return pd.DataFrame()
    df = pd.DataFrame(prices)
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

if __name__ == '__main__':
    print("=" * 50)
    print("国家队ETF份额抓取")
    print("=" * 50)

    # 至少要覆盖 11 个交易日, 否则 10 日增量列永远算不出来
    dates = get_trading_dates(13)
    print(f"日期范围: {dates[-1]} ~ {dates[0]}")

    all_data = []
    
    # === SSE: get historical data ===
    for date_str in dates:
        print(f"Fetching SSE {date_str}...", end=' ')
        df = fetch_sse(date_str)
        if df is not None:
            target = df[df['code'].isin(TARGET_ETFS.keys())]
            all_data.append(target)
            print(f"{len(target)} ETFs")
        else:
            print("skipped")
        time.sleep(0.3)

    # === SZSE: 按日抓取(新版接口支持历史日期) ===
    for date_str in dates:
        print(f"Fetching SZSE {date_str}...", end=' ')
        df_sz = fetch_szse(date_str)
        if df_sz is not None:
            sz_target = df_sz[df_sz['code'].isin(TARGET_ETFS.keys())]
            all_data.append(sz_target)
            print(f"{len(sz_target)} ETFs")
        else:
            print("skipped")
        time.sleep(0.3)
    
    if not all_data:
        print("No data fetched!")
        exit(1)

    combined = pd.concat(all_data, ignore_index=True)
    combined = combined.sort_values(['code', 'date'])
    
    # Pivot
    pivot = combined.pivot_table(
        values='shares', index='code', columns='date', aggfunc='first'
    )
    pivot = pivot.sort_index(axis=1)
    
    # Merge with existing history + preserve rows on fetch failure
    if os.path.exists(CSV_PATH):
        existing = pd.read_csv(CSV_PATH, index_col=0)
        existing.columns = pd.to_datetime(existing.columns)
        existing.index = [str(i).split(' ', 1)[0] for i in existing.index]
        existing = existing[~existing.index.duplicated(keep='last')]
        pivot.index = [str(i).split(' ', 1)[0] for i in pivot.index]
        pivot = pivot[~pivot.index.duplicated(keep='last')]
        for code in existing.index:
            if code in TARGET_ETFS:
                if code in pivot.index:
                    # 抓取失败的历史日期用旧值补齐(旧值为 NaN 时才用新值)
                    pivot.loc[code] = pivot.loc[code].combine_first(existing.loc[code])
                else:
                    # 本次完全没取到该 ETF —— 保留旧数据
                    pivot.loc[code] = existing.loc[code]
    
    # Add names to index
    new_idx = []
    for c in pivot.index:
        code_str = str(c).split(' ')[0] if ' ' in str(c) else str(c)
        name = TARGET_ETFS.get(code_str, ('',))[0]
        new_idx.append(f"{code_str} {name}")
    pivot.index = new_idx
    
    pivot.to_csv(CSV_PATH)
    print(f"\n保存: {CSV_PATH}")
    print(f"ETF数量: {len(pivot)}")
    dates_all = [d for d in pivot.columns if not pd.isna(d)]
    if dates_all:
        print(f"日期范围: {min(dates_all).strftime('%Y-%m-%d')} ~ {max(dates_all).strftime('%Y-%m-%d')}")
    
    # Show latest changes
    print("\n最新日份额变化 (亿份):")
    for code in pivot.index:
        vals = pivot.loc[code].dropna()
        if len(vals) >= 2:
            delta = (vals.iloc[-1] - vals.iloc[-2]) / 1e8
            print(f"  {code}: {delta:+.2f}")

    # === 抓取 ETF 收盘价(用于金额换算), 增量合并 ===
    print("\n抓取 ETF 收盘价 (腾讯)...")
    price_df = fetch_prices(
        list(TARGET_ETFS.keys()),
        (datetime.now() - timedelta(days=60)).strftime('%Y-%m-%d'),
        datetime.now().strftime('%Y-%m-%d'),
    )
    if len(price_df) > 0:
        price_df.to_csv(PRICE_PATH)
        print(f"保存: {PRICE_PATH}  ({price_df.shape[0]} 行 x {price_df.shape[1]} 列)")
    else:
        print("警告: 价格抓取失败, 将回退到硬编码净值")
