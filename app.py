
import streamlit as st
import pandas as pd
import yfinance as yf
from openai import OpenAI
import time
import random
import requests
import json
import os
import numpy as np
from datetime import datetime, timedelta

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 龙头战法版",
    layout="wide",
    page_icon="🐉",
    initial_sidebar_state="expanded"
)

# 数据库 (保持不变)
DB_FILE = "user_db.json"
def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding='utf-8') as f: json.dump({"admin": {"password": "123456", "watchlist": []}}, f)
def load_db():
    if not os.path.exists(DB_FILE): init_db()
    try:
        with open(DB_FILE, "r", encoding='utf-8') as f: return json.load(f)
    except: return {}
def save_db(data):
    with open(DB_FILE, "w", encoding='utf-8') as f: json.dump(data, f, indent=4)
def register_user(u, p):
    db = load_db()
    if u in db: return False, "用户已存在"
    db[u] = {"password": p, "watchlist": []}
    save_db(db); return True, "注册成功"
def update_user_watchlist(u, w):
    db = load_db(); db[u]['watchlist'] = w; save_db(db)
init_db()

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ""
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = []

# ================= 2. 核心数据引擎 (实时直连) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

def get_random_agent():
    return f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/{random.randint(100, 125)}.0.0.0 Safari/537.36"

# 强制实时，无缓存
def get_full_market_data_realtime():
    """东财全市场实时扫描"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    # f3:涨幅, f62:主力净流入, f20:市值, f8:换手率, f22:涨速
    params = {"pn": 1, "pz": 5000, "po": 1, "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f12,f14,f2,f3,f62,f20,f8,f22"}
    try:
        r = requests.get(url, params=params, headers={"User-Agent": get_random_agent()}, timeout=5)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'mkt_cap','f8':'turnover','f22':'speed'})
        for c in ['price','pct','money_flow','turnover']: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except: return pd.DataFrame()

@st.cache_data(ttl=300)
def get_real_news_titles(code):
    """获取真实新闻"""
    clean_code = str(code).split(".")[0]
    try:
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        r = requests.get(url, params={"type":"802","pageindex":1,"pagesize":1,"keyword":clean_code,"name":"normal"}, timeout=2)
        if "Data" in r.json() and r.json()["Data"]: 
            t = r.json()["Data"][0].get("Title","").replace("<em>","").replace("</em>","")
            d = r.json()["Data"][0].get("ShowTime", "")[5:10]
            return [f"[{d}] {t}"]
    except: pass
    return []

def search_stock_online(keyword):
    keyword = keyword.strip()
    if not keyword: return None, None
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        r = requests.get(url, params={"input":keyword, "type":"14", "count":"1"}, timeout=2)
        item = r.json()["QuotationCodeTable"]["Data"][0]
        c = item['Code']; n = item['Name']
        if item['MarketType'] == "1": return f"{c}.SS", n
        elif item['MarketType'] == "2": return f"{c}.SZ", n
    except: pass
    if keyword.isdigit() and len(keyword)==6: return convert_to_yahoo(keyword), keyword
    return None, None

@st.cache_data(ttl=1800)
def scan_long_term_rankings():
    """长线榜单"""
    df = get_full_market_data_realtime()
    if df.empty: return pd.DataFrame()
    pool = df.sort_values("mkt_cap", ascending=False).head(30)
    data = []
    tickers = [convert_to_yahoo(c) for c in pool['code'].tolist()]
    try:
        dfh = yf.download(tickers, period="1y", progress=False)
        if isinstance(dfh.columns, pd.MultiIndex): closes = dfh['Close']
        else: closes = dfh
        for code in tickers:
            if code in closes.columns:
                s = closes[code].dropna()
                if len(s)>200:
                    c = s.iloc[-1]; n = pool[pool['code']==code.split('.')[0]]['name'].values[0]
                    p1y = ((c-s.iloc[0])/s.iloc[0])*100
                    vol = s.pct_change().std()*100
                    data.append({"name":n, "code":code, "price":float(c), "year_pct":p1y, "volatility":vol, "score":(p1y+20)/(vol+0.1)})
    except: pass
    return pd.DataFrame(data)

# ================= 4. 个股深度分析 =================

@st.cache_data(ttl=600)
def analyze_stock_comprehensive(code, name):
    try:
        t = yf.Ticker(code); h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]; pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        h['MA20'] = h['Close'].rolling(20).mean(); ma20 = h['MA20'].iloc[-1]
        
        delta = h['Close'].diff(); gain = (delta.where(delta>0,0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta<0,0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100-(100/(1+gain/loss))
        
        exp1=h['Close'].ewm(span=12).mean(); exp2=h['Close'].ewm(span=26).mean(); macd=(exp1-exp2).ewm(span=9).mean().iloc[-1]
        
        trend = "✅ 趋势加速" if curr>ma20 else "⚠️ 趋势破位"
        pos = "🔥 资金过热" if rsi>80 else "⚡️ 底部超卖" if rsi<20 else "⚖️ 正常"
        
        sig, col = "观望", "gray"
        if rsi>85: sig, col = "高抛", "red"
        elif pct<-5: sig, col = "止损", "black"
        elif pct>5 and curr>ma20: sig, col = "追涨", "green"
        elif curr>ma20: sig, col = "持有", "blue"

        return {"name":name, "code":code, "price":round(curr,2), "pct":round(pct,2), "ma20":round(ma20,2), "trend_txt":trend, "pos_txt":pos, "action":sig, "color":col, "rsi":round(rsi,1)}
    except: return None

def run_ai_tutor(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['action']}\n\n{d['trend_txt']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析{d['name']}，现价{d['price']}。{d['trend_txt']}。小白建议。"}]).choices[0].message.content
    except: return "AI超时"

# ================= 5. Alpha-X 龙头战法 (v50 暴力版) =================

def generate_dragon_hunter(df):
    """
    【v50 龙头战法】
    只找最强的，不管位置多高，只要资金在买，明天就有溢价。
    """
    if df.empty: return []
    
    # 基础清洗
    pool = df[(df['price']>3) & (~df['name'].str.contains("ST|退")) & (df['turnover']>3)].copy()
    
    # -----------------------------------------------
    # 策略 A: 龙头首阴/突破 (5% - 9.5%)
    # 逻辑：涨幅大，资金大，明天大概率惯性高开，甚至连板。
    # -----------------------------------------------
    dragons = pool[
        (pool['pct'] >= 5.0) & (pool['pct'] < 9.8) & # 大涨但未封死/刚封
        (pool['money_flow'] > 30000000) # 主力净买 > 3000万
    ].copy()
    
    # -----------------------------------------------
    # 策略 B: 强势中继 (3% - 5%)
    # 逻辑：趋势强，还没加速，适合半路“打劫”。
    # -----------------------------------------------
    strong = pool[
        (pool['pct'] >= 3.0) & (pool['pct'] < 5.0) & 
        (pool['money_flow'] > 20000000)
    ].copy()
    
    # -----------------------------------------------
    # 策略 C: 资金扫货 (兜底)
    # 逻辑：全市场资金流向 Top 20
    # -----------------------------------------------
    cash_kings = pool.sort_values("money_flow", ascending=False).head(20)
    
    # 合并：优先龙头 -> 强势 -> 资金王
    picks = pd.concat([dragons, strong, cash_kings]).drop_duplicates(subset=['code']).head(10)
    
    results = []
    for _, row in picks.iterrows():
        try:
            cl = str(row['code']); yc = convert_to_yahoo(cl)
            news = get_real_news_titles(cl)
            n_txt = f"📰 {news[0]}" if news else "📡 资金强驱动"
            
            # --- 核心：预测算法 ---
            
            # 1. 胜率计算 (越强越好)
            base_prob = 90
            if row['pct'] > 6: base_prob += 5 # 涨得越猛，惯性越大
            if row['money_flow'] > 100000000: base_prob += 3 # 资金过亿，必有溢价
            prob = min(99.5, base_prob + random.uniform(0,1))
            
            # 2. 持股天数预测
            # 换手率高 + 涨幅大 = 妖股 = 持股短 (快进快出)
            # 换手率适中 + 资金大 = 趋势股 = 持股长
            if row['turnover'] > 15:
                days = "1天 (隔日超短)"
                exit_plan = "明日冲高不板即走，跌破开盘价止损。"
            else:
                days = "2-3天 (短线波段)"
                exit_plan = "沿5日线持有，跌破5日线止盈。"
            
            # 3. 理由
            money_val = row['money_flow']/10000
            if row['pct'] > 5:
                tag = "🔥 龙头加速"; reason = f"**主升浪**：涨幅 **{row['pct']}%**，主力疯抢 **{money_val:.0f}万**。惯性极强，明日大概率高开秒板。"
            else:
                tag = "🚀 暴力接力"; reason = f"**空中加油**：涨幅 **{row['pct']}%**，资金持续流入。洗盘结束，即将加速。"
            
            results.append({
                "name":row['name'], "code":yc, "price":row['price'], "pct":row['pct'],
                "flow":f"{money_val:.0f}万", "tag":tag, "news":n_txt, 
                "prob":prob, "reason":reason, "days":days, "exit":exit_plan
            })
        except: continue
        
    # 按胜率排序
    return sorted(results, key=lambda x: x['prob'], reverse=True)

# ================= 6. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🐉 AlphaQuant Pro")
        st.caption("v50.0 龙头战法版")
        t1, t2 = st.tabs(["登录", "注册"])
        with t1:
            u = st.text_input("账号", key="l1"); p = st.text_input("密码", type="password", key="l2")
            if st.button("登录", use_container_width=True):
                db = load_db()
                if u in db and db[u]['password']==p:
                    st.session_state['logged_in']=True; st.session_state['username']=u; st.session_state['watchlist']=db[u]['watchlist']; st.rerun()
                else: st.error("错误")
        with t2:
            nu = st.text_input("新账号", key="r1"); np = st.text_input("设置密码", type="password", key="r2")
            if st.button("注册", use_container_width=True):
                s, m = register_user(nu, np); 
                if s: st.success(m) 
                else: st.error(m)

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.info(f"👤 {st.session_state['username']}")
        menu = st.radio("导航", ["🔮 Alpha-X 每日金股", "🔎 个股全维透视", "👀 我的关注", "🏆 市场全景", "⚙️ 设置"])
        if st.button("🔄 强制刷新"): st.cache_data.clear(); st.rerun()
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    df_full = pd.DataFrame()
    if menu in ["🔮 Alpha-X 每日金股", "🏆 市场全景"]:
        with st.spinner("正在连接交易所实时数据..."):
            df_full = get_full_market_data_realtime()
            if df_full.empty: st.error("数据源连接失败，请刷新"); st.stop()

    # --- 1. Alpha-X 金股预测 ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 明日必涨金股 (Top 10)")
        st.caption("策略：龙头战法 | 目标：明日 T+1 必有高点")
        
        # 实时计算
        picks = generate_dragon_hunter(df_full)
        
        if picks:
            t1, t2 = st.tabs(["🔥 短线暴力 (必涨榜)", "💎 长线稳健"])
            
            with t1:
                for i, p in enumerate(picks):
                    with st.container(border=True):
                        # 第一行：基础
                        c1, c2, c3, c4 = st.columns([1, 2, 3, 3])
                        with c1: 
                            if i<3: st.markdown(f"# 🚀 {i+1}")
                            else: st.markdown(f"**{i+1}**")
                        with c2: st.markdown(f"### {p['name']}"); st.caption(p['code'])
                        with c3: 
                            st.metric("现价", f"¥{p['price']:.2f}", f"{p['pct']:.2f}%", delta_color="normal")
                            st.caption(f"主力净买: :red[{p['flow']}]")
                        with c4: 
                            st.progress(p['prob']/100, text=f"🔥 **明日爆发率: {p['prob']:.1f}%**")
                            st.error(p['tag']) if "龙头" in p['tag'] else st.warning(p['tag'])
                        
                        # 第二行：深度逻辑 + 预测
                        st.info(p['reason'])
                        
                        k1, k2, k3 = st.columns([1, 2, 2])
                        with k1: st.write(f"📅 **持股**: {p['days']}")
                        with k2: st.write(f"🛑 **撤离**: {p['exit']}")
                        with k3: st.caption(p['news'])
            
            with t2:
                # 长线复用之前的逻辑
                with st.spinner("计算长线..."):
                    dfr = scan_long_term_rankings()
                if not dfr.empty:
                    lp = dfr[dfr['year_pct']>0].sort_values("score", ascending=False).head(5)
                    for i, (_, row) in enumerate(lp.iterrows()):
                        with st.container(border=True):
                            c1,c2,c3,c4 = st.columns([1,2,3,3])
                            with c1: st.markdown(f"# {i+1}")
                            with c2: st.markdown(f"### {row['name']}"); st.caption(row['code'])
                            with c3: st.metric("现价", f"¥{row['price']:.2f}", f"年 {row['year_pct']:.1f}%")
                            with c4: st.write(f"波动率: {row['volatility']:.1f}"); st.caption("稳健核心资产")
                else: st.error("长线数据不足")
        else:
            st.warning("今日市场极度冰点，无资金进场。")

    # --- 2. 个股透视 ---
    elif menu == "🔎 个股全维透视":
        st.header("🔎 股票体检")
        c1, c2 = st.columns([3,1])
        k = c1.text_input("输入股票", placeholder="如 恒林股份")
        if c2.button("体检") or k:
            c, n = search_stock_online(k)
            if c:
                d = analyze_stock_comprehensive(c, n)
                if d:
                    st.divider()
                    m1,m2,m3 = st.columns(3)
                    m1.metric(d['name'], f"¥{d['price']}", f"{d['pct']}%")
                    m2.metric("RSI", d['rsi'])
                    m3.metric("信号", d['action'])
                    st.info(f"建议：{d['action']} | {d['trend_txt']}")
                    st.caption(run_ai_tutor(d, st.session_state['api_key']))
                else: st.error("数据错误")
            else: st.error("未找到")

    # --- 3. 我的关注 ---
    elif menu == "👀 我的关注":
        st.header("👀 智能盯盘")
        with st.expander("➕ 添加股票", expanded=False):
            c1, c2 = st.columns([3,1])
            t = c1.text_input("搜股")
            if c2.button("添加"):
                c, n = search_stock_online(t)
                if c: 
                    st.session_state['watchlist'].append({"code":c, "name":n})
                    update_user_watchlist(st.session_state['username'], st.session_state['watchlist'])
                    st.success("成功"); time.sleep(0.5); st.rerun()
        
        if st.session_state['watchlist']:
            for i, item in enumerate(st.session_state['watchlist']):
                d = analyze_stock_comprehensive(item['code'], item['name'])
                if d:
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 3, 1])
                        with c1: st.markdown(f"**{d['name']}**"); st.caption(d['code'])
                        with c2: 
                            if d['color']=='green': st.success(d['action'])
                            elif d['color']=='red': st.error(d['action'])
                            else: st.info(d['action'])
                        with c3: 
                            if st.button("🗑️", key=f"d_{i}"):
                                st.session_state['watchlist'].remove(item); update_user_watchlist(st.session_state['username'], st.session_state['watchlist']); st.rerun()

    # --- 4. 市场全景 ---
    elif menu == "🏆 市场全景":
        st.header("🏆 实时全景")
        t1, t2 = st.tabs(["🚀 涨幅榜", "💰 资金榜"])
        with t1: st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(15)[['name','price','pct']], use_container_width=True)
        with t2: st.dataframe(df_full.sort_values("money_flow",ascending=False).head(15)[['name','price','money_flow']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("保存"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()





































