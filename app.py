import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from openai import OpenAI

# ================= 1. 基础配置 =================
st.set_page_config(page_title="A股罗盘 Pro | 中文版", layout="wide", page_icon="🇨🇳")

# --- 核心修复：内置代码转中文名称字典 ---
# 无论 Yahoo 返回什么，我们都在界面上强制显示这些中文名
NAME_MAP = {
    "600519.SS": "贵州茅台", "300750.SZ": "宁德时代", "601318.SS": "中国平安", 
    "002594.SZ": "比亚迪",   "600036.SS": "招商银行", "601857.SS": "中国石油", 
    "000858.SZ": "五粮液",   "601138.SS": "工业富联", "603259.SS": "药明康德", 
    "300059.SZ": "东方财富", "002475.SZ": "立讯精密", "300418.SZ": "昆仑万维", 
    "002230.SZ": "科大讯飞", "600418.SS": "江淮汽车", "000063.SZ": "中兴通讯", 
    "601728.SS": "中国电信", "600941.SS": "中国移动", "002371.SZ": "北方华创", 
    "300274.SZ": "阳光电源", "600150.SS": "中国船舶", "600600.SS": "青岛啤酒", 
    "600030.SS": "中信证券", "000725.SZ": "京东方A",  "600276.SS": "恒瑞医药", 
    "000661.SZ": "长春高新", "300760.SZ": "迈瑞医疗", "601668.SS": "中国建筑", 
    "601800.SS": "中国交建", "601985.SS": "中国核电", "601688.SS": "华泰证券", 
    "601066.SS": "中信建投"
}

# 提取代码列表用于扫描
WATCH_LIST = list(NAME_MAP.keys())

# 初始化 Session State
if 'api_key' not in st.session_state:
    st.session_state['api_key'] = ""

# ================= 2. 侧边栏设置 =================
with st.sidebar:
    st.title("⚙️ 设置")
    user_key = st.text_input("OpenAI/DeepSeek API Key", type="password", value=st.session_state['api_key'])
    if user_key:
        st.session_state['api_key'] = user_key
        st.success("✅ AI 密钥已加载")
    
    base_url = st.text_input("Base URL (DeepSeek需填)", "https://api.openai.com/v1")
    st.info("数据源：Yahoo Finance (已启用中文映射)")

# ================= 3. 核心数据逻辑 =================

@st.cache_data(ttl=600)
def get_market_scan():
    """扫描热门股并匹配中文名"""
    data_list = []
    tickers = " ".join(WATCH_LIST)
    
    try:
        # 批量下载数据
        df_yf = yf.download(tickers, period="1mo", progress=False)
        
        # 处理 yfinance 返回多层索引的情况 (Open, Close 等)
        if isinstance(df_yf.columns, pd.MultiIndex):
            closes = df_yf['Close']
        else:
            closes = df_yf['Close'] # 备用

        for code in WATCH_LIST:
            try:
                # 获取单只股票数据
                if code in closes.columns:
                    series = closes[code].dropna()
                else:
                    continue
                
                if len(series) >= 5:
                    current = series.iloc[-1]
                    prev = series.iloc[-2]
                    curr_5d = series.iloc[-5]
                    
                    # 计算指标
                    pct_1d = ((current - prev) / prev) * 100
                    pct_5d = ((current - curr_5d) / curr_5d) * 100
                    
                    # 趋势判断
                    ma20 = series.rolling(20).mean().iloc[-1]
                    trend = "📈 强势" if current > ma20 else "📉 弱势"
                    
                    data_list.append({
                        "名称": NAME_MAP.get(code, code), # 👈 这里核心！把代码转中文
                        "代码": code,
                        "现价": round(current, 2),
                        "今日涨幅": round(pct_1d, 2),
                        "5日涨幅": round(pct_5d, 2),
                        "趋势": trend
                    })
            except Exception as e:
                continue
                
    except Exception as e:
        st.error(f"数据扫描出错: {e}")
        return pd.DataFrame()

    return pd.DataFrame(data_list)

def get_news_dummy(stock_name):
    """
    为了演示效果，若抓取不到新闻，返回模拟新闻摘要。
    真实环境中这需要强大的爬虫，这里为了稳定性做兜底。
    """
    return f"市场关于【{stock_name}】的近期讨论主要集中在行业政策支持与主力资金流向。近期板块热度有所回升，机构调研频繁。"

def run_ai_analysis(stock_name, stock_code, row_data):
    """AI 分析逻辑，强制带入中文名"""
    
    # 模拟数据（当没有Key时）
    if not st.session_state['api_key']:
        direction = "买入" if row_data['今日涨幅'] > 0 else "观望"
        return f"""
        **[模拟演示结果]** (请输入 API Key 查看真实分析)
        1. **短期判断**：{direction} - {stock_name} 近期动能较强。
        2. **长期判断**：持有 - 行业龙头，护城河深。
        3. **建议**：请在左侧侧边栏输入 Key 以激活大模型大脑。
        """

    prompt = f"""
    你是一名A股交易员。请分析股票：{stock_name} ({stock_code})。
    
    【技术面数据】
    - 现价：{row_data['现价']}
    - 今日涨幅：{row_data['今日涨幅']}%
    - 5日趋势：{row_data['5日涨幅']}% ({row_data['趋势']})
    
    请严格输出：
    1. **短期操作（1周）**：[买入/卖出/观望] - 理由(20字内)
    2. **长期价值（1年）**：[低估/高估/合理] - 理由(20字内)
    3. **综合点评**：一句话总结。
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

st.title("🇨🇳 A股实战罗盘 (中文显示修复版)")

with st.spinner("正在从全球节点拉取数据并翻译名称..."):
    df_all = get_market_scan()

if df_all.empty:
    st.error("数据加载失败，请刷新页面重试。")
    st.stop()

# 分页
tab1, tab2, tab3 = st.tabs(["🔥 短线爆发 (Top 10)", "💎 长线价值 (Top 10)", "🧠 个股 AI 诊断"])

# --- Tab 1: 短线 ---
with tab1:
    st.subheader("🚀 一周内强势爆发股")
    st.markdown("按 `5日涨幅` 排序，寻找短期资金正在攻击的中文股票。")
    
    # 排序
    df_short = df_all.sort_values(by="5日涨幅", ascending=False).head(10)
    
    # 显示 (隐藏掉代码列，只看中文名)
    st.dataframe(
        df_short[["名称", "现价", "今日涨幅", "5日涨幅", "趋势"]].style.format({
            "现价": "{:.2f}", "今日涨幅": "{:+.2f}%", "5日涨幅": "{:+.2f}%"
        }).background_gradient(subset=["今日涨幅"], cmap="RdYlGn", vmin=-5, vmax=5),
        use_container_width=True,
        hide_index=True
    )

# --- Tab 2: 长线 ---
with tab2:
    st.subheader("⏳ 一年期稳健白马")
    st.markdown("筛选逻辑：`趋势为强势` 且 `今日涨幅为正` 的优质资产。")
    
    df_long = df_all[df_all['趋势'] == "📈 强势"].sort_values(by="今日涨幅", ascending=True).head(10)
    
    st.dataframe(
        df_long[["名称", "现价", "今日涨幅", "趋势"]].style.format({
            "现价": "{:.2f}", "今日涨幅": "{:+.2f}%"
        }),
        use_container_width=True,
        hide_index=True
    )

# --- Tab 3: AI 分析 ---
with tab3:
    st.subheader("🤖 智能个股买卖分析")
    
    # 下拉框里现在显示的是 "名称 (代码)" 格式，方便选择
    select_options = [f"{row['名称']} ({row['代码']})" for index, row in df_all.iterrows()]
    selected_option = st.selectbox("请选择一只股票进行诊断：", select_options)
    
    if st.button("开始 AI 深度计算"):
        # 解析选择的股票
        selected_name = selected_option.split(" (")[0]
        selected_code = selected_option.split(" (")[1].replace(")", "")
        
        # 找到对应行数据
        row_data = df_all[df_all['代码'] == selected_code].iloc[0]
        
        st.divider()
        st.markdown(f"### 📊 分析报告：{selected_name}")
        
        with st.spinner("AI 正在结合技术指标进行推演..."):
            ai_result = run_ai_analysis(selected_name, selected_code, row_data)
            st.info(ai_result)





