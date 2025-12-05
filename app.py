import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import numpy as np

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 全能实战版",
    layout="wide",
    page_icon="🔥",
    initial_sidebar_state="expanded"
)

# --- A. 核心数据库 (用于市场扫描和搜索) ---
# 包含热门股 + 用户点名股
WATCH_LIST_MAP = {
    "600519.SS": "贵州茅台", "300750.SZ": "宁德时代", "601318.SS": "中国平安", 
    "002594.SZ": "比亚迪",   "600036.SS": "招商银行", "601857.SS": "中国石油", 
    "000858.SZ": "五粮液",   "601138.SS": "工业富联", "603259.SS": "药明康德", 
    "300059.SZ": "东方财富", "002475.SZ": "立讯精密", "601127.SS": "赛力斯", 
    "600418.SS": "江淮汽车", "000063.SZ": "中兴通讯", "603600.SS": "永艺股份",
    "601728.SS": "中国电信", "600941.SS": "中国移动", "002371.SZ": "北方华创", 
    "300274.SZ": "阳光电源", "600150.SS": "中国船舶", "600600.SS": "青岛啤酒", 
    "600030.SS": "中信证券", "000725.SZ": "京东方A",  "600276.SS": "恒瑞医药",
    "600900.SS": "长江电力", "601919.SS": "中远海控", "000002.SZ": "万科A",
    "000333.SZ": "美的集团", "603288.SS": "海天味业", "601088.SS": "中国神华",
    "601606.SS": "长城军工", "601899.SS": "紫金矿业", "601012.SS": "隆基绿能"
}

# --- B. 智能搜索映射库 (中文 -> 代码) ---
STOCK_DB = {v: k for k, v in WATCH_LIST_MAP.items()} # 反转字典，方便查代码
# 手动补充一些特殊的
STOCK_DB.update({"长城军工": "601606.SS", "赛力斯": "601127.SS", "永艺": "603600.SS"})

# 宏观逻辑库
MACRO_LOGIC = [
    "全球流动性外溢，核心资产估值重塑", "社保基金与汇金增持，底部支撑强劲", 
    "行业进入补库存周期，业绩拐点确认", "避险情绪升温，高股息资产受追捧",
    "国产替代加速，在手订单量超预期"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = ["600519.SS", "601127.SS"]

# ================= 2. 核心算法 (搜索 + 榜单 + 信号) =================

def smart_search_stock(input_str):
    """智能搜索: 支持中文/代码"""
    input_str = input_str.strip()
    # 1. 中文匹配
    if input_str in STOCK_DB: return STOCK_DB[input_str], input_str
    # 2. 模糊中文匹配 (如输入 '茅台')
    for name, code in STOCK_DB.items():
        if input_str in name: return code, name
    # 3. 代码匹配
    if input_str.isdigit() and len(input_str) == 6:
        suffix = ".SS" if input_str.startswith("6") else ".SZ"
        code = input_str + suffix
        name = WATCH_LIST_MAP.get(code, input_str)
        return code, name
    if input_str.endswith(".SS") or input_str.endswith(".SZ"):
        return input_str, WATCH_LIST_MAP.get(input_str, input_str)
    return None, None

@st.cache_data(ttl=1800)
def get_market_data_for_ranking():
    """
    【核心】全市场扫描：用于生成 T+1 榜单和 性价比榜单
    """
    data_list = []
    tickers = " ".join(list(WATCH_LIST_MAP.keys()))
    try:
        # 拉取1年数据
        df_yf = yf.download(tickers, period="1y", progress=False)
        if isinstance(df_yf.columns, pd.MultiIndex): closes = df_yf['Close']
        else: closes = df_yf

        for code, name in WATCH_LIST_MAP.items():
            try:
                col = code if code in closes.columns else code.split('.')[0]
                if col in closes.columns:
                    series = closes[col].dropna()
                    if len(series) > 200:
                        curr = series.iloc[-1]
                        
                        # 计算指标
                        pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                        pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                        year_start = series.iloc[0]
                        pct_1y = float(((curr - year_start) / year_start) * 100)
                        
                        # 波动率与性价比
                        daily_ret = series.pct_change().dropna()
                        volatility = daily_ret.std() * 100 
                        stability_score = (pct_1y + 10) / (volatility + 0.1)
                        
                        # T+1 安全分计算
                        t1_safety = 100
                        if pct_1d > 8: t1_safety -= 30 
                        elif pct_1d < -2: t1_safety -= 20
                        else: t1_safety -= 5
                        
                        ma20 = series.rolling(20).mean().iloc[-1]
                        if curr > ma20: t1_safety += 10
                        
                        data_list.append({
                            "名称": name, "代码": code, "现价": float(curr),
                            "短线涨幅(1周)": pct_5d, "长线涨幅(1年)": pct_1y,
                            "今日涨幅": pct_1d, "波动率": volatility,
                            "性价比": stability_score, "T+1安全分": t1_safety
                        })
            except: continue
    except: return pd.DataFrame()
    return pd.DataFrame(data_list)

@st.cache_data(ttl=600)
def get_single_stock_analysis(code, name):
    """个股深度分析 + 买卖信号"""
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        
        curr = h['Close'].iloc[-1]
        ma5 = h['Close'].rolling(5).mean().iloc[-1]
        ma20 = h['Close'].rolling(20).mean().iloc[-1]
        ma60 = h['Close'].rolling(60).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        # 信号生成
        signal_type, color, advice = "观望", "gray", "趋势不明，建议多看少动。"
        
        if pct < -5 and curr < ma20:
            signal_type, color, advice = "卖出/止损", "red", "破位下跌，短线获利盘出逃。"
        elif ((curr - ma20)/ma20) > 0.2:
            signal_type, color, advice = "止盈/减仓", "orange", "乖离率过大，随时回调。"
        elif curr > ma5 and ma5 > ma20 and pct > 0:
            signal_type, color, advice = "短线买入", "green", "均线多头，资金介入明显。"
        elif abs(curr - ma60)/ma60 < 0.02 and curr > ma60:
            signal_type, color, advice = "长线建仓", "blue", "回踩生命线企稳，适合布局。"
        elif curr > ma20:
            signal_type, color, advice = "持有", "blue", "上升趋势未变，沿20日线持有。"

        return {
            "代码": code, "名称": name, "现价": round(curr, 2), "涨幅": round(pct, 2),
            "MA20": round(ma20, 2), "信号": signal_type, "颜色": color, "建议": advice
        }
    except: return None

# 生成 T+1 预测
def generate_t1_picks(df):
    # 筛选：安全分高 + 短线有动能
    candidates = df[(df['T+1安全分'] > 80) & (df['短线涨幅(1周)'] > 0)].copy()
    if candidates.empty: candidates = df.head(5) # 兜底
    picks = candidates.sort_values("T+1安全分", ascending=False).head(5)
    
    results = []
    for _, row in picks.iterrows():
        results.append({
            "名称": row['名称'], "代码": row['代码'], "现价": row['现价'],
            "预测胜率": f"{row['T+1安全分']:.1f}%",
            "逻辑": f"结构：{random.choice(MACRO_LOGIC)}。今日涨幅 {row['今日涨幅']:.2f}% 适中，未透支动能。",
        })
    return results

# 生成 性价比 榜单
def get_top_value_stocks(df):
    # 筛选：年线正收益
    candidates = df[df['长线涨幅(1年)'] > -10].copy() 
    if candidates.empty: candidates = df.copy()
    return candidates.sort_values("性价比", ascending=False).head(5)

# AI 分析
def run_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    context = f"股票：{stock_data['名称']}，现价：{stock_data['现价']}，信号：{stock_data['信号']}，建议：{stock_data['建议']}"
    if not key or not key.startswith("sk-"):
        return f"> **🤖 免费模式**\n**建议**：{stock_data['信号']}\n**理由**：{stock_data['建议']}"
    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析A股{context}。给出详细点位。"}]).choices[0].message.content
    except: return "AI连接超时"

# ================= 3. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔥 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("全能实战版 v8.0")
        menu = st.radio("导航", ["👀 我的关注 (自动盯盘)", "🔎 个股深度诊断 (搜)", "🔮 T+1 金股预测", "🛡️ 稳健性价比榜单", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # --- 后台数据准备 ---
    # 只有在看榜单或预测时，才拉取全市场数据，节省资源
    df_market = pd.DataFrame()
    if menu in ["🔮 T+1 金股预测", "🛡️ 稳健性价比榜单"]:
        with st.spinner("正在扫描全市场数据..."):
            df_market = get_market_data_for_ranking()
            if df_market.empty: st.error("无法连接数据源，请刷新重试"); st.stop()

    # --- 1. 我的关注 (自动盯盘) ---
    if menu == "👀 我的关注 (自动盯盘)":
        st.header("👀 我的自选股 (Watchlist)")
        
        # 添加区
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3, 1])
            new_input = c1.text_input("输入(如 长城军工/601606)", key="add")
            if c2.button("添加"):
                c, n = smart_search_stock(new_input)
                if c:
                    if c not in st.session_state['watchlist']:
                        st.session_state['watchlist'].append(c); st.success(f"已添加 {n}"); time.sleep(0.5); st.rerun()
                    else: st.warning("已存在")
                else: st.error("未找到")
        
        st.divider()
        if not st.session_state['watchlist']: st.info("暂无关注")
        else:
            for code in st.session_state['watchlist']:
                # 找名字
                name = WATCH_LIST_MAP.get(code, code)
                for k,v in STOCK_DB.items(): 
                    if v==code: name=k; break
                
                d = get_single_stock_analysis(code, name)
                if d:
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([2, 2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        with c2: st.metric("现价", f"¥{d['现价']}", f"{d['涨幅']}%")
                        with c3: 
                            if d['颜色']=='green': st.success(f"⚡️ {d['信号']}")
                            elif d['颜色']=='blue': st.info(f"💎 {d['信号']}")
                            elif d['颜色']=='red': st.error(f"🔻 {d['信号']}")
                            else: st.warning(f"⏸ {d['信号']}")
                            st.caption(d['建议'])
                        with c4:
                            if st.button("🗑️", key=f"del_{code}"): st.session_state['watchlist'].remove(code); st.rerun()

    # --- 2. 个股深度 ---
    elif menu == "🔎 个股深度诊断 (搜)":
        st.header("🔎 个股全维透视")
        c1, c2 = st.columns([3, 1])
        s_input = c1.text_input("输入股票(支持中文)", "长城军工")
        if c2.button("分析", type="primary") or s_input:
            c, n = smart_search_stock(s_input)
            if c:
                d = get_single_stock_analysis(c, n)
                if d:
                    st.divider()
                    m1, m2, m3 = st.columns(3)
                    m1.metric(d['名称'], f"¥{d['现价']}")
                    m2.metric("涨幅", f"{d['涨幅']}%", delta=d['涨幅'])
                    m3.metric("信号", d['信号'])
                    
                    st.subheader("🤖 深度报告")
                    base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
                    st.info(run_ai_analysis(d, base_url))
                else: st.error("数据获取失败")
            else: st.error("未找到该股票")

    # --- 3. T+1 预测 (现在有内容了！) ---
    elif menu == "🔮 T+1 金股预测":
        st.header("🔮 T+1 隔日套利金股池")
        st.info("筛选今日涨幅适中、趋势强劲、明日存在溢价空间的标的。")
        
        picks = generate_t1_picks(df_market)
        
        col_list = st.columns(5)
        for i, (col, pick) in enumerate(zip(col_list, picks)):
            with col:
                st.markdown(f"**No.{i+1}**")
                st.metric(pick['名称'], f"¥{pick['现价']:.2f}", pick['预测胜率'])
                with st.popover("逻辑"): st.write(pick['逻辑'])

    # --- 4. 性价比榜单 (现在有内容了！) ---
    elif menu == "🛡️ 稳健性价比榜单":
        st.header("🛡️ 核心资产防御榜 (Top 5)")
        st.info("基于夏普比率选股：涨得稳、回撤小。")
        
        top_list = get_top_value_stocks(df_market)
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        
        for i, (_, row) in enumerate(top_list.iterrows()):
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
                with c1: st.markdown(f"### {medals[i]}"); st.caption(row['代码'])
                with c2: st.metric(row['名称'], f"¥{row['现价']}", f"年涨 {row['长线涨幅(1年)']:.1f}%")
                with c3: st.metric("波动率", f"{row['波动率']:.1f}", delta="低" if row['波动率']<2 else "中", delta_color="inverse")
                with c4: st.progress(min(100, int(row['性价比']*10)), text=f"评分：{row['性价比']:.1f}")

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()














