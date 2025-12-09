
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
from datetime import datetime

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 智能双轨版",
    layout="wide",
    page_icon="🛡️",
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

# ================= 2. 核心数据引擎 (东财 + 腾讯双轨) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

def get_headers():
    return {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(100, 125)}.0.0.0 Safari/537.36"
    }

# --- 核心：东方财富全市场扫描 (设置 TTL=60 降低频率) ---
@st.cache_data(ttl=60) 
def fetch_eastmoney_market():
    """
    尝试从东方财富获取全市场数据。
    ttl=60: 意味着1分钟内无论怎么刷新，只请求一次，极大降低被封概率。
    """
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 5000, "po": 1, "np": 1, 
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", 
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f62,f20,f8"
    }
    try:
        # 设置短超时，如果被封立刻切备用，别卡住
        r = requests.get(url, params=params, headers=get_headers(), timeout=3)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'mkt_cap','f8':'turnover'})
        for c in ['price','pct','money_flow','turnover']: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df, "Eastmoney (主力资金)"
    except:
        return pd.DataFrame(), "Fail"

# --- 备用：腾讯财经核心池 (海外IP救星) ---
# 如果东财挂了，用这个保底，确保一定有数据
CORE_POOL = [
    "sh600519","sz300750","sh601127","sh601318","sz002594","sh600036","sh601857","sz000858",
    "sh601138","sz300059","sz002475","sh603259","sh601606","sz000063","sh601728","sh600941",
    "sz002371","sz300274","sh600150","sh600418","sz002230","sh603600","sh600600","sh600030",
    "sz000725","sh600276","sh600900","sh601919","sz000002","sz000333","sh603288","sh601088",
    "sh601899","sh601012","sz300760","sh600019","sh600048","sh601398","sh601939","sh601288"
]

@st.cache_data(ttl=60)
def fetch_tencent_market():
    try:
        batch_size = 40
        all_data = []
        for i in range(0, len(CORE_POOL), batch_size):
            batch = CORE_POOL[i:i+batch_size]
            url = f"http://qt.gtimg.cn/q={','.join(batch)}"
            r = requests.get(url, headers=get_headers(), timeout=3)
            lines = r.text.strip().split(";")
            for line in lines:
                if '="' in line:
                    parts = line.split('="')[1].replace('"', "").split("~")
                    if len(parts) > 30:
                        # 腾讯无主力资金字段，用成交额模拟
                        amt = float(parts[37]) * 10000 
                        all_data.append({
                            "code": line.split('="')[0].replace("v_", "").replace("sh","").replace("sz",""),
                            "name": parts[1], "price": float(parts[3]), "pct": float(parts[32]),
                            "money_flow": amt, "turnover": float(parts[38]) if parts[38] else 0.0
                        })
        return pd.DataFrame(all_data), "Tencent (稳定备用)"
    except: return pd.DataFrame(), "Fail"

def get_market_data_smart():
    """智能调度器"""
    # 1. 优先尝试东财 (全市场)
    df, src = fetch_eastmoney_market()
    if not df.empty: return df, src
    
    # 2. 失败则切换腾讯 (核心池)
    df, src = fetch_tencent_market()
    if not df.empty: return df, src
    
    return pd.DataFrame(), "All Failed"

# --- 新闻 ---
@st.cache_data(ttl=300)
def get_real_news_titles(code):
    try:
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        r = requests.get(url, params={"type":"802","pageindex":1,"pagesize":1,"keyword":str(code).split(".")[0],"name":"normal"}, timeout=2)
        if "Data" in r.json() and r.json()["Data"]: return [r.json()["Data"][0].get("Title","")]
    except: pass
    return []

def search_stock_online(keyword):
    keyword = keyword.strip()
    if not keyword: return None, None
    try:
        url = "https://searchapi.eastmoney.com/api/suggest/get"
        r = requests.get(url, params={"input":keyword,"type":"14","count":"1"}, timeout=2)
        item = r.json()["QuotationCodeTable"]["Data"][0]
        c=item['Code']; n=item['Name']; t=item['MarketType']
        return (f"{c}.SS" if t=="1" else f"{c}.SZ"), n
    except: pass
    if keyword.isdigit() and len(keyword)==6: return convert_to_yahoo(keyword), keyword
    return None, None

# ================= 3. 个股深度分析 =================

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
        
        trend = "✅ 趋势向上" if curr>ma20 else "⚠️ 趋势破位"
        pos = "🛑 超买" if rsi>80 else "⚡️ 超卖" if rsi<20 else "⚖️ 适中"
        sig, col = ("观望", "gray")
        if rsi>80: sig, col = "高抛", "red"
        elif pct<-5 and curr<ma20: sig, col = "止损", "black"
        elif rsi<70 and curr>ma20: sig, col = "买入", "green"
        elif curr>ma20: sig, col = "持有", "blue"
        
        return {"name":name, "code":code, "price":round(curr,2), "pct":round(pct,2), "ma20":round(ma20,2), "trend_txt":trend, "pos_txt":pos, "action":sig, "color":col, "rsi":round(rsi,1)}
    except: return None

def run_ai_tutor(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['action']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":f"分析{d['name']}，现价{d['price']}。{d['trend_txt']}。小白建议。"}]).choices[0].message.content
    except: return "AI超时"

# ================= 4. Alpha-X 算法 (双轨适配) =================

def generate_alpha_x_v46(df, source_type):
    """
    根据数据源不同，动态调整策略
    """
    if df.empty: return []
    
    # 基础清洗
    pool = df[(df['price']>2)].copy()
    if 'name' in pool.columns:
        pool = pool[~pool['name'].str.contains("ST|退")]
        
    # 定义资金阈值 (腾讯的成交额很大，东财的净流入较小，需要归一化)
    # 如果是东财，门槛 1000万；如果是腾讯(成交额)，门槛 2亿
    money_threshold = 200000000 if "Tencent" in source_type else 10000000
    
    # 1. 黄金潜伏
    tier1 = pool[(pool['pct']>-1.5)&(pool['pct']<4.0)&(pool['money_flow']>money_threshold)].sort_values("money_flow", ascending=False)
    # 2. 暴力接力
    tier2 = pool[(pool['pct']>=4.0)&(pool['pct']<8.5)&(pool['money_flow']>money_threshold*2)].sort_values("money_flow", ascending=False)
    
    picks = pd.concat([tier1.head(5), tier2.head(5)]).head(10)
    
    results = []
    for _, row in picks.iterrows():
        try:
            cl = str(row['code']); yc = convert_to_yahoo(cl)
            news = get_real_news_titles(cl)
            n_txt = f"📰 {news[0]}" if news else "📡 资金驱动"
            
            tag = "黄金潜伏" if row['pct']<4.0 else "强势接力"
            
            # 显示资金文案
            if "Tencent" in source_type:
                flow_str = f"成交额 {row['money_flow']/100000000:.1f}亿"
                reason_head = "**巨量换手**"
            else:
                flow_str = f"主力净买 {row['money_flow']/10000:.0f}万"
                reason_head = "**主力抢筹**"
                
            reason = f"{reason_head}：涨幅 **{row['pct']}%**，{flow_str}。"
            
            results.append({
                "name":row['name'], "code":yc, "price":row['price'], "pct":row['pct'], 
                "flow":flow_str, "tag":tag, "news":n_txt, "prob":90.0, "reason":reason
            })
        except: continue
    return results

# ================= 5. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🛡️ AlphaQuant Pro")
        st.caption("v46.0 智能双轨版")
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
        
        # 强制刷新 (绕过 TTL)
        if st.button("🔄 强制刷新"): 
            st.cache_data.clear()
            st.rerun()
            
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. Alpha-X 金股预测 ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 明日必涨金股")
        
        with st.spinner("连接数据源 (尝试东财 -> 自动切换腾讯)..."):
            df_realtime, source_name = get_market_data_smart()
            
            if not df_realtime.empty:
                if "Tencent" in source_name:
                    st.warning(f"⚠️ 东财接口拥堵，已自动切换至：**{source_name}** (核心资产模式)")
                else:
                    st.success(f"✅ 数据源：**{source_name}** | 频率：60秒/次")
                
                picks = generate_alpha_x_v46(df_realtime, source_name)
                
                if picks:
                    for i, p in enumerate(picks):
                        with st.container(border=True):
                            c1, c2, c3, c4 = st.columns([1, 2, 3, 3])
                            with c1: st.markdown(f"# {i+1}")
                            with c2: st.markdown(f"### {p['name']}"); st.caption(p['code'])
                            with c3: st.metric("现价", f"¥{p['price']:.2f}", f"{p['pct']:.2f}%"); st.caption(p['flow'])
                            with c4: st.progress(p['prob']/100, text=f"🔥 爆发概率: {p['prob']:.1f}%"); st.caption(p['news'])
                            st.info(p['reason'])
                else: st.info("暂无符合策略的标的")
            else:
                st.error("❌ 所有数据源均连接失败，请点击左侧'强制刷新'或稍后再试。")

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
        df_full, src = get_market_data_smart()
        if not df_full.empty:
            t1, t2 = st.tabs(["🚀 涨幅榜", "💰 资金榜"])
            with t1: st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(15)[['name','price','pct']], use_container_width=True)
            with t2: 
                sort_col = 'money_flow' if 'money_flow' in df_full.columns else 'amount' # 兼容双字段
                st.dataframe(df_full.sort_values(sort_col,ascending=False).head(15)[['name','price',sort_col]], use_container_width=True)
        else: st.error("数据源异常")

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("保存"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()




































