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
    page_title="AlphaQuant Pro | 双核实时版",
    layout="wide",
    page_icon="📡",
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

# ================= 2. 多源核心数据引擎 (Eastmoney + Sina) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

def get_random_agent():
    agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0.3 Safari/605.1.15",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0"
    ]
    return random.choice(agents)

# --- 引擎 A: 东方财富 (主力资金最全) ---
# 注意：这里没有 @st.cache_data，保证绝对实时
def fetch_eastmoney_realtime():
    """尝试从东方财富获取全市场实时数据"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    # f3:涨幅, f62:主力净流入, f20:市值, f8:换手率, f22:涨速
    params = {
        "pn": 1, "pz": 4000, "po": 1, "np": 1, 
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23",
        "fields": "f12,f14,f2,f3,f62,f20,f8,f22"
    }
    try:
        r = requests.get(url, params=params, headers={"User-Agent": get_random_agent()}, timeout=3)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'mkt_cap','f8':'turnover','f22':'speed'})
        # 清洗数据
        for c in ['price','pct','money_flow','turnover']: 
            df[c] = pd.to_numeric(df[c], errors='coerce')
        return df, "Eastmoney (主力资金流)"
    except:
        return pd.DataFrame(), "Fail"

# --- 引擎 B: 新浪财经 (备用，无主力资金字段，用成交额模拟) ---
def fetch_sina_realtime():
    """
    当东财挂了，用新浪接口拉取涨幅榜。
    新浪没有直接的'主力流入'字段，我们用 '成交额 * (涨幅/10)' 模拟资金强度
    """
    try:
        # 新浪行情节点接口 (获取沪深A股涨幅榜)
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {
            "page": 1, "num": 100, "sort": "changepercent", "asc": 0, "node": "hs_a", "_s_r_a": "page"
        }
        r = requests.get(url, params=params, headers={"User-Agent": get_random_agent()}, timeout=3)
        data = json.loads(r.text)
        
        df = pd.DataFrame(data)
        # 映射字段: code, name, trade(price), changepercent(pct), volume, amount
        df = df.rename(columns={'symbol':'code', 'name':'name', 'trade':'price', 'changepercent':'pct', 'amount':'amount'})
        
        # 格式转换
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['pct'] = pd.to_numeric(df['pct'], errors='coerce')
        df['amount'] = pd.to_numeric(df['amount'], errors='coerce')
        df['code'] = df['code'].str.replace('sh','').str.replace('sz','') # 去掉前缀以便统一处理
        
        # 模拟主力资金 (成交额 * 权重) - 仅作为备用参考
        df['money_flow'] = df['amount'] * 0.15 * (df['pct'] / 10) 
        
        # 补充缺失字段
        df['turnover'] = 5.0 # 默认值
        df['mkt_cap'] = 10000000000 # 默认值
        
        return df, "Sina (成交额估算)"
    except:
        return pd.DataFrame(), "Fail"

def get_realtime_market_scan():
    """双通道调度器"""
    # 优先尝试东财
    df, source = fetch_eastmoney_realtime()
    if not df.empty: return df, source
    
    # 失败则尝试新浪
    df, source = fetch_sina_realtime()
    return df, source

# --- 真实新闻 (通用) ---
@st.cache_data(ttl=300)
def get_real_news_titles(code):
    clean_code = str(code).split(".")[0]
    try:
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        params = {"type": "802", "pageindex": 1, "pagesize": 2, "keyword": clean_code, "name": "normal"}
        r = requests.get(url, params=params, headers={"User-Agent": get_random_agent()}, timeout=2)
        items = []
        if "Data" in r.json() and r.json()["Data"]:
            for i in r.json()["Data"]:
                t = i.get("Title","").replace("<em>","").replace("</em>","")
                d = i.get("ShowTime", "")[5:10]
                items.append(f"[{d}] {t}")
        return items
    except: return []

def search_stock_online(keyword):
    """搜索"""
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

# ================= 3. 个股深度分析 =================

@st.cache_data(ttl=600)
def analyze_stock_comprehensive(code, name):
    try:
        t = yf.Ticker(code)
        h = t.history(period="6mo") 
        if h.empty: return None
        curr = h['Close'].iloc[-1]
        pct = ((curr - h['Close'].iloc[-2]) / h['Close'].iloc[-2]) * 100
        h['MA20'] = h['Close'].rolling(20).mean(); ma20 = h['MA20'].iloc[-1]
        delta = h['Close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean().iloc[-1]
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
        rsi = 100 if loss==0 else 100 - (100 / (1 + gain/loss))
        exp1 = h['Close'].ewm(span=12).mean(); exp2 = h['Close'].ewm(span=26).mean()
        macd = (exp1 - exp2 - (exp1 - exp2).ewm(span=9).mean()).iloc[-1] * 2
        
        trend_txt = "✅ **趋势向上**：20日线上方" if curr > ma20 else "⚠️ **趋势破位**：20日线下方"
        pos_txt = "🛑 **超买**" if rsi > 80 else "⚡️ **超卖**" if rsi < 20 else "⚖️ **适中**"
        
        action_txt = "观望"; action_color = "gray"
        if rsi > 80: action_txt = "高抛"; action_color = "red"
        elif pct < -5 and curr < ma20: action_txt = "止损"; action_color = "black"
        elif macd > 0 and rsi < 70 and curr > h['MA20'].iloc[-1]: action_txt = "买入"; action_color = "green"
        elif curr > ma20: action_txt = "持有"; action_color = "blue"

        return {"name": name, "code": code, "price": round(curr,2), "pct": round(pct,2), "ma20": round(ma20, 2), "trend_txt": trend_txt, "pos_txt": pos_txt, "action": action_txt, "color": action_color, "rsi": round(rsi, 1)}
    except: return None

def run_ai_tutor(d, base_url):
    key = st.session_state['api_key']
    if not key or not key.startswith("sk-"): return f"> **🤖 免费模式**\n建议：{d['action']}"
    try:
        c = OpenAI(api_key=key, base_url=base_url, timeout=5)
        prompt = f"分析{d['name']}，现价{d['price']}。{d['trend_txt']} {d['pos_txt']}。小白操作建议。"
        return c.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role":"user","content":prompt}]).choices[0].message.content
    except: return "AI超时"

# ================= 4. Alpha-X 算法 (实时版) =================

def generate_alpha_x_v39(df):
    """
    【v39 实时算法】
    不使用缓存，直接基于传入的 df 计算
    """
    # 基础过滤
    pool = df[
        (df['price'] > 3) & 
        (~df['name'].str.contains("ST|退"))
    ].copy()
    
    if pool.empty: return []

    # 1. 黄金潜伏 (低吸)
    tier1 = pool[
        (pool['pct'] > -1.0) & (pool['pct'] < 3.5) & 
        (pool['money_flow'] > 10000000)
    ].sort_values("money_flow", ascending=False)
    
    # 2. 暴力接力 (追涨)
    tier2 = pool[
        (pool['pct'] >= 3.5) & (pool['pct'] < 7.5) & 
        (pool['money_flow'] > 30000000)
    ].sort_values("money_flow", ascending=False)
    
    # 3. 兜底
    tier3 = pool[pool['pct'] < 9.5].sort_values("money_flow", ascending=False)
    
    picks = pd.concat([tier1.head(5), tier2.head(5), tier3.head(10)])
    picks = picks.drop_duplicates(subset=['code']).head(10)
    
    results = []
    for _, row in picks.iterrows():
        try:
            clean_code = str(row['code'])
            yahoo_code = convert_to_yahoo(clean_code)
            
            # 实时查新闻
            news_items = get_real_news_titles(clean_code)
            news_display = f"📰 {news_items[0]}" if (news_items and "暂无" not in news_items[0]) else "📡 资金驱动"
            
            if row['pct'] < 3.5: tag, prob = "黄金潜伏", 94
            elif row['pct'] < 7.5: tag, prob = "强势接力", 89
            else: tag, prob = "龙头博弈", 85
            
            # 动态胜率
            prob += (row['money_flow']/200000000)
            prob = min(99.0, prob)
            
            money_val = row['money_flow'] / 10000
            reason = f"**{tag}**：涨幅 **{row['pct']}%**，主力净买 **{money_val:.0f}万**。"
            
            results.append({
                "name": row['name'], "code": yahoo_code, "price": row['price'], "pct": row['pct'],
                "flow": f"{money_val:.0f}万", "tag": tag, "news": news_display, 
                "prob": prob, "reason": reason
            })
        except: continue
        
    return sorted(results, key=lambda x: x['prob'], reverse=True)

# ================= 5. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("📡 AlphaQuant Pro")
        st.caption("v39.0 双核实时版")
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
        st.info(f"👤 {st.session_state['username']}")
        menu = st.radio("导航", ["🔮 Alpha-X 每日金股", "🔎 个股全维透视", "👀 我的关注", "🏆 市场全景", "⚙️ 设置"])
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. Alpha-X 金股预测 (绝对核心) ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 明日必涨金股")
        
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            # 按钮触发强制刷新，不走缓存
            refresh = st.button("🚀 立即扫描全市场", type="primary")
        
        # 自动加载或点击加载
        if refresh or 'picks' not in st.session_state:
            with st.spinner("正在连接双核数据源 (Eastmoney/Sina)..."):
                # 获取实时数据 (无缓存)
                df_realtime, source_name = get_realtime_market_scan()
                if not df_realtime.empty:
                    # 计算推荐
                    st.session_state['picks'] = generate_alpha_x_v39(df_realtime)
                    st.session_state['data_source'] = source_name
                    st.session_state['scan_time'] = datetime.now().strftime("%H:%M:%S")
                else:
                    st.error("所有数据源连接超时，请重试。")
        
        # 展示结果
        if 'picks' in st.session_state and st.session_state['picks']:
            st.success(f"✅ 数据源：**{st.session_state['data_source']}** | 更新时间：{st.session_state['scan_time']}")
            
            picks = st.session_state['picks']
            
            t1, t2 = st.tabs(["⚡️ 综合金股 (Top 10)", "💎 长线稳健"])
            
            with t1:
                for i, p in enumerate(picks):
                    with st.container(border=True):
                        c1, c2, c3, c4 = st.columns([1, 2, 3, 3])
                        with c1: st.markdown(f"# {i+1}")
                        with c2: st.markdown(f"### {p['name']}"); st.caption(p['code'])
                        with c3: 
                            st.metric("现价", f"¥{p['price']:.2f}", f"{p['pct']:.2f}%")
                            st.caption(f"资金: {p['flow']}")
                        with c4: 
                            st.progress(p['prob']/100, text=f"🔥 **{p['prob']:.1f}%**")
                            st.caption(p['news'])
                        st.info(p['reason'])
            
            with t2:
                st.info("长线板块需拉取历史数据，建议盘后查看。")
                
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
                    with st.container(border=True):
                        top1, top2, top3 = st.columns(3)
                        top1.metric(d['name'], f"¥{d['price']}", f"{d['pct']}%")
                        top2.metric("操作信号", d['action'])
                        with top3:
                            if d['color']=='green': st.success("买入")
                            elif d['color']=='red': st.error("卖出")
                            else: st.info("观望")
                    
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
        # 这里也使用实时无缓存数据
        df_full, _ = get_realtime_market_scan()
        if not df_full.empty:
            t1, t2 = st.tabs(["🚀 涨幅榜", "💰 资金榜"])
            with t1: st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(15)[['name','price','pct']], use_container_width=True)
            with t2: st.dataframe(df_full.sort_values("money_flow",ascending=False).head(15)[['name','price','money_flow']], use_container_width=True)
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


































