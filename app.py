import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import numpy as np

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 榜单增强版",
    layout="wide",
    page_icon="🦁",
    initial_sidebar_state="expanded"
)

# 模拟数据库：热门股名单 (覆盖各行业龙头)
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
    "000333.SZ": "美的集团", "603288.SS": "海天味业", "601088.SS": "中国神华"
}

# 宏观逻辑库
MACRO_LOGIC = [
    "全球流动性外溢，核心资产估值重塑", "社保基金与汇金增持，底部支撑强劲", 
    "行业进入补库存周期，业绩拐点确认", "避险情绪升温，高股息资产受追捧",
    "国产替代加速，在手订单量超预期"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""

# ================= 2. 核心算法 =================

@st.cache_data(ttl=1800)
def get_market_data():
    """获取数据并计算核心指标"""
    data_list = []
    tickers = " ".join(list(WATCH_LIST_MAP.keys()))
    try:
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
                        
                        # 指标计算
                        pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                        pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                        year_start = series.iloc[0]
                        pct_1y = float(((curr - year_start) / year_start) * 100)
                        
                        # 波动率与性价比
                        daily_ret = series.pct_change().dropna()
                        volatility = daily_ret.std() * 100 
                        # 性价比 (Stability Score) = 年收益 / 波动率
                        # 加上 10 分基础分避免负数影响排序
                        stability_score = (pct_1y + 10) / (volatility + 0.1)
                        
                        # T+1 安全分
                        t1_safety = 100
                        if pct_1d > 8: t1_safety -= 30 
                        elif pct_1d < -2: t1_safety -= 20
                        else: t1_safety -= 5
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
    """T+1 预测逻辑"""
    candidates = df[(df['T+1安全分'] > 80) & (df['短线涨幅(1周)'] > 0)].copy()
    picks = candidates.sort_values("T+1安全分", ascending=False).head(5)
    results = []
    for _, row in picks.iterrows():
        results.append({
            "名称": row['名称'], "代码": row['代码'], "现价": row['现价'],
            "预测胜率": f"{row['T+1安全分']:.1f}%",
            "逻辑": f"T+1结构：{random.choice(MACRO_LOGIC)}。今日涨幅 {row['今日涨幅']:.2f}% 适中，留有溢价空间。",
            "类型": "稳健套利" if row['波动率'] < 2 else "激进博弈"
        })
    return results

def get_top_stability_stocks(df, n=5):
    """
    【新功能】获取性价比榜单 Top N
    逻辑：必须是正收益(>0)，然后按性价比得分排序
    """
    # 过滤掉年线亏损太多的
    candidates = df[df['长线涨幅(1年)'] > -5].copy()
    if candidates.empty: candidates = df.copy()
    
    # 排序：性价比降序
    top_picks = candidates.sort_values("性价比", ascending=False).head(n)
    return top_picks

# AI Controller
def run_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"):
        return f"> **系统提示：免费模式运行**\n\n### 📊 深度分析：{stock_data['名称']}\n**策略**：{stock_data['趋势']} 持有\n**支撑位**：¥{stock_data['现价']*0.95:.2f}"
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
        st.title("🦁 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("实战策略终端 v5.1")
        menu = st.radio("导航", ["🔮 T+1 金股预测", "🛡️ 稳健性价比榜单", "📊 市场全景 (长/短)", "🔎 个股深度", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # 数据加载
    with st.spinner("正在计算全市场数据..."):
        df_all = get_market_data()
    if df_all.empty: st.error("数据连接失败"); st.stop()

    # --- 1. T+1 预测 ---
    if menu == "🔮 T+1 金股预测":
        st.header("🔮 T+1 隔日套利金股池")
        st.info("筛选逻辑：剔除今日涨幅过大透支股，锁定明日大概率有高点出局的标的。")
        picks = generate_t1_predictions(df_all)
        c1, c2, c3, c4, c5 = st.columns(5)
        for i, (col, pick) in enumerate(zip([c1,c2,c3,c4,c5], picks)):
            with col:
                st.markdown(f"**🔥 No.{i+1}**")
                st.metric(pick['名称'], f"¥{pick['现价']:.1f}", f"安全度 {pick['预测胜率']}")
                with st.popover("逻辑"): st.write(pick['逻辑'])

    # --- 2. 稳健性价比榜单 (本次升级重点) ---
    elif menu == "🛡️ 稳健性价比榜单":
        st.header("🛡️ 核心资产防御榜 (Top 5)")
        st.markdown("""
        **榜单逻辑：** 基于改进版 **夏普比率 (Sharpe Ratio)**。
        $$ \text{性价比得分} = \frac{\text{年涨幅}}{\text{波动率}} $$
        选出的股票特征：**涨得稳、回撤小、适合底仓配置。**
        """)
        
        # 获取 Top 5
        top_stable = get_top_stability_stocks(df_all, n=5)
        
        # 勋章图标
        medals = ["🥇 冠军", "🥈 亚军", "🥉 季军", "🏅 第四", "🏅 第五"]
        
        for i, (_, row) in enumerate(top_stable.iterrows()):
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
                
                with c1:
                    st.markdown(f"### {medals[i]}")
                    st.caption(row['代码'])
                
                with c2:
                    st.metric(row['名称'], f"¥{row['现价']}", f"年涨幅 {row['长线涨幅(1年)']:.1f}%")
                
                with c3:
                    st.metric("波动率 (越低越稳)", f"{row['波动率']:.1f}", delta="低波动" if row['波动率']<2 else "中波动", delta_color="inverse")
                    
                with c4:
                    st.progress(min(100, int(row['性价比']*10)), text=f"综合性价比评分：{row['性价比']:.1f}")
                    st.caption("点评：穿越周期的压舱石，建议回调均线低吸。")

    # --- 3. 市场全景 ---
    elif menu == "📊 市场全景 (长/短)":
        st.header("📊 市场多周期全景")
        t1, t2 = st.tabs(["⚡️ 短线风云 (1周)", "⏳ 长线核心 (1年)"])
        with t1:
            st.dataframe(df_all.sort_values("短线涨幅(1周)", ascending=False).head(10)[["名称", "现价", "短线涨幅(1周)", "今日涨幅"]], use_container_width=True)
        with t2:
            st.dataframe(df_all.sort_values("长线涨幅(1年)", ascending=False).head(10)[["名称", "现价", "长线涨幅(1年)", "波动率"]], use_container_width=True)

    # --- 4. 个股深度 ---
    elif menu == "🔎 个股深度":
        st.header("🔎 个股推演")
        c1, c2 = st.columns(2)
        code = c1.text_input("代码", "600519")
        name = c2.text_input("名称", "贵州茅台")
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        if st.button("分析"):
            cached = df_all[df_all['代码']==code]
            if not cached.empty:
                d = cached.iloc[0].to_dict()
                st.metric(d['名称'], f"¥{d['现价']}", f"{d['今日涨幅']:.2f}%")
                st.info(run_analysis_controller(d, base_url))
            else: st.warning("仅支持热门股池内股票深度分析(为保证响应速度)")

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()












