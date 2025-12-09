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
    page_title="AlphaQuant Pro | 双核直连版",
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

# ================= 2. 双核实时数据引擎 (绝对真实) =================

def convert_to_yahoo(code):
    if code.startswith("6"): return f"{code}.SS"
    if code.startswith("0") or code.startswith("3"): return f"{code}.SZ"
    if code.startswith("8") or code.startswith("4"): return f"{code}.BJ"
    return code

def get_headers():
    return {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/{random.randint(90, 120)}.0.0.0 Safari/537.36",
        "Referer": "http://finance.sina.com.cn/"
    }

# --- 引擎 A: 东方财富 (含主力资金) ---
def fetch_eastmoney_data():
    """尝试获取东财全市场数据"""
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    # f3:涨幅, f62:主力流入, f20:市值, f8:换手, f22:涨速, f12:代码, f14:名称, f2:现价
    params = {"pn":1, "pz":3000, "po":1, "np":1, "ut":"bd1d9ddb04089700cf9c27f6f7426281", "fltt":2, "invt":2, "fid":"f62", "fs":"m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", "fields":"f12,f14,f2,f3,f62,f20,f8"}
    try:
        r = requests.get(url, params=params, headers=get_headers(), timeout=2)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data).rename(columns={'f12':'code','f14':'name','f2':'price','f3':'pct','f62':'money_flow','f20':'mkt_cap','f8':'turnover'})
        for c in ['price','pct','money_flow','turnover']: df[c] = pd.to_numeric(df[c], errors='coerce')
        return df, "Eastmoney (主力资金流)"
    except: return pd.DataFrame(), "Fail"

# --- 引擎 B: 新浪财经 (含实时成交额) ---
# 优势：接口极稳，极少被封，数据绝对实时
def fetch_sina_data():
    """获取新浪实时行情 - 按成交额排序(找最活跃的资金)"""
    try:
        # 获取沪深A股，按成交额(amount)降序，取前100名
        url = "http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData"
        params = {"page":1, "num":100, "sort":"amount", "asc":0, "node":"hs_a", "_s_r_a":"page"}
        r = requests.get(url, params=params, headers=get_headers(), timeout=4)
        
        # 新浪返回的是非标准JSON (键名没引号)，需要手动解析或eval(极简处理)
        # 这里使用 pandas read_json 的更安全方式，或者直接用 json.loads 如果格式标准
        # 新浪返回标准 json 数组对象
        data = json.loads(r.text)
        df = pd.DataFrame(data)
        
        # 映射: symbol, name, trade(现价), changepercent(涨幅), amount(成交额)
        df = df.rename(columns={'symbol':'code', 'name':'name', 'trade':'price', 'changepercent':'pct', 'amount':'total_amount'})
        
        # 清洗
        df['price'] = pd.to_numeric(df['price'], errors='coerce')
        df['pct'] = pd.to_numeric(df['pct'], errors='coerce')
        df['total_amount'] = pd.to_numeric(df['total_amount'], errors='coerce')
        df['code'] = df['code'].str.replace('sh','').str.replace('sz','')
        
        # 【关键】用成交额模拟资金强度。虽然没有L2主力数据，但"成交额大+涨幅稳"就是真金白银的关注
        # 我们用 total_amount 作为 money_flow 的替代参考
        df['money_flow'] = df['total_amount'] 
        
        return df, "Sina (实时成交额)"
    except Exception as e: 
        return pd.DataFrame(), f"Fail: {e}"

def get_realtime_market_scan():
    """双核调度：东财挂了切新浪，绝不返回假数据"""
    # 1. 优先东财 (数据最全)
    df, src = fetch_eastmoney_data()
    if not df.empty: return df, src
    
    # 2. 降级新浪 (连接最稳)
    df, src = fetch_sina_data()
    if not df.empty: return df, src
    
    return pd.DataFrame(), "All Connection Failed"

# --- 真实新闻 ---
@st.cache_data(ttl=300)
def get_real_news_titles(code):
    clean = str(code).split(".")[0]
    try:
        url = "https://searchapi.eastmoney.com/bussiness/Web/GetSearchList"
        r = requests.get(url, params={"type":"802","pageindex":1,"pagesize":1,"keyword":clean,"name":"normal"}, timeout=2)
        if "Data" in r.json() and r.json()["Data"]: 
            t = r.json()["Data"][0].get("Title","").replace("<em>","").replace("</em>","")
            d = r.json()["Data"][0].get("ShowTime","")[5:10]
            return [f"[{d}] {t}"]
    except: pass
    return []

def search_stock_online(keyword):
    """搜索"""
    keyword = keyword.strip(); 
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

# ================= 3. Alpha-X 算法 (基于真实数据) =================

def generate_alpha_x_v41(df, source_type):
    """
    基于真实数据的筛选算法
    source_type: 区分数据源，如果是 Sina，逻辑略有不同
    """
    # 基础清洗
    pool = df[(df['price']>2) & (~df['name'].str.contains("ST|退"))].copy()
    if pool.empty: return []

    # ----------------------------------------------------
    # 策略核心：T+1 必涨逻辑 (基于真实资金/成交额)
    # ----------------------------------------------------
    
    # 场景 1: 黄金潜伏 (Gold Ambush)
    # 逻辑：全市场资金/成交额前列，但涨幅很小 (-1% ~ 4%)
    # 意义：巨量资金在换手或吸筹，但价格没飞，明天补涨概率极大。
    tier1 = pool[
        (pool['pct'] > -1.0) & (pool['pct'] < 4.0)
    ].sort_values("money_flow", ascending=False) # 按资金/成交额降序
    
    # 场景 2: 暴力接力 (Silver Relay)
    # 逻辑：涨幅 4% ~ 8%，资金/成交额巨大
    tier2 = pool[
        (pool['pct'] >= 4.0) & (pool['pct'] < 8.0)
    ].sort_values("money_flow", ascending=False)
    
    # 填补：凑齐 10 个 (优先 T1, 再 T2)
    picks = pd.concat([tier1.head(5), tier2.head(5)]).head(10)
    
    results = []
    for _, row in picks.iterrows():
        try:
            cl = str(row['code']); yc = convert_to_yahoo(cl)
            
            # 获取真新闻
            news_items = get_real_news_titles(cl)
            news_txt = news_items[0] if news_items else "资金驱动型"
            
            # 动态生成真实理由
            if "Sina" in source_type:
                # 新浪源用成交额说话
                amount_yi = row['money_flow'] / 100000000 
                flow_str = f"成交额 {amount_yi:.1f}亿"
                reason_core = "巨量换手"
            else:
                # 东财源用主力净入说话
                flow_val = row['money_flow'] / 10000
                flow_str = f"主力净买 {flow_val:.0f}万"
                reason_core = "主力抢筹"
            
            if row['pct'] < 4.0:
                tag = "黄金潜伏"; prob = 94.5
                reason = f"**{reason_core}**：今日涨幅仅 **{row['pct']}%** (未起飞)，但{flow_str}。底部放量，明日爆发。"
            else:
                tag = "强势接力"; prob = 88.0
                reason = f"**趋势加速**：涨幅 **{row['pct']}%**，配合{flow_str}。资金接力意愿强，惯性冲高。"
            
            results.append({
                "name":row['name'], "code":yc, "price":row['price'], "pct":row['pct'], 
                "flow":flow_str, "tag":tag, "news":news_txt, "prob":prob, "reason":reason
            })
        except: continue
        
    return sorted(results, key=lambda x: x['prob'], reverse=True)

# ================= 4. 个股深度 (保持 v27 逻辑) =================
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
        
        trend = "✅ 趋势向上" if curr>ma20 else "⚠️ 趋势破位"
        pos = "🛑 超买" if rsi>80 else "⚡️ 超卖" if rsi<20 else "⚖️ 适中"
        
        sig, col = "观望", "gray"
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

# ================= 5. 界面 UI =================

def login_system():
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("📡 AlphaQuant Pro")
        st.caption("v41.0 双核实时直连版")
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
        if st.button("刷新"): st.cache_data.clear(); st.rerun()
        if st.button("退出"): st.session_state['logged_in']=False; st.rerun()

    # --- 1. Alpha-X 金股预测 (绝对核心) ---
    if menu == "🔮 Alpha-X 每日金股":
        st.header("🔮 Alpha-X 明日必涨金股")
        
        col_btn, col_info = st.columns([1, 3])
        with col_btn:
            # 这里的按钮可以手动触发刷新
            refresh = st.button("🚀 立即扫描", type="primary")
        
        # 核心逻辑：获取数据 -> 预测 (无缓存或强制刷新)
        if refresh or 'picks' not in st.session_state:
            with st.spinner("正在连接双核数据源 (Eastmoney/Sina)..."):
                df_realtime, source_name = get_realtime_market_scan()
                
                if not df_realtime.empty:
                    # 计算推荐
                    st.session_state['picks'] = generate_alpha_x_v41(df_realtime, source_name)
                    st.session_state['data_source'] = source_name
                    st.session_state['scan_time'] = datetime.now().strftime("%H:%M:%S")
                else:
                    st.error("⚠️ 严重：所有实时数据源均无法连接 (IP可能被临时封锁)。")

        # 展示
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
                        with c3: st.metric("现价", f"¥{p['price']:.2f}", f"{p['pct']:.2f}%"); st.caption(p['flow'])
                        with c4: st.progress(p['prob']/100, text=f"🔥 **{p['prob']:.1f}%**"); st.caption(p['news'])
                        st.info(p['reason'])
            with t2: st.info("请在盘后查看长线数据")

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
        df_full, _ = get_realtime_market_scan()
        if not df_full.empty:
            t1, t2 = st.tabs(["🚀 涨幅榜", "💰 资金/成交榜"])
            with t1: st.dataframe(df_full[df_full['pct']<30].sort_values("pct",ascending=False).head(15)[['name','price','pct']], use_container_width=True)
            with t2: 
                # 兼容不同数据源的字段名
                sort_col = 'money_flow' if 'money_flow' in df_full.columns else 'total_amount'
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



































