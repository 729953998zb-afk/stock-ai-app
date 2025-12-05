
import streamlit as st
import pandas as pd
import yfinance as yf
import requests
from openai import OpenAI

# ================= 1. 基础配置 =================
st.set_page_config(page_title="A股罗盘 | 纯中文版", layout="wide", page_icon="🇨🇳")

# --- 核心：定义中文名映射 (这是我们的字典) ---
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
    "601066.SS": "中信建投", "600900.SS": "长江电力", "601919.SS": "中远海控"
}

# 提取代码列表
WATCH_LIST = list(NAME_MAP.keys())

# 初始化 API Key
if 'api_key' not in st.session_state:
    st.session_state['api_key'] = ""

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.title("⚙️ 系统设置")
    
    # API Key 输入
    user_key = st.text_input("输入 OpenAI/DeepSeek API Key", type="password", value=st.session_state['api_key'])
    if user_key:
        st.session_state['api_key'] = user_key
        st.success("✅ 密钥已加载")
    
    base_url = st.text_input("Base URL (DeepSeek必填)", "https://api.openai.com/v1")
    
    st.divider()
    if st.button("🗑️ 强制刷新数据"):
        st.cache_data.clear()
        st.rerun()

# ================= 3. 核心数据逻辑 (强制匹配中文) =================

@st.cache_data(ttl=300)
def get_data_force_chinese():
    """
    逻辑：先拿到数据，然后遍历 NAME_MAP 字典。
    只有字典里有的，才放进结果列表，并强行赋予中文名。
    """
    data_list = []
    tickers_str = " ".join(WATCH_LIST)
    
    try:
        # 下载数据
        df_yf = yf.download(tickers_str, period="1mo", progress=False)
        
        # 提取收盘价 (处理多层索引问题)
        if isinstance(df_yf.columns, pd.MultiIndex):
            try:
                closes = df_yf['Close']
            except:
                closes = df_yf
        else:
            closes = df_yf

        # 遍历我们的字典 (而不是遍历下载的数据)
        # 这样能保证：只要字典里有中文，结果里一定有中文
        for code, cn_name in NAME_MAP.items():
            try:
                # 尝试从下载的数据里找这个代码
                # 有时候 yfinance 返回的列名没有 .SS 或 .SZ，需要模糊匹配一下
                series = None
                if code in closes.columns:
                    series = closes[code]
                else:
                    # 尝试去掉后缀匹配 (比如 600519.SS -> 600519)
                    short_code = code.split('.')[0]
                    if short_code in closes.columns:
                         series = closes[short_code]
                
                # 如果找到了数据
                if series is not None and len(series.dropna()) >= 5:
                    series = series.dropna()
                    current = series.iloc[-1]
                    prev = series.iloc[-2]
                    curr_5d = series.iloc[-5]
                    
                    # 涨跌幅
                    pct_1d = ((current - prev) / prev) * 100
                    pct_5d = ((current - curr_5d) / curr_5d) * 100
                    
                    # 趋势
                    ma20 = series.rolling(20).mean().iloc[-1]
                    trend = "强势" if current > ma20 else "弱势"
                    
                    # 写入列表 (注意：'名称' 字段被写死为 cn_name)
                    data_list.append({
                        "中文名称": cn_name,  # 👈 核心：直接用字典里的中文
                        "股票代码": code,
                        "现价": float(current),
                        "今日涨幅": float(pct_1d),
                        "5日涨幅": float(pct_5d),
                        "趋势": trend
                    })
            except Exception as inner_e:
                continue # 某个股票失败不影响其他的
                
    except Exception as e:
        st.error(f"严重错误: {e}")
        return pd.DataFrame()

    return pd.DataFrame(data_list)

def run_ai_analysis(cn_name, code, row_data):
    """AI 分析函数"""
    if not st.session_state['api_key']:
        return f"请配置 API Key 以查看对【{cn_name}】的真实分析。当前模拟建议：{cn_name} 属于行业龙头，长期看好。"
    
    prompt = f"""
    分析A股股票：{cn_name} (代码 {code})。
    
    【实时数据】
    - 现价：{row_data['现价']:.2f}
    - 今日涨跌：{row_data['今日涨幅']:.2f}%
    - 5日趋势：{row_data['5日涨幅']:.2f}% ({row_data['趋势']})
    
    请输出简报（必须包含中文名）：
    1. **{cn_name}-短线建议**：[买入/卖出] 理由...
    2. **{cn_name}-长线建议**：[持有/减仓] 理由...
    3. **风险提示**：一句话。
    """
    try:
        client = OpenAI(api_key=st.session_state['api_key'], base_url=base_url)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 报错: {e}"

# ================= 4. 页面显示逻辑 =================

st.title("🇨🇳 A股实战罗盘 (中文强制修正版)")

with st.spinner("正在从全球节点同步数据并匹配中文名..."):
    df_all = get_data_force_chinese()

if df_all.empty:
    st.error("数据暂时无法获取，请点击侧边栏'强制刷新数据'按钮。")
    st.stop()

# 定义显示的列配置 (强制格式化)
column_config = {
    "中文名称": st.column_config.TextColumn("股票名称", help="公司中文全称"),
    "股票代码": st.column_config.TextColumn("代码"),
    "现价": st.column_config.NumberColumn("现价", format="¥%.2f"),
    "今日涨幅": st.column_config.NumberColumn("今日涨幅", format="%.2f%%"),
    "5日涨幅": st.column_config.NumberColumn("5日涨幅", format="%.2f%%"),
}

tab1, tab2, tab3 = st.tabs(["🔥 短线榜 (中文)", "💎 长线榜 (中文)", "🧠 AI 深度分析"])

# --- Tab 1: 短线 ---
with tab1:
    st.subheader("🚀 短期爆发力排行榜")
    # 排序
    df_short = df_all.sort_values(by="5日涨幅", ascending=False).head(10)
    # 强制重新排列列顺序，把中文名称放第一位
    df_display = df_short[["中文名称", "现价", "今日涨幅", "5日涨幅", "股票代码"]]
    
    st.dataframe(
        df_display,
        column_config=column_config,
        use_container_width=True,
        hide_index=True
    )

# --- Tab 2: 长线 ---
with tab2:
    st.subheader("⏳ 长期价值排行榜")
    # 筛选
    df_long = df_all[df_all['趋势']=="强势"].sort_values(by="今日涨幅", ascending=True).head(10)
    # 重新排列
    df_display_long = df_long[["中文名称", "现价", "今日涨幅", "趋势", "股票代码"]]
    
    st.dataframe(
        df_display_long,
        column_config=column_config,
        use_container_width=True,
        hide_index=True
    )

# --- Tab 3: AI 分析 ---
with tab3:
    st.subheader("🤖 智能个股诊断")
    
    # 制作下拉框选项：显示 "贵州茅台 (600519.SS)"
    select_map = {f"{row['中文名称']} ({row['股票代码']})": row['股票代码'] for index, row in df_all.iterrows()}
    selected_label = st.selectbox("请选择股票：", list(select_map.keys()))
    
    if st.button("开始 AI 分析"):
        # 找回数据
        selected_code = select_map[selected_label]
        # 从原始数据中提取中文名
        row_data = df_all[df_all['股票代码'] == selected_code].iloc[0]
        cn_name = row_data['中文名称']
        
        st.divider()
        st.markdown(f"### 📊 分析报告：{cn_name}")
        
        with st.spinner(f"AI 正在分析 {cn_name} 的技术面..."):
            ai_res = run_ai_analysis(cn_name, selected_code, row_data)
            st.info(ai_res)





