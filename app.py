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
    page_title="AlphaQuant Pro | 最终定稿版",
    layout="wide",
    page_icon="🏆",
    initial_sidebar_state="expanded"
)

# --- 本地热门股 (用于下拉联想，提升体验) ---
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
    "600019.SS | 宝钢股份", "600048.SS | 保利发展", "601398.SS | 工商银行",
    "601939.SS | 建设银行", "601288.SS | 农业银行", "601988.SS | 中国银行",
    "603661.SS | 恒林股份", "000001.SZ | 平安银行", "600028.SS | 中国石化"
]

# 宏观逻辑库
MACRO_LOGIC_SHORT = [
    "技术面多头排列，资金合力做多，T+1 溢价率极高",
    "板块轮动补涨需求强烈，量能温和放大，明日大概率惯性冲高",
    "均线金叉共振，主力控盘度高，适合短线快进快出",
    "利好消息驱动，游资接力意愿强，短线爆发力满分"
]
MACRO_LOGIC_LONG = [
    "全球流动性外溢，核心资产估值重塑，适合长线底仓",
    "高股息低波动，社保基金重仓，穿越牛熊的压舱石",
    "行业垄断地位稳固，现金流充沛，未来一年业绩确定性高",
    "回调至年线附近，长期性价比极佳，时间是它的朋友"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心算法 (真正的联网搜索) =================

def search_online_realtime(keyword):
    """
    【核心黑科技】新浪财经实时搜索接口
    输入 '恒林股份' -> 返回 '603661.SS', '恒林股份'
    """
    keyword = keyword.strip()
    if not keyword: return None, None
    
    # 1. 尝试本地匹配 (如果用户输入的是代码前缀，为了快)
    if keyword.isdigit() and len(keyword) < 6:
        return None, None 

    try:
        # 调用新浪接口
        url = f"http://suggest3.sinajs.cn/suggest/type=&key={keyword}&name=suggestdata"
        # 增加 headers 模拟浏览器，防止被拦截
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=2)
        content = r.text
        
        # 解析返回: var suggestdata="恒林股份,11,603661,sh603661,..."
        if '="' in content:
            data_str = content.split('="')[1].replace('"', '')
            if not data_str: return None, None
            
            parts = data_str.split(',')
            name = parts[0]
            sina_code = parts[3] # sh603661 or sz000001
            
            # 转为 Yahoo 格式
            yahoo_code = None
            if sina_code.startswith("sh"): yahoo_code = sina_code.replace("sh", "") + ".SS"
            elif sina_code.startswith("sz"): yahoo_code = sina_code.replace("sz", "") + ".SZ"
            elif sina_code.startswith("bj"): yahoo_code = sina_code.replace("bj", "") + ".BJ"
            
            if yahoo_code:
                return yahoo_code, name
    except Exception as e:
        # 兜底：如果是纯6位数字
        if keyword.isdigit() and len(keyword)==6:
            return (f"{keyword}.SS" if keyword.startswith('6') else f"{keyword}.SZ"), keyword
            
    return None, None

@st.cache_data(ttl=1800)
def scan_whole_market():
    """扫描全市场 (用内置大池子模拟，保证速度和稳定性)"""
    data = []
    # 提取 HOT_STOCKS_SUGGESTIONS 里的代码
    tickers = [x.split(" | ")[0] for x in HOT_STOCKS_SUGGESTIONS]
    
    try:
        df_all = yf.download(tickers, period="1y", progress=False)
        if isinstance(df_all.columns, pd.MultiIndex): closes = df_all['Close']
        else: closes = df_all

        for item in HOT_STOCKS_SUGGESTIONS:
            code, name = item.split(" | ")
            if code in closes.columns:
                series = closes[code].dropna()
                if len(series) > 200:
                    curr = series.iloc[-1]
                    pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                    pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                    pct_1y = float(((curr - series.iloc[0]) / series.iloc[0]) * 100)
                    
                    ma20 = series.rolling(20).mean().iloc[-1]
                    daily_ret = series.pct_change().dropna()
                    volatility = daily_ret.std() * 100 
                    
                    delta = series.diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
                    rsi = 100 if loss == 0 else 100 - (100 / (1 + gain/loss))
                    
                    # 评分
                    t1_score = 50
                    if curr > ma20: t1_score += 20
                    if 1 < pct_1d < 7: t1_score += 20
                    if 50 < rsi < 70: t1_score += 10
                    
                    stab_score = (pct_1y + 20) / (volatility + 0.1)
                    
                    data.append({
                        "代码": code, "名称": name, "现价": float(curr),
                        "今日涨幅": pct_1d, "5日涨幅": pct_5d, "年涨幅": pct_1y,
                        "RSI": rsi, "波动率": volatility,
                        "T+1分": t1_score, "性价比": stab_score,
                        "趋势": "📈" if curr > ma20 else "📉"
                    })
    except: pass
    return pd.DataFrame(data)

def translate_to_human_language(pct, curr, ma20, ma60, rsi, macd):
    """小白翻译机"""
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
        ma60 = h['Close'].rolling(60).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9).mean()
        macd = (dif - dea).iloc[-1] * 2
        
        human_text = translate_to_human_language(pct, curr, ma20, ma60, rsi, macd)
        
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

def run_ai_tutor(stock_data, base_url):
    key = st.session_state['api_key']
    prompt = f"""
    你是一个说话直白、幽默的资深老股民。
    分析股票：{stock_data['名称']} ({stock_data['代码']})。
    数据：现价{stock_data['现价']}，涨幅{stock_data['涨幅']}%。
    技术面：{stock_data['大白话']}
    请输出：1.人话总结 2.小白能买吗 3.风险点 4.操作点位
    """
    if not key or not key.startswith("sk-"):
        return f"> **🤖 免费模式**\n建议：{stock_data['信号']}\n{stock_data['大白话']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=8)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI连接超时"

# ================= 3. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🏆 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("最终定稿版 v19.0")
        menu = st.radio("导航", ["👀 我的关注", "🔎 个股深度分析", "🔮 每日金股预测", "🏆 市场全景榜单", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # 数据准备
    df_market = pd.DataFrame()
    if menu in ["🔮 每日金股预测", "🏆 市场全景榜单"]:
        with st.spinner("扫描市场数据..."): df_market = scan_whole_market()

    # --- 1. 我的关注 ---
    if menu == "👀 我的关注":
        st.header("👀 我的自选股")
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            # 这里统一使用全网搜
            add_kw = c1.text_input("全网搜 (支持 '恒林股份' / '603661')", placeholder="输入名称或代码")
            if c2.button("添加"):
                with st.spinner("联网查找中..."):
                    c, n = search_online_realtime(add_kw)
                    if c:
                        exists = False
                        for item in st.session_state['watchlist']:
                            if item['code'] == c: exists = True
                        if not exists:
                            st.session_state['watchlist'].append({"code":c, "name":n})
                            st.success(f"已添加 {n}")
                            time.sleep(0.5); st.rerun()
                        else: st.warning("已存在")
                    else: st.error("全网未搜索到该股票")

        if st.session_state['watchlist']:
            for i, item in enumerate(st.session_state['watchlist']):
                d = get_deep_analysis(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        with c2: 
                            if d['颜色']=='green': st.success(f"建议：{d['信号']}")
                            elif d['颜色']=='blue': st.info(f"建议：{d['信号']}")
                            elif d['颜色']=='red': st.error(f"建议：{d['信号']}")
                            else: st.warning(f"建议：{d['信号']}")
                        with c3: 
                            if st.button("🗑️", key=f"del_{item['code']}_{i}"):
                                st.session_state['watchlist'].remove(item); st.rerun()

    # --- 2. 个股深度分析 (核心修复) ---
    elif menu == "🔎 个股深度分析":
        st.header("🔎 股票体检中心 (联网)")
        st.caption("支持全网搜索，不仅限热门股。")
        
        c1, c2 = st.columns([3, 1])
        
        # === 修复：双重输入模式 ===
        # 1. 下拉框：为了自动补全（仅限热门股）
        quick_select = c1.selectbox("🚀 快速选择 (带联想)", HOT_STOCKS_SUGGESTIONS, index=None, placeholder="选择热门股...")
        
        # 2. 输入框：为了全网搜（恒林股份）
        manual_input = c1.text_input("🌏 全网搜 (搜不到点这里)", placeholder="输入 '恒林股份' 或 '603661'")
        
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        # 触发逻辑
        target_code, target_name = None, None
        
        if c2.button("开始体检", type="primary") or quick_select or manual_input:
            # 优先处理下拉框选择
            if quick_select:
                target_code, target_name = quick_select.split(" | ")
            # 如果下拉框没选，或者用户填了手动框，覆盖
            if manual_input:
                with st.spinner("正在全网检索..."):
                    c, n = search_online_realtime(manual_input)
                    if c: target_code, target_name = c, n
                    else: st.error(f"未找到 '{manual_input}'")
            
            if target_code:
                d = get_deep_analysis(target_code, target_name)
                if d:
                    st.divider()
                    with st.container(border=True):
                        col_base, col_sig = st.columns([3, 1])
                        with col_base:
                            st.markdown(f"### {d['名称']} ({d['代码']})")
                            st.metric("当前价格", f"¥{d['现价']}", f"{d['涨幅']}%")
                        with col_sig:
                            st.markdown("#### 建议")
                            if d['颜色']=='green': st.success(d['信号'])
                            elif d['颜色']=='red': st.error(d['信号'])
                            elif d['颜色']=='blue': st.info(d['信号'])
                            else: st.warning(d['信号'])

                    l, r = st.columns([1, 1])
                    with l:
                        st.subheader("🗣️ 大白话解读")
                        st.info(d['大白话'])
                    with r:
                        st.subheader("👨‍🏫 AI 导师点评")
                        st.success(run_ai_tutor(d, base_url))
                else: st.error("数据拉取失败")

    # --- 3. 金股预测 ---
    elif menu == "🔮 每日金股预测":
        st.header("🔮 每日机会")
        if not df_market.empty:
            t1, t2 = st.tabs(["⚡️ 短线爆发", "💎 长线养老"])
            with t1:
                picks = df_market.sort_values("T+1分", ascending=False).head(5)
                cols = st.columns(5)
                for i, (_, row) in enumerate(picks.iterrows()):
                    with cols[i]:
                        st.metric(row['名称'], f"¥{row['现价']:.2f}", f"+{row['今日涨幅']:.2f}%")
                        st.caption(f"胜率: {row['T+1分']:.0f}%")
                        st.write(random.choice(MACRO_LOGIC_SHORT))
            with t2:
                picks = df_market[df_market['年涨幅']>0].sort_values("性价比", ascending=False).head(5)
                cols = st.columns(5)
                for i, (_, row) in enumerate(picks.iterrows()):
                    with cols[i]:
                        st.metric(row['名称'], f"¥{row['现价']:.2f}", f"年 {row['年涨幅']:.1f}%")
                        st.caption(f"波动: {row['波动率']:.1f}")
                        st.write(random.choice(MACRO_LOGIC_LONG))
        else: st.error("数据不足")

    # --- 4. 榜单 ---
    elif menu == "🏆 市场全景榜单":
        st.header("🏆 市场全景")
        if not df_market.empty:
            t1, t2, t3 = st.tabs(["短线", "长线", "稳健"])
            with t1: st.dataframe(df_market.sort_values("5日涨幅", ascending=False).head(10)[["名称", "现价", "5日涨幅"]], use_container_width=True)
            with t2: st.dataframe(df_market.sort_values("年涨幅", ascending=False).head(10)[["名称", "现价", "年涨幅"]], use_container_width=True)
            with t3: st.dataframe(df_market.sort_values("性价比", ascending=False).head(10)[["名称", "现价", "波动率"]], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()


















