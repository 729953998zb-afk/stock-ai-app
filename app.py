import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import json
import os

# ================= 1. 全局配置 & 数据库初始化 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 账户云同步版",
    layout="wide",
    page_icon="☁️",
    initial_sidebar_state="expanded"
)

# --- 简单的 JSON 数据库系统 ---
DB_FILE = "user_db.json"

def init_db():
    """初始化数据库文件"""
    if not os.path.exists(DB_FILE):
        # 创建默认 admin 账号
        default_data = {
            "admin": {
                "password": "123456",
                "watchlist": [{"code": "600519.SS", "name": "贵州茅台"}]
            }
        }
        with open(DB_FILE, "w", encoding='utf-8') as f:
            json.dump(default_data, f, ensure_ascii=False, indent=4)

def load_db():
    """读取所有用户数据"""
    if not os.path.exists(DB_FILE): init_db()
    try:
        with open(DB_FILE, "r", encoding='utf-8') as f:
            return json.load(f)
    except: return {}

def save_db(data):
    """保存数据到硬盘"""
    with open(DB_FILE, "w", encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

def update_user_watchlist(username, new_watchlist):
    """更新指定用户的关注列表"""
    db = load_db()
    if username in db:
        db[username]['watchlist'] = new_watchlist
        save_db(db)

def register_user(username, password):
    """注册新用户"""
    db = load_db()
    if username in db:
        return False, "用户已存在"
    db[username] = {
        "password": password,
        "watchlist": [] # 新用户默认空列表
    }
    save_db(db)
    return True, "注册成功，请登录"

def verify_login(username, password):
    """验证登录"""
    db = load_db()
    if username not in db: return False, "用户不存在"
    if db[username]['password'] == password:
        return True, db[username]['watchlist']
    return False, "密码错误"

# 初始化数据库
init_db()

# Session 初始化
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ""
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = []

# ================= 2. 核心数据引擎 (复用 v23 逻辑) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

@st.cache_data(ttl=60)
def get_full_market_data():
    """东财全市场扫描"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {"pn": 1, "pz": 5000, "po": 1, "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f12,f14,f2,f3,f62,f20,f8"}
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'market_cap','f8':'turnover'})
        for c in ['price','pct','money_flow','turnover']: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except: return pd.DataFrame()

def search_stock_online(keyword):
    """全网搜索"""
    keyword = keyword.strip()
    if not keyword: return None, None
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        params = {"input": keyword, "type": "14", "token": "D43BF722C8E33BDC906FB84D85E326E8", "count": "5"}
        r = requests.get(url, params=params, timeout=2)
        item = r.json()["QuotationCodeTable"]["Data"][0]
        code = item['Code']; name = item['Name']
        if item['MarketType'] == "1": return f"{code}.SS", name
        elif item['MarketType'] == "2": return f"{code}.SZ", name
        else: return f"{code}.BJ", name
    except: pass
    if keyword.isdigit() and len(keyword)==6: return convert_to_yahoo(keyword), keyword
    return None, None

@st.cache_data(ttl=600)
def analyze_single_stock(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        h['MA20'] = h['Close'].rolling(20).mean()
        ma20 = h['MA20'].iloc[-1]
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        signal, color, advice = "观望", "gray", "趋势不明"
        if rsi > 80: signal, color, advice = "高危 / 卖出", "red", "RSI超买"
        elif (curr-ma20)/ma20 > 0.15: signal, color, advice = "过热预警", "orange", "乖离率过大"
        elif rsi < 45 and curr > ma20 and -2 < pct < 2: signal, color, advice = "潜伏买入", "green", "缩量回踩企稳"
        elif curr > ma20: signal, color, advice = "持有", "blue", "上升通道"

        return {"代码": code, "名称": name, "现价": round(curr,2), "涨幅": round(pct,2), "MA20": round(ma20,2), "RSI": round(rsi,1), "信号": signal, "颜色": color, "建议": advice}
    except: return None

def run_ai_analysis(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['信号']}\n理由：{d['建议']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析{d['名称']}，RSI={d['RSI']}，涨幅{d['涨幅']}%。给出建议。"}]).choices[0].message.content
    except: return "AI超时"

# 策略函数
def scan_for_ambush(df):
    picks = df[(df['pct']>-1.5)&(df['pct']<2.5)&(df['money_flow']>10000000)&(df['price']>3)].sort_values("money_flow", ascending=False).head(15)
    res = []
    for _,r in picks.iterrows():
        try: res.append({"名称":r['name'], "代码":convert_to_yahoo(r['code']), "现价":r['price'], "涨幅":r['pct'], "资金":f"+{r['money_flow']/10000:.0f}万", "逻辑":"主力潜伏吸筹"})
        except: continue
        if len(res)>=5: break
    return res

def scan_for_warnings(df):
    picks = df[(df['turnover']>10)&(df['pct']>5)].sort_values("turnover", ascending=False).head(5)
    res = []
    for _,r in picks.iterrows():
        res.append({"名称":r['name'], "代码":convert_to_yahoo(r['code']), "现价":r['price'], "涨幅":r['pct'], "换手":f"{r['turnover']}%", "逻辑":"高位巨量换手"})
    return res

# ================= 3. 用户认证系统 =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("☁️ AlphaQuant Pro")
        st.caption("账户云同步版 v24.0")
        
        tab1, tab2 = st.tabs(["登录 (Login)", "注册 (Register)"])
        
        with tab1:
            u_login = st.text_input("账号", key="l_u")
            p_login = st.text_input("密码", type="password", key="l_p")
            if st.button("🚀 登录", type="primary", use_container_width=True):
                success, data = verify_login(u_login, p_login)
                if success:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = u_login
                    st.session_state['watchlist'] = data # 加载云端数据
                    st.success(f"欢迎回来，{u_login}！正在同步自选股...")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error(data)
                    
        with tab2:
            u_reg = st.text_input("新账号", key="r_u")
            p_reg = st.text_input("设置密码", type="password", key="r_p")
            p_reg2 = st.text_input("确认密码", type="password", key="r_p2")
            if st.button("✨ 注册并登录", use_container_width=True):
                if p_reg != p_reg2:
                    st.error("两次密码不一致")
                elif not u_reg or not p_reg:
                    st.error("账号密码不能为空")
                else:
                    success, msg = register_user(u_reg, p_reg)
                    if success:
                        st.success("注册成功！请切换到登录页登录。")
                    else:
                        st.error(msg)

# ================= 4. 主程序 =================

def main_app():
    # 侧边栏显示当前用户
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.info(f"👤 当前用户: **{st.session_state['username']}**")
        
        menu = st.radio("功能导航", ["👀 我的关注 (云同步)", "🔮 策略雷达 (潜伏/预警)", "🔎 个股深度", "🏆 市场全景", "⚙️ 设置"])
        
        if st.button("退出登录"):
            st.session_state['logged_in'] = False
            st.session_state['username'] = ""
            st.session_state['watchlist'] = []
            st.rerun()

    df_full = pd.DataFrame()
    if menu in ["🔮 策略雷达 (潜伏/预警)", "🏆 市场全景"]:
        with st.spinner("连接交易所数据中..."):
            df_full = get_full_market_data()
            if df_full.empty: st.error("数据源异常"); st.stop()

    # --- 1. 我的关注 (带云同步) ---
    if menu == "👀 我的关注 (云同步)":
        st.header("👀 我的自选股 (已云端备份)")
        
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            k = c1.text_input("搜全网 (如 恒林股份)")
            if c2.button("添加"):
                c, n = search_stock_online(k)
                if c:
                    exists = any(i['code'] == c for i in st.session_state['watchlist'])
                    if not exists: 
                        # 更新 Session
                        st.session_state['watchlist'].append({"code":c, "name":n})
                        # 【核心】同步到数据库
                        update_user_watchlist(st.session_state['username'], st.session_state['watchlist'])
                        
                        st.success(f"已添加 {n} 并同步至云端"); time.sleep(0.5); st.rerun()
                    else: st.warning("已存在")
                else: st.error("未找到")

        if st.session_state['watchlist']:
            for i, item in enumerate(st.session_state['watchlist']):
                d = analyze_single_stock(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['名称']}**"); st.caption(d['代码'])
                        with c2: 
                            if d['颜色']=='green': st.success(f"建议：{d['信号']}")
                            elif d['颜色']=='red': st.error(f"建议：{d['信号']}")
                            else: st.info(f"建议：{d['信号']}")
                            st.caption(d['建议'])
                        with c3: 
                            if st.button("🗑️", key=f"del_{i}"):
                                # 更新 Session
                                st.session_state['watchlist'].remove(item)
                                # 【核心】同步到数据库
                                update_user_watchlist(st.session_state['username'], st.session_state['watchlist'])
                                st.rerun()
        else:
            st.info("暂无关注。添加的股票会自动保存到您的账号中。")

    # --- 2. 策略雷达 ---
    elif menu == "🔮 策略雷达 (潜伏/预警)":
        st.header("🔮 智能策略雷达")
        t1, t2 = st.tabs(["🌱 潜伏机会 (买)", "⚠️ 高危预警 (卖)"])
        with t1:
            st.info("筛选：价格横盘 + 主力资金大买")
            picks = scan_for_ambush(df_full)
            if picks:
                cols = st.columns(5)
                for i, (col, p) in enumerate(zip(cols, picks)):
                    with col:
                        st.markdown(f"**{p['名称']}**")
                        st.metric(f"¥{p['现价']}", f"{p['涨幅']}%")
                        st.markdown(f":red[{p['资金']}]")
                        st.success("潜伏")
            else: st.warning("无机会")
        with t2:
            st.error("筛选：高位放量滞涨")
            risks = scan_for_warnings(df_full)
            if risks:
                cols = st.columns(5)
                for i, (col, p) in enumerate(zip(cols, risks)):
                    with col:
                        st.markdown(f"**{p['名称']}**")
                        st.metric(f"¥{p['现价']}", f"{p['涨幅']}%", delta_color="inverse")
                        st.markdown(f"换手: {p['换手']}")
                        st.error("预警")

    # --- 3. 个股深度 ---
    elif menu == "🔎 个股深度":
        st.header("🔎 个股全维透视")
        c1, c2 = st.columns([3,1])
        k = c1.text_input("全网搜")
        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
        if c2.button("分析") or k:
            c, n = search_stock_online(k)
            if c:
                d = analyze_single_stock(c, n)
                if d:
                    st.divider()
                    m1,m2,m3 = st.columns(3)
                    m1.metric(d['名称'], f"¥{d['现价']}", f"{d['涨幅']}%")
                    m2.metric("RSI", d['RSI'])
                    m3.metric("信号", d['信号'])
                    st.info(run_ai_analysis(d, base_url))
                else: st.error("数据错误")
            else: st.error("未找到")

    # --- 4. 市场全景 ---
    elif menu == "🏆 市场全景":
        st.header("🏆 实时全景")
        t1, t2 = st.tabs(["涨幅榜", "资金榜"])
        with t1: st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(15)[['code','name','price','pct']], use_container_width=True)
        with t2: st.dataframe(df_full.sort_values("money_flow",ascending=False).head(15)[['code','name','price','money_flow']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()






















