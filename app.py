import streamlit as st
import pandas as pd
import requests

st.set_page_config(page_title="连接测试诊断", layout="wide")

st.title("🛠️ Streamlit Cloud 连接诊断模式")

# --- 测试 1: 检查库是否安装 ---
st.subheader("1. 环境检查")
try:
    import akshare as ak
    st.success(f"✅ AkShare 库已安装，版本: {ak.__version__}")
except ImportError:
    st.error("❌ AkShare 未安装！请检查 GitHub 仓库中是否有 requirements.txt 文件。")
    st.stop()

# --- 测试 2: 检查基础网络连通性 ---
st.subheader("2. 国际互联网连通性测试")
try:
    response = requests.get("https://www.google.com", timeout=5)
    st.success(f"✅ 能够访问 Google (Status: {response.status_code}) - 说明云端服务器网络正常")
except Exception as e:
    st.warning(f"⚠️ 无法访问 Google: {e}")

# --- 测试 3: 检查国内数据源连通性 (AkShare) ---
st.subheader("3. AkShare 数据源穿透测试")
st.write("Streamlit Cloud 服务器位于海外，可能会被国内财经网站拦截。")

if st.button("开始 AkShare 数据抓取测试"):
    
    # 测试 A: 新闻接口 (通常较容易成功)
    st.write("--- 测试 A: 获取财经新闻 ---")
    try:
        with st.spinner("正在抓取财联社电报..."):
            news_df = ak.stock_info_global_cls_em()
            if not news_df.empty:
                st.success(f"✅ 成功获取新闻！共 {len(news_df)} 条")
                st.dataframe(news_df.head(3))
            else:
                st.warning("⚠️ 接口返回了空数据")
    except Exception as e:
        st.error(f"❌ 新闻接口失败 (可能是被反爬拦截): {e}")

    # 测试 B: 实时股价接口 (容易被封)
    st.write("--- 测试 B: 获取上证指数 ---")
    try:
        with st.spinner("正在抓取大盘数据..."):
            index_df = ak.stock_zh_index_spot()
            sh_index = index_df[index_df['名称'] == '上证指数']
            st.success(f"✅ 成功获取指数: {sh_index['最新价'].values[0]}")
    except Exception as e:
        st.error(f"❌ 股价接口失败: {e}")
        st.info("💡 提示：如果新闻能用但股价不能用，说明该接口对海外IP有严格限制。")

