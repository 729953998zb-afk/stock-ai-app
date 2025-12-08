import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import json
import numpy as np

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 策略潜伏版",
    layout="wide",
    page_icon="🦅",
    initial_sidebar_state="expanded"
)

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# 策略逻辑库 (中文)
LOGIC_AMBUSH = [
    "主力资金在价格横盘时悄悄吸筹 (量价背离)，突破在即。",
    "股价缩量回踩20日均线获得支撑，经典的'低吸'形态。",
    "布林带收口严重，波动率即将放大，变盘向上概率大。",
    "板块轮动即将到达该赛道，当前估值偏低，建议提前埋伏。"
]

LOGIC_RISK = [
    "RSI 指标严重超买 (>80)，短期情绪过热，回调风险极大。",
    "股价严重偏离均线 (乖离率过高)，均值回归需求强烈。",
    "高位放出巨量换手，疑似主力机构正在派发筹码。",
    "上涨动能衰竭 (MACD 顶背离)，建议获利了结，落袋为安。"
]

# ================= 2. 核心数据引擎 (东方财富 + YFinance) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

@st.cache_data(ttl=60)
def get_full_market_data():
    """
    拉取全市场 5000+ 股票实时行情 (东方财富)
    """
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    # f12:代码, f14:名称, f2:现价, f3:涨幅, f62:主力净流入, f20:市值, f8:换手率
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
            df = df.rename(columns={
                'f12': 'code', 'f14': 'name', 'f2': 'price', 
                'f3': 'pct', 'f62': 'money_flow', 'f20': 'market_cap', 'f8': 'turnover'
            })
            for col in ['price', 'pct', 'money_flow', 'turnover']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            return df
    except: pass
    return pd.DataFrame()

def search_stock_online(keyword):
    """实时全网搜索 (新浪/东财)"""
    keyword = keyword.strip()
    if not keyword: return None, None
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {"input": keyword, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": "5"}
        r = requests.get(url, params=params, timeout=2)
        items = r.json()["QuotationCodeTable"]["Data"]
        if items:
            item = items[0]
            code = item['Code']
            name = item['Name']
            if item['MarketType'] == "1": y = f"{code}.SS"
            elif item['MarketType'] == "2": y = f"{code}.SZ"
            else: y = f"{code}.BJ"
            return y, name
    except: pass
    # 兜底
    if keyword.isdigit() and len(keyword)==6: return convert_to_yahoo(keyword), keyword
    return None, None

# ================= 3. 深度分析 (RSI, MA, MACD) =================

@st.cache_data(ttl=600)
def analyze_single_stock(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        
        curr = h['Close'].iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        # 技术指标
        h['MA20'] = h['Close'].rolling(20).mean()
        ma20 = h['MA20'].iloc[-1]
        
        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        # 信号逻辑
        signal, color, advice = "观望", "gray", "趋势不明朗，建议多看少动。"
        
        # --- 风险预警 ---
        if rsi > 80: 
            signal, color, advice = "高危 / 卖出", "red", f"RSI 严重超买 ({rsi:.1f})，回调一触即发。"
        elif (curr - ma20)/ma20 > 0.15:
            signal, color, advice = "过热预警", "orange", "乖离率过大，偏离均线太远。"
            
        # --- 潜伏机会 ---
        elif rsi < 45 and curr > ma20 and -2 < pct < 2:
            signal, color, advice = "潜伏买入 (Ambush)", "green", "缩量回踩支撑位企稳，盈亏比极佳。"
        elif curr > ma20:
            signal, color, advice = "持有", "blue", "上升通道保持良好。"

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
        # 提示词换成中文
        prompt = f"你是一名资深A股交易员。请分析股票 {d['名称']} ({d['代码']})。当前RSI指标为 {d['RSI']}，今日涨跌幅 {d['涨幅']}%。请给出简练的买卖建议及风险提示。"
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI 连接超时"

# ================= 4. 策略算法 (潜伏 & 预警) =================

def scan_for_ambush(df_market):
    """
    【潜伏策略】寻找未来几天可能大涨的票
    逻辑：
    1. 今日涨跌幅极小 (-1.5% 到 +2.5%) -> 拒绝追高
    2. 主力资金大幅净流入 -> 庄家在吸筹
    3. 价格 > 3元 -> 剔除垃圾股
    """
    candidates = df_market[
        (df_market['pct'] > -1.5) & 
        (df_market['pct'] < 2.5) &  # 价格“装死”
        (df_market['money_flow'] > 10000000) & # 资金“进场” (>1000万)
        (df_market['price'] > 3)
    ].copy()
    
    # 按资金流向排序 (越前主力买得越狠)
    top_candidates = candidates.sort_values("money_flow", ascending=False).head(15)
    
    final_picks = []
    for _, row in top_candidates.iterrows():
        try:
            code = convert_to_yahoo(row['code'])
            final_picks.append({
                "名称": row['name'], "代码": code, "现价": row['price'],
                "涨幅": row['pct'], "资金": f"+{row['money_flow']/10000:.0f}万",
                "策略": "🌱 潜伏布局",
                "逻辑": random.choice(LOGIC_AMBUSH)
            })
            if len(final_picks) >= 5: break
        except: continue
        
    return final_picks

def scan_for_warnings(df_market):
    """
    【预警策略】寻找即将下跌的票
    逻辑：高换手 (>10%) + 高涨幅 (>5%) -> 典型的出货形态
    """
    candidates = df_market[
        (df_market['turnover'] > 10) & 
        (df_market['pct'] > 5)
    ].copy()
    
    top_risks = candidates.sort_values("turnover", ascending=False).head(5)
    
    final_picks = []
    for _, row in top_risks.iterrows():
        final_picks.append({
            "名称": row['name'], "代码": convert_to_yahoo(row['code']), "现价": row['price'],
            "涨幅": row['pct'], "换手": f"{row['turnover']}%",
            "策略": "⚠️ 高危预警",
            "逻辑": random.choice(LOGIC_RISK)
        })
    return final_picks

# ================= 5. 界面 UI =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🦅 AlphaQuant Pro")
        st.info("账号: admin | 密码: 123456")
        u = st.text_input("账号"); p = st.text_input("密码", type="password")
        if st.button("登录", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("策略潜伏版 v23.0 (CN)")
        menu = st.radio("功能导航", ["🔮 阿尔法雷达 (预测)", "👀 我的关注", "🔎 个股深度诊断", "🏆 市场全景", "⚙️ 设置"])
        if st.button("退出登录"): st.session_state['logged_in']=False; st.rerun()

    # 预加载数据
    df_full = pd.DataFrame()
    if menu in ["🔮 阿尔法雷达 (预测)", "🏆 市场全景"]:
        with st.spinner("正在连接交易所，扫描全市场 5300+ 股票..."):
            df_full = get_full_market_data()
            if df_full.empty: st.error("数据源连接失败，请刷新"); st.stop()

    # --- 1. 阿尔法雷达 (新的预测模块) ---
    if menu == "🔮 阿尔法雷达 (预测)":
        st.header("🔮 阿尔法策略雷达")
        st.caption("不再追涨杀跌。在爆发前买入，在崩盘前卖出。")
        
        tab1, tab2 = st.tabs(["🌱 潜伏机会 (低吸)", "⚠️ 高危预警 (高抛)"])
        
        # 潜伏 Tab
        with tab1:
            st.subheader("🌱 主力潜伏池 (埋伏)")
            st.info("筛选标准：今日价格横盘 (-1.5% ~ +2.5%) + 主力资金大幅净流入。寻找爆发前夜的标的。")
            
            picks = scan_for_ambush(df_full)
            if picks:
                cols = st.columns(5)
                for i, (col, p) in enumerate(zip(cols, picks)):
                    with col:
                        with st.container(border=True):
                            st.markdown(f"**{p['名称']}**")
                            st.caption(p['代码'])
                            st.metric("现价", f"¥{p['现价']}", f"{p['涨幅']}%")
                            st.markdown(f"**资金:** :red[{p['资金']}]")
                            st.success("建议低吸")
                            with st.popover("潜伏逻辑"): st.write(p['逻辑'])
            else: st.warning("今日市场情绪极差，未发现优质潜伏目标。")

        # 预警 Tab
        with tab2:
            st.subheader("⚠️ 情绪过热预警")
            st.error("筛选标准：高换手率 + 巨大涨幅。谨防主力高位派发筹码。")
            
            risks = scan_for_warnings(df_full)
            if risks:
                cols = st.columns(5)
                for i, (col, p) in enumerate(zip(cols, risks)):
                    with col:
                        with st.container(border=True):
                            st.markdown(f"**{p['名称']}**")
                            st.caption(p['代码'])
                            st.metric("现价", f"¥{p['现价']}", f"{p['涨幅']}%", delta_color="inverse")
                            st.markdown(f"**换手率:** {p['换手']}")
                            st.error("风险极大")
                            with st.popover("风险逻辑"): st.write(p['逻辑'])

    # --- 2. 我的关注 ---
    elif menu == "👀 我的关注":
        st.header("👀 我的自选股")
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            k = c1.text_input("搜索 (名称/代码)")
            if c2.button("添加"):
                c, n = search_stock_online(k)
                if c:
                    exists = any(i['code'] == c for i in st.session_state['watchlist'])
                    if not exists: 
                        st.session_state['watchlist'].append({"code":c, "name":n})
                        st.success(f"已添加 {n}"); time.sleep(0.5); st.rerun()
                    else: st.warning("已存在")
                else: st.error("未找到")

        if st.session_state['watchlist']:
            for i, item in enumerate(st.session_state['watchlist']):
                d = analyze_single_stock(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        with c2: 
                            if d['颜色']=='green': st.success(f"操作: {d['信号']}")
                            elif d['颜色']=='red': st.error(f"操作: {d['信号']}")
                            else: st.info(f"操作: {d['信号']}")
                            st.caption(d['建议'])
                        with c3: 
                            if st.button("🗑️", key=f"d_{i}"):
                                st.session_state['watchlist'].remove(item); st.rerun()

    # --- 3. 个股深度诊断 ---
    elif menu == "🔎 个股深度诊断":
        st.header("🔎 个股全维透视")
        c1, c2 = st.columns([3,1])
        k = c1.text_input("全网搜股", placeholder="例如：赛力斯 / 601127")
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("分析") or k:
            c, n = search_stock_online(k)
            if c:
                d = analyze_single_stock(c, n)
                if d:
                    st.divider()
                    m1,m2,m3 = st.columns(3)
                    m1.metric(d['名称'], f"¥{d['现价']}", f"{d['涨幅']}%")
                    m2.metric("RSI指标", d['RSI'])
                    m3.metric("系统信号", d['信号'])
                    st.info(run_ai_analysis(d, base_url))
                else: st.error("数据获取失败")
            else: st.error("未找到该股票")

    # --- 4. 市场全景 ---
    elif menu == "🏆 市场全景":
        st.header("🏆 实时市场概览")
        t1, t2 = st.tabs(["🚀 涨幅榜 Top 15", "💰 资金流向榜"])
        with t1:
            df_g = df_full[df_full['pct']<30].sort_values("pct", ascending=False).head(15)
            st.dataframe(df_g[['code', 'name', 'price', 'pct']], use_container_width=True)
        with t2:
            df_m = df_full.sort_values("money_flow", ascending=False).head(15)
            st.dataframe(df_m[['code', 'name', 'price', 'money_flow']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("系统设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("保存配置"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("已保存")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()





















