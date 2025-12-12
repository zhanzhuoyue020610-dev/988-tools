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
from bs4 import BeautifulSoup 

# 忽略 SSL 警告
warnings.filterwarnings("ignore")

# ==========================================
# 🔧 988 Group 云端配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# 1. 页面配置
st.set_page_config(
    page_title="988 Group CRM", 
    layout="wide", 
    page_icon="🚛",
    initial_sidebar_state="expanded"
)

# 2. 高级 CSS (含 HTML 按钮样式)
st.markdown("""
<style>
    /* 全局字体 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    
    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: #f8f9fc;
    }
    
    /* 隐藏默认组件 */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* 侧边栏 */
    section[data-testid="stSidebar"] {
        background-color: #ffffff;
        border-right: 1px solid #ebedf0;
    }
    
    /* 主按钮样式 (Python 生成的) */
    div.stButton > button {
        background: linear-gradient(135deg, #0052cc 0%, #003366 100%);
        color: white;
        border: none;
        padding: 0.75rem 1.5rem;
        border-radius: 10px;
        font-weight: 600;
        font-size: 16px;
        transition: all 0.3s ease;
        box-shadow: 0 4px 12px rgba(0, 82, 204, 0.2);
        width: 100%;
        text-transform: uppercase;
    }
    div.stButton > button:hover {
        transform: translateY(-2px);
        box-shadow: 0 8px 16px rgba(0, 82, 204, 0.3);
    }

    /* === 核心修复：自定义 HTML 链接按钮样式 === */
    /* 这将替代 st.link_button，永不崩溃 */
    .custom-wa-btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        background: linear-gradient(135deg, #25D366 0%, #128C7E 100%); /* WhatsApp 风格渐变 */
        color: white !important;
        text-decoration: none !important;
        font-weight: 600;
        font-size: 14px;
        padding: 8px 16px;
        border-radius: 8px;
        width: 100%;
        margin-top: 5px;
        margin-bottom: 5px;
        box-shadow: 0 2px 5px rgba(37, 211, 102, 0.2);
        transition: all 0.2s ease;
        border: 1px solid transparent;
    }
    .custom-wa-btn:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 10px rgba(37, 211, 102, 0.3);
        color: white !important;
    }
    .custom-wa-btn:active {
        transform: translateY(0);
    }
    
    /* 结果卡片 */
    div[data-testid="stExpander"] {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        margin-bottom: 12px;
    }
    div[data-testid="stExpander"]:hover {
        border-color: #0052cc;
        box-shadow: 0 4px 12px rgba(0,0,0,0.05);
    }
</style>
""", unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)
    else:
        st.markdown("# 🚛 **988 Group**")
        
    st.markdown("### **Intelligent Sourcing CRM**")
    st.caption("v28.0 Stable (HTML Core) ✨")
    st.markdown("---")
    
    try:
        default_cn_user = st.secrets["CN_USER_ID"]
        default_cn_key = st.secrets["CN_API_KEY"]
        default_openai = st.secrets["OPENAI_KEY"]
        status_color = "🟢"
        status_text = "Cloud Connected"
    except FileNotFoundError:
        default_cn_user = ""
        default_cn_key = ""
        default_openai = ""
        status_color = "🟠"
        status_text = "Local Mode"

    st.info(f"{status_color} System Status: **{status_text}**")

    with st.expander("🔧 Developer Settings"):
        use_proxy = st.checkbox("Enable Proxy", value=False)
        proxy_port = st.text_input("Proxy URL", value="http://127.0.0.1:10809")
        check_user_id = st.text_input("CN User ID", value=default_cn_user)
        check_key = st.text_input("CN Key", value=default_cn_key, type="password")
        openai_key = st.text_input("OpenAI Key", value=default_openai, type="password")

# === 核心函数 ===

def get_proxy_config():
    if use_proxy and proxy_port: return proxy_port.strip()
    return None

def extract_web_content(url):
    if not url or not isinstance(url, str) or "http" not in url: return None
    headers = {"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            desc = ""
            meta = soup.find('meta', attrs={'name': 'description'})
            if meta: desc = meta.get('content', '')
            return f"Page Title: {title} | Description: {desc[:200]}"
    except: return None
    return None

def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
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
    if not api_key or not user_id: st.error("Configuration Missing"); return set()

    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    my_proxy_str = get_proxy_config()
    req_proxies = {"http": my_proxy_str, "https": my_proxy_str} if my_proxy_str else None
    
    with st.status("📡 Connecting to Verification Server...", expanded=True) as status:
        status.write(f"Uploading {len(phone_list)} numbers...")
        file_content = "\n".join(phone_list)
        files = {'file': ('input.txt', file_content, 'text/plain')}
        data_payload = {'user_id': user_id} 
        try:
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data=data_payload, proxies=req_proxies, timeout=30, verify=False)
            if resp.status_code != 200:
                status.update(label="❌ Upload Failed", state="error"); return set()
            task_id = resp.json().get("task_id")
        except: status.update(label="❌ Network Error", state="error"); return set()

        status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
        result_url = None
        for i in range(80):
            try:
                time.sleep(4)
                poll_resp = requests.get(status_url, headers=headers, params={'user_id': user_id}, proxies=req_proxies, timeout=30, verify=False)
                if poll_resp.status_code == 200:
                    p_data = poll_resp.json()
                    s = p_data.get("status")
                    d = p_data.get("success", 0) + p_data.get("failure", 0)
                    t = p_data.get("total", 1)
                    status.write(f"Verifying... {d}/{t} (Status: {s})")
                    if s in ["exported", "completed"]: result_url = p_data.get("result_url"); break
            except: pass
        
        if not result_url: status.update(label="❌ Timeout", state="error"); return set()
            
        try:
            status.write("Downloading report...")
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
                status.update(label=f"✅ Done! {len(valid_numbers_set)} active accounts found.", state="complete")
        except: status.update(label="❌ Parse Error", state="error")
    return valid_numbers_set

def get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name):
    if pd.isna(shop_name): shop_name = "Seller"
    if pd.isna(shop_link): shop_link = "Ozon Store"
    source_info = f"URL: {shop_link}"
    if web_content: source_info += f"\nScraped Page Content: {web_content}"
    
    prompt = f"""
    Role: Business Manager at "988 Group" (China). Sender: "{rep_name}". Target: "{shop_name}".
    Source: {source_info}
    Context: 988 Group = Sourcing + Logistics to Russia.
    Task: Polite Russian WhatsApp intro.
    Structure:
    1. "Здравствуйте, [Name]! Меня зовут {rep_name} (988 Group)."
    2. "Saw your store..."
    3. "We supply [Niche] items + shipping/customs to Russia."
    4. "Catalog?"
    Output: Russian text only.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.7, max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except:
        return f"Здравствуйте, {shop_name}! Меня зовут {rep_name} (988 Group). Мы занимаемся поставками из Китая."

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# === 主程序 ===

st.title("988 Group | Intelligent CRM")
st.markdown("""
    <div style='background-color: #e6f0ff; padding: 15px; border-radius: 10px; border-left: 5px solid #0052cc; margin-bottom: 20px;'>
        <strong>🚀 AI-Driven Workflow:</strong>  Upload Leads &rarr; Auto-Verify Numbers &rarr; Scrape Store Info &rarr; Generate Personalized Pitch
    </div>
""", unsafe_allow_html=True)

uploaded_file = st.file_uploader("📂 Upload Lead List (Excel/CSV)", type=['xlsx', 'csv'])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file, header=None)
        else: df = pd.read_excel(uploaded_file, header=None)
        df = df.astype(str)
        st.success(f"✅ Loaded {len(df)} rows.")
    except: st.stop()
        
    st.markdown("### 1️⃣ Setup Mapping")
    with st.container():
        c1, c2, c3 = st.columns(3)
        with c1: shop_col_idx = st.selectbox("🏷️ Store Name Column", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2: link_col_idx = st.selectbox("🔗 Link Column", range(len(df.columns)), index=0)
        with c3: rep_name = st.text_input("👤 Your Name (Signature)", value="", placeholder="e.g. Anna")

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 LAUNCH ENGINE", type="primary"):
        if not rep_name: st.error("⚠️ Please enter your name."); st.stop()
        my_proxy_str = get_proxy_config()
        if not openai_key: st.error("❌ OpenAI Key Missing"); st.stop()

        client = None
        if my_proxy_str:
            try:
                try: http_client = httpx.Client(proxy=my_proxy_str, verify=False)
                except: http_client = httpx.Client(proxies=my_proxy_str, verify=False)
                client = OpenAI(api_key=openai_key, http_client=http_client)
            except: st.error("Proxy Error"); st.stop()
        else: client = OpenAI(api_key=openai_key)

        # 1. Extract
        all_raw_phones = set()
        phone_to_rows = {}
        progress_bar = st.progress(0)
        for i, row in df.iterrows():
            extracted = extract_all_numbers(row)
            for p in extracted:
                all_raw_phones.add(p)
                if p not in phone_to_rows: phone_to_rows[p] = []
                phone_to_rows[p].append(i)
            progress_bar.progress((i+1)/len(df))
        if not all_raw_phones: st.error("No numbers found."); st.stop()

        # 2. Verify
        valid_phones_set = process_checknumber_task(list(all_raw_phones))
        
        # 3. Generate
        if valid_phones_set:
            st.markdown("---")
            st.markdown("### 📊 Live Dashboard")
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Raw Numbers", len(all_raw_phones))
            kpi2.metric("Verified WA", len(valid_phones_set))
            rate = len(valid_phones_set)/len(all_raw_phones)*100 if len(all_raw_phones)>0 else 0
            kpi3.metric("Success Rate", f"{rate:.1f}%")
            
            st.info(f"🧠 AI is generating messages for **{rep_name}**...")
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
                    web_content = extract_web_content(shop_link)
                    ai_msg = get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name)
                    links = [make_wa_link(p, ai_msg) for p in row_valid]
                    final_results.append({
                        "Shop Name": shop_name,
                        "Personalized Message": ai_msg,
                        "Phones List": row_valid,
                        "Links List": links
                    })
                ai_bar.progress((idx_step+1)/len(sorted_indices))
            
            st.markdown("### 🎯 Generated Leads")
            for i, item in enumerate(final_results):
                with st.expander(f"🏢 {item['Shop Name']}"):
                    st.markdown(f"**📝 AI Pitch:**")
                    st.info(item['Personalized Message'])
                    
                    # === 核心防崩替换：使用纯 HTML 渲染按钮 ===
                    cols = st.columns(len(item['Links List']) if len(item['Links List']) < 4 else 4)
                    for j, (phone_num, link) in enumerate(zip(item['Phones List'], item['Links List'])):
                        col_idx = j % 4
                        with cols[col_idx]:
                            # 直接写入 HTML，彻底避开 Streamlit 组件报错
                            st.markdown(
                                f'''<a href="{link}" target="_blank" class="custom-wa-btn">
                                    📲 Chat (+{phone_num})
                                   </a>''', 
                                unsafe_allow_html=True
                            )
            
            csv = pd.DataFrame(final_results).to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Download Report", csv, "988_leads.csv", "text/csv")
        else:
            st.warning("No valid WhatsApp numbers found.")
