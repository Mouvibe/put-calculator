import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 页面配置 ---
st.set_page_config(page_title="卖Put年化收益计算器", page_icon="💰", layout="wide")

# --- 侧边栏设置 ---
st.sidebar.header("⚙️ 参数设置")
ticker = st.sidebar.text_input("股票代码 (美股)", value="NVDA").upper().strip()

# 新增：价格选择逻辑
st.sidebar.subheader("💰 计算逻辑")
price_basis = st.sidebar.radio(
    "权利金价格基准",
    options=["买一价 (Bid) - 保守/推荐", "最新价 (Last) - 市场成交", "卖一价 (Ask) - 乐观/挂单"],
    index=0,
    help="作为期权卖方(Seller)，'Bid'是你立刻能卖出的价格；'Last'是最近一笔成交价；'Ask'是买方要价，你通常很难以此价格立刻成交。"
)

# 筛选条件
st.sidebar.subheader("🔍 筛选过滤")
min_annualized_return = st.sidebar.slider("最低目标年化收益 (%)", 0, 100, 15)
min_safety_margin = st.sidebar.slider("最低安全边际/跌幅保护 (%)", 0, 50, 10)
show_otm_only = st.sidebar.checkbox("只显示价外期权 (OTM)", value=True)

st.title("💰 美股 Put 卖方年化收益计算器")
st.markdown("实时获取期权链数据，支持多维度价格模型计算。")

# --- 核心逻辑 ---
if ticker:
    try:
        with st.spinner(f"正在拉取 {ticker} 的数据..."):
            stock = yf.Ticker(ticker)
            
            # 获取股价
            info = stock.info
            current_price = info.get('currentPrice') or info.get('regularMarketPrice') or info.get('previousClose')
            
            if not current_price:
                st.error("❌ 无法获取当前股价，请检查代码。")
                st.stop()

            # 显示当前行情
            col1, col2, col3 = st.columns(3)
            col1.metric("当前股价", f"${current_price:.2f}")
            
            # 确定要使用的价格列名
            if "Bid" in price_basis:
                target_price_col = 'bid'
                display_premium_col = '权利金(Bid)'
            elif "Last" in price_basis:
                target_price_col = 'lastPrice'
                display_premium_col = '权利金(Last)'
            else:
                target_price_col = 'ask'
                display_premium_col = '权利金(Ask)'
            
            col2.metric("计算基准", display_premium_col)

            # 获取期权到期日
            expirations = stock.options
            if not expirations:
                st.error("未找到期权数据。")
                st.stop()
            
            # 默认选择最近的3个日期
            default_exp = expirations[:3] if len(expirations) >= 3 else expirations
            selected_dates = st.multiselect(
                "📅 选择到期日", 
                options=expirations,
                default=default_exp
            )

            if not selected_dates:
                st.warning("请至少选择一个到期日。")
                st.stop()

            all_puts = []
            progress_bar = st.progress(0)
            
            for i, date in enumerate(selected_dates):
                progress_bar.progress((i + 1) / len(selected_dates))
                
                # 获取期权链
                opt = stock.option_chain(date)
                puts = opt.puts
                
                # 计算 DTE
                exp_dt = datetime.strptime(date, "%Y-%m-%d")
                dte = (exp_dt - datetime.now()).days
                if dte <= 0: dte = 1 
                
                # 1. 过滤 Strike
                if show_otm_only:
                    puts = puts[puts['strike'] < current_price]
                else:
                    puts = puts[(puts['strike'] > current_price * 0.7) & (puts['strike'] < current_price * 1.1)]

                # 2. 获取权利金 (根据用户选择)
                # 处理异常值：如果数据缺失，填0
                puts['premium'] = puts[target_price_col].fillna(0)
                
                # 特殊处理：如果是选Bid且Bid为0（可能休市或无流动性），虽然真实，但为了避免误解，也可以不显示或标红
                # 这里我们保持原样计算，收益率会是0
                
                # 3. 计算指标
                puts['Annualized Return %'] = (puts['premium'] / puts['strike']) * (365 / dte) * 100
                puts['Safety Margin %'] = ((current_price - puts['strike']) / current_price) * 100
                puts['Break Even'] = puts['strike'] - puts['premium']
                
                # 辅助列
                puts['Expiration'] = date
                puts['DTE'] = dte
                
                # 4. 筛选
                puts = puts[puts['Annualized Return %'] >= min_annualized_return]
                puts = puts[puts['Safety Margin %'] >= min_safety_margin]

                # 选取展示列
                # 注意：这里我们把成交量和未平仓也加上，方便判断流动性
                display_cols = ['Expiration', 'DTE', 'strike', 'premium', 'Annualized Return %', 'Safety Margin %', 'Break Even', 'volume', 'openInterest']
                
                if not puts.empty:
                    all_puts.append(puts[display_cols])

            progress_bar.empty()

            # --- 结果展示 ---
            if all_puts:
                final_df = pd.concat(all_puts)
                final_df = final_df.sort_values(by=['Expiration', 'strike'], ascending=[True, False])
                
                # 动态重命名列
                final_df.columns = ['到期日', '天数', '行权价', display_premium_col, '年化收益率%', '安全边际%', '盈亏平衡点', '成交量', '未平仓']

                st.success(f"✅ 基于【{display_premium_col}】计算完成，共 {len(final_df)} 个机会")
                
                st.dataframe(
                    final_df.style
                    .format({
                        '行权价': '{:.2f}', 
                        display_premium_col: '{:.2f}', 
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
                st.warning(f"在当前【{display_premium_col}】下，没有找到符合筛选条件的期权。请尝试：\n1. 切换价格基准（如使用 Last）\n2. 降低目标年化收益")

    except Exception as e:
        st.error(f"发生错误: {e}")