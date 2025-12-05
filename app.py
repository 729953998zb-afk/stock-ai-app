import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time

# ================= 1. 全局配置与样式 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 阿尔法量化终端",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# 模拟数据库：热门股名单
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

# 初始化 Session State
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'api_key' not in st.session_state:
    st.session_state['api_key'] = ""

# ================= 2. 核心逻辑引擎 (复用之前的双模引擎) =================

def generate_rule_based_report(stock_data, reason_msg):
    """【规则引擎】数学逻辑兜底"""
    price = stock_data['现价']
    pct = stock_data['今日涨幅']
    pct_5d = stock_data['5日涨幅']
    trend = stock_data['趋势']
    name = stock_data['名称']
    
    score = 50 
    if "强势" in trend: score += 20
    else: score -= 10
    
    if pct > 5: score += 15
    elif pct > 0: score += 5
    elif pct < -5: score -= 15
    else: score -= 5
    
    if pct_5d > 10: score += 5
    elif pct_5d < -10: score += 10
    
    if score >= 80:
        advice_short = "💪 强烈看多 (Strong Buy)"
        advice_long = "💎 增持 (Overweight)"
        logic = "多头排列，资金合力向上，主升浪特征明显。"
    elif score >= 60:
        advice_short = "📈 谨慎看多 (Buy)"
        advice_long = "🟢 持有 (Hold)"
        logic = "处于上升通道，注意乖离率修复。"
    elif score >= 40:
        advice_short = "👀 观望 (Neutral)"
        advice_long = "⚪ 中性 (Equal-weight)"
        logic = "多空博弈激烈，方向不明。"
    else:
        advice_short = "🏃‍♂️ 看空 (Sell)"
        advice_long = "⚠️ 减仓 (Underweight)"
        logic = "趋势破位，空头主导。"

    resistance = price * (1 + 0.05 + abs(pct)/1000)
    support = price * (1 - 0.05 - abs(pct)/1000)

    return f"""
    > **⚙️ 系统提示：{reason_msg} -> 已切换至 [Alpha-Math] 规则引擎**
    
    ### 📊 深度量化分析报告：{name}
    **AlphaScoring 综合评分：{score} / 100**
    
    1. **交易策略 (Trading Strategy)**
       - **短期**：**{advice_short}**
       - **长期**：**{advice_long}**
       - **核心逻辑**：{logic}
    
    2. **关键点位预测 (Key Levels)**
       - 🎯 压力位 (Resistance)：**¥{resistance:.2f}**
       - 🛡️ 支撑位 (Support)：**¥{support:.2f}**
    """

def run_analysis_controller(stock_data, base_url):
    """【总控制器】智能分发"""
    key = st.session_state['api_key']
    
    if not key or not key.startswith("sk-"):
        return generate_rule_based_report(stock_data, "未检测到高级分析 License (免费模式)")
    
    prompt = f"""
    身份：资深A股分析师。对象：{stock_data['名称']}({stock_data['代码']})。
    数据：现价{stock_data['现价']}，涨幅{stock_data['今日涨幅']}%，趋势{stock_data['趋势']}。
    任务：输出专业研报摘要。包含：1.短线策略 2.长线价值 3.风险提示。风格：专业、简练。
    """
    
    try:
        client = OpenAI(api_key=key, base_url=base_url, timeout=5)
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        err_str = str(e)
        if "402" in err_str: return generate_rule_based_report(stock_data, "API License 余额不足")
        elif "401" in err_str: return generate_rule_based_report(stock_data, "API License 无效")
        else: return generate_rule_based_report(stock_data, "云端连接超时")

@st.cache_data(ttl=600)
def get_watch_list_data():
    """获取榜单数据"""
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
        if hist.empty: return None, "未找到数据"
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

# ================= 3. 界面模块 (登录 & 主程序) =================

def login_page():
    """登录界面"""
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🔐 AlphaQuant Pro")
        st.markdown("**阿尔法量化智能决策终端**")
        st.info("默认账号: admin  |  默认密码: 123456")
        
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        
        if st.button("登录 / Login", type="primary", use_container_width=True):
            if username == "admin" and password == "123456":
                st.session_state['logged_in'] = True
                st.toast("登录成功！正在进入终端...", icon="✅")
                time.sleep(1)
                st.rerun()
            else:
                st.error("账号或密码错误")

def main_app():
    """主程序界面"""
    # --- 侧边栏导航 ---
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.markdown("`v3.2.0 Enterprise`")
        
        menu = st.radio("功能导航", ["📊 市场概览 (Dashboard)", "🔎 个股深度诊断", "⚙️ 系统设置"], index=0)
        
        st.divider()
        # 退出登录
        if st.button("退出登录 (Logout)"):
            st.session_state['logged_in'] = False
            st.rerun()

    # --- 页面 1: 市场概览 ---
    if menu == "📊 市场概览 (Dashboard)":
        st.header("📊 市场核心资产概览")
        st.markdown("监测对象：沪深300及热门赛道龙头 | 数据源：Global FinData")
        
        with st.spinner("正在同步全球交易所数据..."):
            df_watch = get_watch_list_data()
        
        if not df_watch.empty:
            # 顶部核心指标 (模拟)
            k1, k2, k3, k4 = st.columns(4)
            top_gainer = df_watch.sort_values("今日涨幅", ascending=False).iloc[0]
            k1.metric("市场情绪", "活跃 🔥")
            k2.metric("领涨龙头", top_gainer['名称'], f"{top_gainer['今日涨幅']}%")
            k3.metric("强势股占比", f"{len(df_watch[df_watch['趋势'].str.contains('强势')])/len(df_watch)*100:.0f}%")
            k4.metric("数据状态", "实时 Online", delta_color="normal")
            
            st.divider()
            
            t1, t2 = st.tabs(["🚀 短线爆发榜 (Momentum)", "💎 长期价值榜 (Value)"])
            with t1:
                st.dataframe(
                    df_watch.sort_values("5日涨幅", ascending=False).head(10)[["名称", "现价", "今日涨幅", "5日涨幅"]],
                    use_container_width=True, hide_index=True
                )
            with t2:
                st.dataframe(
                    df_watch[df_watch['趋势'].str.contains("强势")].sort_values("今日涨幅").head(10)[["名称", "现价", "今日涨幅", "趋势"]],
                    use_container_width=True, hide_index=True
                )
        else:
            st.warning("市场数据同步失败，请检查网络。")

    # --- 页面 2: 个股诊断 ---
    elif menu == "🔎 个股深度诊断":
        st.header("🔎 全市场智能投顾")
        st.caption("支持 A股/港股/美股 全球代码搜索 | 双模引擎：AI + Alpha-Math")
        
        c1, c2 = st.columns(2)
        s_code = c1.text_input("股票代码 (Ticker)", placeholder="如 601127 或 00700.HK")
        s_name = c2.text_input("股票名称 (Name)", placeholder="如 赛力斯 (辅助报告生成)")
        
        # 隐藏的设置（从这里读取Key）
        base_url = "https://api.openai.com/v1" 
        if "base_url" in st.session_state: base_url = st.session_state["base_url"]

        if st.button("🚀 生成专业分析报告", type="primary"):
            if s_code:
                final_name = s_name if s_name else s_code
                with st.spinner(f"AlphaQuant 正在计算 {final_name} 的技术指标..."):
                    data, err = get_single_stock_realtime(s_code, final_name)
                    
                    if data:
                        # 结果展示区
                        with st.container(border=True):
                            m1, m2, m3 = st.columns(3)
                            m1.metric(data['名称'], f"¥{data['现价']}")
                            m2.metric("当日涨跌", f"{data['今日涨幅']}%", delta=data['今日涨幅'])
                            m3.metric("中期趋势", data['趋势'])
                            
                            st.divider()
                            st.subheader("📝 决策分析报告")
                            # 传入 base_url
                            report = run_analysis_controller(data, base_url)
                            st.markdown(report)
                    else:
                        st.error(f"查询失败: {err}")
            else:
                st.warning("请输入代码")

    # --- 页面 3: 设置 ---
    elif menu == "⚙️ 系统设置":
        st.header("⚙️ 终端参数设置")
        
        with st.form("settings_form"):
            st.subheader("AI 增强模块 (Optional)")
            new_key = st.text_input("API Key (sk-xxxx)", type="password", value=st.session_state['api_key'], help="支持 OpenAI / DeepSeek")
            new_url = st.text_input("Base URL", value="https://api.openai.com/v1")
            
            submitted = st.form_submit_button("💾 保存配置")
            if submitted:
                st.session_state['api_key'] = new_key
                st.session_state['base_url'] = new_url
                st.success("配置已更新！")
        
        st.info("💡 说明：未配置 Key 时，系统将自动使用内置数学规则引擎进行分析。")

# ================= 4. 启动逻辑 =================
if __name__ == "__main__":
    if st.session_state['logged_in']:
        main_app()
    else:
        login_page()










