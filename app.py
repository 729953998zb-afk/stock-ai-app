import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import re

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 稳定运行版",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

# 初始化 Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
# 确保 watchlist 是列表且内部没有重复数据 (初始化)
if 'watchlist' not in st.session_state: 
    st.session_state['watchlist'] = [{"code": "600519.SS", "name": "贵州茅台"}]

# ================= 2. 核心算法 =================

def search_online_realtime(keyword):
    """新浪财经实时搜索接口"""
    keyword = keyword.strip()
    if not keyword: return None, None
    
    try:
        url = f"http://suggest3.sinajs.cn/suggest/type=&key={keyword}&name=suggestdata"
        r = requests.get(url, timeout=2)
        content = r.text
        
        if '="' in content:
            data_str = content.split('="')[1].replace('"', '')
            if not data_str: return None, None
            
            parts = data_str.split(',')
            name = parts[0]
            sina_code = parts[3]
            
            if sina_code.startswith("sh"): yahoo_code = sina_code.replace("sh", "") + ".SS"
            elif sina_code.startswith("sz"): yahoo_code = sina_code.replace("sz", "") + ".SZ"
            elif sina_code.startswith("bj"): yahoo_code = sina_code.replace("bj", "") + ".BJ"
            else: return None, None
            
            return yahoo_code, name
    except Exception as e:
        if keyword.isdigit() and len(keyword)==6:
            return (f"{keyword}.SS" if keyword.startswith('6') else f"{keyword}.SZ"), keyword
            
    return None, None

def translate_to_human_language(pct, curr, ma20, ma60, rsi, macd):
    """小白翻译机"""
    advice_list = []
    
    # 1. 看涨跌幅
    if pct > 9: advice_list.append("🔥 **今天涨停了/快涨停了！** 这种时候别追了，容易炸板被套。手里有的拿稳，明天冲高再跑。")
    elif pct > 3: advice_list.append("😍 **今天涨势不错！** 资金进场很坚决，势头正猛。")
    elif pct < -3: advice_list.append("😭 **今天跌得有点惨。** 空头正在宣泄情绪，别急着抄底，小心半山腰。")
    
    # 2. 看均线
    if curr > ma20: advice_list.append("✅ **股价在20日线上方。** 简单说就是趋势是向上的，主力还在，拿着比较安全。")
    else: advice_list.append("⚠️ **股价跌破20日线了。** 说明短期趋势坏了，主力可能在撤退，新手建议观望。")
        
    if curr > ma60 and abs(curr-ma60)/curr < 0.05: advice_list.append("💎 **回踩到了60日生命线。** 这通常是长线资金的买点，性价比很高！")

    # 3. 看 RSI
    if rsi > 75: advice_list.append("🛑 **RSI报警(太贵了)！** 现在买进区就像在山顶站岗，风险很大，建议止盈卖出。")
    elif rsi < 25: advice_list.append("⚡️ **RSI超卖(太便宜了)。** 这里大概率会有反弹，激进的可以试着抢一口肉。")
        
    # 4. 看 MACD
    if macd > 0: advice_list.append("📈 **MACD红柱子。** 说明买的人比卖的人多，上涨动能还在。")
    else: advice_list.append("📉 **MACD绿柱子。** 说明卖压还是很大，还得跌一会儿。")
        
    return "\n\n".join(advice_list)

@st.cache_data(ttl=600)
def get_deep_analysis(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        
        # 计算指标
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
        ma60 = h['MA60'].iloc[-1]
        rsi = h['RSI'].iloc[-1]
        m_val = macd.iloc[-1]
        
        human_text = translate_to_human_language(pct, curr, ma20, ma60, rsi, m_val)
        
        # 信号系统
        signal = "观望"
        color = "gray"
        if rsi > 80: signal, color = "高抛/止盈", "red"
        elif pct < -5 and curr < ma20: signal, color = "止损/卖出", "red"
        elif m_val > 0 and rsi < 70 and curr > h['MA5'].iloc[-1]: signal, color = "短线买入", "green"
        elif curr > ma20: signal, color = "持有", "blue"

        return {
            "代码": code, "名称": name, "现价": round(curr, 2), "涨幅": round(pct, 2),
            "MA20": round(ma20, 2), "RSI": round(rsi, 1), "MACD": round(m_val, 3),
            "信号": signal, "颜色": color, "大白话": human_text
        }
    except: return None

# AI 分析
def run_ai_tutor(stock_data, base_url):
    key = st.session_state['api_key']
    prompt = f"""
    你是一个说话直白、幽默的资深老股民（投资导师）。
    你要给炒股小白分析这只股票：{stock_data['名称']} ({stock_data['代码']})。
    数据如下：现价{stock_data['现价']} (涨幅 {stock_data['涨幅']}%)，均线情况：{stock_data['大白话']}
    请输出一份分析，包含：1.【人话总结】 2.【小白能买吗？】 3.【风险在哪里？】 4.【操作剧本】
    """
    if not key or not key.startswith("sk-"):
        return f"> **🤖 免费模式**\n\n**小白能买吗？**：{stock_data['信号']}\n\n**为什么？**\n{stock_data['大白话']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=10)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI连接超时"

# ================= 3. 界面逻辑 =================

def login_page():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.markdown("<br><br>", unsafe_allow_html=True)
        st.title("🎓 AlphaQuant Pro")
        st.caption("小白也能懂的智能投顾")
        st.info("账号: admin | 密码: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("登录", type="primary", use_container_width=True):
            if u=="admin" and p=="123456": st.session_state['logged_in']=True; st.rerun()

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("稳定性修复版 v17.0")
        menu = st.radio("功能菜单", ["🔎 个股深度分析", "👀 我的关注", "🔮 每日金股预测", "⚙️ 设置"])
        if st.button("退出登录"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. 个股深度分析 ---
    if menu == "🔎 个股深度分析":
        st.header("🔎 股票体检中心")
        c1, c2 = st.columns([3, 1])
        search_kw = c1.text_input("🔍 输入股票 (例如：恒林股份 / 603661)", placeholder="想查什么直接输...")
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        
        if c2.button("开始体检", type="primary") or search_kw:
            with st.spinner(f"正在全网搜索 '{search_kw}'..."):
                code, name = search_online_realtime(search_kw)
                if code:
                    d = get_deep_analysis(code, name)
                    if d:
                        st.divider()
                        with st.container(border=True):
                            col_base, col_sig = st.columns([3, 1])
                            with col_base:
                                st.markdown(f"### {d['名称']} ({d['代码']})")
                                st.metric("当前价格", f"¥{d['现价']}", f"{d['涨幅']}%")
                            with col_sig:
                                st.markdown("#### 📢 建议操作")
                                if d['颜色'] == 'green': st.success(f"**{d['信号']}**")
                                elif d['颜色'] == 'red': st.error(f"**{d['信号']}**")
                                elif d['颜色'] == 'blue': st.info(f"**{d['信号']}**")
                                else: st.warning(f"**{d['信号']}**")

                        l, r = st.columns([1, 1])
                        with l:
                            st.subheader("🗣️ 大白话解读")
                            with st.container(border=True):
                                st.markdown(d['大白话'])
                        with r:
                            st.subheader("👨‍🏫 AI 导师点评")
                            with st.container(border=True):
                                st.markdown(run_ai_tutor(d, base_url))
                    else: st.error("数据拉取失败")
                else: st.error("未找到该股票")

    # --- 2. 我的关注 (核心修复点) ---
    elif menu == "👀 我的关注":
        st.header("👀 我的自选股")
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            add_kw = c1.text_input("输入股票名/代码")
            if c2.button("添加"):
                c, n = search_online_realtime(add_kw)
                if c: 
                    # --- 修复逻辑：检查是否已存在 ---
                    exists = False
                    for item in st.session_state['watchlist']:
                        if item['code'] == c:
                            exists = True
                            break
                    
                    if not exists:
                        st.session_state['watchlist'].append({"code":c, "name":n})
                        st.success(f"已添加 {n}")
                        time.sleep(0.5); st.rerun()
                    else:
                        st.warning(f"{n} 已经在关注列表中了")
                else: st.error("未找到")

        if st.session_state['watchlist']:
            # --- 修复逻辑：使用 enumerate 获取索引 i ---
            # 这样 key=f"del_{item['code']}_{i}" 就能保证唯一，避免报错
            for i, item in enumerate(st.session_state['watchlist']):
                d = get_deep_analysis(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        
                        with c2: 
                            if d['颜色'] == 'green':
                                st.success(f"建议：{d['信号']}")
                            elif d['颜色'] == 'blue':
                                st.info(f"建议：{d['信号']}")
                            elif d['颜色'] == 'red':
                                st.error(f"建议：{d['信号']}")
                            else:
                                st.warning(f"建议：{d['信号']}")
                                
                        with c3: 
                            # 使用索引 i 来构建唯一的 Key，彻底解决 DuplicateElementKey 错误
                            if st.button("🗑️", key=f"del_{item['code']}_{i}"):
                                st.session_state['watchlist'].remove(item)
                                st.rerun()

    # --- 3. 金股预测 ---
    elif menu == "🔮 每日金股预测":
        st.header("🔮 每日机会")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("**🔥 短线爆发**")
            st.metric("赛力斯", "¥98.5", "+3.2%")
            st.caption("资金流入大，趋势向上")
        with c2:
            st.markdown("**💎 长线养老**")
            st.metric("长江电力", "¥25.6", "+0.5%")
            st.caption("每年分红，波动很小")

    # --- 4. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_page()

















