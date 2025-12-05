import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import numpy as np

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 深度逻辑版",
    layout="wide",
    page_icon="🧠",
    initial_sidebar_state="expanded"
)

# --- 本地热门股字典 ---
HOT_STOCKS_SUGGESTIONS = [
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
    "600019.SS | 宝钢股份", "600048.SS | 保利发展", "601138.SS | 工业富联"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心算法 (硬核技术指标) =================

def calculate_technical_indicators(df):
    """
    【硬核计算】手动计算 RSI, MACD, 均线
    """
    # 1. 计算均线
    df['MA5'] = df['Close'].rolling(window=5).mean()
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA60'] = df['Close'].rolling(window=60).mean()
    
    # 2. 计算 RSI (14日)
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # 3. 计算 MACD (12, 26, 9)
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['DIF'] = exp1 - exp2
    df['DEA'] = df['DIF'].ewm(span=9, adjust=False).mean()
    df['MACD'] = (df['DIF'] - df['DEA']) * 2
    
    return df

@st.cache_data(ttl=600)
def get_deep_analysis_data(code, name):
    """
    【深度分析引擎】
    获取数据 -> 计算指标 -> 生成详细的买卖逻辑
    """
    try:
        t = yf.Ticker(code)
        h = t.history(period="1y") 
        if h.empty: return None
        
        # 计算技术指标
        df = calculate_technical_indicators(h)
        curr = df['Close'].iloc[-1]
        prev = df['Close'].iloc[-2]
        ma5 = df['MA5'].iloc[-1]
        ma20 = df['MA20'].iloc[-1]
        ma60 = df['MA60'].iloc[-1]
        rsi = df['RSI'].iloc[-1]
        macd = df['MACD'].iloc[-1]
        prev_macd = df['MACD'].iloc[-2]
        
        pct = ((curr - prev) / prev) * 100
        
        # --- 健全的信号判定逻辑 ---
        
        # 默认状态
        strategy = "观望 (Wait)"
        time_frame = "暂无机会"
        reason = "趋势不明显，建议空仓等待。"
        color = "gray"
        action_price = "N/A"
        
        # 1. 卖出信号 (优先级最高)
        if rsi > 80:
            strategy = "🔴 止盈卖出"
            time_frame = "立即操作"
            reason = f"RSI指标严重超买({rsi:.1f})，短线回调风险极大。"
            color = "red"
        elif curr < ma20 and pct < -3:
            strategy = "🔴 止损离场"
            time_frame = "立即操作"
            reason = "放量跌破20日支撑线，上升趋势破坏。"
            color = "red"
            
        # 2. 短线买入信号
        elif (macd > 0 and prev_macd < 0) or (curr > ma5 and ma5 > ma20 and rsi < 70):
            strategy = "⚡️ 短线做多"
            time_frame = "1-3天"
            reason = f"MACD金叉或均线多头排列，且RSI({rsi:.1f})健康，动能充足。"
            color = "green"
            action_price = f"回踩五日线 {ma5:.2f} 可买"
            
        # 3. 长线买入/持有信号
        elif curr > ma60 and abs(curr - ma60)/ma60 < 0.05:
            strategy = "💎 长线建仓"
            time_frame = "3-6个月"
            reason = "股价回踩60日生命线获得强支撑，是中长线黄金买点。"
            color = "blue"
            action_price = f"现价 {curr:.2f} 附近"
        elif curr > ma20:
            strategy = "🛡️ 继续持有"
            time_frame = "跟随趋势"
            reason = "上升通道保持良好，未触及止损位。"
            color = "blue"
            
        # 4. 超跌反弹
        elif rsi < 20:
            strategy = "🔥 超跌博弈"
            time_frame = "短线反弹"
            reason = f"RSI进入超卖区({rsi:.1f})，存在技术性反弹需求。"
            color = "orange"

        return {
            "代码": code, "名称": name, 
            "现价": round(curr, 2), "涨幅": round(pct, 2),
            "MA20": round(ma20, 2), "RSI": round(rsi, 1), "MACD": round(macd, 3),
            "策略": strategy, "周期": time_frame, "理由": reason, 
            "点位": action_price, "颜色": color
        }
    except Exception as e:
        return None

# 搜索辅助
def search_online(keyword):
    keyword = keyword.strip()
    if not keyword: return None, None
    for item in HOT_STOCKS_SUGGESTIONS:
        c, n = item.split(" | ")
        if keyword in n or keyword in c: return c, n
    # 纯代码回退
    if keyword.isdigit() and len(keyword)==6: 
        suffix = ".SS" if keyword.startswith("6") else ".SZ"
        return keyword+suffix, keyword
    return None, None

# AI 分析 (全面升级 Prompt)
def run_deep_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    
    # 构造非常详细的上下文
    context = f"""
    股票：{stock_data['名称']} ({stock_data['代码']})
    现价：{stock_data['现价']} (涨跌 {stock_data['涨幅']}%)
    技术指标：RSI={stock_data['RSI']}, MACD={stock_data['MACD']}, MA20={stock_data['MA20']}
    系统判定策略：{stock_data['策略']}
    系统判定理由：{stock_data['理由']}
    """
    
    if not key or not key.startswith("sk-"):
        return f"""
        > **🤖 免费模式分析报告**
        
        **1. 核心结论**：{stock_data['策略']}
        
        **2. 详细理由**：
        - **技术面**：{stock_data['理由']}
        - **资金面**：当前RSI为 {stock_data['RSI']}，MACD为 {stock_data['MACD']}，显示{ '多头' if stock_data['MACD']>0 else '空头' }动能。
        
        **3. 操作建议**：
        - **买入点**：{stock_data['点位']}
        - **止损位**：跌破 {stock_data['MA20']} 离场。
        - **周期**：建议按 {stock_data['周期']} 操作。
        """
        
    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=8)
        prompt = f"""
        你是一名华尔街资深交易员。请根据以下数据写一份深度分析报告：
        {context}
        
        要求输出格式如下：
        ### 1. 核心判断 (Buy/Sell/Hold)
        ### 2. 技术面逻辑 (详细解释RSI和均线形态)
        ### 3. 资金面与情绪 (模拟分析)
        ### 4. 实战交易计划 (明确给出买入价、止盈价、止损价)
        """
        return client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI连接超时，请检查网络。"

# ================= 3. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🧠 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("深度逻辑版 v13.0")
        menu = st.radio("导航", ["👀 我的关注 (智能管家)", "🔎 个股深度分析 (全面)", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. 我的关注 (健全的盯盘系统) ---
    if menu == "👀 我的关注 (智能管家)":
        st.header("👀 智能盯盘系统 (Smart Watchlist)")
        st.caption("实时计算 RSI/MACD/均线，给出明确的长短线操作指令。")
        
        # 添加
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3, 1])
            k = c1.selectbox("搜索", HOT_STOCKS_SUGGESTIONS, index=None, placeholder="选择或手动输入...")
            k_man = c1.text_input("手动输入代码", key="man")
            if c2.button("添加"):
                target = k if k else k_man
                if target:
                    if " | " in target: c, n = target.split(" | ")
                    else: c, n = search_online(target)
                    if c:
                        st.session_state['watchlist'].append({"code": c, "name": n})
                        st.success(f"已添加 {n}"); time.sleep(0.5); st.rerun()
        
        st.divider()
        
        # 列表展示
        if not st.session_state['watchlist']: st.info("暂无关注股票")
        else:
            for item in st.session_state['watchlist']:
                d = get_deep_analysis_data(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        # 第一行：基础信息
                        col_base, col_tech, col_strategy, col_action = st.columns([2, 2, 3, 1])
                        
                        with col_base:
                            st.markdown(f"### {d['名称']}")
                            st.caption(f"代码: {d['代码']}")
                            st.write(f"**现价: ¥{d['现价']}** ({d['涨幅']}%)")
                            
                        with col_tech:
                            # 显示硬核指标
                            st.write(f"RSI(14): **{d['RSI']}**")
                            st.write(f"MACD: **{d['MACD']}**")
                            st.write(f"均线: {'多头' if d['现价']>d['MA20'] else '空头'}")
                            
                        with col_strategy:
                            # 显示明确策略
                            if d['颜色'] == 'green':
                                st.success(f"**{d['策略']}** ({d['周期']})")
                            elif d['颜色'] == 'blue':
                                st.info(f"**{d['策略']}** ({d['周期']})")
                            elif d['颜色'] == 'red':
                                st.error(f"**{d['策略']}** ({d['周期']})")
                            else:
                                st.warning(f"**{d['策略']}** ({d['周期']})")
                            
                            st.caption(f"💡 理由: {d['理由']}")
                            
                        with col_action:
                            if st.button("❌", key=f"del_{item['code']}"):
                                st.session_state['watchlist'].remove(item)
                                st.rerun()

    # --- 2. 个股深度分析 (内容全面) ---
    elif menu == "🔎 个股深度分析 (全面)":
        st.header("🔎 全维深度诊断报告")
        
        c1, c2 = st.columns([3, 1])
        k = c1.selectbox("选择股票", HOT_STOCKS_SUGGESTIONS, index=None)
        k_man = c1.text_input("或手动输入代码", placeholder="600519")
        
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("生成深度报告", type="primary") or k or k_man:
            target = k if k else k_man
            if target:
                if " | " in target: c, n = target.split(" | ")
                else: c, n = search_online(target)
                
                if c:
                    with st.spinner(f"正在计算 {n} 的 RSI、MACD 及资金流向..."):
                        d = get_deep_analysis_data(c, n)
                        if d:
                            st.divider()
                            # 1. 仪表盘
                            m1, m2, m3, m4 = st.columns(4)
                            m1.metric("现价", f"¥{d['现价']}", f"{d['涨幅']}%")
                            m2.metric("RSI (相对强弱)", d['RSI'], delta="超买" if d['RSI']>70 else "正常")
                            m3.metric("MACD (趋势)", d['MACD'], delta_color="normal")
                            m4.metric("智能信号", d['策略'], delta_color="off")
                            
                            # 2. 详细分析区
                            cl, cr = st.columns([2, 1])
                            
                            with cl:
                                st.subheader("📝 AI 深度逻辑解析")
                                report = run_deep_ai_analysis(d, base_url)
                                st.markdown(report)
                                
                            with cr:
                                st.subheader("⚖️ 交易执行计划")
                                with st.container(border=True):
                                    st.write(f"**🎯 建议操作**: {d['策略']}")
                                    st.write(f"**⏳ 建议周期**: {d['周期']}")
                                    st.divider()
                                    st.write(f"**🟢 买入关注**: {d['点位']}")
                                    st.write(f"**🔴 止损参考**: 跌破 {d['MA20']}")
                                    st.caption(f"*注：止损位基于20日均线动态计算*")
                        else: st.error("数据拉取失败")
                else: st.error("未找到")

    # --- 3. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()















