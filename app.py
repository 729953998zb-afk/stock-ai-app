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
    page_title="AlphaQuant Pro | 永久典藏修复版",
    layout="wide",
    page_icon="💎",
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

# ================= 3. 核心数据引擎 =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

@st.cache_data(ttl=60)
def get_full_market_data():
    """东财全市场实时扫描"""
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
    try:
        url = f"https://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        params = {"type": "802", "pageindex": 1, "pagesize": 2, "keyword": code, "name": "normal"}
        r = requests.get(url, params=params, timeout=2)
        items = [i.get("Title","").replace("<em>","").replace("</em>","") for i in r.json().get("Data",[])]
        return items if items else ["暂无重大利好，走势独立", "资金静默期"]
    except: return ["市场情绪共振", "技术面修复"]

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
def scan_whole_market():
    """
    全市场扫描引擎
    """
    # 模拟的全市场池子 (实际使用时可扩展)
    MARKET_POOL = {
        "600519.SS": "贵州茅台", "300750.SZ": "宁德时代", "601127.SS": "赛力斯",
        "601318.SS": "中国平安", "002594.SZ": "比亚迪", "600036.SS": "招商银行",
        "601857.SS": "中国石油", "000858.SZ": "五粮液", "601138.SS": "工业富联",
        "603259.SS": "药明康德", "300059.SZ": "东方财富", "002475.SZ": "立讯精密",
        "601606.SS": "长城军工", "603600.SS": "永艺股份", "000063.SZ": "中兴通讯",
        "601728.SS": "中国电信", "600941.SS": "中国移动", "002371.SZ": "北方华创",
        "300274.SZ": "阳光电源", "600150.SS": "中国船舶", "600600.SS": "青岛啤酒",
        "600030.SS": "中信证券", "000725.SZ": "京东方A", "600276.SS": "恒瑞医药",
        "600900.SS": "长江电力", "601919.SS": "中远海控", "000002.SZ": "万科A",
        "000333.SZ": "美的集团", "603288.SS": "海天味业", "601088.SS": "中国神华"
    }
    
    data = []
    tickers = list(MARKET_POOL.keys())
    try:
        df_all = yf.download(tickers, period="1y", progress=False)
        if isinstance(df_all.columns, pd.MultiIndex): closes = df_all['Close']
        else: closes = df_all

        for code in tickers:
            if code in closes.columns:
                series = closes[code].dropna()
                if len(series) > 200:
                    curr = series.iloc[-1]
                    name = MARKET_POOL[code]
                    
                    pct_1d = float(((curr - series.iloc[-2]) / series.iloc[-2]) * 100)
                    pct_5d = float(((curr - series.iloc[-6]) / series.iloc[-6]) * 100)
                    pct_1y = float(((curr - series.iloc[0]) / series.iloc[0]) * 100)
                    
                    ma20 = series.rolling(20).mean().iloc[-1]
                    daily_ret = series.pct_change().dropna()
                    volatility = daily_ret.std() * 100
                    
                    delta = series.diff()
                    gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
                    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
                    if loss == 0: rsi = 100
                    else: rsi = 100 - (100 / (1 + gain/loss))
                    
                    # --- 修复点：评分逻辑修正 ---
                    t1_score = 50
                    if curr > ma20: t1_score += 20
                    
                    if 1.5 < pct_1d < 7.5:
                        t1_score += 20
                    elif pct_1d > 8.5:
                        t1_score -= 20 # 涨停难买
                    elif pct_1d < 0:
                        t1_score -= 10
                        
                    if 50 < rsi < 75: t1_score += 10
                    
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
        dif = exp1 - exp2
        dea = dif.ewm(span=9).mean()
        macd = (dif - dea).iloc[-1] * 2
        
        # --- 逻辑生成 ---
        trend_txt = ""
        if curr > h['MA20'].iloc[-1]:
            if vol_curr > vol_avg * 1.5: trend_txt = "🔥 **主力正在抢筹！** 放量上涨，庄家进场意愿非常强，这是要搞事情的节奏。"
            else: trend_txt = "✅ **主力稳坐钓鱼台。** 缩量上涨或横盘，说明没人卖，筹码很稳，继续持有。"
        else:
            if vol_curr > vol_avg * 1.5: trend_txt = "😱 **主力正在出货！** 放量下跌，有人在疯狂抛售，赶紧跑，别接飞刀。"
            else: trend_txt = "❄️ **没人玩了。** 缩量阴跌，这里是冷宫，别进去浪费时间。"
            
        pos_txt = ""
        if rsi > 80: pos_txt = "🛑 **太贵了！(极度危险)** 现在的价格严重虚高，随时会爆。"
        elif rsi < 20: pos_txt = "⚡️ **太便宜了！(黄金坑)** 跌无可跌，遍地是黄金。"
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

# ================= 5. Alpha-X 算法 =================

def generate_alpha_x_v28(df):
    """双梯队潜伏算法"""
    pool = df[(df['price']>3)&(~df['name'].str.contains("ST|退"))&(df['turnover']>1)].copy()
    tier1 = pool[(pool['pct']>-1.0)&(pool['pct']<3.5)&(pool['money_flow']>15000000)].copy()
    tier2 = pool[(pool['pct']>=3.5)&(pool['pct']<7.0)&(pool['money_flow']>40000000)].copy()
    
    picks = tier1.sort_values("money_flow", ascending=False).head(5)
    if len(picks) < 5:
        picks = pd.concat([picks, tier2.sort_values("money_flow", ascending=False).head(5-len(picks))])
        
    res = []
    for _, r in picks.iterrows():
        news = get_real_news_titles(r['code'])
        tag = "黄金潜伏" if r['pct']<3.5 else "强势接力"
        res.append({
            "name":r['name'], "code":convert_to_yahoo(r['code']), "price":r['price'], "pct":r['pct'],
            "flow":f"{r['money_flow']/10000:.0f}万", "tag":tag, "news":" | ".join(news[:1])
        })
    return res

# ================= 6. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("💎 AlphaQuant Pro")
        st.caption("v30.0 紧急修复版")
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
        with st.spinner("连接交易所实时数据..."):
            df_full = get_full_market_data()
            if df_full.empty: st.error("数据源离线"); st.stop()
    
    # 预先扫描榜单数据 (如果需要)
    df_rank = pd.DataFrame()
    if menu == "🏆 市场全景榜单": # 修正：确保这里逻辑通顺，v29用了 scan_whole_market
        # 这里为了全景榜的 长线/稳健 榜单，我们需要 scan_whole_market
        pass

    # --- 1. Alpha-X 金股预测 ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 每日金股")
        st.markdown("**核心策略**：优先推荐涨幅小、资金大的潜伏股；结合实时真实利好。")
        
        # 为了长线榜，我们也需要扫描 yfinance
        with st.spinner("正在计算量化指标..."):
            df_rank = scan_whole_market()

        picks = generate_alpha_x_v28(df_full)
        
        t1, t2 = st.tabs(["⚡️ 短线爆发", "💎 长线稳健"])
        
        with t1:
            if picks:
                for i, p in enumerate(picks):
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 2, 2, 3])
                        with c1: st.markdown(f"# {i+1}")
                        with c2: st.markdown(f"### {p['name']}"); st.caption(p['code'])
                        with c3: st.metric("现价", f"¥{p['price']}", f"{p['pct']}%"); st.caption(f"主力: {p['flow']}")
                        with c4: st.info(f"📰 **情报**：{p['news']}"); st.caption(f"策略：{p['tag']}")
            else: st.warning("今日无合适标的")
            
        with t2:
            if not df_rank.empty:
                # 长线：年涨幅>0，按性价比排序
                long_picks = df_rank[df_rank['年涨幅']>0].sort_values("性价比", ascending=False).head(5)
                for i, (_, row) in enumerate(long_picks.iterrows()):
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 2, 2, 3])
                        with c1: st.markdown(f"# {i+1}")
                        with c2: st.markdown(f"### {row['名称']}"); st.caption(row['代码'])
                        with c3: st.metric("现价", f"¥{row['现价']:.2f}", f"年涨 {row['年涨幅']:.1f}%")
                        with c4: st.write(f"波动率: {row['波动率']:.1f}"); st.caption("高股息/低波动核心资产")
            else: st.error("长线数据计算失败")

    # --- 2. 个股全维透视 ---
    elif menu == "🔎 个股全维透视":
        st.header("🔎 股票体检中心")
        c1, c2 = st.columns([3,1])
        k = c1.text_input("输入股票 (如 恒林股份)", placeholder="搜全网...")
        
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
                            st.write(f"🛑 **止损线**：跌破 **¥{d['ma20']}** 无脑走。")
                            st.write(f"🎯 **压力位**：涨到 **¥{d['pressure']}** 减点仓。")
                        
                        st.subheader("👨‍🏫 AI 导师")
                        base_url = st.session_state.get("base_url", "https://api.openai.com/v1")
                        st.caption(run_ai_tutor(d, base_url))
                else: st.error("数据拉取失败")
            else: st.error("未找到")

    # --- 3. 我的关注 ---
    elif menu == "👀 我的关注":
        st.header("👀 智能盯盘")
        with st.expander("➕ 添加", expanded=False):
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
        
        # 即使不开预测页，这里也要准备数据
        if df_full.empty: df_full = get_full_market_data()
        
        # 尝试获取历史数据榜单
        with st.spinner("计算长线榜单中..."):
            df_rank = scan_whole_market()
            
        t1, t2, t3 = st.tabs(["🚀 短线榜", "⏳ 长线榜", "🛡️ 稳健榜"])
        with t1: 
            st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(10)[['name','price','pct']], use_container_width=True)
        with t2: 
            if not df_rank.empty: st.dataframe(df_rank.sort_values("年涨幅", ascending=False).head(10)[['名称', '现价', '年涨幅']], use_container_width=True)
            else: st.info("长线数据加载中...")
        with t3: 
            if not df_rank.empty: st.dataframe(df_rank.sort_values("性价比", ascending=False).head(10)[['名称', '现价', '波动率']], use_container_width=True)
            else: st.info("稳健数据加载中...")

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("API 设置")
        k = st.text_input("Key", type="password")
        if st.button("Save"): st.session_state['api_key']=k; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()

























