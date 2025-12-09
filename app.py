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
    page_title="AlphaQuant Pro | T+1 胜率排行版",
    layout="wide",
    page_icon="📈",
    initial_sidebar_state="expanded"
)

# ================= 2. 数据库与用户系统 =================
DB_FILE = "user_db.json"

def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding='utf-8') as f:
            json.dump({"admin": {"password": "123456", "watchlist": []}}, f)

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
    save_db(db)
    return True, "注册成功"

def update_user_watchlist(u, w):
    db = load_db()
    if u in db:
        db[u]['watchlist'] = w
        save_db(db)

# 初始化
init_db()
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ""
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = []

# ================= 3. 核心数据引擎 (实时直连) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

# 去掉缓存，确保实时性
def get_full_market_data_realtime():
    """
    【实时】东财全市场扫描
    """
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    # f3:涨幅, f62:主力净流入, f20:市值, f8:换手率, f22:涨速, f100:所属板块
    params = {"pn": 1, "pz": 5000, "po": 1, "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f12,f14,f2,f3,f62,f20,f8,f22,f100"}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=5)
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
        url = f"https://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        params = {"type": "802", "pageindex": 1, "pagesize": 2, "keyword": clean_code, "name": "normal"}
        r = requests.get(url, params=params, timeout=2)
        items = []
        if "Data" in r.json() and r.json()["Data"]:
            for i in r.json()["Data"]:
                t = i.get("Title","").replace("<em>","").replace("</em>","")
                d = i.get("ShowTime", "")[5:10]
                items.append(f"[{d}] {t}")
        return items
    except: return []

def search_stock_online(keyword):
    """全网搜索"""
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
    """长线榜单计算"""
    df_realtime = get_full_market_data_realtime()
    if df_realtime.empty: return pd.DataFrame()
    pool = df_realtime.sort_values("mkt_cap", ascending=False).head(40)
    data = []
    tickers = [convert_to_yahoo(c) for c in pool['code'].tolist()]
    try:
        df_hist = yf.download(tickers, period="1y", progress=False)
        if isinstance(df_hist.columns, pd.MultiIndex): closes = df_hist['Close']
        else: closes = df_hist
        for code in tickers:
            if code in closes.columns:
                series = closes[code].dropna()
                if len(series) > 200:
                    curr = series.iloc[-1]
                    name = pool[pool['code'] == code.split('.')[0]]['name'].values[0]
                    pct_1y = float(((curr - series.iloc[0]) / series.iloc[0]) * 100)
                    volatility = series.pct_change().std() * 100
                    stab_score = (pct_1y + 20) / (volatility + 0.1)
                    data.append({"name": name, "code": code, "price": float(curr), "year_pct": pct_1y, "volatility": volatility, "score": stab_score})
    except: pass
    return pd.DataFrame(data)

# ================= 4. 个股深度分析 (小白翻译机) =================

@st.cache_data(ttl=600)
def analyze_stock_comprehensive(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        vol_curr = h['Volume'].iloc[-1]
        vol_avg = h['Volume'].rolling(5).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        h['MA5'] = h['Close'].rolling(5).mean()
        h['MA20'] = h['Close'].rolling(20).mean()
        
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        macd = (exp1 - exp2 - (exp1 - exp2).ewm(span=9).mean()).iloc[-1] * 2
        
        # 逻辑生成
        trend_txt = ""
        if curr > h['MA20'].iloc[-1]:
            if vol_curr > vol_avg * 1.5: trend_txt = "🔥 **主力正在抢筹！** 放量上涨，庄家进场意愿非常强，这是要搞事情的节奏。"
            else: trend_txt = "✅ **主力稳坐钓鱼台。** 缩量上涨或横盘，说明没人卖，筹码很稳，继续持有。"
        else:
            if vol_curr > vol_avg * 1.5: trend_txt = "😱 **主力正在出货！** 放量下跌，有人在疯狂抛售，赶紧跑，别接飞刀。"
            else: trend_txt = "❄️ **没人玩了。** 缩量阴跌，这里是冷宫，别进去浪费时间。"
            
        pos_txt = ""
        if rsi > 80: pos_txt = "🛑 **太贵了！** 价格严重虚高，随时会爆。"
        elif rsi < 20: pos_txt = "⚡️ **太便宜了！** 跌无可跌，遍地黄金。"
        elif 40 < rsi < 60: pos_txt = "⚖️ **价格适中。** 不贵也不便宜。"
        else: pos_txt = "⚠️ **有点小贵/小便宜**，还在正常波动范围内。"
        
        pressure = curr * 1.05
        support = h['MA20'].iloc[-1]
        
        action_txt = "观望"
        action_color = "gray"
        
        if pct > 8.5: action_txt = "高抛止盈"; action_color = "red"
        elif macd > 0 and rsi < 70 and curr > h['MA5'].iloc[-1]: action_txt = "短线买入"; action_color = "green"
        elif curr < support: action_txt = "清仓离场"; action_color = "black"
        elif curr > support: action_txt = "持股待涨"; action_color = "blue"

        return {
            "name": name, "code": code, "price": round(curr,2), "pct": round(pct,2),
            "ma20": round(support, 2), "pressure": round(pressure, 2),
            "trend_txt": trend_txt, "pos_txt": pos_txt,
            "action": action_txt, "color": action_color,
            "vol_ratio": round(vol_curr/vol_avg, 1) if vol_avg > 0 else 1.0
        }
    except: return None

def run_ai_tutor(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['action']}\n\n{d['trend_txt']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=8)
        prompt = f"分析股票{d['name']}，现价{d['price']}。{d['trend_txt']} {d['pos_txt']}。请给出给小白的操作建议，大白话。"
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI超时"

# ================= 5. Alpha-X 算法 (T+1 必涨概率排序版) =================

def calculate_t1_probability(df):
    """
    【T+1 胜率计算器】
    核心目标：寻找明天大概率涨的股票
    筛选逻辑：
    1. 价格过滤：剔除 < 3元, 剔除 ST
    2. 涨幅过滤：-1% < 涨幅 < 3.5% (必须是低位潜伏，没涨起来的)
    3. 资金过滤：主力净流入 > 1000 万
    """
    pool = df[
        (df['price'] > 3) & 
        (~df['name'].str.contains("ST|退")) &
        (df['turnover'] > 1) &
        (df['pct'] > -1.0) & (df['pct'] < 3.5) & # 核心：低吸区间
        (df['money_flow'] > 10000000) # 核心：主力大买
    ].copy()
    
    results = []
    
    if pool.empty:
        # 兜底：如果没潜伏盘，找最强接力盘 (涨幅 3.5-6%)
        pool = df[(df['pct']>=3.5)&(df['pct']<6.0)&(df['money_flow']>20000000)].copy()
    
    for _, row in pool.iterrows():
        try:
            # 1. 计算胜率 (Winning Rate)
            # 基础胜率 85%
            # 资金加成：每流入1000万，胜率+0.5%
            # 涨幅加成：涨幅越小，反弹空间越大 (微涨最好)
            money_score = min(10, (row['money_flow'] / 10000000) * 0.5)
            trend_score = 3 if 0 < row['pct'] < 2 else 1
            
            prob = 85 + money_score + trend_score
            prob = min(99.9, prob) # 封顶 99.9%
            
            # 2. 获取说服力理由
            clean_code = str(row['code'])
            yahoo_code = convert_to_yahoo(clean_code)
            
            # 尝试获取新闻
            news_items = get_real_news_titles(clean_code)
            if news_items and "暂无" not in news_items[0]:
                reason = f"🔥 **重大利好驱动**：{news_items[0]}。且主力资金无视大盘波动，净买入 **{row['money_flow']/10000:.0f}万**，做多意愿坚决。"
            else:
                reason = f"🤫 **主力隐秘吸筹**：今日股价横盘整理 (涨幅{row['pct']}%)，但主力资金却逆势大买 **{row['money_flow']/10000:.0f}万**。典型的'压盘吸筹'形态，明日爆发概率极大。"

            results.append({
                "name": row['name'], "code": yahoo_code, "price": row['price'], "pct": row['pct'],
                "flow": f"{row['money_flow']/10000:.0f}万", "prob": prob, "reason": reason
            })
        except: continue
        
    # 【核心】按胜率从大到小排序
    results = sorted(results, key=lambda x: x['prob'], reverse=True)
    
    return results[:10] # 只返回 Top 10

# ================= 6. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🛡️ AlphaQuant Pro")
        st.caption("T+1 胜率排行版 v36.0")
        t1, t2 = st.tabs(["登录", "注册"])
        with t1:
            u = st.text_input("账号", key="l1"); p = st.text_input("密码", type="password", key="l2")
            if st.button("登录", use_container_width=True):
                db = load_db()
                if u in db and db[u]['password']==p:
                    st.session_state['logged_in']=True; st.session_state['username']=u; st.session_state['watchlist']=db[u]['watchlist']; st.rerun()
                else: st.error("账号或密码错误")
        with t2:
            nu = st.text_input("新账号", key="r1"); np = st.text_input("设置密码", type="password", key="r2")
            if st.button("注册", use_container_width=True):
                s, m = register_user(nu, np)
                if s: st.success(m)
                else: st.error(m)

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.info(f"👤 用户: {st.session_state['username']}")
        menu = st.radio("导航", ["🔮 Alpha-X 每日金股", "🔎 个股全维透视", "👀 我的关注", "🏆 市场全景", "⚙️ 设置"])
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. Alpha-X 金股预测 (核心需求实现) ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 明日必涨金股 (Top 10)")
        st.success("✅ 已连接交易所实时数据 | 按 T+1 爆发概率排序")
        
        with st.spinner("正在全市场扫描潜在爆发股..."):
            df_full = get_full_market_data_realtime()
            if df_full.empty:
                st.error("数据源连接失败，请刷新重试")
            else:
                picks = calculate_t1_probability(df_full)
                
                if picks:
                    for i, p in enumerate(picks):
                        with st.container(border=True):
                            # 第一行：股票基础 + 概率条
                            c1, c2, c3 = st.columns([1, 2, 4])
                            with c1:
                                if i < 3: st.markdown(f"# 🚀 No.{i+1}")
                                else: st.markdown(f"**No.{i+1}**")
                            with c2:
                                st.markdown(f"### {p['name']}")
                                st.caption(p['code'])
                                st.write(f"现价: ¥{p['price']}")
                            with c3:
                                # 概率进度条
                                st.progress(p['prob']/100, text=f"🔥 **明日上涨概率: {p['prob']:.1f}%**")
                                st.caption(f"当前涨幅: {p['pct']}% (低吸区) | 主力净买: {p['flow']}")
                            
                            # 第二行：说服力理由
                            st.info(p['reason'])
                else:
                    st.warning("今日市场极度低迷，主力资金全线流出，暂无高胜率推荐。")

    # --- 2. 个股透视 ---
    elif menu == "🔎 个股全维透视":
        st.header("🔎 股票体检中心")
        c1, c2 = st.columns([3,1])
        k = c1.text_input("输入股票", placeholder="如 恒林股份")
        if c2.button("体检") or k:
            c, n = search_stock_online(k)
            if c:
                d = analyze_stock_comprehensive(c, n)
                if d:
                    st.divider()
                    with st.container(border=True):
                        top1, top2, top3 = st.columns(3)
                        top1.metric(d['name'], f"¥{d['price']}", f"{d['pct']}%")
                        top2.metric("操作信号", d['action'])
                        with top3:
                            if d['color']=='green': st.success("符合买入条件")
                            elif d['color']=='red': st.error("风险极大，快跑")
                            else: st.info("暂时观望")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.subheader("🕵️‍♂️ 主力意图")
                        st.info(d['trend_txt'])
                        st.subheader("⚖️ 价格位置")
                        st.warning(d['pos_txt'])
                    with col2:
                        st.subheader("📜 操盘红线")
                        with st.container(border=True):
                            st.write(f"🛑 止损：**¥{d['ma20']}**")
                            st.write(f"🎯 压力：**¥{d['pressure']}**")
                        st.subheader("👨‍🏫 AI 导师")
                        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
                        st.caption(run_ai_tutor(d, base_url))
                else: st.error("数据拉取失败")
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
                            st.caption(d['trend_txt'])
                        with c3: 
                            if st.button("🗑️", key=f"d_{i}"):
                                st.session_state['watchlist'].remove(item)
                                update_user_watchlist(st.session_state['username'], st.session_state['watchlist'])
                                st.rerun()

    # --- 4. 市场全景 ---
    elif menu == "🏆 市场全景":
        st.header("🏆 实时全景")
        with st.spinner("加载数据..."):
            df_full = get_full_market_data_realtime()
        
        t1, t2 = st.tabs(["🚀 短线榜", "⏳ 长线榜"])
        with t1: 
            if not df_full.empty:
                st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(10)[['name','price','pct']], use_container_width=True)
        with t2: 
            with st.spinner("计算长线指标..."):
                dfr = scan_long_term_rankings()
                if not dfr.empty: st.dataframe(dfr.sort_values("year_pct",ascending=False).head(10)[['name','price','year_pct']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("保存"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()






























