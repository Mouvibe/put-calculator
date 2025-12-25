import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime
import time

# --- 页面配置 ---
st.set_page_config(page_title="卖Put年化收益计算器", page_icon="💰", layout="wide")

# --- 缓存函数：核心防封锁逻辑 ---
# ttl=300 表示缓存 300秒 (5分钟)。在这5分钟内，无论怎么调参数，都不会重新请求雅虎。
@st.cache_data(ttl=300, show_spinner=False)
def fetch_option_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        
        # 1. 获取股价 (增加重试机制)
        # 尝试多次获取价格，因为有时候网络波动
        current_price = None
        for key in ['currentPrice', 'regularMarketPrice', 'previousClose', 'open']:
            try:
                val = stock.info.get(key)
                if val:
                    current_price = val
                    break
            except:
                continue
                
        if not current_price:
            return None, "无法获取当前股价，可能是代码错误或雅虎接口波动。"

        # 2. 获取到期日
        expirations = stock.options
        if not expirations:
            return None, "未找到期权链数据。"

        # 默认只抓取最近 3 个到期日，减少数据量，降低被封概率
        target_expirations = expirations[:3]
        
        all_puts_raw = []
        
        for date in target_expirations:
            try:
                # 获取期权链
                opt = stock.option_chain(date)
                puts = opt.puts
                
                # 添加日期信息
                puts['expiration'] = date
                exp_dt = datetime.strptime(date, "%Y-%m-%d")
                dte = (exp_dt - datetime.now()).days
                if dte <= 0: dte = 1
                puts['dte'] = dte
                
                # 预先筛选：只保留稍微靠谱的数据 (Strike 在 0.5倍 到 1.2倍股价之间)
                # 这样可以减少后续处理的数据量
                puts = puts[(puts['strike'] > current_price * 0.5) & (puts['strike'] < current_price * 1.2)]
                
                all_puts_raw.append(puts)
                
                # 稍微暂停 0.1 秒，温柔一点，避免被判定为攻击
                time.sleep(0.1) 
                
            except Exception:
                continue # 如果某一天的数据抓取失败，跳过，继续抓下一天

        if not all_puts_raw:
            return None, "没有获取到有效的期权数据。"

        final_df = pd.concat(all_puts_raw)
        return final_df, current_price

    except Exception as e:
        return None, f"数据抓取严重错误: {str(e)}"

# --- 侧边栏 ---
st.sidebar.header("⚙️ 参数设置")
ticker = st.sidebar.text_input("股票代码 (美股)", value="NVDA").upper().strip()

st.sidebar.subheader("💰 计算基准")
price_basis = st.sidebar.radio(
    "权利金价格",
    options=["买一价 (Bid)", "最新价 (Last)", "卖一价 (Ask)"],
    index=0
)

st.sidebar.subheader("🔍 筛选过滤")
min_annualized_return = st.sidebar.slider("最低年化收益 (%)", 0, 100, 15)
min_safety_margin = st.sidebar.slider("最低安全边际 (%)", 0, 50, 10)
show_otm_only = st.sidebar.checkbox("只显示价外 (OTM)", value=True)

# 强制刷新按钮
if st.sidebar.button("🔄 强制刷新数据"):
    st.cache_data.clear()

# --- 主界面 ---
st.title("💰 美股 Put 卖方计算器 (防封版)")

if ticker:
    with st.spinner(f"正在从雅虎财经拉取 {ticker} 数据... (缓存有效期5分钟)"):
        # 调用缓存函数
        raw_df, price_info = fetch_option_data(ticker)
        
        if isinstance(price_info, str): # 如果返回的是错误信息
            st.error(f"❌ {price_info}")
            if "Too Many Requests" in price_info or "Rate limited" in str(price_info):
                st.warning("⚠️ 雅虎财经限制了访问频率。建议：\n1. 等待几分钟再试。\n2. 尝试换一个冷门的股票代码测试。\n3. 如果持续报错，建议在本地电脑运行此脚本。")
        else:
            current_price = price_info
            
            # --- 数据处理逻辑 (在缓存数据基础上进行计算) ---
            # 1. 确定价格列
            if "Bid" in price_basis:
                p_col = 'bid'
                disp_col = '权利金(Bid)'
            elif "Last" in price_basis:
                p_col = 'lastPrice'
                disp_col = '权利金(Last)'
            else:
                p_col = 'ask'
                disp_col = '权利金(Ask)'
            
            df = raw_df.copy()
            
            # 2. 过滤 OTM
            if show_otm_only:
                df = df[df['strike'] < current_price]
            
            # 3. 计算
            df['premium'] = df[p_col].fillna(0)
            df['Annualized Return %'] = (df['premium'] / df['strike']) * (365 / df['dte']) * 100
            df['Safety Margin %'] = ((current_price - df['strike']) / current_price) * 100
            df['Break Even'] = df['strike'] - df['premium']
            
            # 4. 筛选
            df = df[df['Annualized Return %'] >= min_annualized_return]
            df = df[df['Safety Margin %'] >= min_safety_margin]
            
            # 5. 展示
            col1, col2 = st.columns(2)
            col1.metric("当前股价", f"${current_price:.2f}")
            col2.caption(f"数据缓存已开启。如需最新数据，请点击左侧'强制刷新'。")
            
            if not df.empty:
                df = df.sort_values(by=['expiration', 'strike'], ascending=[True, False])
                
                display_cols = ['expiration', 'dte', 'strike', 'premium', 'Annualized Return %', 'Safety Margin %', 'Break Even', 'volume', 'openInterest']
                df_disp = df[display_cols].copy()
                df_disp.columns = ['到期日', '天数', '行权价', disp_col, '年化收益率%', '安全边际%', '盈亏平衡点', '成交量', '未平仓']
                
                st.dataframe(
                    df_disp.style
                    .format({
                        '行权价': '{:.2f}', 
                        disp_col: '{:.2f}', 
                        '年化收益率%': '{:.2f}', 
                        '安全边际%': '{:.2f}',
                        '盈亏平衡点': '{:.2f}',
                        '成交量': '{:.0f}',
                        '未平仓': '{:.0f}'
                    })
                    .background_gradient(subset=['年化收益率%'], cmap='RdYlGn', vmin=0, vmax=50)
                    .background_gradient(subset=['安全边际%'], cmap='Blues', vmin=0, vmax=20),
                    height=600,
                    use_container_width=True
                )
            else:
                st.warning("没有找到符合筛选条件的期权。尝试降低收益要求？")
else:
    st.info("👈 请在左侧输入代码")
