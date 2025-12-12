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
    page_title="988 Group - Intelligent System", 
    layout="wide", 
    page_icon="🚛",
    initial_sidebar_state="expanded"
)

# 2. UI 美化 (保持 v21 的高级感)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #f4f6f9; border-right: 1px solid #e0e0e0;}
    h1 {color: #003366; font-weight: 700; letter-spacing: -1px;}
    div.stButton > button {
        background: linear-gradient(135deg, #004aad 0%, #003366 100%);
        color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 8px; 
        font-weight: 600; transition: all 0.3s ease; box-shadow: 0 4px 6px rgba(0, 74, 173, 0.2); width: 100%;
    }
    div.stButton > button:hover {transform: translateY(-2px); box-shadow: 0 6px 12px rgba(0, 74, 173, 0.3);}
    div[data-testid="stExpander"] {
        background: white; border: 1px solid #edf2f7; border-radius: 12px; 
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05); margin-bottom: 12px;
    }
    div[data-testid="stStatusWidget"] {border-radius: 10px; border: 1px solid #e2e8f0;}
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
    """爬虫模块：获取标题和描述"""
    if not url or not isinstance(url, str) or "http" not in url: return None
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7"
    }
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
    """提取 7/8/9 开头的号码"""
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    # 模式A: +7 或 8 开头的11位
    matches_standard = re.findall(r'(\+?(?:7|8)(?:[\s\-\(\)]*\d){10})', full_text)
    # 模式B: 9 开头的10位
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
    
    status_box = st.status("📡 Establishing Connection...", expanded=True)
    status_box.write(f"Uploading {len(phone_list)} numbers...")
    
    file_content = "\n".join(phone_list)
    files = {'file': ('input.txt', file_content, 'text/plain')}
    data_payload = {'user_id': user_id} 
    try:
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data=data_payload, proxies=req_proxies, timeout=30, verify=False)
        if resp.status_code != 200:
            status_box.update(label="❌ Upload Failed", state="error"); return set()
        task_id = resp.json().get("task_id")
    except: status_box.update(label="❌ Network Error", state="error"); return set()

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

def get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name):
    """
    v22.0: 增加 rep_name (业务员名字)
    """
    if pd.isna(shop_name): shop_name = "Seller"
    if pd.isna(shop_link): shop_link = "Ozon Store"
    
    source_info = f"URL: {shop_link}"
    if web_content: source_info += f"\nScraped Page Content: {web_content}"
    
    # === 988 Group 礼貌开场 Prompt ===
    prompt = f"""
    Role: Senior Business Development Manager at "988 Group" (China).
    Sender Name: "{rep_name}" 
    Target: Ozon Seller "{shop_name}".
    Source Info: {source_info}
    
    Context:
    988 Group is a Supply Chain Partner (Sourcing + Logistics to Russia).
    
    Task:
    Write a polite, high-conversion Russian WhatsApp message.
    
    Structure:
    1. Greeting & Intro: "Здравствуйте, [Shop Name]! Меня зовут {rep_name} (988 Group)." (Use "Menya zovut" - My name is).
    2. Hook: Mention you saw their store and specific niche products (infer from Source Info).
    3. Value: "We help supply these specific items from China factories + handle customs/shipping."
    4. CTA: "Can I send you a catalog/quote?"
    5. Sign-off: "С уважением, {rep_name}."
    
    Constraints:
    - Tone: Polite, Professional, Warm.
    - Language: Native Russian.
    - Length: Approx 40-50 words.
    
    Output: Only the Russian message.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, 
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except:
        return f"Здравствуйте, {shop_name}! Меня зовут {rep_name} (988 Group). Мы занимаемся поставками из Китая. Можно прислать предложение?"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# === 主程序界面 ===

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
        
    with st.container():
        st.info("👇 Step 1: Map Columns & Identity")
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            shop_col_idx = st.selectbox("🏷️ Store Name Column", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2:
            link_col_idx = st.selectbox("🔗 Link Column", range(len(df.columns)), index=0)
        with c3:
            # === 新增：业务员名字输入框 ===
            rep_name = st.text_input("👤 Your Name (Signature)", value="", placeholder="e.g. Anna")

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 START AI ENGINE", type="primary"):
        
        # 强制要求输入名字
        if not rep_name:
            st.error("⚠️ Please enter your name in the 'Your Name' box above.")
            st.stop()
            
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
        valid_phones_set = process_checknumber_task(list(all_raw_phones))
        
        # 3. AI 生成
        if valid_phones_set:
            st.markdown("---")
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("Raw Numbers", len(all_raw_phones))
            kpi2.metric("Verified WA", len(valid_phones_set))
            rate = len(valid_phones_set)/len(all_raw_phones)*100 if len(all_raw_phones)>0 else 0
            kpi3.metric("Conversion Rate", f"{rate:.1f}%")
            
            st.success(f"🧠 AI is writing personalized messages for {rep_name}...")
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
                    
                    # 爬取 + AI生成 (带入 rep_name)
                    web_content = extract_web_content(shop_link)
                    ai_msg = get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name)
                    
                    links = [make_wa_link(p, ai_msg) for p in row_valid]
                    final_results.append({
                        "Shop Name": shop_name,
                        "Link": shop_link,
                        "Phone": ", ".join(row_valid),
                        "Personalized Message": ai_msg,
                        "Direct Link": " | ".join(links)
                    })
                ai_bar.progress((idx_step+1)/len(sorted_indices))
            
            res_df = pd.DataFrame(final_results)
            
            st.subheader("🎯 Qualified Leads")
            for _, item in res_df.head(50).iterrows():
                with st.expander(f"🏢 {item['Shop Name']}"):
                    st.write(f"**Generated:** {item['Personalized Message']}")
                    for l in item['Direct Link'].split(" | "): 
                        st.link_button("📲 Send via WhatsApp", l)
            
            csv = res_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 Download Final Report", csv, "988_premium_leads.csv", "text/csv")
        else:
            st.warning("No valid WhatsApp numbers found.")
