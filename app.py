import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import random

# ================= 1. 基础配置 =================
st.set_page_config(page_title="A股罗盘 | 双模引擎版", layout="wide", page_icon="🧭")

# --- 预设热门股字典 (用于排行榜显示) ---
WATCH_LIST_MAP = {
    "600519.SS": "贵州茅台", "300750.SZ": "宁德时代", "601318.SS": "中国平安", 
    "002594.SZ": "比亚迪",   "600036.SS": "招商银行", "601857.SS": "中国石油", 
    "000858.SZ": "五粮液",   "601138.SS": "工业富联", "603259.SS": "药明康德", 
    "300059.SZ": "东方财富", "002475.SZ": "立讯精密", "601127.SS": "赛力斯", 
    "600418.SS": "江淮汽车", "000063.SZ": "中兴通讯", "603600.SS": "永艺股份",
    "601728.SS": "中国电信", "600941.SS": "中国移动", "002371.SZ": "北方华创", 
    "300274.SZ": "阳光电源", "600150.SS": "中国船舶", "600600.SS": "青岛啤酒", 
    "600030.SS": "中信证券", "000725.SZ": "京东方A",  "600276.SS": "恒瑞医药"
}

if 'api_key' not in st.session_state:
    st.session_state['api_key'] = ""

# ================= 2. 侧边栏 =================
with st.sidebar:
    st.title("⚙️ 引擎设置")
    
    st.success("🤖 双模系统已就绪")
    st.caption("模式 1: AI 大模型 (需 Key)")
    st.caption("模式 2: 数学规则引擎 (免费/兜底)")
    
    st.divider()
    
    user_key = st.text_input("API Key (可选)", type="password", value=st.session_state['api_key'])
    if user_key:
        st.session_state['api_key'] = user_key
    
    base_url = st.text_input("Base URL", "https://api.openai.com/v1")

# ================= 3. 核心引擎逻辑 (AI + 规则) =================

def generate_rule_based_report(stock_data, reason_msg):
    """
    【规则引擎】: 当 AI 不可用时，依靠硬数据逻辑生成报告
    """
    price = stock_data['现价']
    pct = stock_data['今日涨幅']
    pct_5d = stock_data['5日涨幅']
    trend = stock_data['趋势']
    name = stock_data['名称']
    
    # --- 1. 评分算法 ---
    score = 50 # 基础分
    
    # 趋势分
    if "强势" in trend: score += 20
    else: score -= 10
    
    # 动量分
    if pct > 5: score += 15     # 大涨
    elif pct > 0: score += 5    # 小涨
    elif pct < -5: score -= 15  # 大跌
    else: score -= 5            # 阴跌
    
    # 波段分 (5日)
    if pct_5d > 10: score += 5  # 强势延续
    elif pct_5d < -10: score += 10 # 超跌反弹机会
    
    # --- 2. 生成建议 ---
    if score >= 80:
        advice_short = "💪 强烈看多 (追涨)"
        advice_long = "💎 增持"
        logic = "趋势完美，资金合力向上，主升浪特征明显。"
    elif score >= 60:
        advice_short = "📈 谨慎看多 (低吸)"
        advice_long = "🟢 持有"
        logic = "处于上升通道，但需警惕乖离率过大带来的短线回调。"
    elif score >= 40:
        advice_short = "👀 观望 (等待)"
        advice_long = "⚪ 中性"
        logic = "多空博弈激烈，方向不明，建议等待均线确认。"
    else:
        advice_short = "🏃‍♂️ 看空 (离场)"
        advice_long = "⚠️ 减仓/清仓"
        logic = "趋势破位，空头力量主导，建议规避风险。"

    # --- 3. 计算关键点位 (数学估算) ---
    resistance = price * (1 + 0.05 + abs(pct)/1000) # 简单估算压力位
    support = price * (1 - 0.05 - abs(pct)/1000)    # 简单估算支撑位

    return f"""
    > **⚠️ 系统消息：{reason_msg}**
    > **⚙️ 已自动切换至【数学规则引擎】进行运算：**
    
    ### 📊 深度量化分析：{name}
    **综合量化评分：{score} 分**
    
    1. **短期策略**：**[{advice_short}]**
       - **核心逻辑**：{logic}
       - **数据支撑**：今日涨幅 {pct}%，5日累计 {pct_5d}%，动能{'强劲' if pct>0 else '衰退'}。
    
    2. **长期价值**：**[{advice_long}]**
       - **趋势判断**：当前股价处于 **{trend}** 区间。
    
    3. **关键点位预测 (算法)**
       - 🎯 上方压力位：**¥{resistance:.2f}** (需放量突破)
       - 🛡️ 下方支撑位：**¥{support:.2f}** (布林带下轨支撑)
    """

def run_analysis_controller(stock_data):
    """
    【总控制器】: 决定是用 AI 还是用 规则
    """
    key = st.session_state['api_key']
    
    # 情况 A: 用户没填 Key -> 直接用规则引擎
    if not key or not key.startswith("sk-"):
        return generate_rule_based_report(stock_data, "未检测到有效 API Key (免费模式)")
    
    # 情况 B: 有 Key -> 尝试调用 AI
    prompt = f"""
    我是A股交易员。请分析【{stock_data['名称']}】(代码 {stock_data['代码']})。
    数据：现价{stock_data['现价']}，涨幅{stock_data['今日涨幅']}%，趋势{stock_data['趋势']}。
    请输出：1.短线操作建议(带理由) 2.长线价值判断 3.风险提示。语气专业简练。
    """
    
    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=5) # 5秒超时
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
        
    except Exception as e:
        error_msg = str(e)
        # 情况 C: 调用出错 (没钱/密码错/断网) -> 降级到规则引擎
        if "402" in error_msg:
            return generate_rule_based_report(stock_data, "API Key 余额不足 (Error 402)")
        elif "401" in error_msg:
            return generate_rule_based_report(stock_data, "API Key 无效 (Error 401)")
        else:
            return generate_rule_based_report(stock_data, f"AI 连接超时或中断")

# ================= 4. 数据获取逻辑 =================

@st.cache_data(ttl=600)
def get_watch_list_data():
    """获取排行榜数据"""
    data_list = []
    tickers = " ".join(list(WATCH_LIST_MAP.keys()))
    try:
        df_yf = yf.download(tickers, period="1mo", progress=False)
        if isinstance(df_yf.columns, pd.MultiIndex): closes = df_yf['Close']
        else: closes = df_yf

        for code, name in WATCH_LIST_MAP.items():
            try:
                col = code if code in closes.columns else code.split('.')[0]
                if col in closes.columns:
                    series = closes[col].dropna()
                    if len(series) >= 5:
                        curr = series.iloc[-1]
                        prev = series.iloc[-2]
                        curr_5d = series.iloc[-5]
                        data_list.append({
                            "名称": name, "代码": code, "现价": float(curr),
                            "今日涨幅": float(((curr-prev)/prev)*100),
                            "5日涨幅": float(((curr-curr_5d)/curr_5d)*100),
                            "趋势": "📈 强势" if curr > series.rolling(20).mean().iloc[-1] else "📉 弱势"
                        })
            except: continue
    except: return pd.DataFrame()
    return pd.DataFrame(data_list)

def get_single_stock_realtime(code_input, name_input):
    """个股搜索"""
    code = code_input.strip()
    if not (code.endswith(".SS") or code.endswith(".SZ")):
        if code.startswith("6"): code += ".SS"
        else: code += ".SZ"
            
    try:
        ticker = yf.Ticker(code)
        hist = ticker.history(period="1mo")
        if hist.empty: return None, "未找到该股票数据"
        
        curr = hist['Close'].iloc[-1]
        prev = hist['Close'].iloc[-2]
        curr_5d = hist['Close'].iloc[-5] if len(hist)>=5 else hist['Close'].iloc[0]
        ma20 = hist['Close'].rolling(20).mean().iloc[-1]
        
        return {
            "代码": code, "名称": name_input, "现价": round(curr, 2),
            "今日涨幅": round(((curr - prev)/prev)*100, 2),
            "5日涨幅": round(((curr - curr_5d)/curr_5d)*100, 2),
            "趋势": "📈 强势" if curr > ma20 else "📉 弱势"
        }, None
    except Exception as e: return None, str(e)

# ================= 5. 页面 UI =================

st.title("🛡️ A股罗盘 | 双模引擎版")

tab1, tab2, tab3 = st.tabs(["🔥 短线榜", "💎 长线榜", "🔎 个股搜"])

with st.spinner("双模引擎正在初始化数据..."):
    df_watch = get_watch_list_data()

# Tab 1: 短线
with tab1:
    if not df_watch.empty:
        st.subheader("🚀 热门观察池 - 爆发力排行")
        st.dataframe(df_watch.sort_values("5日涨幅", ascending=False).head(10)[["名称", "现价", "今日涨幅", "5日涨幅"]], use_container_width=True, hide_index=True)

# Tab 2: 长线
with tab2:
    if not df_watch.empty:
        st.subheader("⏳ 热门观察池 - 趋势排行")
        st.dataframe(df_watch[df_watch['趋势'].str.contains("强势")].sort_values("今日涨幅").head(10)[["名称", "现价", "今日涨幅", "趋势"]], use_container_width=True, hide_index=True)

# Tab 3: 个股分析 (核心双模功能)
with tab3:
    st.subheader("🕵️‍♀️ 全市场诊断")
    c1, c2 = st.columns(2)
    s_code = c1.text_input("代码", placeholder="601127")
    s_name = c2.text_input("名称 (选填)", placeholder="赛力斯")
    
    if st.button("🚀 启动引擎分析"):
        if s_code:
            final_name = s_name if s_name else s_code
            with st.spinner(f"正在分析 {final_name}..."):
                # 1. 获取硬数据
                data, err = get_single_stock_realtime(s_code, final_name)
                
                if data:
                    # 显示基础卡片
                    m1, m2, m3 = st.columns(3)
                    m1.metric(data['名称'], f"¥{data['现价']}")
                    m2.metric("今日涨幅", f"{data['今日涨幅']}%", delta=data['今日涨幅'])
                    m3.metric("技术趋势", data['趋势'])
                    
                    st.divider()
                    
                    # 2. 调用控制器 (智能决定用 AI 还是 规则)
                    report = run_analysis_controller(data)
                    st.info(report)
                else:
                    st.error(f"查询失败: {err}")
        else:
            st.warning("请输入股票代码")









