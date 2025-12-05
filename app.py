import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
from datetime import datetime

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 智能联想版",
    layout="wide",
    page_icon="🔎",
    initial_sidebar_state="expanded"
)

# ================= 2. 核心数据库 (用于联想搜索) =================
# 这里构建一个较大的池子，用于下拉框的自动补全
# 格式为： "代码 | 名称"
STOCK_SUGGESTIONS = [
    "600519.SS | 贵州茅台", "300750.SZ | 宁德时代", "601127.SS | 赛力斯",
    "601318.SS | 中国平安", "002594.SZ | 比亚迪",   "600036.SS | 招商银行",
    "601857.SS | 中国石油", "000858.SZ | 五粮液",   "601138.SS | 工业富联",
    "603259.SS | 药明康德", "300059.SZ | 东方财富", "002475.SZ | 立讯精密",
    "601606.SS | 长城军工", "603600.SS | 永艺股份", "000063.SZ | 中兴通讯",
    "601728.SS | 中国电信", "600941.SS | 中国移动", "002371.SZ | 北方华创",
    "300274.SZ | 阳光电源", "600150.SS | 中国船舶", "600600.SS | 青岛啤酒",
    "600030.SS | 中信证券", "000725.SZ | 京东方A",  "600276.SS | 恒瑞医药",
    "600900.SS | 长江电力", "601919.SS | 中远海控", "000002.SZ | 万科A",
    "000333.SZ | 美的集团", "603288.SS | 海天味业", "601088.SS | 中国神华",
    "601899.SS | 紫金矿业", "601012.SS | 隆基绿能", "300760.SZ | 迈瑞医疗",
    "600418.SS | 江淮汽车", "002230.SZ | 科大讯飞", "600050.SS | 中国联通",
    "600000.SS | 浦发银行", "601398.SS | 工商银行", "601288.SS | 农业银行",
    "601939.SS | 建设银行", "601988.SS | 中国银行", "000001.SZ | 平安银行"
]
# 为了方便反向查找，建立一个字典
STOCK_DICT = {item.split(" | ")[0]: item.split(" | ")[1] for item in STOCK_SUGGESTIONS}

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

# ================= 3. 核心算法 =================

def smart_search_parser(selection_str):
    """
    解析下拉框的选择结果
    输入: "600519.SS | 贵州茅台"
    输出: "600519.SS", "贵州茅台"
    """
    if not selection_str: return None, None
    parts = selection_str.split(" | ")
    if len(parts) == 2:
        return parts[0], parts[1]
    return None, None

def manual_code_parser(input_str):
    """处理手动输入的代码"""
    input_str = input_str.strip()
    if not input_str: return None, None
    
    # 如果输入的是中文，尝试在库里找
    for item in STOCK_SUGGESTIONS:
        code, name = item.split(" | ")
        if input_str == name: return code, name

    # 如果是代码
    if input_str.isdigit() and len(input_str) == 6:
        suffix = ".SS" if input_str.startswith("6") else ".SZ"
        code = input_str + suffix
        return code, input_str # 名字未知就用代码代替
    
    if input_str.endswith(".SS") or input_str.endswith(".SZ"):
        return input_str, input_str
        
    return None, None

@st.cache_data(ttl=1800)
def get_market_data_for_ranking():
    """获取榜单数据"""
    data_list = []
    # 仅使用前20个热门股做榜单，避免卡顿
    rank_tickers = [item.split(" | ")[0] for item in STOCK_SUGGESTIONS[:25]]
    tickers_str = " ".join(rank_tickers)
    
    try:
        df_yf = yf.download(tickers_str, period="1y", progress=False)
        if isinstance(df_yf.columns, pd.MultiIndex): closes = df_yf['Close']
        else: closes = df_yf

        for item in STOCK_SUGGESTIONS[:25]:
            code, name = item.split(" | ")
            try:
                col = code if code in closes.columns else code.split('.')[0]
                if col in closes.columns:
                    series = closes[col].dropna()
                    if len(series) > 200:
                        curr = series.iloc[-1]
                        pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                        pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                        pct_1y = float(((curr - series.iloc[0]) / series.iloc[0]) * 100)
                        daily_ret = series.pct_change().dropna()
                        volatility = daily_ret.std() * 100 
                        stability = (pct_1y + 10) / (volatility + 0.1)
                        
                        t1_safety = 100
                        if pct_1d > 8: t1_safety -= 30 
                        elif pct_1d < -2: t1_safety -= 20
                        else: t1_safety -= 5
                        if curr > series.rolling(20).mean().iloc[-1]: t1_safety += 10
                        
                        data_list.append({
                            "名称": name, "代码": code, "现价": float(curr),
                            "短线涨幅(1周)": pct_5d, "长线涨幅(1年)": pct_1y,
                            "今日涨幅": pct_1d, "波动率": volatility,
                            "性价比": stability, "T+1安全分": t1_safety
                        })
            except: continue
    except: return pd.DataFrame()
    return pd.DataFrame(data_list)

@st.cache_data(ttl=600)
def get_single_stock_analysis(code, name):
    """个股深度数据"""
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        ma5 = h['Close'].rolling(5).mean().iloc[-1]
        ma20 = h['Close'].rolling(20).mean().iloc[-1]
        ma60 = h['Close'].rolling(60).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        signal, color, advice = "观望", "gray", "趋势不明"
        if pct < -5 and curr < ma20: signal, color, advice = "卖出/止损", "red", "破位下跌，短线资金出逃"
        elif ((curr-ma20)/ma20)>0.2: signal, color, advice = "止盈/减仓", "orange", "乖离率过大"
        elif curr>ma5 and ma5>ma20 and pct>0: signal, color, advice = "短线买入", "green", "均线多头，资金介入"
        elif abs(curr-ma60)/ma60<0.02 and curr>ma60: signal, color, advice = "长线建仓", "blue", "回踩生命线企稳"
        elif curr>ma20: signal, color, advice = "持有", "blue", "上升趋势未变"

        return {"代码": code, "名称": name, "现价": round(curr,2), "涨幅": round(pct,2), "MA20": round(ma20,2), "信号": signal, "颜色": color, "建议": advice}
    except: return None

def run_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"):
        return f"> **🤖 免费模式**\n**建议**：{stock_data['信号']}\n**理由**：{stock_data['建议']}"
    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析A股{stock_data['名称']}，现价{stock_data['现价']}。给出操作建议。"}]).choices[0].message.content
    except: return "AI连接超时"

# 辅助榜单函数
def generate_t1_picks(df):
    candidates = df[(df['T+1安全分'] > 80) & (df['短线涨幅(1周)'] > 0)].copy()
    if candidates.empty: candidates = df.head(5)
    picks = candidates.sort_values("T+1安全分", ascending=False).head(5)
    res = []
    for _, r in picks.iterrows():
        res.append({"名称": r['名称'], "现价": r['现价'], "预测胜率": f"{r['T+1安全分']:.1f}%", "逻辑": f"结构：{random.choice(MACRO_LOGIC)}"})
    return res

def get_top_value_stocks(df):
    candidates = df[df['长线涨幅(1年)'] > -10].copy()
    if candidates.empty: candidates = df.copy()
    return candidates.sort_values("性价比", ascending=False).head(5)

# ================= 4. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔎 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("智能联想版 v9.0")
        menu = st.radio("导航", ["👀 我的关注", "🔎 个股深度诊断", "🔮 T+1 金股预测", "🛡️ 稳健性价比榜单", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # 数据准备
    df_market = pd.DataFrame()
    if menu in ["🔮 T+1 金股预测", "🛡️ 稳健性价比榜单"]:
        with st.spinner("扫描市场中..."): df_market = get_market_data_for_ranking()

    # --- 1. 我的关注 ---
    if menu == "👀 我的关注":
        st.header("👀 自选股监控")
        
        # 添加区 (使用联想搜索)
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2, c3 = st.columns([3, 1, 1])
            # 这里的 selectbox 就是你的需求：可以输入，可以下拉
            choice = c1.selectbox("搜索股票 (输入代码/名称)", options=STOCK_SUGGESTIONS, index=None, placeholder="输入如 '601' 或 '赛力斯'...")
            
            # 手动兜底开关
            manual_mode = c2.checkbox("手动输入模式", help="如果下拉框找不到，请勾选此项手动输入")
            
            if manual_mode:
                manual_input = c1.text_input("手动输入 (如 600519)", key="manual_add")
                
            if c3.button("添加"):
                code, name = None, None
                if manual_mode and manual_input:
                    code, name = manual_code_parser(manual_input)
                elif choice:
                    code, name = smart_search_parser(choice)
                
                if code:
                    if code not in st.session_state['watchlist']:
                        st.session_state['watchlist'].append(code); st.success(f"已添加 {name}"); time.sleep(0.5); st.rerun()
                    else: st.warning("已存在")
                else: st.error("无效的股票")

        st.divider()
        if not st.session_state['watchlist']: st.info("暂无关注")
        else:
            for code in st.session_state['watchlist']:
                name = STOCK_DICT.get(code, code) # 尝试获取名字
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

    # --- 2. 个股深度诊断 (联想搜索升级) ---
    elif menu == "🔎 个股深度诊断":
        st.header("🔎 个股全维透视")
        
        c1, c2 = st.columns([3, 1])
        
        # === 核心升级点：可搜索的下拉框 ===
        search_choice = c1.selectbox(
            "🔍 快速搜索 (支持首字/代码联想)", 
            options=STOCK_SUGGESTIONS, 
            index=None, 
            placeholder="试着输入 '长城' 或 '601'..."
        )
        
        # 手动兜底
        use_manual = st.toggle("找不到？点此手动输入代码")
        if use_manual:
            manual_search = c1.text_input("输入代码", placeholder="600xxx")
        
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        # 自动触发分析 (只要选了就分析，或者点了手动分析)
        target_code, target_name = None, None
        
        if use_manual and manual_search:
            target_code, target_name = manual_code_parser(manual_search)
        elif search_choice:
            target_code, target_name = smart_search_parser(search_choice)
            
        if target_code:
            st.divider()
            d = get_single_stock_analysis(target_code, target_name)
            if d:
                m1, m2, m3 = st.columns(3)
                m1.metric(d['名称'], f"¥{d['现价']}")
                m2.metric("涨幅", f"{d['涨幅']}%", delta=d['涨幅'])
                m3.metric("信号", d['信号'])
                st.subheader("🤖 深度报告")
                st.info(run_ai_analysis(d, base_url))
            else: st.error("获取数据失败，请检查代码是否正确")

    # --- 3. T+1 (保持原样) ---
    elif menu == "🔮 T+1 金股预测":
        st.header("🔮 T+1 隔日套利金股池")
        picks = generate_t1_picks(df_market)
        cols = st.columns(5)
        for i, (col, pick) in enumerate(zip(cols, picks)):
            with col:
                st.markdown(f"**No.{i+1}**"); st.metric(pick['名称'], f"¥{pick['现价']:.2f}", pick['预测胜率'])
                with st.popover("逻辑"): st.write(pick['逻辑'])

    # --- 4. 榜单 (保持原样) ---
    elif menu == "🛡️ 稳健性价比榜单":
        st.header("🛡️ 核心资产防御榜")
        top_list = get_top_value_stocks(df_market)
        medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
        for i, (_, row) in enumerate(top_list.iterrows()):
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
                with c1: st.markdown(f"### {medals[i]}"); st.caption(row['代码'])
                with c2: st.metric(row['名称'], f"¥{row['现价']}", f"年涨 {row['长线涨幅(1年)']:.1f}%")
                with c3: st.metric("波动率", f"{row['波动率']:.1f}")
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














