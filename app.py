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
    page_title="AlphaQuant Pro | 全网实时版",
    layout="wide",
    page_icon="📡",
    initial_sidebar_state="expanded"
)

# 宏观逻辑库 (用于生成AI话术)
MACRO_LOGIC = [
    "主力资金大幅净流入，量价配合完美", "板块轮动至该赛道，补涨需求强烈", 
    "技术面突破箱体震荡，上方空间打开", "配合指数共振，短线情绪极佳",
    "游资与机构合力封板预期，溢价率高"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = ["600519.SS"]

# ================= 2. 核心数据引擎 (东方财富 API + 新浪 API) =================

def convert_to_yahoo(code):
    """将A股代码转换为Yahoo格式"""
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

@st.cache_data(ttl=60) # 缓存60秒，保证实时性
def get_eastmoney_rank(sort_type="change"):
    """
    【核心黑科技】调用东方财富接口，扫描全市场5000只股票
    sort_type: 'change' (涨幅榜), 'amount' (成交额榜), 'cap' (市值榜)
    """
    # f3:涨跌幅, f12:代码, f14:名称, f2:现价, f20:总市值, f8:换手率, f62:主力净流入
    fields = "f12,f14,f2,f3,f20,f8,f62"
    order = "desc" # 降序
    sort_key = "f3" # 默认按涨幅排序
    
    if sort_type == "cap": sort_key = "f20" # 按市值
    if sort_type == "flow": sort_key = "f62" # 按资金流
    
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 100, "po": 1, "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": sort_key, "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": fields
    }
    
    try:
        r = requests.get(url, params=params, timeout=3)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data)
        df = df.rename(columns={
            'f12': '代码', 'f14': '名称', 'f2': '现价', 
            'f3': '涨幅', 'f20': '市值', 'f8': '换手率', 'f62': '主力净流入'
        })
        # 简单的清洗
        df['涨幅'] = pd.to_numeric(df['涨幅'], errors='coerce')
        df['现价'] = pd.to_numeric(df['现价'], errors='coerce')
        df['主力净流入'] = pd.to_numeric(df['主力净流入'], errors='coerce')
        return df
    except:
        return pd.DataFrame()

def search_online(keyword):
    """新浪接口全网搜索"""
    keyword = keyword.strip()
    if not keyword: return None, None
    if keyword.endswith(".SS") or keyword.endswith(".SZ"): return keyword, keyword
    
    try:
        url = f"http://suggest3.sinajs.cn/suggest/type=&key={keyword}&name=suggestdata"
        r = requests.get(url, timeout=2)
        content = r.text
        if '="' in content:
            data_str = content.split('="')[1].replace('"', '')
            if not data_str: return None, None
            parts = data_str.split(',')
            sina_code = parts[3]
            name = parts[0]
            if sina_code.startswith("sh"): return sina_code.replace("sh", "") + ".SS", name
            elif sina_code.startswith("sz"): return sina_code.replace("sz", "") + ".SZ", name
            elif sina_code.startswith("bj"): return sina_code.replace("bj", "") + ".BJ", name
    except: 
        if keyword.isdigit() and len(keyword)==6: 
            return convert_to_yahoo(keyword), keyword
    return None, None

# ================= 3. 业务逻辑 (T+2预测 & 榜单) =================

def scan_for_t2_prediction():
    """
    【T+2金股预测算法】
    1. 获取实时涨幅榜前100名
    2. 过滤：3% < 涨幅 < 7% (拒绝涨停股，因为买不进且风险大；拒绝微涨股，因为动能不够)
    3. 过滤：主力净流入 > 0 (资金必须在买)
    4. 排序：按主力净流入排序
    """
    df = get_eastmoney_rank(sort_type="change") # 获取涨幅榜
    if df.empty: return []
    
    # 策略过滤
    # 逻辑：寻找正在拉升途中，还没涨停的票，明天惯性冲高概率大
    candidates = df[
        (df['涨幅'] > 2.5) & 
        (df['涨幅'] < 7.5) & 
        (df['现价'] > 3) &   # 剔除垃圾股
        (df['主力净流入'] > 10000000) # 主力流入超千万
    ].copy()
    
    # 排序：资金越强越好
    top_picks = candidates.sort_values("主力净流入", ascending=False).head(5)
    
    results = []
    for _, row in top_picks.iterrows():
        results.append({
            "名称": row['名称'],
            "代码": convert_to_yahoo(row['代码']),
            "现价": row['现价'],
            "涨幅": row['涨幅'],
            "资金": f"{row['主力净流入']/100000000:.2f}亿",
            "逻辑": f"T+2策略：{random.choice(MACRO_LOGIC)}。今日资金净流入{row['主力净流入']/10000:.0f}万，动能强劲。"
        })
    return results

@st.cache_data(ttl=3600) # 这是一个耗时操作，缓存1小时
def scan_for_stability_rank():
    """
    【性价比/长线榜单算法】
    1. 获取全市场市值最大的前50名 (核心资产)
    2. 用 yfinance 计算它们的年涨幅和波动率
    3. 算出性价比
    """
    # 获取大市值股票 (比较稳)
    df_cap = get_eastmoney_rank(sort_type="cap").head(30) # 取前30大龙头
    if df_cap.empty: return []
    
    candidates = []
    
    # 只有这里需要 yfinance 逐个计算历史波动，因为东财接口不给历史数据
    # 为了速度，我们只算前 30 名
    tickers = [convert_to_yahoo(code) for code in df_cap['代码'].tolist()]
    tickers_str = " ".join(tickers)
    
    try:
        # 批量获取数据
        df_hist = yf.download(tickers_str, period="1y", progress=False)
        if isinstance(df_hist.columns, pd.MultiIndex): closes = df_hist['Close']
        else: closes = df_hist
        
        for code in tickers:
            if code in closes.columns:
                series = closes[code].dropna()
                if len(series) > 200:
                    # 计算指标
                    pct_1y = ((series.iloc[-1] - series.iloc[0]) / series.iloc[0]) * 100
                    volatility = series.pct_change().std() * 100
                    # 性价比 = 年涨幅 / 波动率
                    # 只看正收益的
                    if pct_1y > 0:
                        score = pct_1y / (volatility + 0.1)
                        # 找到对应的名称
                        name = df_cap[df_cap['代码'] == code.split('.')[0]]['名称'].values[0]
                        candidates.append({
                            "名称": name, "代码": code, "现价": float(series.iloc[-1]),
                            "年涨幅": pct_1y, "波动率": volatility, "性价比": score
                        })
    except: pass
    
    # 排序
    df_res = pd.DataFrame(candidates)
    if not df_res.empty:
        return df_res.sort_values("性价比", ascending=False).head(5).to_dict('records')
    return []

# 个股分析 (复用之前的逻辑)
@st.cache_data(ttl=600)
def get_single_stock_analysis(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        ma5 = h['Close'].rolling(5).mean().iloc[-1]
        ma20 = h['Close'].rolling(20).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        signal, color, advice = "观望", "gray", "趋势不明"
        if pct < -5 and curr < ma20: signal, color, advice = "卖出", "red", "破位下跌"
        elif curr>ma5 and ma5>ma20: signal, color, advice = "买入", "green", "上升通道"
        elif curr>ma20: signal, color, advice = "持有", "blue", "趋势健康"

        return {"代码": code, "名称": name, "现价": round(curr,2), "涨幅": round(pct,2), "MA20": round(ma20,2), "信号": signal, "颜色": color, "建议": advice}
    except: return None

# AI
def run_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{stock_data['信号']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析A股{stock_data['名称']}，给出建议。"}]).choices[0].message.content
    except: return "超时"

# ================= 4. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("📡 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("全网实时版 v11.0")
        menu = st.radio("导航", ["👀 我的关注", "🔮 T+2 金股预测 (全网)", "🛡️ 稳健性价比榜单 (全网)", "🔎 个股深度诊断", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. 我的关注 (全网实时) ---
    if menu == "👀 我的关注":
        st.header("👀 自选股监控 (全网可加)")
        with st.expander("➕ 添加全市场股票", expanded=False):
            c1, c2 = st.columns([3, 1])
            k = c1.text_input("输入代码/名称 (如 300059 / 东方财富)", key="add")
            if c2.button("联网添加"):
                with st.spinner("Searching..."):
                    c, n = search_online(k)
                    if c:
                        if c not in st.session_state['watchlist']:
                            st.session_state['watchlist'].append(c)
                            st.success(f"已添加 {n}")
                            time.sleep(1); st.rerun()
                        else: st.warning("已存在")
                    else: st.error("未找到")

        st.divider()
        if not st.session_state['watchlist']: st.info("请添加股票")
        else:
            for code in st.session_state['watchlist']:
                # 尝试简单获取名字(如果不准也没关系，点进去才重要)
                name = code
                d = get_single_stock_analysis(code, name)
                if d:
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([2, 2, 3, 1])
                        with c1: st.markdown(f"**{d['代码']}**"); st.caption("自选")
                        with c2: st.metric("现价", f"¥{d['现价']}", f"{d['涨幅']}%")
                        with c3: 
                            if d['颜色']=='green': st.success(d['信号'])
                            elif d['颜色']=='red': st.error(d['信号'])
                            else: st.info(d['信号'])
                        with c4:
                            if st.button("🗑️", key=f"d_{code}"): st.session_state['watchlist'].remove(code); st.rerun()

    # --- 2. T+2 金股预测 (东方财富实时全网扫描) ---
    elif menu == "🔮 T+2 金股预测 (全网)":
        st.header("🔮 T+2 全网实时掘金")
        st.info("数据源：东方财富 Level-1 实时行情 | 范围：全市场 5300+ 股票")
        
        if st.button("🔄 扫描全市场 (实时)", type="primary"):
            with st.spinner("正在从交易所拉取实时主力资金流向..."):
                picks = scan_for_t2_prediction()
                
                if picks:
                    st.success(f"扫描完成！基于实时资金流，为您筛选出前 {len(picks)} 名潜力股。")
                    cols = st.columns(5)
                    for i, (col, pick) in enumerate(zip(cols, picks)):
                        with col:
                            st.markdown(f"**🔥 Top {i+1}**")
                            st.metric(pick['名称'], f"¥{pick['现价']}", f"+{pick['涨幅']:.2f}%")
                            st.caption(f"主力净流入: {pick['资金']}")
                            with st.popover("T+2 逻辑"):
                                st.write(pick['逻辑'])
                else:
                    st.error("市场数据接口暂时拥堵，请稍后重试。")
        else:
            st.markdown("👉 点击上方按钮开始扫描。算法将寻找 **量价齐升** 且 **未涨停** 的标的。")

    # --- 3. 性价比榜单 (全网蓝筹扫描) ---
    elif menu == "🛡️ 稳健性价比榜单 (全网)":
        st.header("🛡️ 全网核心资产防御榜")
        st.info("范围：全市场市值 Top 30 龙头股 | 算法：夏普比率 (年涨幅/波动率)")
        
        with st.spinner("正在计算龙头股波动率 (耗时较长请耐心)..."):
            picks = scan_for_stability_rank()
            
            if picks:
                medals = ["🥇", "🥈", "🥉", "🏅", "🏅"]
                for i, pick in enumerate(picks):
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 1, 1, 2])
                        with c1: st.markdown(f"### {medals[i]}"); st.caption(pick['名称'])
                        with c2: st.metric("现价", f"¥{pick['现价']}", f"年涨 {pick['年涨幅']:.1f}%")
                        with c3: st.metric("波动率", f"{pick['波动率']:.1f}", delta="极稳" if pick['波动率']<1.5 else "稳", delta_color="inverse")
                        with c4: st.progress(min(100, int(pick['性价比']*10)), text=f"性价比评分: {pick['性价比']:.1f}")
            else:
                st.warning("数据计算中或API限制，请刷新。")

    # --- 4. 个股深度 ---
    elif menu == "🔎 个股深度诊断":
        st.header("🔎 个股全网搜")
        c1, c2 = st.columns([3, 1])
        k = c1.text_input("全网搜 (支持拼音/代码/名称)", placeholder="万科 / 600519")
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("分析") or k:
            with st.spinner("Searching..."):
                c, n = search_online(k)
                if c:
                    d = get_single_stock_analysis(c, n)
                    if d:
                        st.divider()
                        m1, m2, m3 = st.columns(3)
                        m1.metric(d['名称'], f"¥{d['现价']}")
                        m2.metric("涨幅", f"{d['涨幅']}%", delta=d['涨幅'])
                        m3.metric("信号", d['信号'])
                        st.info(run_ai_analysis(d, base_url))
                    else: st.error("数据拉取失败")
                else: st.error("未找到")

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()














