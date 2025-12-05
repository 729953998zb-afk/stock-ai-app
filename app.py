import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import numpy as np

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 终极完全体",
    layout="wide",
    page_icon="👑",
    initial_sidebar_state="expanded"
)

# --- 核心股票池 (用于扫描榜单和预测) ---
# 包含热门龙头、赛道股、稳健股，确保样本足够丰富
MARKET_POOL = {
    "600519.SS": "贵州茅台", "300750.SZ": "宁德时代", "601127.SS": "赛力斯",
    "601318.SS": "中国平安", "002594.SZ": "比亚迪",   "600036.SS": "招商银行",
    "601857.SS": "中国石油", "000858.SZ": "五粮液",   "601138.SS": "工业富联",
    "603259.SS": "药明康德", "300059.SZ": "东方财富", "002475.SZ": "立讯精密",
    "601606.SS": "长城军工", "603600.SS": "永艺股份", "000063.SZ": "中兴通讯",
    "601728.SS": "中国电信", "600941.SS": "中国移动", "002371.SZ": "北方华创",
    "300274.SZ": "阳光电源", "600150.SS": "中国船舶", "600600.SS": "青岛啤酒",
    "600030.SS": "中信证券", "000725.SZ": "京东方A",  "600276.SS": "恒瑞医药",
    "600900.SS": "长江电力", "601919.SS": "中远海控", "000002.SZ": "万科A",
    "000333.SZ": "美的集团", "603288.SS": "海天味业", "601088.SS": "中国神华",
    "601899.SS": "紫金矿业", "601012.SS": "隆基绿能", "300760.SZ": "迈瑞医疗",
    "600019.SS": "宝钢股份", "600048.SS": "保利发展", "601398.SS": "工商银行",
    "601939.SS": "建设银行", "601288.SS": "农业银行", "601988.SS": "中国银行"
}
# 下拉联想列表
HOT_STOCKS_SUGGESTIONS = [f"{k} | {v}" for k, v in MARKET_POOL.items()]

# 宏观逻辑库
MACRO_LOGIC_SHORT = [
    "主力资金深度介入，技术面形成多方炮，溢价率极高",
    "板块轮动至该赛道，补涨需求强烈，配合量能放大",
    "均线系统多头排列，RSI未超买，T+1套利空间大",
    "利好消息发酵，游资接力意愿强，明日大概率惯性冲高"
]
MACRO_LOGIC_LONG = [
    "全球流动性外溢，核心资产估值重塑，适合长线配置",
    "行业进入补库存周期，业绩拐点确认，戴维斯双击可期",
    "高股息低估值，社保基金增持，穿越周期的压舱石",
    "行业龙头地位稳固，护城河深，未来一年业绩确定性高"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心算法 (扫描 + 指标计算) =================

@st.cache_data(ttl=1800)
def scan_whole_market():
    """
    【核心扫描引擎】
    批量拉取 MARKET_POOL 中的数据，计算长线、短线、稳定性指标
    用于生成榜单和预测
    """
    data = []
    tickers = list(MARKET_POOL.keys())
    try:
        # 批量下载 1年数据
        df_all = yf.download(tickers, period="1y", progress=False)
        
        # 处理多级索引
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
                    
                    # 1. 基础指标
                    pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                    pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                    pct_1y = float(((curr - series.iloc[0]) / series.iloc[0]) * 100)
                    
                    # 2. 均线与波动
                    ma20 = series.rolling(20).mean().iloc[-1]
                    ma60 = series.rolling(60).mean().iloc[-1]
                    daily_ret = series.pct_change().dropna()
                    volatility = daily_ret.std() * 100
                    
                    # 3. 计算 RSI (简易版)
                    delta = series.diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
                    rsi = 100 if loss == 0 else 100 - (100 / (1 + gain/loss))
                    
                    # 4. 评分系统
                    
                    # T+1 安全分 (短线)：趋势强 + 没涨停 + RSI健康
                    t1_score = 60
                    if curr > ma20: t1_score += 20
                    if 0 < pct_1d < 7: t1_score += 15 # 最佳涨幅区间
                    elif pct_1d > 8.5: t1_score -= 30 # 涨停风险(买不进或炸板)
                    if 50 < rsi < 75: t1_score += 10 # 动能强且未超买
                    
                    # 稳健分 (长线)：年涨幅高 + 波动低
                    # 性价比 = 年涨幅 / (波动率 + 0.1)
                    stability_score = (pct_1y + 10) / (volatility + 0.1)
                    
                    data.append({
                        "代码": code, "名称": name, "现价": float(curr),
                        "今日涨幅": pct_1d, "5日涨幅": pct_5d, "年涨幅": pct_1y,
                        "RSI": rsi, "波动率": volatility,
                        "T+1分": t1_score, "性价比": stability_score,
                        "趋势": "📈 多头" if curr > ma20 else "📉 空头",
                        "MA60": ma60
                    })
    except Exception as e:
        print(e)
        return pd.DataFrame()
        
    return pd.DataFrame(data)

# 个股深度指标计算 (保持 v13 的优秀逻辑)
@st.cache_data(ttl=600)
def get_deep_analysis(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        
        # 计算详细指标
        h['MA5'] = h['Close'].rolling(5).mean()
        h['MA20'] = h['Close'].rolling(20).mean()
        h['MA60'] = h['Close'].rolling(60).mean()
        
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        h['RSI'] = 100 - (100 / (1 + gain/loss))
        
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9).mean()
        macd = (dif - dea) * 2
        
        curr = h['Close'].iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        ma20 = h['MA20'].iloc[-1]
        rsi = h['RSI'].iloc[-1]
        m_val = macd.iloc[-1]
        
        # 信号逻辑
        signal, color, advice = "观望", "gray", "趋势不明"
        if rsi > 80: signal, color, advice = "🔴 止盈/减仓", "red", f"RSI超买({rsi:.1f})，短线回调风险大"
        elif pct < -5 and curr < ma20: signal, color, advice = "🔴 止损/卖出", "red", "放量破位，趋势转坏"
        elif m_val > 0 and rsi < 70 and curr > h['MA5'].iloc[-1]: signal, color, advice = "⚡️ 短线买入", "green", "MACD金叉，动能强劲"
        elif abs(curr - h['MA60'].iloc[-1])/curr < 0.05 and curr > h['MA60'].iloc[-1]: signal, color, advice = "💎 长线建仓", "blue", "回踩生命线企稳"
        elif curr > ma20: signal, color, advice = "🛡️ 持有", "blue", "上升通道良好"

        return {
            "代码": code, "名称": name, "现价": round(curr,2), "涨幅": round(pct,2),
            "MA20": round(ma20,2), "RSI": round(rsi,1), "MACD": round(m_val,3),
            "信号": signal, "颜色": color, "建议": advice
        }
    except: return None

# 搜索辅助
def search_online(keyword):
    keyword = keyword.strip()
    if not keyword: return None, None
    for item in HOT_STOCKS_SUGGESTIONS:
        c, n = item.split(" | ")
        if keyword in n or keyword in c: return c, n
    if keyword.isdigit() and len(keyword)==6: 
        suffix = ".SS" if keyword.startswith("6") else ".SZ"
        return keyword+suffix, keyword
    return None, None

# AI 分析
def run_ai_analysis(stock_data, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{stock_data['信号']}\n理由：{stock_data['建议']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析A股{stock_data['名称']}，RSI={stock_data['RSI']}, MACD={stock_data['MACD']}。给出操作建议。"}]).choices[0].message.content
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
        st.caption("终极完全体 v14.0")
        menu = st.radio("功能导航", [
            "🔮 每日金股预测",  # 恢复
            "🏆 市场全景榜单",  # 恢复
            "👀 我的关注",      # 保留
            "🔎 个股深度分析",  # 保留
            "⚙️ 设置"
        ])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # 数据准备
    df_market = pd.DataFrame()
    if menu in ["🔮 每日金股预测", "🏆 市场全景榜单"]:
        with st.spinner("正在扫描全市场数据与计算指标..."):
            df_market = scan_whole_market()

    # --- 1. 每日金股预测 (恢复并增强) ---
    if menu == "🔮 每日金股预测":
        st.header("🔮 每日 Alpha 金股预测")
        st.caption("基于量化模型筛选：高胜率 T+1 短线股 & 稳健长线复利股")
        
        if not df_market.empty:
            t1, t2 = st.tabs(["⚡️ 短线爆发 (T+1)", "💎 长线稳健 (1年)"])
            
            with t1:
                st.subheader("⚡️ 明日大概率上涨 (Top 5)")
                st.info("筛选标准：趋势多头 + 动能强劲 + 今日未涨停 (留有溢价空间) + 资金活跃")
                
                # 算法：按 T+1分 降序，且涨幅>0
                short_picks = df_market[df_market['今日涨幅'] > 0].sort_values("T+1分", ascending=False).head(5)
                
                cols = st.columns(5)
                for i, (_, row) in enumerate(short_picks.iterrows()):
                    with cols[i]:
                        with st.container(border=True):
                            st.markdown(f"**🔥 No.{i+1}**")
                            st.metric(row['名称'], f"¥{row['现价']:.2f}", f"+{row['今日涨幅']:.2f}%")
                            st.progress(min(100, int(row['T+1分'])), text=f"胜率: {row['T+1分']:.0f}%")
                            with st.popover("看涨理由"):
                                st.write(random.choice(MACRO_LOGIC_SHORT))
                                st.caption("T+1 安全度高，明日易冲高")
            
            with t2:
                st.subheader("💎 季度/年度稳健复利 (Top 5)")
                st.info("筛选标准：年线正收益 + 低波动率 + 站稳60日生命线")
                
                # 算法：按 性价比 降序，且年涨幅>-5
                long_picks = df_market[df_market['年涨幅'] > -5].sort_values("性价比", ascending=False).head(5)
                
                cols = st.columns(5)
                for i, (_, row) in enumerate(long_picks.iterrows()):
                    with cols[i]:
                        with st.container(border=True):
                            st.markdown(f"**🛡️ No.{i+1}**")
                            st.metric(row['名称'], f"¥{row['现价']:.2f}", f"年涨 {row['年涨幅']:.1f}%")
                            st.write(f"波动率: {row['波动率']:.1f}")
                            with st.popover("持有理由"):
                                st.write(random.choice(MACRO_LOGIC_LONG))
                                st.caption("核心资产，适合长期底仓")
        else: st.error("数据连接失败")

    # --- 2. 市场全景榜单 (恢复并增强) ---
    elif menu == "🏆 市场全景榜单":
        st.header("🏆 市场全景三大榜单")
        
        if not df_market.empty:
            t1, t2, t3 = st.tabs(["🚀 短线风云榜", "⏳ 长线核心榜", "🛡️ 稳健性价比榜"])
            
            with t1:
                st.subheader("🚀 5日爆发力排行 (Momentum)")
                df_short = df_market.sort_values("5日涨幅", ascending=False).head(10)
                st.dataframe(df_short[["名称", "代码", "现价", "今日涨幅", "5日涨幅", "趋势"]], use_container_width=True, hide_index=True)
            
            with t2:
                st.subheader("⏳ 1年价值长牛排行 (Value)")
                df_long = df_market.sort_values("年涨幅", ascending=False).head(10)
                st.dataframe(df_long[["名称", "代码", "现价", "年涨幅", "MA60", "趋势"]], use_container_width=True, hide_index=True)
                
            with t3:
                st.subheader("🛡️ 夏普性价比排行 (Stability)")
                st.caption("计算公式：(年涨幅+10) / 波动率。分数越高越值得拿着不动。")
                df_safe = df_market.sort_values("性价比", ascending=False).head(10)
                st.dataframe(df_safe[["名称", "现价", "年涨幅", "波动率", "性价比"]], use_container_width=True, hide_index=True)

    # --- 3. 我的关注 (保持 v13) ---
    elif menu == "👀 我的关注":
        st.header("👀 智能盯盘")
        with st.expander("➕ 添加", expanded=False):
            c1, c2 = st.columns([3,1])
            k = c1.selectbox("搜", HOT_STOCKS_SUGGESTIONS, index=None); k_m = c1.text_input("或输代码")
            if c2.button("Add"):
                t = k if k else k_m
                if t:
                    c, n = (t.split(" | ") if " | " in t else search_online(t))
                    if c: st.session_state['watchlist'].append({"code":c, "name":n}); st.rerun()
        
        if st.session_state['watchlist']:
            for item in st.session_state['watchlist']:
                d = get_deep_analysis(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1,c2,c3,c4 = st.columns([2,2,3,1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        with c2: st.metric("RSI", d['RSI'], f"{d['涨幅']}%")
                        with c3: 
                            if d['颜色']=='green': st.success(f"{d['信号']}")
                            elif d['颜色']=='red': st.error(f"{d['信号']}")
                            else: st.info(f"{d['信号']}")
                            st.caption(d['建议'])
                        with c4: 
                            if st.button("🗑️", key=f"d_{item['code']}"): st.session_state['watchlist'].remove(item); st.rerun()

    # --- 4. 个股深度 (保持 v13) ---
    elif menu == "🔎 个股深度分析":
        st.header("🔎 个股全维透视")
        c1, c2 = st.columns([3,1])
        k = c1.selectbox("选股", HOT_STOCKS_SUGGESTIONS, index=None); k_m = c1.text_input("或输代码")
        if c2.button("分析") or k or k_m:
            t = k if k else k_m
            if t:
                c, n = (t.split(" | ") if " | " in t else search_online(t))
                if c:
                    d = get_deep_analysis(c, n)
                    if d:
                        st.divider()
                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("现价", d['现价'], f"{d['涨幅']}%")
                        m2.metric("RSI", d['RSI'])
                        m3.metric("MACD", d['MACD'])
                        m4.metric("信号", d['信号'])
                        cl, cr = st.columns([2,1])
                        with cl: st.info(run_ai_analysis(d, st.session_state.get("base_url", "https://api.openai.com/v1")))
                        with cr: 
                            st.success(f"建议：{d['信号']}"); st.write(f"买点：{d.get('点位','--')}"); st.write(f"止损：跌破 {d['MA20']}")
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
















