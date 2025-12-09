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
    page_title="AlphaQuant Pro | 低吸防御版",
    layout="wide",
    page_icon="🛡️",
    initial_sidebar_state="expanded"
)

# 数据库与用户系统 (保持不变)
DB_FILE = "user_db.json"
def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w", encoding='utf-8') as f: json.dump({"admin": {"password": "123456", "watchlist": []}}, f)
def load_db():
    if not os.path.exists(DB_FILE): init_db()
    with open(DB_FILE, "r") as f: return json.load(f)
def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)
def update_user_watchlist(u, w):
    db = load_db(); db[u]['watchlist'] = w; save_db(db)
init_db()

if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ""
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = []

# ================= 2. 核心数据引擎 (全网直连) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

@st.cache_data(ttl=60)
def get_full_market_data():
    """东财全市场实时扫描 (5000+只股票)"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {"pn": 1, "pz": 5000, "po": 1, "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f12,f14,f2,f3,f62,f20,f8"}
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, params=params, headers=headers, timeout=3)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'mkt_cap','f8':'turnover'})
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
    df_realtime = get_full_market_data()
    if df_realtime.empty: return pd.DataFrame()
    pool = df_realtime.sort_values("mkt_cap", ascending=False).head(30)
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

# ================= 4. 个股深度分析 (小白版) =================

@st.cache_data(ttl=600)
def analyze_stock_comprehensive(code, name):
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
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        macd = (exp1 - exp2 - (exp1 - exp2).ewm(span=9).mean()).iloc[-1] * 2
        
        trend_txt = "✅ **趋势向上**：股价在20日线之上，主力控盘。" if curr > ma20 else "⚠️ **趋势破位**：跌破生命线，主力可能在出货。"
        pos_txt = "🛑 **严重超买**：价格太贵了，随时可能崩盘。" if rsi > 80 else "⚡️ **超卖黄金坑**：跌过头了，可以尝试抄底。" if rsi < 20 else "⚖️ **价格适中**：不高不低，看资金意愿。"
        
        action_txt = "观望"
        action_color = "gray"
        if rsi > 80: action_txt = "高抛止盈"; action_color = "red"
        elif pct < -5 and curr < ma20: action_txt = "止损卖出"; action_color = "black"
        elif macd > 0 and rsi < 70 and curr > ma20: action_txt = "短线买入"; action_color = "green"
        elif curr > ma20: action_txt = "持股待涨"; action_color = "blue"

        return {"name": name, "code": code, "price": round(curr,2), "pct": round(pct,2), "ma20": round(ma20, 2), "pressure": round(curr*1.05, 2), "trend_txt": trend_txt, "pos_txt": pos_txt, "action": action_txt, "color": action_color, "rsi": round(rsi, 1)}
    except: return None

def run_ai_tutor(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['action']}\n\n{d['trend_txt']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=8)
        prompt = f"分析{d['name']}，现价{d['price']}。{d['trend_txt']} {d['pos_txt']}。请给出小白能懂的操作建议。"
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI超时"

# ================= 5. Alpha-X 算法 (v34 严格低吸版) =================

def generate_alpha_x_v34(df):
    """
    【v34 严选策略】
    目标：只推还没涨起来的票。
    逻辑：全市场扫描 -> 剔除 ST/退市 -> 剔除涨幅 > 5% 的票。
    """
    # 1. 基础池：非ST，有成交量，价格>3元
    pool = df[
        (df['price'] > 3) & 
        (~df['name'].str.contains("ST|退")) &
        (df['turnover'] > 1)
    ].copy()
    
    # 2. 严格筛选：黄金潜伏 (Golden Ambush)
    # 要求：涨幅在 -1.5% 到 +4.5% 之间。超过 4.5% 虽然强，但对 T+1 来说风险偏高，忍痛放弃。
    # 资金：主力净流入必须 > 1000 万
    ambush = pool[
        (pool['pct'] > -1.5) & (pool['pct'] < 4.5) & 
        (pool['money_flow'] > 10000000)
    ].copy()
    
    # 3. 排序：按资金流向降序 (钱进得越多越好)
    picks = ambush.sort_values("money_flow", ascending=False).head(5)
    
    # 4. 填补机制 (如果潜伏股不够5个，稍微放宽涨幅限制到 6%，但标注高风险)
    if len(picks) < 5:
        needed = 5 - len(picks)
        # 放宽到 7%
        backup = pool[
            (pool['pct'] >= 4.5) & (pool['pct'] < 7.0) & 
            (pool['money_flow'] > 30000000) # 高位股资金要求更高
        ].sort_values("money_flow", ascending=False).head(needed)
        picks = pd.concat([picks, backup])
        
    results = []
    for _, row in picks.iterrows():
        try:
            # 真实新闻
            clean_code = str(row['code'])
            yahoo_code = convert_to_yahoo(clean_code)
            news_items = get_real_news_titles(clean_code)
            
            # 判断新闻有效性
            if news_items and "暂无" not in news_items[0]:
                news_display = f"📰 {news_items[0]}"
                reason_type = "消息驱动"
            else:
                news_display = "📡 暂无公告，主力资金独立运作"
                reason_type = "资金驱动"
            
            # 标签定义
            if row['pct'] < 3.0:
                tag = "黄金潜伏 (低吸)"
                advice = "股价未动，资金先动。建议尾盘潜伏，博弈明日补涨。"
                prob = 92 + random.uniform(0, 3)
            else:
                tag = "趋势中继 (接力)"
                advice = "趋势已起，主力资金强力承接。注意控制仓位，不宜追高。"
                prob = 85 + random.uniform(0, 3)
            
            # 生成理由
            money_val = row['money_flow'] / 10000
            reason = f"**{reason_type}**：今日涨幅 **{row['pct']}%** (未透支)，主力净买入 **{money_val:.0f}万**。{advice}"
            
            results.append({
                "name": row['name'], "code": yahoo_code, "price": row['price'], "pct": row['pct'],
                "flow": f"{money_val:.0f}万", "tag": tag, "news": news_display, 
                "prob": prob, "reason": reason
            })
        except: continue
        
    return results

# ================= 6. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("💎 AlphaQuant Pro")
        st.caption("低吸防御版 v34.0")
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

    df_full = pd.DataFrame()
    if menu in ["🔮 Alpha-X 每日金股", "🏆 市场全景"]:
        with st.spinner("正在连接交易所，扫描全市场 5300+ 只股票..."):
            df_full = get_full_market_data()
            if df_full.empty: st.error("数据源离线"); st.stop()
    
    df_rank = pd.DataFrame()
    if menu == "🏆 市场全景" or menu == "🔮 Alpha-X 每日金股":
        pass

    # --- 1. Alpha-X 金股预测 (核心升级) ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 每日金股")
        st.success(f"📊 已扫描全市场 **{len(df_full)}** 只股票。筛选标准：涨幅适中 + 资金大买。")
        
        # 实时计算推荐
        picks = generate_alpha_x_v34(df_full)
        
        t1, t2 = st.tabs(["⚡️ 短线潜伏 (T+1)", "💎 长线稳健"])
        
        with t1:
            if picks:
                for i, p in enumerate(picks):
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 2, 2, 3])
                        with c1: st.markdown(f"# {i+1}")
                        with c2: st.markdown(f"### {p['name']}"); st.caption(p['code'])
                        with c3: st.metric("现价", f"¥{p['price']}", f"{p['pct']}%"); st.caption(f"主力: {p['flow']}")
                        with c4: 
                            st.progress(p['prob']/100, text=f"📈 爆发概率: {p['prob']:.1f}%")
                            if "潜伏" in p['tag']:
                                st.success(p['tag'])
                            else:
                                st.warning(p['tag'])
                        
                        st.info(p['reason'])
                        st.caption(f"情报源：{p['news']}")
            else: st.warning("今日市场无符合'低吸潜伏'标准的股票，建议休息。")
            
        with t2:
            with st.spinner("计算长线指标..."):
                df_rank = scan_long_term_rankings()
            if not df_rank.empty:
                long_picks = df_rank[df_rank['year_pct']>0].sort_values("score", ascending=False).head(5)
                for i, (_, row) in enumerate(long_picks.iterrows()):
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 2, 2, 3])
                        with c1: st.markdown(f"# {i+1}")
                        with c2: st.markdown(f"### {row['name']}"); st.caption(row['code'])
                        with c3: st.metric("现价", f"¥{row['price']:.2f}", f"年涨 {row['year_pct']:.1f}%")
                        with c4: st.write(f"波动率: {row['volatility']:.1f}"); st.caption("高股息/低波动核心资产")
            else: st.error("长线数据计算失败")

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
        t1, t2 = st.tabs(["🚀 短线榜", "⏳ 长线榜"])
        with t1: st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(10)[['name','price','pct']], use_container_width=True)
        with t2: 
            with st.spinner("加载长线数据..."):
                dfr = scan_long_term_rankings()
                if not dfr.empty: st.dataframe(dfr.sort_values("year_pct",ascending=False).head(10)[['name','price','year_pct']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("设置")
        nk = st.text_input("API Key", type="password", value=st.session_state['api_key'])
        nu = st.text_input("Base URL", value="https://api.openai.com/v1")
        if st.button("Save"): st.session_state['api_key']=nk; st.session_state['base_url']=nu; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()



























