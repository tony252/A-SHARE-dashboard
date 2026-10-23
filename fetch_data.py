"""
A股风格指数数据抓取脚本 v4
策略: 新浪API(快, 16:00即有数据)优先, 腾讯API(准但慢)作sh000919/918备用
备选: tushare (需设置 TUSHARE_TOKEN 环境变量)
"""
import sys, io, os, time
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

import pandas as pd
import akshare as ak

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(BASE, 'data', 'style_indices_v2.csv')

# ==================== INDEX DEFINITIONS ====================
STYLE_INDICES = [
    ('大盘价值', 'sh000919'), ('大盘成长', 'sh000918'),
    # 注意: 399374=中盘成长, 399375=中盘价值 (腾讯/新浪行情名核对)
    ('中盘价值', 'sz399375'), ('中盘成长', 'sz399374'),
    # 注意: 399376=小盘成长, 399377=小盘价值 (腾讯/新浪行情名核对)
    ('小盘价值', 'sz399377'), ('小盘成长', 'sz399376'),
]
BENCHMARK_INDICES = [
    ('沪深300','sh000300'), ('上证指数','sh000001'), ('中证500','sh000905'),
    ('中证1000','sh000852'), ('上证50','sh000016'), ('创业板指','sz399006'),
    ('中证红利','sh000922'),
]
ALL_INDICES = STYLE_INDICES + BENCHMARK_INDICES
ALL_COLS = [name for name, _ in ALL_INDICES]
SLEEP_SEC = 0.3

# sh000919/000918: Sina API返回过期数据(2019), 必须用TX
TX_ONLY = {'sh000919', 'sh000918'}

TUSHARE_MAP = {
    '上证指数':'000001.SH','沪深300':'000300.SH','上证50':'000016.SH',
    '中证500':'000905.SH','中证1000':'000852.SH','创业板指':'399006.SZ',
    '中证红利':'000922.SH','大盘价值':'000919.SH','大盘成长':'000918.SH',
    '中盘价值':'399375.SZ','中盘成长':'399374.SZ','小盘价值':'399377.SZ','小盘成长':'399376.SZ',
}

# ==================== FETCH FUNCTIONS ====================
def fetch_sina(name, symbol):
    """Sina API — fast updates, published by ~16:00"""
    try:
        df = ak.stock_zh_index_daily(symbol=symbol)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        return df['close'].rename(name)
    except Exception:
        return None

def fetch_tx(name, symbol, start, end):
    """Tencent API — accurate but publishes later (~16:30-17:00)"""
    try:
        df = ak.stock_zh_index_daily_tx(symbol=symbol, start_date=start, end_date=end)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date').sort_index()
        return df['close'].rename(name)
    except Exception:
        return None

def try_tushare(name, ts_code, start, end):
    """tushare — fastest if token available"""
    token = os.environ.get('TUSHARE_TOKEN', '')
    if not token:
        return None
    try:
        import tushare as ts
        ts.set_token(token)
        pro = ts.pro_api()
        df = pro.index_daily(ts_code=ts_code, start_date=start, end_date=end)
        if df is not None and len(df) > 0:
            df['trade_date'] = pd.to_datetime(df['trade_date'])
            df = df.set_index('trade_date').sort_index()
            return df['close'].rename(name)
    except Exception:
        pass
    return None

# ==================== MAIN FETCH ====================
def fetch_all(start='20130101', end='20260710'):
    """Fetch all indices: tushare > Sina > TX"""
    series_list = []
    use_tushare = bool(os.environ.get('TUSHARE_TOKEN', ''))

    for name, symbol in ALL_INDICES:
        s = None
        src = ''

        # 1. tushare (if configured)
        if use_tushare and name in TUSHARE_MAP:
            s = try_tushare(name, TUSHARE_MAP[name], start, end)
            if s is not None:
                src = 'tushare'

        # 2. Sina (fast, for most indices)
        if s is None and symbol not in TX_ONLY:
            s = fetch_sina(name, symbol)
            if s is not None:
                src = 'sina'
                # Only keep last 90 days; existing CSV has full history
                s = s.iloc[-90:]
                # Smart check: if Sina's latest data is older than TX, use TX
                from datetime import datetime, timedelta
                today_str = datetime.now().strftime('%Y%m%d')
                if s.index[-1].strftime('%Y%m%d') < today_str:
                    tx_s = fetch_tx(name, symbol, start, end)
                    if tx_s is not None and len(tx_s) > 0 and tx_s.index[-1] > s.index[-1]:
                        tx_s = tx_s[tx_s.index >= s.index[0]]  # only recent data from TX
                        s = pd.concat([s.iloc[:-5], tx_s]) if len(s) > 5 else tx_s
                        s = s[~s.index.duplicated(keep='last')].sort_index()
                        src = 'sina+tx'

        # 3. TX (slow but reliable, required for sh000919/918)
        if s is None:
            s = fetch_tx(name, symbol, start, end)
            if s is not None:
                src = 'tx'

        if s is not None:
            print(f"  {name} [{src}] {s.index[0].strftime('%Y-%m-%d')}~{s.index[-1].strftime('%Y-%m-%d')} ({len(s)} rows)")
            series_list.append(s)
        else:
            print(f"  {name} FAILED!")
        time.sleep(SLEEP_SEC)

    df = pd.concat(series_list, axis=1).sort_index().ffill()
    style_cols = [n for n, _ in STYLE_INDICES]
    df = df.dropna(subset=style_cols, how='all')
    return df

def fetch_all_full_history():
    """全量抓取: 忽略本地 CSV, 从 2010 年起重建整条历史(用于修正历史标签)"""
    return fetch_all(start='20100101', end=datetime.now().strftime('%Y%m%d'))

# ==================== MAIN ====================
if __name__ == '__main__':
    print("=" * 60)
    print("A股风格指数数据抓取 v4 (Sina优先 + TX兜底)")
    token = os.environ.get('TUSHARE_TOKEN', '')
    print(f"tushare: {'已配置' if token else '未配置'}")
    print("=" * 60)

    existing = None
    if os.path.exists(CSV_PATH):
        existing = pd.read_csv(CSV_PATH, index_col=0, parse_dates=True)
        print(f"已有数据: {len(existing)} 行, {existing.index[0].strftime('%Y-%m-%d')} ~ {existing.index[-1].strftime('%Y-%m-%d')}")
        from datetime import datetime, timedelta
        fetch_start = (existing.index[-1] - timedelta(days=30)).strftime('%Y%m%d')
        today_str = datetime.now().strftime('%Y%m%d')
        print(f"增量更新: {fetch_start} ~ {today_str}")
    else:
        fetch_start, today_str = '20130101', '20260710'
        print(f"全量获取: {fetch_start} ~ {today_str}")

    print("\n抓取中 (策略: Sina→TX)...")
    df_new = fetch_all(start=fetch_start, end=today_str)

    if existing is not None and len(df_new) > 0:
        # Keep existing historical data, fill with new where available
        combined = existing.combine_first(df_new)
        combined = combined.sort_index()
        print(f"\n合并: {len(combined)} 行")
        df_final = combined
    else:
        df_final = df_new

    # Check: if last row has ffill'd style data (incomplete update), drop it
    if len(df_final) >= 2:
        last = df_final.iloc[-1]
        prev = df_final.iloc[-2]
        style_names = [n for n, _ in STYLE_INDICES]
        unchanged = [n for n in style_names if abs(last[n] - prev[n]) < 0.001]
        if len(unchanged) >= 3:  # 3+ style indices unchanged → incomplete
            print(f"\n⚠ 最新行数据不完整({','.join(unchanged)}未变)，已剔除 {df_final.index[-1].strftime('%Y-%m-%d')}")
            df_final = df_final.iloc[:-1]

    df_final = df_final[ALL_COLS]
    os.makedirs(os.path.dirname(CSV_PATH), exist_ok=True)
    df_final.to_csv(CSV_PATH, float_format='%.4f')
    print(f"\n保存: {CSV_PATH}")
    print(f"日期: {df_final.index[0].strftime('%Y-%m-%d')} ~ {df_final.index[-1].strftime('%Y-%m-%d')} ({len(df_final)} 行)")
    print(f"最新 ({df_final.index[-1].strftime('%Y-%m-%d')}):")
    for col in ALL_COLS:
        print(f"  {col}: {df_final[col].iloc[-1]:.2f}")
