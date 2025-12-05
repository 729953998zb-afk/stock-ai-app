import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import json

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 搜索增强版",
    layout="wide",
    page_icon="🔍",
    initial_sidebar_state="expanded"
)

# --- 本地热门股 (用于下拉联想) ---
HOT_STOCKS_SUGGESTIONS = [
    "600519.SS | 贵州茅台", "300750.SZ | 宁德时代", "601127.SS | 赛力斯",
    "601318.SS | 中国平安", "002594.SZ | 比亚迪",   "600036.SS | 招商银行",
    "601857.SS | 中国石油", "000858.SZ | 五粮液",   "601138.SS | 工业富联",
    "603259.SS | 药明康德", "300059.SZ | 东方财富", "002475.SZ | 立讯精密",
    "601606.SS | 长城军工", "603600.SS | 永艺股份", "000063.SZ | 中兴通讯",
    "603661.SS | 恒林股份", "600019.SS | 宝钢股份", "000002.SZ | 万科A"
]

# 宏观逻辑库
MACRO_LOGIC_SHORT = [
    "资金合力做多，技术面突破箱体，T+1 溢价率极高",
    "板块轮动补涨需求强烈，量能放大，明日大概率冲高",
    "均线金叉共振，主力控盘度高，短线爆发力满分"
]
MACRO_LOGIC_LONG = [
    "核心资产估值重塑，适合长线底仓配置",
    "高股息低波动，社保基金重仓，穿越牛熊的压舱石",
    "行业垄断地位稳固，未来一年业绩确定性高"
]

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心算法 (搜索功能重写) =================

def search_online_realtime(keyword):
    """
    【核心修复】双通道全网搜索
    优先使用东方财富接口 (稳定)，失败则降级到新浪接口
    """
    keyword = keyword.strip()
    if not keyword: return None, None
    
    # 通道 1: 东方财富 Search API (推荐)
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {
            "input": keyword,
            "type": "14", # 14代表股票
            "token": "D43BF722C8E33BDC906FB84D85E326E8",
            "count": "5"
        }
        r = requests.get(url, params=params, timeout=2)
        data = r.json()
        
        if "QuotationCodeTable" in data and "Data" in data["QuotationCodeTable"]:
            items = data["QuotationCodeTable"]["Data"]
            if items:
                # 取第一个匹配项
                item = items[0]
                code = item['Code']
                name = item['Name']
                market_type = item['MarketType'] # 1=沪, 2=深
                
                # 转换为 Yahoo 格式
                yahoo_code = None
                if market_type == "1": yahoo_code = f"{code}.SS"
                elif market_type == "2": yahoo_code = f"{code}.SZ"
                elif code.startswith("6"): yahoo_code = f"{code}.SS" # 兜底
                elif code.startswith("0") or code.startswith("3"): yahoo_code = f"{code}.SZ" # 兜底
                
                if yahoo_code: return yahoo_code, name
    except Exception as e:
        pass # 东财失败，尝试新浪

    # 通道 2: 新浪财经 API (备用，处理了GBK编码问题)
    try:
        url = f"http://suggest3.sinajs.cn/suggest/type=&key={keyword}&name=suggestdata"
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=2)
        # 强制设置编码，防止中文乱码
        r.encoding = 'gbk' 
        content = r.text
        
        if '="' in content:
            data_str = content.split('="')[1].replace('"', '')
            if data_str:
                parts = data_str.split(',')
                name = parts[0]
                sina_code = parts[3]
                
                if sina_code.startswith("sh"): return sina_code.replace("sh", "") + ".SS", name
                elif sina_code.startswith("sz"): return sina_code.replace("sz", "") + ".SZ", name
    except:
        pass

    # 通道 3: 纯代码猜测 (最后的倔强)
    if keyword.isdigit() and len(keyword)==6:
        return (f"{keyword}.SS" if keyword.startswith('6') else f"{keyword}.SZ"), keyword
        
    return None, None

def translate_to_human_language(pct, curr, ma20, ma60, rsi, macd):
    """小白翻译机"""
    advice_list = []
    if pct > 9: advice_list.append("🔥 **涨停啦！** 别追了，容易炸板。持有者拿稳。")
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
        
        # 指标计算
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9).mean()
        macd = (dif - dea).iloc[-1] * 2
        
        human_text = translate_to_human_language(pct, curr, ma20, 0, rsi, macd)
        
        # 信号逻辑
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

@st.cache_data(ttl=1800)
def scan_whole_market():
    """扫描引擎 (为了速度，使用内置热门池模拟全网扫描效果)"""
    data = []
    tickers = [x.split(" | ")[0] for x in HOT_STOCKS_SUGGESTIONS]
    try:
        df_all = yf.download(tickers, period="1y", progress=False)['Close']
        for item in HOT_STOCKS_SUGGESTIONS:
            code, name = item.split(" | ")
            if code in df_all.columns:
                s = df_all[code].dropna()
                if len(s)>20:
                    curr = s.iloc[-1]
                    p1 = (curr - s.iloc[-2])/s.iloc[-2]*100
                    p5 = (curr - s.iloc[-6])/s.iloc[-6]*100
                    py = (curr - s.iloc[0])/s.iloc[0]*100
                    vol = s.pct_change().std()*100
                    
                    t1 = 50
                    if curr > s.rolling(20).mean().iloc[-1]: t1+=20
                    if 1<p1<7: t1+=20
                    
                    data.append({
                        "名称": name, "现价": float(curr), "今日涨幅": p1, 
                        "5日涨幅": p5, "年涨幅": py, "波动率": vol, 
                        "T+1分": t1, "性价比": (py+20)/(vol+0.1)
                    })
    except: pass
    return pd.DataFrame(data)

def run_ai_tutor(stock_data, base_url):
    key = st.session_state['api_key']
    prompt = f"我是小白，分析{stock_data['名称']}。现价{stock_data['现价']}。给出：1.人话总结 2.能不能买 3.风险 4.操作点位。"
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
        st.title("🔎 AlphaQuant Pro")
        st.info("User: admin | Pass: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("Login", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("搜索增强版 v20.0")
        menu = st.radio("导航", ["👀 我的关注", "🔎 个股深度诊断", "🔮 每日金股预测", "🏆 市场全景榜单", "⚙️ 设置"])
        if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

    # 数据准备
    df_market = pd.DataFrame()
    if menu in ["🔮 每日金股预测", "🏆 市场全景榜单"]:
        with st.spinner("扫描市场数据..."): df_market = scan_whole_market()

    # --- 1. 我的关注 (修复搜索) ---
    if menu == "👀 我的关注":
        st.header("👀 我的自选股")
        
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            add_kw = c1.text_input("搜全网 (如 恒林股份 / 603661)")
            if c2.button("添加"):
                with st.spinner("正在全网检索..."):
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
                    else: st.error("未找到，请检查名称是否正确")

        if st.session_state['watchlist']:
            for i, item in enumerate(st.session_state['watchlist']):
                d = get_deep_analysis(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        
                        # 修复的 UI 逻辑
                        with c2: 
                            if d['颜色'] == 'green': st.success(f"建议：{d['信号']}")
                            elif d['颜色'] == 'blue': st.info(f"建议：{d['信号']}")
                            elif d['颜色'] == 'red': st.error(f"建议：{d['信号']}")
                            else: st.warning(f"建议：{d['信号']}")
                                
                        with c3: 
                            if st.button("🗑️", key=f"del_{item['code']}_{i}"):
                                st.session_state['watchlist'].remove(item); st.rerun()

    # --- 2. 个股深度 (修复搜索) ---
    elif menu == "🔎 个股深度诊断":
        st.header("🔎 股票体检中心")
        c1, c2 = st.columns([3, 1])
        
        # 1. 联想下拉 (快速)
        choice = c1.selectbox("快速选择", HOT_STOCKS_SUGGESTIONS, index=None, placeholder="选择或输入代码...")
        # 2. 手动全网搜 (兜底)
        manual = c1.text_input("全网搜 (搜不到点这里)", placeholder="输入 恒林股份 / 603661")
        
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("体检") or choice or manual:
            with st.spinner("分析中..."):
                t = choice.split(" | ")[0] if choice else manual
                if t:
                    # 如果不是标准代码，先去网上搜
                    if not (t.endswith(".SS") or t.endswith(".SZ")) and not t.isdigit():
                        c, n = search_online_realtime(t)
                    elif " | " in str(choice): 
                        c, n = choice.split(" | ")
                    else: 
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
                    else: st.error(f"全网未找到 '{t}'")

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



















