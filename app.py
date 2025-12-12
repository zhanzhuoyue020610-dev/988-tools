import streamlit as st
import pandas as pd
import re
import urllib.parse
from openai import OpenAI
import requests
import warnings
import httpx
import time
import io
import os
from bs4 import BeautifulSoup # 用于解析网页内容

# 忽略 SSL 警告
warnings.filterwarnings("ignore")

# ==========================================
# 🔧 988 Group 云端配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# 1. 页面配置 (Page Config)
st.set_page_config(
    page_title="988 Group - Intelligent Supply Chain", 
    layout="wide", 
    page_icon="🚛",
    initial_sidebar_state="expanded"
)

# 2. 高级感 CSS 注入 (Premium UI)
st.markdown("""
<style>
    /* 全局字体与背景 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
    }
    
    /* 隐藏 Streamlit 默认组件 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* 侧边栏样式 */
    section[data-testid="stSidebar"] {
        background-color: #f4f6f9;
        border-right: 1px solid #e0e0e0;
    }
    
    /* 标题样式 */
    h1 {
        color: #003366; /* 988 深蓝 */
        font-weight: 700;
        letter-spacing: -1px;
    }
    
    /* 核心按钮美化 */
    div.stButton > button {
        background: linear-gradient(135deg, #004aad 0%, #003366 100%);
        color: white;
        border: none;
        padding: 0.6rem 1.2rem;
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.3s ease;
        box-shadow: 0 4px 6px rgba(0, 74, 173, 0.2);
        width: 100%;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 6px 12px rgba(0, 74, 173, 0.3);
    }
    
    /* 结果卡片 (Glassmorphism) */
    div[data-testid="stExpander"] {
        background: white;
        border: 1px solid #edf2f7;
        border-radius: 12px;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
        margin-bottom: 12px;
        transition: box-shadow 0.2s;
    }
    div[data-testid="stExpander"]:hover {
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        border-color: #cbd5e0;
    }
    
    /* 状态提示框 */
    div[data-testid="stStatusWidget"] {
        border-radius: 10px;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=180)
    else:
        st.markdown("## 🚛 **988 Group**")
        
    st.markdown("---")
    st.markdown("### 📊 Control Panel")
    
    # 密钥读取
    try:
        default_cn_user = st.secrets["CN_USER_ID"]
        default_cn_key = st.secrets["CN_API_KEY"]
        default_openai = st.secrets["OPENAI_KEY"]
        is_configured = True
        st.caption("✅ Cloud Secrets Loaded")
    except FileNotFoundError:
        default_cn_user = ""
        default_cn_key = ""
        default_openai = ""
        is_configured = False
        st.caption("⚠️ Local Mode")

    with st.expander("🔧 System Config"):
        use_proxy = st.checkbox("Enable Proxy (Local)", value=False)
        proxy_port = st.text_input("Proxy URL", value="http://127.0.0.1:10809")
        check_user_id = st.text_input("CN User ID", value=default_cn_user)
        check_key = st.text_input("CN Key", value=default_cn_key, type="password")
        openai_key = st.text_input("OpenAI Key", value=default_openai, type="password")

# === 核心功能模块 ===

def get_proxy_config():
    if use_proxy and proxy_port: return proxy_port.strip()
    return None

def extract_web_content(url):
    """
    爬虫模块：尝试获取网页标题和描述
    """
    if not url or not isinstance(url, str) or "http" not in url:
        return None
        
    # 伪装成真实浏览器
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
    
    try:
        # 设置短超时，防止 Ozon 卡死程序
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # 获取标题
            title = soup.title.string.strip() if soup.title else ""
            # 获取描述
            desc = ""
            meta = soup.find('meta', attrs={'name': 'description'})
            if meta:
                desc = meta.get('content', '')
            
            return f"Page Title: {title} | Description: {desc[:200]}"
    except:
        return None # 爬取失败则返回 None，后续 AI 会自动回退到 URL 分析
    return None

def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    # v20.0 正则提取逻辑
    matches_standard = re.findall(r'(\+?(?:7|8)(?:[\s\-\(\)]*\d){10})', full_text)
    matches_short = re.findall(r'(?:\D|^)(9(?:[\s\-\(\)]*\d){9})(?:\D|$)', full_text)
    all_raw_matches = matches_standard + matches_short
    
    candidates = []
    for raw in all_raw_matches:
        if isinstance(raw, tuple): raw = raw[0]
        digits = re.sub(r'\D', '', str(raw))
        clean_num = None
        if len(digits) == 11:
            if digits.startswith('7'): clean_num = digits
            elif digits.startswith('8'): clean_num = '7' + digits[1:]
        elif len(digits) == 10 and digits.startswith('9'):
            clean_num = '7' + digits
        if clean_num: candidates.append(clean_num)
    return list(set(candidates))

def process_checknumber_task(phone_list):
    if not phone_list: return set()
    valid_numbers_set = set()
    
    api_key = check_key.strip()
    user_id = check_user_id.strip()
    if not api_key or not user_id: st.error("Missing API Key/User ID"); return set()

    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    my_proxy_str = get_proxy_config()
    req_proxies = {"http": my_proxy_str, "https": my_proxy_str} if my_proxy_str else None
    
    status_box = st.status("📡 Establishing Connection...", expanded=True)
    status_box.write(f"Uploading {len(phone_list)} numbers for verification...")
    
    # 1. Upload
    file_content = "\n".join(phone_list)
    files = {'file': ('input.txt', file_content, 'text/plain')}
    data_payload = {'user_id': user_id} 
    try:
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data=data_payload, proxies=req_proxies, timeout=30, verify=False)
        if resp.status_code != 200:
            status_box.update(label="❌ Upload Failed", state="error"); st.error(resp.text); return set()
        task_id = resp.json().get("task_id")
    except: status_box.update(label="❌ Network Error", state="error"); return set()

    # 2. Poll
    status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
    result_url = None
    for i in range(80):
        try:
            time.sleep(4)
            poll_resp = requests.get(status_url, headers=headers, params={'user_id': user_id}, proxies=req_proxies, timeout=30, verify=False)
            if poll_resp.status_code == 200:
                p_data = poll_resp.json()
                status = p_data.get("status")
                done = p_data.get("success", 0) + p_data.get("failure", 0)
                total = p_data.get("total", 1)
                status_box.write(f"Verifying... {done}/{total} (Status: {status})")
                if status in ["exported", "completed"]: result_url = p_data.get("result_url"); break
        except: pass
            
    if not result_url: status_box.update(label="❌ Timeout", state="error"); return set()
        
    # 3. Download
    try:
        status_box.write("Analyzing report...")
        f_resp = requests.get(result_url, proxies=req_proxies, verify=False)
        if f_resp.status_code == 200:
            try: res_df = pd.read_excel(io.BytesIO(f_resp.content))
            except: res_df = pd.read_csv(io.BytesIO(f_resp.content))
            res_df.columns = [c.lower() for c in res_df.columns]
            for _, r in res_df.iterrows():
                ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                num = str(r.get('number') or r.get('phone') or '')
                cn = re.sub(r'\D', '', num)
                if "yes" in ws or "valid" in ws: valid_numbers_set.add(cn)
            status_box.update(label=f"✅ Verified: {len(valid_numbers_set)} active accounts", state="complete")
    except: status_box.update(label="❌ Parse Error", state="error")

    return valid_numbers_set

def get_ai_message_premium(client, shop_name, shop_link, web_content):
    """
    v21.0 旗舰 AI 逻辑：结合网页内容 + URL + 店名
    """
    if pd.isna(shop_name): shop_name = "Seller"
    if pd.isna(shop_link): shop_link = "Ozon Store"
    
    # 构建信息源
    source_info = f"URL: {shop_link}"
    if web_content:
        source_info += f"\nScraped Page Content: {web_content}"
    
    prompt = f"""
    Role: Senior Business Development Director at "988 Group" (China).
    Target: Ozon Seller "{shop_name}".
    Source Info: 
    {source_info}
    
    Context:
    988 Group is a premier Supply Chain Partner offering:
    1. Direct Sourcing (Factory Pricing).
    2. Logistics & Customs Clearance to Russia (Door-to-Door).
    
    Task:
    1. Analyze the 'Source Info' to identify their EXACT product niche (e.g., Baby Strollers, Car DVRs, Pet Food).
    2. Create a hyper-personalized Russian WhatsApp message.
    
    Structure:
    - Opening: "Saw your [Specific Product] collection on Ozon..." (Be specific!)
    - Value: "We help top sellers source [Specific Product] directly from China factories + handle shipping to Moscow."
    - CTA: "Open to a quote?"
    
    Constraint: Native Russian. Professional yet conversational. <40 words.
    Output: Russian text only.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, 
            max_tokens=250
        )
        return response.choices[0].message.content.strip()
    except:
        return f"Здравствуйте, {shop_name}! Мы 988 Group (Китай). Поможем с закупкой и доставкой товаров. Актуально?"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# === 主程序界面 ===

# 头部 Header
st.markdown("### 🚀 988 Group AI-Driven Supply Chain")
st.markdown("Automated Sourcing & Logistics Lead Generation")
st.markdown("---")

uploaded_file = st.file_uploader("📂 Upload Lead List (Excel/CSV)", type=['xlsx', 'csv'])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file, header=None)
        else: df = pd.read_excel(uploaded_file, header=None)
        df = df.astype(str)
    except: st.stop()
        
    # 高级列选择器
    with st.container():
        st.info("👇 Map your data columns for AI Context")
        c1, c2 = st.columns(2)
        with c1:
            shop_col_idx = st.selectbox("🏷️ Store Name Column", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2:
            link_col_idx = st.selectbox("🔗 Store Link Column (Crucial for AI)", range(len(df.columns)), index=0)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 START AI ENGINE", type="primary"):
        
        # 1. 鉴权
        my_proxy_str = get_proxy_config()
        if not openai_key: st.error("❌ OpenAI Key Missing"); st.stop()

        client = None
        if my_proxy_str:
            try:
                try: http_client = httpx.Client(proxy=my_proxy_str, verify=False)
                except: http_client = httpx.Client(proxies=my_proxy_str, verify=False)
                client = OpenAI(api_key=openai_key, http_client=http_client)
            except: st.error("Proxy Error"); st.stop()
        else:
            client = OpenAI(api_key=openai_key)

        # 2. 提取
        all_raw_phones = set()
        phone_to_rows = {}
        
        # 进度显示
        progress_text = st.empty()
        progress_bar = st.progress(0)
        
        for i, row in df.iterrows():
            extracted = extract_all_numbers(row)
            for p in extracted:
                all_raw_phones.add(p)
                if p not in phone_to_rows: phone_to_rows[p] = []
                phone_to_rows[p].append(i)
            progress_bar.progress((i+1)/len(df))
            
        if not all_raw_phones: st.error("No numbers found."); st.stop()

        # 3. 验号
        valid_phones_set = process_checknumber_task(list(all_raw_phones))
        
        # 4. AI 生成 (含爬虫)
        if valid_phones_set:
            # 数据看板
            st.markdown("---")
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Raw Numbers", len(all_raw_phones))
            kpi2.metric("Verified WA", len(valid_phones_set))
            kpi3.metric("Conversion Rate", f"{len(valid_phones_set)/len(all_raw_phones)*100:.1f}%")
            
            st.success("🧠 AI is analyzing store content & writing copy...")
            final_results = []
            
            valid_rows_indices = set()
            for p in valid_phones_set:
                for r in phone_to_rows.get(p, []): valid_rows_indices.add(r)
            sorted_indices = sorted(list(valid_rows_indices))
            
            ai_bar = st.progress(0)
            
            for idx_step, row_idx in enumerate(sorted_indices):
                row = df.iloc[row_idx]
                row_phones = extract_all_numbers(row)
                row_valid = [p for p in row_phones if p in valid_phones_set]
                
                if row_valid:
                    shop_name = row[shop_col_idx]
                    shop_link = row[link_col_idx]
                    
                    # === 关键步骤：尝试爬取内容 ===
                    web_content = extract_web_content(shop_link)
                    
                    # === AI 生成 ===
                    ai_msg = get_ai_message_premium(client, shop_name, shop_link, web_content)
                    
                    links = [make_wa_link(p, ai_msg) for p in row_valid]
                    final_results.append({
                        "Shop Name": shop_name,
                        "Link": shop_link,
                        "AI Context": "Scraped" if web_content else "URL Only",
                        "Phone": ", ".join(row_valid),
                        "Personalized Message": ai_msg,
                        "Direct Link": " | ".join(links)
                    })
                ai_bar.progress((idx_step+1)/len(sorted_indices))
            
            res_df = pd.DataFrame(final_results)
            
            st.subheader("🎯 Qualified Leads")
            for _, item in res_df.head(50).iterrows():
                with st.expander(f"🏢 {item['Shop Name']} ({item['AI Context']})"):
                    st.write(f"**Generated:** {item['Personalized Message']}")
                    st.caption(f"Source: {item['Link']}")
                    for l in item['Direct Link'].split(" | "): 
                        st.link_button("📲 Send via WhatsApp", l)
            
            csv = res_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Download Final Report", csv, "988_premium_leads.csv", "text/csv")
        else:
            st.warning("No valid WhatsApp numbers found.")
