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
    page_title="988 Group - Omni-Channel System", 
    layout="wide", 
    page_icon="🚛",
    initial_sidebar_state="expanded"
)

# 2. UI 美化
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #f4f6f9; border-right: 1px solid #e0e0e0;}
    h1 {color: #003366; font-weight: 700;}
    
    /* 按钮样式优化 */
    div.stButton > button {
        border-radius: 6px; font-weight: 600; width: 100%;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    
    /* 结果卡片 */
    div[data-testid="stExpander"] {
        background: white; border: 1px solid #edf2f7; border-radius: 8px; 
        margin-bottom: 8px;
    }
    a {text-decoration: none;}
</style>
""", unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=180)
    else:
        st.markdown("## 🚛 **988 Group**")
        
    st.markdown("### Omni-Channel Acquisition")
    st.caption("v24.0: Stable Release")
    
    try:
        default_cn_user = st.secrets["CN_USER_ID"]
        default_cn_key = st.secrets["CN_API_KEY"]
        default_openai = st.secrets["OPENAI_KEY"]
        st.caption("✅ Cloud Secrets Loaded")
    except FileNotFoundError:
        default_cn_user = ""
        default_cn_key = ""
        default_openai = ""
        st.caption("⚠️ Local Mode")

    with st.expander("🔧 System Config"):
        use_proxy = st.checkbox("Enable Proxy", value=False)
        proxy_port = st.text_input("Proxy URL", value="http://127.0.0.1:10809")
        check_user_id = st.text_input("CN User ID", value=default_cn_user)
        check_key = st.text_input("CN Key", value=default_cn_key, type="password")
        openai_key = st.text_input("OpenAI Key", value=default_openai, type="password")

# === 核心功能 ===

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
    if not api_key or not user_id: st.error("配置缺失"); return set()

    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    my_proxy_str = get_proxy_config()
    req_proxies = {"http": my_proxy_str, "https": my_proxy_str} if my_proxy_str else None
    
    status_box = st.status("📡 Analyzing numbers...", expanded=True)
    status_box.write(f"Checking {len(phone_list)} numbers via API...")
    
    file_content = "\n".join(phone_list)
    files = {'file': ('input.txt', file_content, 'text/plain')}
    data_payload = {'user_id': user_id} 
    try:
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data=data_payload, proxies=req_proxies, timeout=30, verify=False)
        if resp.status_code != 200:
            status_box.update(label="❌ API Error (Skipping Check)", state="error")
            return set(phone_list) 
        task_id = resp.json().get("task_id")
    except: return set(phone_list)

    status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
    result_url = None
    for i in range(80):
        try:
            time.sleep(3)
            poll_resp = requests.get(status_url, headers=headers, params={'user_id': user_id}, proxies=req_proxies, timeout=30, verify=False)
            if poll_resp.status_code == 200:
                p_data = poll_resp.json()
                status = p_data.get("status")
                if status in ["exported", "completed"]: result_url = p_data.get("result_url"); break
        except: pass
            
    if not result_url: return set(phone_list)
        
    try:
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
            status_box.update(label=f"✅ Found {len(valid_numbers_set)} active WA accounts", state="complete")
    except: pass
    return valid_numbers_set

def get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name):
    if pd.isna(shop_name): shop_name = "Seller"
    if pd.isna(shop_link): shop_link = "Ozon Store"
    
    source_info = f"URL: {shop_link}"
    if web_content: source_info += f"\nScraped Page Content: {web_content}"
    
    prompt = f"""
    Role: Business Development Manager at "988 Group" (China).
    Sender: "{rep_name}". Target: Ozon Seller "{shop_name}".
    Source Info: {source_info}
    
    Context: 988 Group = Supply Chain Partner (Sourcing + Logistics to Russia).
    
    Task: Write a polite Russian message for WhatsApp/Telegram.
    
    Structure:
    1. Greeting: "Здравствуйте, [Shop Name]! Меня зовут {rep_name} (988 Group)."
    2. Hook: "Saw your [Niche] store on Ozon..."
    3. Value: "We help source these items + handle shipping/customs to Moscow."
    4. CTA: "Catalog/Quote?"
    5. Sign-off: "С уважением, {rep_name}."
    
    Constraint: Native Russian, <50 words.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except:
        return f"Здравствуйте, {shop_name}! Меня зовут {rep_name} (988 Group). Мы занимаемся поставками из Китая."

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

def make_tg_link(phone):
    return f"https://t.me/+{phone}"

# === 主程序界面 ===

st.markdown("### 🚀 988 Group Omni-Channel System")
st.markdown("WhatsApp & Telegram Automated Outreach")
st.markdown("---")

uploaded_file = st.file_uploader("📂 Upload Lead List (Excel/CSV)", type=['xlsx', 'csv'])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file, header=None)
        else: df = pd.read_excel(uploaded_file, header=None)
        df = df.astype(str)
    except: st.stop()
        
    with st.container():
        st.info("👇 Configuration")
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            shop_col_idx = st.selectbox("🏷️ Store Name Column", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2:
            link_col_idx = st.selectbox("🔗 Link Column", range(len(df.columns)), index=0)
        with c3:
            rep_name = st.text_input("👤 Your Name", value="", placeholder="e.g. Anna")

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 START DUAL-CHANNEL ENGINE", type="primary"):
        if not rep_name: st.error("⚠️ Enter your name!"); st.stop()
        
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

        # 1. 提取
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

        # 2. 验号
        wa_valid_set = process_checknumber_task(list(all_raw_phones))
        
        # 3. AI 生成 & 结果呈现
        st.markdown("---")
        st.success(f"✅ Ready! Validated {len(wa_valid_set)} WA numbers. Generating dual links...")
        
        final_results = []
        sorted_numbers = sorted(list(all_raw_phones))
        processed_rows = set()
        
        ai_bar = st.progress(0)
        
        for idx_step, p in enumerate(sorted_numbers):
            row_indices = phone_to_rows[p]
            for r_idx in row_indices:
                if r_idx in processed_rows: continue
                processed_rows.add(r_idx)
                
                row = df.iloc[r_idx]
                shop_name = row[shop_col_idx]
                shop_link = row[link_col_idx]
                
                web_content = extract_web_content(shop_link)
                ai_msg = get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name)
                
                wa_link = make_wa_link(p, ai_msg) if p in wa_valid_set else None
                tg_link = make_tg_link(p)
                
                final_results.append({
                    "Shop Name": shop_name,
                    "Phone": p,
                    "AI Message": ai_msg,
                    "WA_Link": wa_link,
                    "TG_Link": tg_link
                })
            ai_bar.progress((idx_step+1)/len(sorted_numbers))
            
        st.subheader("🎯 Dual-Channel Leads")
        
        # === 核心修复点：为每个按钮添加唯一的 key ===
        for i, item in enumerate(final_results):
            with st.expander(f"🏢 {item['Shop Name']} (+{item['Phone']})"):
                st.write(f"**Draft:** {item['AI Message']}")
                
                c_wa, c_tg = st.columns(2)
                
                with c_wa:
                    # 使用 enumerate 的索引 i 来保证 key 唯一
                    if item['WA_Link']:
                        st.link_button(f"🟢 WhatsApp", item['WA_Link'], use_container_width=True, key=f"wa_{i}")
                    else:
                        st.button(f"⚪ No WhatsApp", disabled=True, use_container_width=True, key=f"nowa_{i}")
                
                with c_tg:
                    st.link_button(f"🔵 Telegram", item['TG_Link'], use_container_width=True, key=f"tg_{i}")
                    st.caption("Copy text above first")
