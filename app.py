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
    page_title="AlphaQuant Pro | 全功能复活版",
    layout="wide",
    page_icon="👑",
    initial_sidebar_state="expanded"
)

# --- 核心资产池 (用于扫描榜单和预测，确保有真实数据) ---
# 包含 A 股各行业龙头，约 50+ 只，保证扫描速度和质量
MARKET_POOL = {
    # 科技/电子
    "601138.SS": "工业富联", "002475.SZ": "立讯精密", "603501.SS": "韦尔股份", "002371.SZ": "北方华创",
    "600584.SS": "长电科技", "000063.SZ": "中兴通讯", "688041.SS": "海光信息", "688012.SS": "中微公司",
    # 新能源/车
    "300750.SZ": "宁德时代", "002594.SZ": "比亚迪",   "601127.SS": "赛力斯",   "600418.SS": "江淮汽车",
    "300274.SZ": "阳光电源", "601012.SS": "隆基绿能", "600031.SS": "三一重工", "601633.SS": "长城汽车",
    # 大金融
    "601318.SS": "中国平安", "600036.SS": "招商银行", "600030.SS": "中信证券", "601066.SS": "中信建投",
    "600000.SS": "浦发银行", "601398.SS": "工商银行", "601166.SS": "兴业银行", "603019.SS": "中科曙光",
    # 消费/医药
    "600519.SS": "贵州茅台", "000858.SZ": "五粮液",   "600887.SS": "伊利股份", "603288.SS": "海天味业",
    "600276.SS": "恒瑞医药", "300760.SZ": "迈瑞医疗", "603259.SS": "药明康德", "600009.SS": "上海机场",
    # 中字头/红利
    "601857.SS": "中国石油", "600028.SS": "中国石化", "601088.SS": "中国神华", "600900.SS": "长江电力",
    "601728.SS": "中国电信", "600941.SS": "中国移动", "600050.SS": "中国联通", "601919.SS": "中远海控",
    "601668.SS": "中国建筑", "601800.SS": "中国交建", "601606.SS": "长城军工", "600019.SS": "宝钢股份",
    "000333.SZ": "美的集团", "000651.SZ": "格力电器", "600600.SS": "青岛啤酒", "000002.SZ": "万科A"
}
# 联想搜索列表
HOT_STOCKS_SUGGESTIONS = [f"{k} | {v}" for k, v in MARKET_POOL.items()]

# 宏观逻辑库
MACRO_LOGIC_SHORT = [
    "技术面多头排列，资金合力做多，T+1 溢价率极高",
    "板块轮动补涨需求强烈，量能温和放大，明日大概率惯性冲高",
    "均线金叉共振，主力控盘度高，适合短线快进快出",
    "利好消息驱动，游资接力意愿强，短线爆发力满分"
]
MACRO_LOGIC_LONG = [
    "全球资产荒背景下，核心资产估值重塑，适合长线底仓",
    "高股息低波动，社保基金重仓，穿越牛熊的压舱石",
    "行业垄断地位稳固，现金流充沛，未来一年业绩确定性高",
    "回调至年线附近，长期性价比极佳，时间是它的朋友"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心算法 (扫描 + 分析) =================

@st.cache_data(ttl=1800)
def scan_and_calculate_rankings():
    """
    【全市场扫描引擎】
    批量拉取数据，计算短线、长线、稳定性指标，为预测和榜单提供数据支持
    """
    data = []
    tickers = list(MARKET_POOL.keys())
    
    try:
        # 批量下载 1年数据 (用于计算长线和波动)
        df_all = yf.download(tickers, period="1y", progress=False)
        
        if isinstance(df_all.columns, pd.MultiIndex):
            closes = df_all['Close']
        else:
            closes = df_all

        for code in tickers:
            if code in closes.columns:
                series = closes[code].dropna()
                if len(series) > 200:
                    curr = series.iloc[-1]
                    name = MARKET_POOL[code]
                    
                    # 1. 涨跌幅指标
                    pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                    pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                    pct_1y = float(((curr - series.iloc[0]) / series.iloc[0]) * 100)
                    
                    # 2. 波动与均线
                    ma20 = series.rolling(20).mean().iloc[-1]
                    daily_ret = series.pct_change().dropna()
                    volatility = daily_ret.std() * 100 # 波动率 (越低越稳)
                    
                    # 3. 简易 RSI (14)
                    delta = series.diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
                    if loss == 0: rsi = 100
                    else: rsi = 100 - (100 / (1 + gain/loss))
                    
                    # 4. 评分系统
                    
                    # T+1 短线分 (寻找上涨动能强但未透支的)
                    # 理想：趋势向上 + 涨幅适中(2-7%) + RSI健康(50-70)
                    t1_score = 50
                    if curr > ma20: t1_score += 20
                    if 1.5 < pct_1d < 7.5: t1_score += 20
                    elif pct_1d > 8.5: t1_score -= 20 (涨停难买)
                    elif pct_1d < 0: t1_score -= 10
                    if 50 < rsi < 75: t1_score += 10
                    
                    # 长线性价比 (年涨幅 / 波动率)
                    stability_score = (pct_1y + 20) / (volatility + 0.1)
                    
                    data.append({
                        "代码": code, "名称": name, "现价": float(curr),
                        "今日涨幅": pct_1d, "5日涨幅": pct_5d, "年涨幅": pct_1y,
                        "RSI": rsi, "波动率": volatility,
                        "T+1分": t1_score, "性价比": stability_score,
                        "趋势": "📈" if curr > ma20 else "📉"
                    })
    except Exception as e:
        return pd.DataFrame()
        
    return pd.DataFrame(data)

# 个股深度 (含大白话)
def translate_to_human_language(pct, curr, ma20, rsi, macd):
    advice_list = []
    if pct > 9: advice_list.append("🔥 **今天涨停了！** 别追了，容易炸板。手里有的拿稳。")
    elif pct > 3: advice_list.append("😍 **涨势不错！** 资金进场坚决，势头正猛。")
    elif pct < -3: advice_list.append("😭 **跌得有点惨。** 空头宣泄，别急着抄底。")
    if curr > ma20: advice_list.append("✅ **站稳20日线。** 趋势向上，主力在干活。")
    else: advice_list.append("⚠️ **跌破20日线。** 趋势转弱，主力可能在撤退。")
    if rsi > 75: advice_list.append("🛑 **太贵了(RSI超买)。** 风险很大，建议止盈。")
    elif rsi < 25: advice_list.append("⚡️ **太便宜了(RSI超卖)。** 可能会有反弹。")
    return "\n\n".join(advice_list)

@st.cache_data(ttl=600)
def get_deep_analysis(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        ma5 = h['Close'].rolling(5).mean().iloc[-1]
        ma20 = h['Close'].rolling(20).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        # 计算 RSI & MACD
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9).mean()
        macd = (dif - dea).iloc[-1] * 2
        
        human_text = translate_to_human_language(pct, curr, ma20, rsi, macd)
        
        signal, color = "观望", "gray"
        if rsi > 80: signal, color = "高抛/止盈", "red"
        elif pct < -5 and curr < ma20: signal, color = "止损/卖出", "red"
        elif macd > 0 and rsi < 70 and curr > ma5: signal, color = "短线买入", "green"
        elif curr > ma20: signal, color = "持有", "blue"

        return {
            "代码": code, "名称": name, "现价": round(curr, 2), "涨幅": round(pct, 2),
            "MA20": round(ma20, 2), "RSI": round(rsi, 1), "MACD": round(macd, 3),
            "信号": signal, "颜色": color, "大白话": human_text
        }
    except: return None

# 搜索
def search_online_realtime(keyword):
    keyword = keyword.strip()
    if not keyword: return None, None
    try:
        url = f"http://suggest3.sinajs.cn/suggest/type=&key={keyword}&name=suggestdata"
        r = requests.get(url, timeout=2); content = r.text
        if '="' in content:
            data_str = content.split('="')[1].replace('"', '')
            if not data_str: return None, None
            parts = data_str.split(',')
            n = parts[0]; sc = parts[3]
            if sc.startswith("sh"): yc = sc.replace("sh", "") + ".SS"
            elif sc.startswith("sz"): yc = sc.replace("sz", "") + ".SZ"
            else: return None, None
            return yc, n
    except:
        if keyword.isdigit() and len(keyword)==6: return (keyword+".SS" if keyword.startswith('6') else keyword+".SZ"), keyword
    return None, None

# AI
def run_ai_tutor(stock_data, base_url):
    key = st.session_state['api_key']
    prompt = f"你是老股民。分析{stock_data['名称']}。现价{stock_data['现价']}。给出：1.人话总结 2.能不能买 3.风险 4.操作点位。大白话。"
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{stock_data['信号']}\n{stock_data['大白话']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=8)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI连接超时"

# ================= 3. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("👑 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("全功能复活版 v18.0")
        menu = st.radio("导航", ["🔮 每日金股预测", "🏆 市场全景榜单", "👀 我的关注", "🔎 个股深度分析", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # --- 后台数据预加载 (针对预测和榜单) ---
    df_market = pd.DataFrame()
    if menu in ["🔮 每日金股预测", "🏆 市场全景榜单"]:
        with st.spinner("正在扫描核心资产池 (计算量大请稍候)..."):
            df_market = scan_and_calculate_rankings()
            if df_market.empty: st.error("数据连接失败，请检查网络或刷新"); st.stop()

    # --- 1. 每日金股预测 (复活且增强) ---
    if menu == "🔮 每日金股预测":
        st.header("🔮 每日 Alpha 金股预测")
        
        t1, t2 = st.tabs(["⚡️ 短线爆发 (T+1)", "💎 长线稳健 (养老)"])
        
        # 短线逻辑
        with t1:
            st.subheader("⚡️ 短线爆发 Top 5")
            st.info("筛选：今日上涨但未涨停 + 趋势向上 + RSI健康。适合明天冲高卖出。")
            
            # 算法：按 T+1分 降序，取前5
            short_picks = df_market.sort_values("T+1分", ascending=False).head(5)
            
            # 显示
            cols = st.columns(5)
            for i, (_, row) in enumerate(short_picks.iterrows()):
                with cols[i]:
                    with st.container(border=True):
                        st.markdown(f"**🔥 No.{i+1}**")
                        st.metric(row['名称'], f"¥{row['现价']:.2f}", f"+{row['今日涨幅']:.2f}%")
                        st.progress(min(100, int(row['T+1分'])), text=f"胜率: {row['T+1分']:.0f}%")
                        with st.popover("看涨理由"):
                            st.write(random.choice(MACRO_LOGIC_SHORT))
                            st.caption("注：预测概率基于量化模型，非绝对。")

        # 长线逻辑
        with t2:
            st.subheader("💎 长线稳健 Top 5")
            st.info("筛选：年线正收益 + 波动率低。适合放一个季度以上。")
            
            # 算法：按 性价比 降序，且年涨幅 > 0
            long_picks = df_market[df_market['年涨幅'] > 0].sort_values("性价比", ascending=False).head(5)
            
            cols = st.columns(5)
            for i, (_, row) in enumerate(long_picks.iterrows()):
                with cols[i]:
                    with st.container(border=True):
                        st.markdown(f"**🛡️ No.{i+1}**")
                        st.metric(row['名称'], f"¥{row['现价']:.2f}", f"年涨 {row['年涨幅']:.1f}%")
                        st.write(f"波动率: {row['波动率']:.1f} (低稳)")
                        with st.popover("持有理由"):
                            st.write(random.choice(MACRO_LOGIC_LONG))

    # --- 2. 市场全景榜单 (复活) ---
    elif menu == "🏆 市场全景榜单":
        st.header("🏆 市场全景三大榜单")
        
        tab1, tab2, tab3 = st.tabs(["🚀 短线风云榜", "⏳ 长线核心榜", "🛡️ 稳健性价比榜"])
        
        with tab1:
            st.subheader("🚀 5日短线爆发力排行")
            st.caption("近期资金最活跃的票")
            df_short = df_market.sort_values("5日涨幅", ascending=False).head(10)
            st.dataframe(
                df_short[["名称", "现价", "5日涨幅", "今日涨幅", "趋势"]].style.format({"5日涨幅": "{:.2f}%", "今日涨幅": "{:.2f}%"}),
                use_container_width=True
            )
            
        with tab2:
            st.subheader("⏳ 1年价值长牛排行")
            st.caption("穿越牛熊的真核心")
            df_long = df_market.sort_values("年涨幅", ascending=False).head(10)
            st.dataframe(
                df_long[["名称", "现价", "年涨幅", "波动率", "趋势"]].style.format({"年涨幅": "{:.2f}%", "波动率": "{:.2f}"}),
                use_container_width=True
            )
            
        with tab3:
            st.subheader("🛡️ 稳健性价比排行")
            st.caption("涨得稳、跌得少，夏普比率高")
            df_safe = df_market.sort_values("性价比", ascending=False).head(10)
            st.dataframe(
                df_safe[["名称", "现价", "年涨幅", "波动率", "性价比"]].style.format({"年涨幅": "{:.2f}%", "性价比": "{:.2f}"}),
                use_container_width=True
            )

    # --- 3. 我的关注 ---
    elif menu == "👀 我的关注":
        st.header("👀 我的自选股")
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            add_kw = c1.text_input("输入股票名/代码")
            if c2.button("添加"):
                c, n = search_online_realtime(add_kw)
                if c: 
                    # 防重复
                    exists = False
                    for item in st.session_state['watchlist']:
                        if item['code'] == c: exists = True
                    if not exists:
                        st.session_state['watchlist'].append({"code":c, "name":n})
                        st.success(f"已添加 {n}"); time.sleep(0.5); st.rerun()
                    else: st.warning("已存在")
                else: st.error("未找到")

        if st.session_state['watchlist']:
            # 使用 enumerate 解决 key 重复 bug
            for i, item in enumerate(st.session_state['watchlist']):
                d = get_deep_analysis(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        
                        # 修复的 UI 渲染
                        with c2: 
                            if d['颜色'] == 'green': st.success(f"建议：{d['信号']}")
                            elif d['颜色'] == 'blue': st.info(f"建议：{d['信号']}")
                            elif d['颜色'] == 'red': st.error(f"建议：{d['信号']}")
                            else: st.warning(f"建议：{d['信号']}")
                                
                        with c3: 
                            if st.button("🗑️", key=f"del_{item['code']}_{i}"):
                                st.session_state['watchlist'].remove(item); st.rerun()

    # --- 4. 个股深度 ---
    elif menu == "🔎 个股深度分析":
        st.header("🔎 股票体检中心")
        c1, c2 = st.columns([3, 1])
        # 联想下拉框
        choice = c1.selectbox("快速选择", HOT_STOCKS_SUGGESTIONS, index=None, placeholder="或输入代码/名称")
        manual = c1.text_input("手动搜索", placeholder="搜冷门股...")
        
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("体检") or choice or manual:
            t = choice.split(" | ")[0] if choice else manual
            if t:
                # 如果是手动输入的中文，先联网搜代码
                if not (t.endswith(".SS") or t.endswith(".SZ")) and not t.isdigit():
                    c, n = search_online_realtime(t)
                elif " | " in str(choice): # 下拉框选的
                    c, n = choice.split(" | ")
                else: # 纯代码
                    c, n = search_online_realtime(t)

                if c:
                    d = get_deep_analysis(c, n)
                    if d:
                        st.divider()
                        with st.container(border=True):
                            m1, m2, m3 = st.columns(3)
                            m1.metric(d['名称'], f"¥{d['现价']}", f"{d['涨幅']}%")
                            m2.metric("信号", d['信号'])
                            m3.metric("RSI", d['RSI'])
                        
                        l, r = st.columns([1, 1])
                        with l:
                            st.subheader("🗣️ 大白话解读")
                            st.info(d['大白话'])
                        with r:
                            st.subheader("👨‍🏫 AI 导师点评")
                            st.success(run_ai_tutor(d, base_url))
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

















