import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI

# ================= 1. 基础配置 =================
st.set_page_config(page_title="A股罗盘 | 全市场搜索版", layout="wide", page_icon="🔍")

# --- 预设的热门股字典 (仅用于 Tab 1 和 Tab 2 的排行榜显示) ---
# 只有在这个列表里的股票才会出现在"短线/长线推荐"里，防止服务器卡死
WATCH_LIST_MAP = {
    "600519.SS": "贵州茅台", "300750.SZ": "宁德时代", "601318.SS": "中国平安", 
    "002594.SZ": "比亚迪",   "600036.SS": "招商银行", "601857.SS": "中国石油", 
    "000858.SZ": "五粮液",   "601138.SS": "工业富联", "603259.SS": "药明康德", 
    "300059.SZ": "东方财富", "002475.SZ": "立讯精密", "601127.SS": "赛力斯", # 你提到的
    "600418.SS": "江淮汽车", "000063.SZ": "中兴通讯", "603600.SS": "永艺股份", # 你提到的
    "601728.SS": "中国电信", "600941.SS": "中国移动", "002371.SZ": "北方华创", 
    "300274.SZ": "阳光电源", "600150.SS": "中国船舶", "600600.SS": "青岛啤酒", 
    "600030.SS": "中信证券", "000725.SZ": "京东方A",  "600276.SS": "恒瑞医药"
}

# 初始化 Session State
if 'api_key' not in st.session_state:
    st.session_state['api_key'] = ""

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.title("⚙️ 设置")
    user_key = st.text_input("OpenAI/DeepSeek API Key", type="password", value=st.session_state['api_key'])
    if user_key:
        st.session_state['api_key'] = user_key
        st.success("✅ 密钥已加载")
    
    base_url = st.text_input("Base URL", "https://api.openai.com/v1")
    st.divider()
    st.info("模式说明：\n1. 推荐榜单：基于预设热门股。\n2. 个股分析：支持全市场任意搜。")

# ================= 3. 数据获取逻辑 =================

@st.cache_data(ttl=600)
def get_watch_list_data():
    """获取预设列表的数据 (用于排行榜)"""
    data_list = []
    tickers = " ".join(list(WATCH_LIST_MAP.keys()))
    
    try:
        df_yf = yf.download(tickers, period="1mo", progress=False)
        # 处理多级索引
        if isinstance(df_yf.columns, pd.MultiIndex):
            closes = df_yf['Close']
        else:
            closes = df_yf

        for code, name in WATCH_LIST_MAP.items():
            try:
                # 模糊匹配列名
                col_name = code
                if code not in closes.columns:
                     if code.split('.')[0] in closes.columns:
                         col_name = code.split('.')[0]
                     else:
                         continue

                series = closes[col_name].dropna()
                if len(series) >= 5:
                    curr = series.iloc[-1]
                    prev = series.iloc[-2]
                    curr_5d = series.iloc[-5]
                    
                    data_list.append({
                        "名称": name,
                        "代码": code,
                        "现价": float(curr),
                        "今日涨幅": float(((curr - prev)/prev)*100),
                        "5日涨幅": float(((curr - curr_5d)/curr_5d)*100),
                        "趋势": "强势" if curr > series.rolling(20).mean().iloc[-1] else "弱势"
                    })
            except:
                continue
    except:
        return pd.DataFrame()
    
    return pd.DataFrame(data_list)

def get_single_stock_realtime(code_input, name_input="未知股票"):
    """
    获取任意单只股票的数据
    逻辑：自动判断后缀 .SS 还是 .SZ
    """
    code = code_input.strip()
    # 自动补充后缀
    if not (code.endswith(".SS") or code.endswith(".SZ")):
        if code.startswith("6"):
            code += ".SS" # 沪市
        elif code.startswith("0") or code.startswith("3"):
            code += ".SZ" # 深市
        elif code.startswith("4") or code.startswith("8"):
            code += ".BJ" # 北交所(Yfinance支持较差，尝试一下)
            
    try:
        ticker = yf.Ticker(code)
        hist = ticker.history(period="1mo")
        
        if hist.empty:
            return None, "未找到数据，请检查代码是否正确"
            
        curr = hist['Close'].iloc[-1]
        prev = hist['Close'].iloc[-2]
        curr_5d = hist['Close'].iloc[-5] if len(hist) >= 5 else hist['Close'].iloc[0]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        
        data = {
            "代码": code,
            "名称": name_input, # 用户自己输入的名称，或者默认
            "现价": round(curr, 2),
            "今日涨幅": round(((curr - prev)/prev)*100, 2),
            "5日涨幅": round(((curr - curr_5d)/curr_5d)*100, 2),
            "趋势": "📈 强势" if curr > ma20 else "📉 弱势"
        }
        return data, None
    except Exception as e:
        return None, str(e)

def run_ai_analysis(stock_data):
    """AI 分析"""
    if not st.session_state['api_key']:
        return "⚠️ 请先在侧边栏输入 API Key 才能进行 AI 深度分析。"
        
    prompt = f"""
    我是A股投资者。请分析【{stock_data['名称']}】(代码 {stock_data['代码']})。
    
    【实时技术指标】
    - 现价：{stock_data['现价']}
    - 今日涨幅：{stock_data['今日涨幅']}%
    - 5日累计：{stock_data['5日涨幅']}%
    - 均线趋势：{stock_data['趋势']}
    
    请输出决策简报：
    1. **短期博弈建议（1周）**：[买入/观望/止盈] - 理由...
    2. **长期价值建议（1年）**：[低估/合理/高估] - 理由...
    3. **关键点位预测**：上方压力位/下方支撑位（基于波动估算）。
    """
    try:
        client = OpenAI(api_key=st.session_state['api_key'], base_url=base_url)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 连接失败: {e}"

# ================= 4. 页面 UI =================

st.title("🔍 A股罗盘 | 自由搜索版")

tab1, tab2, tab3 = st.tabs(["🔥 热门股短线榜", "💎 热门股长线榜", "🔎 个股自由搜 (重点)"])

# --- 预设榜单逻辑 (Tab 1 & 2) ---
with st.spinner("正在刷新热门股池..."):
    df_watch = get_watch_list_data()

# Tab 1: 短线
with tab1:
    if not df_watch.empty:
        st.subheader("🚀 热门观察池 - 短线排行")
        st.dataframe(
            df_watch.sort_values("5日涨幅", ascending=False).head(10)[["名称", "代码", "现价", "今日涨幅", "5日涨幅"]],
            use_container_width=True, hide_index=True
        )
    else:
        st.warning("数据加载中或网络超时，请刷新。")

# Tab 2: 长线
with tab2:
    if not df_watch.empty:
        st.subheader("⏳ 热门观察池 - 趋势排行")
        st.dataframe(
            df_watch[df_watch['趋势']=="强势"].sort_values("今日涨幅").head(10)[["名称", "代码", "现价", "今日涨幅", "趋势"]],
            use_container_width=True, hide_index=True
        )

# --- Tab 3: 自由搜索 (解决你的问题) ---
with tab3:
    st.subheader("🕵️‍♀️ 全市场个股诊断")
    st.markdown("这里可以查询 **任意** A股代码，不再受限于预设列表。")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        # 输入框：让用户自由输入
        search_code = st.text_input("输入代码 (如 601127)", placeholder="例如：601127 或 603600")
    with col2:
        # 补充名称框：因为 Yahoo 不一定知道中文名，用户手动输入更准确
        search_name = st.text_input("股票名称 (辅助AI分析)", placeholder="例如：赛力斯")

    if st.button("🚀 开始分析"):
        if search_code:
            st.divider()
            # 1. 获取数据
            with st.spinner(f"正在全球节点搜索 {search_code} ..."):
                # 如果用户没填名称，默认叫“该股票”
                final_name = search_name if search_name else search_code
                stock_data, error = get_single_stock_realtime(search_code, final_name)
            
            if stock_data:
                # 2. 显示基本面卡片
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("股票名称", stock_data['名称'])
                c2.metric("最新价", f"¥{stock_data['现价']}")
                c3.metric("今日涨幅", f"{stock_data['今日涨幅']}%", delta=stock_data['今日涨幅'])
                c4.metric("趋势", stock_data['趋势'])
                
                # 3. AI 分析
                st.subheader(f"🤖 AI 深度报告: {stock_data['名称']}")
                with st.spinner("AI 正在计算策略..."):
                    report = run_ai_analysis(stock_data)
                    st.info(report)
            else:
                st.error(f"查询失败: {error}")
                st.caption("提示：请输入纯数字代码，如 601127。如果是港股请加后缀，如 0700.HK")
        else:
            st.warning("请输入代码！")







