import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
from datetime import datetime

# --- 页面配置 ---
st.set_page_config(page_title="A股罗盘 (海外加速版)", layout="wide", page_icon="🚀")

# --- 核心函数：获取股价 (使用 yfinance，海外访问稳定) ---
def get_stock_data_yf(symbol_code):
    """
    yfinance 需要后缀: 沪市 .SS, 深市 .SZ
    例如: 600519 -> 600519.SS
    """
    suffix = ".SS" if symbol_code.startswith("6") else ".SZ"
    ticker_str = symbol_code + suffix
    
    try:
        stock = yf.Ticker(ticker_str)
        # 获取今日数据
        hist = stock.history(period="1mo") # 获取近1个月
        if hist.empty:
            return None, None
            
        current_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        change_pct = ((current_price - prev_close) / prev_close) * 100
        
        info = {
            "name": symbol_code, # yfinance 获取中文名较难，暂时用代码代替
            "price": round(current_price, 2),
            "pct": round(change_pct, 2),
            "hist": hist
        }
        return info, hist
    except Exception as e:
        return None, None

# --- 核心函数：获取新闻 (使用简单爬虫，绕过 AkShare 版本问题) ---
@st.cache_data(ttl=600)
def get_simple_news():
    # 备用方案：直接请求新浪财经 API (比 AkShare 更轻量)
    url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=10&page=1"
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        r = requests.get(url, headers=headers, timeout=5)
        if r.status_code == 200:
            data = r.json()
            if 'result' in data and 'data' in data['result']:
                news_list = []
                for item in data['result']['data']:
                    news_list.append({
                        "time": datetime.fromtimestamp(int(item['ctime'])).strftime('%H:%M'),
                        "title": item['title'],
                        "url": item['url']
                    })
                return news_list
        return []
    except:
        return []

# --- 界面逻辑 ---

st.title("🚀 A股罗盘 (海外云端版)")
st.caption("数据源: Yahoo Finance (股价) + 新浪财经 (新闻)")

# 1. 宏观/指数看板
col1, col2, col3 = st.columns(3)
# 上证指数在 Yahoo 代码是 000001.SS
sh_info, _ = get_stock_data_yf("000001")

with col1:
    if sh_info:
        st.metric("上证指数", sh_info['price'], f"{sh_info['pct']}%")
    else:
        st.metric("上证指数", "加载中...", "---")

with col2:
    # 茅台作为风向标
    mt_info, _ = get_stock_data_yf("600519")
    if mt_info:
        st.metric("贵州茅台 (风向标)", mt_info['price'], f"{mt_info['pct']}%")

with col3:
    st.info("ℹ️ 说明：此版本专为 Streamlit Cloud 优化，解决了IP拦截和库版本不兼容问题。")

st.divider()

# 2. 功能分区
tab1, tab2 = st.tabs(["🔥 实时消息面", "📈 个股K线分析"])

with tab1:
    st.subheader("最新财经快讯")
    if st.button("刷新新闻"):
        st.cache_data.clear()
        st.rerun()
        
    news = get_simple_news()
    if news:
        for n in news:
            with st.container(border=True):
                st.markdown(f"**{n['time']}** | [{n['title']}]({n['url']})")
    else:
        st.warning("新闻加载失败，可能是网络暂时波动。")

with tab2:
    st.subheader("个股查询")
    code_input = st.text_input("输入6位代码 (如 300750)", "300750")
    
    if code_input:
        with st.spinner("正在从 Yahoo 全球节点拉取数据..."):
            info, hist_data = get_stock_data_yf(code_input)
        
        if info:
            c1, c2 = st.columns([1, 3])
            with c1:
                st.metric(f"代码: {code_input}", info['price'], f"{info['pct']}%")
                if info['pct'] > 0:
                    st.success("✅ 趋势向上")
                else:
                    st.error("📉 趋势向下")
            
            with c2:
                # 画K线图
                fig = go.Figure(data=[go.Candlestick(x=hist_data.index,
                                open=hist_data['Open'],
                                high=hist_data['High'],
                                low=hist_data['Low'],
                                close=hist_data['Close'])])
                fig.update_layout(height=350, margin=dict(l=0,r=0,t=0,b=0))
                st.plotly_chart(fig, use_container_width=True)
                
            st.write("注：Yahoo Finance 数据可能有 15 分钟延迟。")
        else:
            st.error("未找到该股票数据，请检查代码是否正确。")


