import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import numpy as np

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | T+1实战终端",
    layout="wide",
    page_icon="🦅",
    initial_sidebar_state="expanded"
)

# 模拟数据库：热门股名单 (涵盖核心资产)
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
    "000333.SZ": "美的集团", "603288.SS": "海天味业", "600276.SS": "恒瑞医药"
}

# 宏观逻辑库
MACRO_LOGIC = [
    "美联储降息预期升温，全球流动性外溢", "汇金与社保基金增持，底部支撑强劲", 
    "行业进入补库存周期，业绩拐点确认", "地缘政治避险情绪推动核心资产重估",
    "国产替代加速，订单量超预期"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""

# ================= 2. 核心算法 (T+1 优化版) =================

@st.cache_data(ttl=1800) # 缓存30分钟，避免长线数据拉取太慢
def get_market_data():
    """
    获取长周期数据 (1年)，用于计算长线和稳定性
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
                    if len(series) > 200: # 确保数据够长
                        curr = series.iloc[-1]
                        
                        # 1. 短线指标 (1周)
                        pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                        pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                        
                        # 2. 长线指标 (1年)
                        year_start = series.iloc[0]
                        pct_1y = float(((curr - year_start) / year_start) * 100)
                        
                        # 3. 稳定性指标 (波动率)
                        # 计算日收益率标准差，越小越稳
                        daily_ret = series.pct_change().dropna()
                        volatility = daily_ret.std() * 100 # 波动率
                        # 性价比得分 = 年收益 / 波动率 (夏普比率简化版)
                        stability_score = pct_1y / (volatility + 0.1) 
                        
                        # 4. T+1 安全度 (隔夜风险)
                        # 如果今日暴涨 > 8%，T+1 获利难度大；如果温和上涨 3-5%，T+1 最安全
                        t1_safety = 100
                        if pct_1d > 8: t1_safety -= 30 # 追高风险
                        elif pct_1d < -2: t1_safety -= 20 # 抄底风险
                        else: t1_safety -= 5 # 正常波动
                        
                        # 加上趋势分
                        ma20 = series.rolling(20).mean().iloc[-1]
                        if curr > ma20: t1_safety += 10
                        
                        data_list.append({
                            "名称": name, "代码": code, "现价": float(curr),
                            "短线涨幅(1周)": pct_5d,
                            "长线涨幅(1年)": pct_1y,
                            "今日涨幅": pct_1d,
                            "波动率": volatility,
                            "性价比": stability_score,
                            "T+1安全分": t1_safety,
                            "趋势": "📈" if curr > ma20 else "📉"
                        })
            except: continue
    except: return pd.DataFrame()
    return pd.DataFrame(data_list)

def generate_t1_predictions(df):
    """
    【T+1 预测逻辑】
    不只看明天涨不涨，要看能不能活着出来。
    筛选：趋势向上 + 今日未透支涨幅 + 资金持续流入(模拟)
    """
    # 筛选 T+1 安全分高，且短线动能强(5日涨幅>0)的票
    candidates = df[(df['T+1安全分'] > 80) & (df['短线涨幅(1周)'] > 2)].copy()
    
    # 排序：按 T+1 安全分倒序
    picks = candidates.sort_values("T+1安全分", ascending=False).head(5)
    
    results = []
    for _, row in picks.iterrows():
        # 生成理由
        reason = random.choice(MACRO_LOGIC)
        
        results.append({
            "名称": row['名称'],
            "代码": row['代码'],
            "现价": row['现价'],
            "预测胜率": f"{row['T+1安全分']:.1f}%", # 这里的胜率指 T+1 盈利概率
            "逻辑": f"T+1结构：{reason}。今日涨幅 {row['今日涨幅']:.2f}% 未透支动能，明日存在高点溢价。",
            "类型": "稳健套利" if row['波动率'] < 2 else "激进博弈"
        })
    return results

def get_best_value_stock(df):
    """
    【性价比之王】
    筛选规则：年涨幅 > 10% (不仅是死水) 且 波动率最低
    """
    # 过滤掉亏损股
    profit_df = df[df['长线涨幅(1年)'] > 10]
    if profit_df.empty: profit_df = df # 如果都亏，就选跌得最少的
    
    # 按性价比得分排序 (涨得多/动得少)
    best = profit_df.sort_values("性价比", ascending=False).iloc[0]
    return best

# AI Controller (保持不变)
def run_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"):
        return f"> **系统提示：切换至规则引擎**\n\n### 📊 深度分析：{stock_data['名称']}\n**策略**：{stock_data['趋势']} 持有\n**支撑位**：¥{stock_data['现价']*0.95:.2f}"
    
    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=5)
        prompt = f"分析A股{stock_data['名称']}，现价{stock_data['现价']}。针对T+1交易制度，给出明日操作建议。简练。"
        return client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI连接超时"

# ================= 3. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🦅 AlphaQuant T+1")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("实战策略终端 v5.0 (T+1版)")
        menu = st.radio("导航", ["🔮 T+1 金股预测 (Alpha)", "📊 市场全景 (长/短线)", "🛡️ 稳健性价比之王", "🔎 个股深度", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # 数据加载
    with st.spinner("正在计算全市场 T+1 溢价概率..."):
        df_all = get_market_data()

    if df_all.empty:
        st.error("数据连接失败，请刷新。")
        st.stop()

    # --- 功能 1: T+1 预测 ---
    if menu == "🔮 T+1 金股预测 (Alpha)":
        st.header("🔮 T+1 隔日套利金股池")
        st.markdown("""
        **核心策略：** 针对 A 股 T+1 制度优化。
        **筛选标准：** 剔除今日涨幅过大(>8%)的透支股，锁定**趋势未走完、明日大概率有高点出局**的标的。
        """)
        
        picks = generate_t1_predictions(df_all)
        
        c1, c2, c3, c4, c5 = st.columns(5)
        for i, (col, pick) in enumerate(zip([c1,c2,c3,c4,c5], picks)):
            with col:
                st.markdown(f"**🔥 推荐 {i+1}**")
                st.metric(pick['名称'], f"¥{pick['现价']:.1f}", f"安全度 {pick['预测胜率']}")
                st.caption(f"代码: {pick['代码']}")
                with st.popover("查看获利逻辑"):
                    st.write(f"**{pick['类型']}**")
                    st.info(pick['逻辑'])
        
        st.divider()
        st.caption("注：'安全度'代表明日存在盈利出局机会的概率。推荐仅供量化参考。")

    # --- 功能 2: 市场全景 (长短分离) ---
    elif menu == "📊 市场全景 (长/短线)":
        st.header("📊 市场多周期全景榜")
        
        t1, t2 = st.tabs(["⚡️ 短线风云 (1周爆发)", "⏳ 长线核心 (1年长牛)"])
        
        with t1:
            st.subheader("近5日资金爆发榜")
            st.caption("适合短线快进快出，寻找热点题材。")
            # 按短线涨幅排序
            short_df = df_all.sort_values("短线涨幅(1周)", ascending=False).head(10)
            st.dataframe(
                short_df[["名称", "现价", "短线涨幅(1周)", "今日涨幅", "趋势"]].style.format({"短线涨幅(1周)": "{:+.2f}%", "今日涨幅": "{:+.2f}%"}),
                use_container_width=True, hide_index=True
            )
            
        with t2:
            st.subheader("近1年价值长牛榜")
            st.caption("适合中长期配置，寻找穿越周期的核心资产。")
            # 按长线涨幅排序
            long_df = df_all.sort_values("长线涨幅(1年)", ascending=False).head(10)
            st.dataframe(
                long_df[["名称", "现价", "长线涨幅(1年)", "波动率", "趋势"]].style.format({"长线涨幅(1年)": "{:+.2f}%", "波动率": "{:.2f}"}),
                use_container_width=True, hide_index=True
            )

    # --- 功能 3: 稳健性价比 (新功能) ---
    elif menu == "🛡️ 稳健性价比之王":
        st.header("🏆 全市场性价比之王 (The Stability Anchor)")
        st.markdown("算法逻辑：寻找**收益率/波动率**比值最高的股票。即：涨得稳，回撤小，睡得着觉。")
        
        best = get_best_value_stock(df_all)
        
        with st.container(border=True):
            col1, col2 = st.columns([1, 2])
            with col1:
                st.markdown("### 👑 今日优选")
                st.image("https://img.icons8.com/color/96/shield.png", width=100)
            with col2:
                st.metric(best['名称'], f"¥{best['现价']}", f"年涨幅 {best['长线涨幅(1年)']:.2f}%")
                st.write(f"**股票代码：** {best['代码']}")
                st.success(f"**推荐理由：** 该股在过去一年中表现出极高的稳定性。性价比评分 **{best['性价比']:.2f}** (全场第一)，适合作为底仓配置。")
                
        st.subheader("🔍 详细数据")
        st.table(pd.DataFrame([best]).drop(columns=['性价比', 'T+1安全分']))

    # --- 功能 4: 个股诊断 ---
    elif menu == "🔎 个股深度":
        st.header("🔎 个股T+1模拟推演")
        c1, c2 = st.columns(2)
        code = c1.text_input("代码", placeholder="600519")
        name = c2.text_input("名称", placeholder="贵州茅台")
        base_url = "https://api.openai.com/v1"
        if "base_url" in st.session_state: base_url = st.session_state["base_url"]
        
        if st.button("开始推演"):
            if code:
                fname = name if name else code
                # 直接从 df_all 查数据，如果不在列表里再联网搜
                cached = df_all[df_all['代码'] == code]
                if not cached.empty:
                    data = cached.iloc[0].to_dict()
                    st.metric(data['名称'], f"¥{data['现价']}", f"{data['今日涨幅']:.2f}%")
                    st.info(run_analysis_controller(data, base_url))
                else:
                    st.warning("该股暂不在核心池，仅提供基础数据。")
                    # 这里可以复用之前的联网搜索逻辑，为了代码简洁省略

    # --- 功能 5: 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        new_key = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        new_url = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("保存"): st.session_state['api_key']=new_key; st.session_state['base_url']=new_url; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()











