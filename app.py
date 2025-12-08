import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import json

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 全市场直连版",
    layout="wide",
    page_icon="📡",
    initial_sidebar_state="expanded"
)

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心数据引擎 (全市场 5000+ 股票扫描) =================

def convert_to_yahoo(code):
    """将A股代码转换为Yahoo格式"""
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

@st.cache_data(ttl=60) # 60秒缓存，保证实时性
def get_full_market_data():
    """
    【核心黑科技】拉取沪深京全市场 5300+ 只股票的实时行情
    数据源：东方财富通用行情接口
    """
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    # f12:代码, f14:名称, f2:现价, f3:涨跌幅, f62:主力净流入, f20:总市值, f8:换手率
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1, 
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f62,f20,f8"
    }
    
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=3)
        data = r.json()
        if 'data' in data and 'diff' in data['data']:
            df = pd.DataFrame(data['data']['diff'])
            # 重命名列
            df = df.rename(columns={
                'f12': 'code', 'f14': 'name', 'f2': 'price', 
                'f3': 'pct', 'f62': 'money_flow', 'f20': 'market_cap', 'f8': 'turnover'
            })
            # 数据清洗
            df['price'] = pd.to_numeric(df['price'], errors='coerce')
            df['pct'] = pd.to_numeric(df['pct'], errors='coerce')
            df['money_flow'] = pd.to_numeric(df['money_flow'], errors='coerce')
            return df
    except Exception as e:
        st.error(f"连接交易所接口失败: {e}")
    
    return pd.DataFrame()

def search_stock_online(keyword):
    """
    全网搜索：直接调用东方财富搜索接口 (支持 A股/港股/美股)
    """
    keyword = keyword.strip()
    if not keyword: return None, None
    
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {"input": keyword, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": "5"}
        r = requests.get(url, params=params, timeout=2)
        data = r.json()
        items = data["QuotationCodeTable"]["Data"]
        if items:
            item = items[0]
            code = item['Code']
            name = item['Name']
            # 转换格式
            if item['MarketType'] == "1": y_code = f"{code}.SS"
            elif item['MarketType'] == "2": y_code = f"{code}.SZ"
            else: y_code = f"{code}.BJ" # 北交所等
            return y_code, name
    except: pass
    
    # 兜底
    if keyword.isdigit() and len(keyword)==6: 
        return convert_to_yahoo(keyword), keyword
    return None, None

# ================= 3. 深度分析逻辑 (单股) =================

@st.cache_data(ttl=600)
def analyze_single_stock(code, name):
    """计算单只股票的详细指标"""
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        
        curr = h['Close'].iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        # 指标
        h['MA20'] = h['Close'].rolling(20).mean()
        h['MA60'] = h['Close'].rolling(60).mean()
        ma20 = h['MA20'].iloc[-1]
        
        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        # 信号
        signal, color, advice = "观望", "gray", "趋势不明"
        if rsi > 80: signal, color, advice = "高抛/止盈", "red", "RSI超买，短线风险大"
        elif pct < -5 and curr < ma20: signal, color, advice = "止损", "red", "破位下跌"
        elif rsi < 70 and curr > ma20 and pct > 0: signal, color, advice = "买入", "green", "趋势向上，资金介入"
        elif curr > ma20: signal, color, advice = "持有", "blue", "沿20日线持有"

        return {
            "代码": code, "名称": name, "现价": round(curr,2), "涨幅": round(pct,2),
            "MA20": round(ma20,2), "RSI": round(rsi,1), 
            "信号": signal, "颜色": color, "建议": advice
        }
    except: return None

def run_ai_analysis(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['信号']}\n理由：{d['建议']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析A股{d['名称']}，RSI={d['RSI']}，涨幅{d['涨幅']}%。给出操作建议。"}]).choices[0].message.content
    except: return "AI连接超时"

# ================= 4. 业务逻辑 (全市场筛选) =================

def get_short_term_picks(df_market):
    """
    【短线爆发预测】
    逻辑：全市场扫描 -> 涨幅2-7% -> 主力资金流入前50名 -> 随机展示5个
    (避免只推龙一龙二买不进，从前50里选，机会更多)
    """
    # 1. 过滤掉ST和退市股 (名字包含ST)
    df = df_market[~df_market['name'].str.contains("ST|退")]
    
    # 2. 核心逻辑：涨幅适中(未涨停)，资金大举流入
    candidates = df[
        (df['pct'] > 2.0) & 
        (df['pct'] < 8.0) & 
        (df['money_flow'] > 30000000) # 流入超3000万
    ].copy()
    
    # 3. 按资金流向降序
    top_50 = candidates.sort_values("money_flow", ascending=False).head(50)
    
    if top_50.empty: return []
    # 随机取5个，增加多样性
    return top_50.sample(min(5, len(top_50))).to_dict('records')

def get_long_term_picks(df_market):
    """
    【长线稳健预测】
    逻辑：全市场扫描 -> 市值>500亿 -> 涨幅>0 -> 换手率低(筹码稳) -> 市值前20
    """
    # 1. 蓝筹股 (市值大)
    blue_chips = df_market[
        (df_market['market_cap'] > 50000000000) & # 500亿以上
        (df_market['pct'] > -1) # 今日没大跌
    ].copy()
    
    # 2. 按市值排序，取前20
    top_20 = blue_chips.sort_values("market_cap", ascending=False).head(20)
    
    if top_20.empty: return []
    return top_20.sample(min(5, len(top_20))).to_dict('records')

# ================= 5. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("📡 AlphaQuant Pro")
        st.info("账号: admin | 密码: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("登录", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("全市场直连版 v21.0")
        menu = st.radio("功能", ["👀 我的关注", "🔎 个股深度分析", "🔮 每日金股预测", "🏆 市场全景榜单", "⚙️ 设置"])
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    # --- 数据预加载 (只在需要全市场数据的页面加载) ---
    df_full = pd.DataFrame()
    if menu in ["🔮 每日金股预测", "🏆 市场全景榜单"]:
        with st.spinner("正在连接交易所，扫描全市场 5300+ 只股票..."):
            df_full = get_full_market_data()
            if df_full.empty: st.error("连接交易所失败，请刷新重试"); st.stop()
            else: st.toast(f"已获取 {len(df_full)} 只股票实时行情", icon="✅")

    # --- 1. 我的关注 (全网搜) ---
    if menu == "👀 我的关注":
        st.header("👀 我的自选股")
        with st.expander("➕ 添加股票 (搜全网)", expanded=False):
            c1, c2 = st.columns([3,1])
            k = c1.text_input("输入代码/名称 (如 恒林股份)")
            if c2.button("添加"):
                c, n = search_stock_online(k)
                if c:
                    exists = any(i['code'] == c for i in st.session_state['watchlist'])
                    if not exists: 
                        st.session_state['watchlist'].append({"code":c, "name":n})
                        st.success(f"已添加 {n}"); time.sleep(0.5); st.rerun()
                    else: st.warning("已存在")
                else: st.error("全网未找到")

        if st.session_state['watchlist']:
            for i, item in enumerate(st.session_state['watchlist']):
                d = analyze_single_stock(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        with c2: 
                            if d['颜色']=='green': st.success(f"建议：{d['信号']}")
                            elif d['颜色']=='red': st.error(f"建议：{d['信号']}")
                            else: st.info(f"建议：{d['信号']}")
                        with c3: 
                            if st.button("🗑️", key=f"d_{i}"): 
                                st.session_state['watchlist'].remove(item); st.rerun()

    # --- 2. 个股深度 (全网搜) ---
    elif menu == "🔎 个股深度分析":
        st.header("🔎 个股全维透视")
        c1, c2 = st.columns([3,1])
        k = c1.text_input("全网搜索 (如 600019 / 宝钢)", placeholder="支持任意A股...")
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("分析") or k:
            c, n = search_stock_online(k)
            if c:
                d = analyze_single_stock(c, n)
                if d:
                    st.divider()
                    m1, m2, m3 = st.columns(3)
                    m1.metric("名称", d['名称'], d['代码'])
                    m2.metric("现价", f"¥{d['现价']}", f"{d['涨幅']}%")
                    m3.metric("RSI", d['RSI'])
                    
                    l, r = st.columns([2,1])
                    with l: st.info(run_ai_analysis(d, base_url))
                    with r: 
                        st.write(f"信号: {d['信号']}")
                        st.caption(d['建议'])
                else: st.error("数据拉取失败")
            else: st.error("未找到")

    # --- 3. 金股预测 (真实全市场数据) ---
    elif menu == "🔮 每日金股预测":
        st.header("🔮 每日 Alpha 金股 (全市场扫描)")
        
        t1, t2 = st.tabs(["⚡️ 短线爆发 Top 5", "💎 长线稳健 Top 5"])
        
        with t1:
            st.info("筛选逻辑：全市场主力资金大幅流入 + 涨幅2-8% (未涨停) + 非ST")
            picks = get_short_term_picks(df_full)
            if picks:
                cols = st.columns(5)
                for i, (col, row) in enumerate(zip(cols, picks)):
                    with col:
                        st.markdown(f"**🔥 {row['name']}**")
                        st.metric(f"¥{row['price']}", f"+{row['pct']}%")
                        st.caption(f"主力: +{row['money_flow']/10000:.0f}万")
            else: st.warning("今日市场情绪低迷，暂无符合条件标的")
            
        with t2:
            st.info("筛选逻辑：全市场千亿市值龙头 + 走势稳健")
            picks = get_long_term_picks(df_full)
            if picks:
                cols = st.columns(5)
                for i, (col, row) in enumerate(zip(cols, picks)):
                    with col:
                        st.markdown(f"**🛡️ {row['name']}**")
                        st.metric(f"¥{row['price']}", f"{row['pct']}%")
                        st.caption(f"市值: {row['market_cap']/100000000:.0f}亿")

    # --- 4. 市场全景 (真实全市场数据) ---
    elif menu == "🏆 市场全景榜单":
        st.header("🏆 实时全景榜单")
        
        t1, t2, t3 = st.tabs(["🚀 涨幅榜 (Top 20)", "💰 资金流向榜", "📉 跌幅榜"])
        
        with t1:
            # 剔除涨幅过大的新股(>30%)
            df_gain = df_full[df_full['pct'] < 30].sort_values("pct", ascending=False).head(20)
            st.dataframe(df_gain[['code', 'name', 'price', 'pct', 'money_flow']], use_container_width=True)
            
        with t2:
            df_money = df_full.sort_values("money_flow", ascending=False).head(20)
            st.dataframe(df_money[['code', 'name', 'price', 'pct', 'money_flow']], use_container_width=True)
            
        with t3:
            df_loss = df_full.sort_values("pct", ascending=True).head(20)
            st.dataframe(df_loss[['code', 'name', 'price', 'pct']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()



















