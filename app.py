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

# ================= 1. 全局配置 =================
st.set_page_config(
    page_title="AlphaQuant Pro | 全维深度版",
    layout="wide",
    page_icon="🎓",
    initial_sidebar_state="expanded"
)

# 数据库初始化
DB_FILE = "user_db.json"
def init_db():
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, "w") as f: json.dump({"admin": {"password": "123456", "watchlist": []}}, f)
def load_db():
    if not os.path.exists(DB_FILE): init_db()
    with open(DB_FILE, "r") as f: return json.load(f)
def save_db(data):
    with open(DB_FILE, "w") as f: json.dump(data, f, indent=4)
def update_user_watchlist(u, w):
    db = load_db(); db[u]['watchlist'] = w; save_db(db)
init_db()

# Session
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'username' not in st.session_state: st.session_state['username'] = ""
if 'api_key' not in st.session_state: st.session_state['api_key'] = ""
if 'watchlist' not in st.session_state: st.session_state['watchlist'] = []

# ================= 2. 核心数据引擎 (保持全网搜) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

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

@st.cache_data(ttl=60)
def get_full_market_data():
    """全市场扫描 (用于预测)"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {"pn": 1, "pz": 5000, "po": 1, "np": 1, "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields": "f12,f14,f2,f3,f62,f20,f8"}
    try:
        r = requests.get(url, params=params, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        df = pd.DataFrame(r.json()['data']['diff']).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'mkt_cap','f8':'turnover'})
        for c in ['price','pct','money_flow','turnover']: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df
    except: return pd.DataFrame()

# ================= 3. 全维深度分析引擎 (核心升级) =================

@st.cache_data(ttl=600)
def analyze_stock_comprehensive(code, name):
    """
    【全维深度体检】
    维度：趋势、位置、动能、资金
    输出：大白话报告
    """
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        
        # 1. 基础数据
        curr = h['Close'].iloc[-1]
        vol_curr = h['Volume'].iloc[-1]
        vol_avg = h['Volume'].rolling(5).mean().iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        
        # 2. 技术指标计算
        h['MA5'] = h['Close'].rolling(5).mean()
        h['MA20'] = h['Close'].rolling(20).mean()
        h['MA60'] = h['Close'].rolling(60).mean()
        
        # RSI
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        
        # MACD
        exp1 = h['Close'].ewm(span=12).mean()
        exp2 = h['Close'].ewm(span=26).mean()
        dif = exp1 - exp2
        dea = dif.ewm(span=9).mean()
        macd = (dif - dea).iloc[-1] * 2
        
        # 3. 【小白翻译机】逻辑生成
        
        # A. 主力意图 (看量能和均线)
        trend_txt = ""
        if curr > h['MA20'].iloc[-1]:
            if vol_curr > vol_avg * 1.5: trend_txt = "🔥 **主力正在抢筹！** 放量上涨，庄家进场意愿非常强，这是要搞事情的节奏。"
            else: trend_txt = "✅ **主力稳坐钓鱼台。** 缩量上涨或横盘，说明没人卖，筹码很稳，继续持有。"
        else:
            if vol_curr > vol_avg * 1.5: trend_txt = "😱 **主力正在出货！** 放量下跌，有人在疯狂抛售，赶紧跑，别接飞刀。"
            else: trend_txt = "❄️ **没人玩了。** 缩量阴跌，这里是冷宫，别进去浪费时间。"
            
        # B. 价格安全度 (看RSI和乖离率)
        pos_txt = ""
        if rsi > 80: pos_txt = "🛑 **太贵了！(极度危险)** 现在的价格严重虚高，就像吹大的气球，随时会爆。"
        elif rsi < 20: pos_txt = "⚡️ **太便宜了！(黄金坑)** 跌无可跌，遍地是黄金，胆子大可以试着捡一点。"
        elif 40 < rsi < 60: pos_txt = "⚖️ **价格适中。** 不贵也不便宜，能不能涨主要看明天心情（资金面）。"
        else: pos_txt = "⚠️ **有点小贵/小便宜**，还在正常波动范围内。"
        
        # C. 操盘红线 (具体点位)
        pressure = curr * 1.05 # 简易压力位
        support = h['MA20'].iloc[-1] # 生命线
        
        action_txt = ""
        action_color = "gray"
        
        if pct > 8: 
            action_txt = "高抛止盈"; action_color = "red"
        elif macd > 0 and rsi < 70 and curr > h['MA5'].iloc[-1]:
            action_txt = "短线买入"; action_color = "green"
        elif curr < h['MA20'].iloc[-1]:
            action_txt = "清仓离场"; action_color = "black"
        else:
            action_txt = "持股待涨"; action_color = "blue"

        return {
            "name": name, "code": code, "price": round(curr,2), "pct": round(pct,2),
            "ma20": round(support, 2), "pressure": round(pressure, 2),
            "trend_txt": trend_txt, "pos_txt": pos_txt,
            "action": action_txt, "color": action_color,
            "vol_ratio": round(vol_curr/vol_avg, 1)
        }
    except: return None

def generate_sniper_predictions(df):
    """(保留上一版的优秀预测逻辑)"""
    pool = df[(df['pct']>-1.5)&(df['pct']<3.5)&(df['price']>4)].copy()
    pool = pool[pool['money_flow']>20000000]
    top_picks = pool.sort_values("money_flow", ascending=False).head(5)
    results = []
    for _, r in top_picks.iterrows():
        try:
            results.append({
                "名称": r['name'], "代码": convert_to_yahoo(r['code']), 
                "现价": r['price'], "涨幅": r['pct'], 
                "资金": f"+{r['money_flow']/10000:.0f}万",
                "逻辑": "主力压盘吸筹，洗盘结束"
            })
        except: continue
    return results

# ================= 4. 界面逻辑 =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🦅 AlphaQuant Pro")
        st.info("账号: admin | 密码: 123456")
        u = st.text_input("ID"); p = st.text_input("PW", type="password")
        if st.button("🚀 登录"):
            db = load_db()
            if u in db and db[u]['password'] == p:
                st.session_state['logged_in']=True; st.session_state['username']=u; st.session_state['watchlist']=db[u]['watchlist']; st.rerun()
            else: st.error("错误")

def main_app():
    with st.sidebar:
        st.title("AlphaQuant Pro")
        st.caption("全维深度·大白话版 v27.0")
        menu = st.radio("导航", ["🔎 个股深度 (小白必看)", "🔮 主力潜伏 (预测)", "👀 我的关注", "🏆 市场全景", "⚙️ 设置"])
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. 个股深度 (核心升级) ---
    if menu == "🔎 个股深度 (小白必看)":
        st.header("🔎 股票体检中心")
        st.caption("输入名字，AI 用大白话告诉你：主力在干嘛？能不能买？")
        
        c1, c2 = st.columns([3,1])
        k = c1.text_input("输入股票 (如 恒林股份 / 603661)")
        if c2.button("开始体检") or k:
            c, n = search_stock_online(k)
            if c:
                d = analyze_stock_comprehensive(c, n)
                if d:
                    st.divider()
                    # 顶部：结论卡片
                    with st.container(border=True):
                        col_main, col_res = st.columns([3, 1])
                        with col_main:
                            st.markdown(f"### {d['name']} ({d['code']})")
                            st.metric("现价", f"¥{d['price']}", f"{d['pct']}%")
                        with col_res:
                            st.markdown("#### 🤖 最终结论")
                            if d['color']=='green': st.success(f"**{d['action']}**")
                            elif d['color']=='red': st.error(f"**{d['action']}**")
                            elif d['color']=='black': st.error(f"**{d['action']}**")
                            else: st.info(f"**{d['action']}**")

                    # 中部：大白话分析
                    st.subheader("🗣️ 深度人话解读")
                    c_left, c_right = st.columns(2)
                    
                    with c_left:
                        with st.container(border=True):
                            st.markdown("#### 1. 🕵️‍♂️ 主力意图")
                            st.info(d['trend_txt'])
                            st.caption(f"量能倍数: {d['vol_ratio']} (大于1.5说明放量)")
                    
                    with c_right:
                        with st.container(border=True):
                            st.markdown("#### 2. ⚖️ 价格位置")
                            st.warning(d['pos_txt'])
                            st.caption("基于 RSI 指标判断买卖拥挤度")

                    # 底部：剧本
                    st.subheader("📜 操盘剧本 (如果一定要做)")
                    with st.container(border=True):
                        k1, k2 = st.columns(2)
                        with k1: st.error(f"🛑 **生命线 (止损位)**：\n\n **¥{d['ma20']}** (跌破就跑，别犹豫)")
                        with k2: st.success(f"🎯 **压力位 (止盈位)**：\n\n **¥{d['pressure']}** (到了这里大概率要回调)")

                else: st.error("数据拉取失败")
            else: st.error("未找到")

    # --- 2. 主力潜伏 (保留) ---
    elif menu == "🔮 主力潜伏 (预测)":
        st.header("🔮 明日涨停预备队")
        with st.spinner("扫描全市场吸筹股..."):
            df = get_full_market_data()
            if not df.empty:
                picks = generate_sniper_predictions(df)
                if picks:
                    for i, p in enumerate(picks):
                        with st.container(border=True):
                            c1, c2, c3 = st.columns([1, 2, 2])
                            with c1: st.markdown(f"**🚀 {p['名称']}**")
                            with c2: st.metric("低位现价", f"¥{p['现价']}", f"{p['涨幅']}%")
                            with c3: st.metric("主力吸筹", p['资金'], delta="进场")
                            st.caption(f"💡 逻辑：{p['逻辑']}")
                else: st.warning("今日无潜伏机会")
            else: st.error("数据源离线")

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

    # --- 4. 全景 ---
    elif menu == "🏆 市场全景":
        st.header("🏆 实时全景")
        df = get_full_market_data()
        if not df.empty:
            t1, t2 = st.tabs(["涨幅榜", "资金榜"])
            with t1: st.dataframe(df[df['pct']<30].sort_values("pct",ascending=False).head(10)[['name','price','pct']], use_container_width=True)
            with t2: st.dataframe(df.sort_values("money_flow",ascending=False).head(10)[['name','price','money_flow']], use_container_width=True)

    # --- 5. 设置 ---
    elif menu == "⚙️ 设置":
        st.header("API 设置")
        k = st.text_input("Key", type="password")
        if st.button("Save"): st.session_state['api_key']=k; st.success("Saved")

if __name__ == "__main__":
    if st.session_state['logged_in']: main_app()
    else: login_system()
























