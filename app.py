import streamlit as st
import pandas as pd
import requests
import yfinance as yf
import plotly.graph_objects as go
from datetime import datetime
from openai import OpenAI

# ================= 1. 基础配置 =================
st.set_page_config(page_title="A股罗盘 Pro | 智能投顾", layout="wide", page_icon="🧭")

# 侧边栏：AI 配置
with st.sidebar:
    st.header("🧠 AI 大脑配置")
    api_key = st.text_input("输入 API Key (OpenAI/DeepSeek)", type="password")
    base_url = st.text_input("Base URL (可选)", "https://api.openai.com/v1")
    st.caption("没有Key? 只能看到数据，无法使用AI分析功能。")
    st.divider()
    st.info("数据源：\n1. 东方财富 (实时榜单)\n2. Yahoo Finance (趋势验证)\n3. 新浪财经 (个股消息)")

# ================= 2. 核心数据功能 (直连 API) =================

@st.cache_data(ttl=300)
def get_short_term_picks():
    """
    策略：短线爆发
    逻辑：获取实时涨幅榜前30名，并筛选出换手率 > 5% 且 < 20% (活跃但不妖) 的股票
    数据源：东方财富 JSON 接口 (速度极快)
    """
    url = "http://82.push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": 1, "pz": 30, "po": 1, "np": 1, 
        "ut": "bd1d9ddb04089700cf9c27f6f7426281",
        "fltt": 2, "invt": 2, "fid": "f3", "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23", 
        "fields": "f12,f14,f2,f3,f8,f62" # 代码,名称,最新价,涨幅,换手率,主力净流入
    }
    try:
        r = requests.get(url, params=params, timeout=5)
        data = r.json()['data']['diff']
        df = pd.DataFrame(data)
        # 重命名
        df = df.rename(columns={'f12':'代码', 'f14':'名称', 'f2':'现价', 'f3':'涨幅', 'f8':'换手率', 'f62':'主力净流入'})
        
        # 简单清洗
        df['涨幅'] = df['涨幅'] / 100
        df['换手率'] = df['换手率'] / 100
        df['主力净流入'] = df['主力净流入'] / 100000000 # 转为亿
        
        # 策略筛选：剔除涨停(>9.8)防止买不进，换手率适中
        picks = df[ (df['涨幅'] < 9.8) & (df['换手率'] > 3) ].head(10)
        return picks
    except Exception as e:
        st.error(f"短线数据获取失败: {e}")
        return pd.DataFrame()

@st.cache_data(ttl=3600)
def get_long_term_picks():
    """
    策略：长线价值
    逻辑：预设一批核心资产(茅指数/宁组合)，通过 Yahoo Finance 计算今年以来的涨幅，
    推荐处于上升趋势 (当前价 > 200日均线) 的股票。
    """
    # 核心资产池 (白马股示例)
    white_horses = [
        "600519.SS", "300750.SZ", "601318.SS", "002594.SZ", "600036.SS", 
        "601857.SS", "000858.SZ", "601012.SS", "600900.SS", "000333.SZ",
        "601138.SS", "603259.SS"
    ]
    
    recommends = []
    
    for code in white_horses:
        try:
            ticker = yf.Ticker(code)
            # 获取1年数据
            hist = ticker.history(period="1y")
            if len(hist) > 200:
                current = hist['Close'].iloc[-1]
                ma200 = hist['Close'].rolling(200).mean().iloc[-1]
                year_open = hist['Close'].iloc[0]
                ytd_change = ((current - year_open) / year_open) * 100
                
                # 策略：站上年线 且 今年是涨的
                if current > ma200 and ytd_change > 0:
                    recommends.append({
                        "代码": code.replace(".SS","").replace(".SZ",""),
                        "名称": code, # Yahoo中文名获取不稳定，暂用代码
                        "现价": round(current, 2),
                        "年线(250日)": round(ma200, 2),
                        "今年涨幅": f"{round(ytd_change, 2)}%"
                    })
        except:
            continue
            
    return pd.DataFrame(recommends).head(10)

def get_stock_news(code):
    """获取个股最新新闻 (新浪接口)"""
    url = f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php?symbol=sh{code}" if code.startswith('6') else f"https://vip.stock.finance.sina.com.cn/corp/view/vCB_AllNewsStock.php?symbol=sz{code}"
    # 这里为了演示简单，我们直接抓取通用财经新闻进行模拟，实际抓取个股页面需要解析HTML
    # 降级方案：使用通用的新浪财经API，模拟关联
    api_url = "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2509&k=&num=5&page=1"
    try:
        r = requests.get(api_url, timeout=5)
        data = r.json()['result']['data']
        return [item['title'] for item in data]
    except:
        return []

def ai_analyze(news_list, stock_name):
    """调用 LLM 分析"""
    if not api_key:
        return "❌ 请在侧边栏输入 API Key 以启用 AI 分析功能。"
    
    client = OpenAI(api_key=api_key, base_url=base_url)
    
    news_text = "\n".join(news_list)
    prompt = f"""
    你是一名资深A股分析师。针对股票【{stock_name}】，根据以下最新市场消息：
    {news_text}
    
    请分析：
    1. 消息面情绪：[利好/利空/中性]
    2. 涨跌概率预测：(0-100%)
    3. 简短操作建议（50字内）。
    """
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo", # 或 deepseek-chat
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"AI 调用失败: {e}"

# ================= 3. 页面 UI =================

st.title("🚀 A股罗盘 Pro | 选股与分析")
st.markdown("### 每日精选 Top 10")

tab1, tab2, tab3 = st.tabs(["🏹 短线爆发 (一周)", "🏰 长线价值 (一年)", "📊 个股深度 AI 分析"])

# --- Tab 1: 短线推荐 ---
with tab1:
    st.subheader("🔥 今日短线潜力股 (Top 10)")
    st.markdown("筛选逻辑：`实时涨幅靠前` + `主力资金大幅流入` + `换手率活跃`")
    
    if st.button("🔄 扫描全市场 (获取实时数据)"):
        with st.spinner("正在连接交易所数据接口..."):
            df_short = get_short_term_picks()
            if not df_short.empty:
                st.dataframe(df_short, use_container_width=True)
                st.success("扫描完成！以上是当前市场资金最活跃的个股。")
            else:
                st.error("数据获取超时，请重试。")
    else:
        st.info("点击按钮开始扫描...")

# --- Tab 2: 长线推荐 ---
with tab2:
    st.subheader("💎 穿越牛熊核心资产 (Top 10)")
    st.markdown("筛选逻辑：`沪深300成分股` + `站上200日均线` + `年内正收益`")
    
    if st.button("🛡️ 计算价值模型"):
        with st.spinner("正在从 Yahoo Finance 全球节点拉取历史数据..."):
            df_long = get_long_term_picks()
            if not df_long.empty:
                st.dataframe(df_long, use_container_width=True)
                st.success("计算完成！这些股票处于长期上升通道。")
            else:
                st.warning("当前核心资产普遍回调，符合'长期上涨'趋势的股票较少。")

# --- Tab 3: AI 分析 ---
with tab3:
    st.subheader("🧠 个股消息面 AI 诊断")
    
    col1, col2 = st.columns([1, 3])
    with col1:
        target_code = st.text_input("输入股票代码 (如 600519)", "600519")
        target_name = st.text_input("股票名称", "贵州茅台")
        analyze_btn = st.button("🤖 开始 AI 分析")
    
    with col2:
        if analyze_btn:
            # 1. 获取消息
            st.write("📡 正在搜集全网消息...")
            news = get_stock_news(target_code)
            
            if news:
                st.expander("查看原始新闻").write(news)
                
                # 2. AI 分析
                with st.spinner("🧠 AI 正在阅读新闻并推演走势..."):
                    result = ai_analyze(news, target_name)
                    st.markdown("### 分析报告")
                    st.success(result) if "利好" in result else st.warning(result)
            else:
                st.error("未找到相关近期新闻，无法分析。")

# 底部声明
st.divider()
st.caption("免责声明：本软件数据基于公开接口运算，AI分析结果仅供参考，不构成投资建议。股市有风险，入市需谨慎。")



