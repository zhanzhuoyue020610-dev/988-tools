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
import hashlib
import datetime
from bs4 import BeautifulSoup 
import cloudscraper # 必须安装

try:
    from supabase import create_client, Client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

warnings.filterwarnings("ignore")

# ==========================================
# 🔧 988 Group 系统配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# ==========================================
# ☁️ Supabase
# ==========================================
@st.cache_resource
def init_supabase():
    if not SUPABASE_INSTALLED: return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: return None

supabase = init_supabase()

# 数据库函数
def login_user(u, p):
    if not supabase: return None
    pwd_hash = hashlib.sha256(p.encode()).hexdigest()
    try:
        res = supabase.table('users').select("*").eq('username', u).eq('password', pwd_hash).execute()
        return res.data[0] if res.data else None
    except: return None

def create_user(u, p, n):
    if not supabase: return False
    try:
        pwd = hashlib.sha256(p.encode()).hexdigest()
        supabase.table('users').insert({"username": u, "password": pwd, "role": "sales", "real_name": n}).execute()
        return True
    except: return False

def log_click_event(username, shop, phone, target):
    if not supabase: return
    try:
        supabase.table('clicks').insert({
            "username": username, "shop_name": shop, "phone": phone, "target": target
        }).execute()
    except: pass

def save_leads_to_db(username, leads_data):
    if not supabase or not leads_data: return
    try:
        rows = []
        for item in leads_data:
            rows.append({
                "username": username, "shop_name": item['Shop'], "shop_link": item['Link'],
                "phone": item['Phone'], "ai_message": item['Msg'], "is_valid": (item['Status']=='valid')
            })
        supabase.table('leads').insert(rows).execute()
    except: pass

def get_admin_stats():
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    try:
        c = pd.DataFrame(supabase.table('clicks').select("*").execute().data)
        l = pd.DataFrame(supabase.table('leads').select("username, is_valid, created_at").execute().data)
        return c, l
    except: return pd.DataFrame(), pd.DataFrame()

def get_user_leads_history(username):
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table('leads').select("*").eq('username', username).order('created_at', desc=True).limit(200).execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

# ==========================================
# 🎨 UI Style (蓝宝石极简)
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f8f9fc;}
    
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #ffffff; border-right: 1px solid #e5e7eb;}
    
    /* 主按钮 */
    div.stButton > button {
        background: linear-gradient(135deg, #0052cc 0%, #003366 100%);
        color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 8px; 
        font-weight: 600; font-size: 15px; box-shadow: 0 4px 12px rgba(0, 82, 204, 0.2); width: 100%;
    }
    div.stButton > button:hover {transform: translateY(-2px); box-shadow: 0 8px 16px rgba(0, 82, 204, 0.3);}
    
    /* HTML 按钮 (防崩) */
    .btn-action {
        display: block; padding: 8px 12px; color: white !important; text-decoration: none !important;
        border-radius: 6px; font-weight: 500; text-align: center; font-size: 14px; margin-bottom: 4px;
        transition: opacity 0.2s;
    }
    .btn-action:hover { opacity: 0.9; }
    .wa-green { background-color: #10b981; } 
    .tg-blue { background-color: #0ea5e9; } 
    
    /* 结果卡片 */
    div[data-testid="stExpander"] {
        background: white; border: 1px solid #e2e8f0; border-radius: 10px; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# === 核心逻辑 ===

def extract_all_numbers(row_series):
    """
    你指定的最佳提取逻辑
    """
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

def get_proxy_config(): return None

# === 绝杀文案引擎 (Killer Copy Engine) ===

def get_niche_from_url(url):
    """暴力拆解 URL 获取类目"""
    if not url or "http" not in str(url): return ""
    try:
        stopwords = ['ozon', 'ru', 'com', 'seller', 'products', 'category', 'catalog', 'detail', 'html', 'https', 'www']
        path = urllib.parse.urlparse(url).path
        clean_path = re.sub(r'[\/\-\_\.]', ' ', path)
        words = re.findall(r'[a-zA-Z]{3,}', clean_path)
        meaningful = [w for w in words if w.lower() not in stopwords]
        return ", ".join(meaningful[:5])
    except: return ""

def extract_web_content(url):
    """CloudScraper + URL Fallback"""
    content = ""
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=4)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            if title: content += f"Page Title: {title}. "
    except: pass
    
    url_niche = get_niche_from_url(url)
    if url_niche: content += f"URL Keywords: {url_niche}. "
    
    return content if content else "General Store"

def process_checknumber_task(phone_list, api_key, user_id):
    if not phone_list: return {}
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    
    with st.status("📡 Cloud Verification...", expanded=True) as status:
        status.write(f"Checking {len(phone_list)} numbers...")
        try:
            files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, timeout=30, verify=False)
            if resp.status_code != 200: 
                status.update(label=f"⚠️ API Error (Skip)", state="error"); return status_map
            task_id = resp.json().get("task_id")
        except: return status_map

        status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
        result_url = None
        for i in range(60):
            try:
                time.sleep(3)
                poll = requests.get(status_url, headers=headers, params={'user_id': user_id}, timeout=30, verify=False)
                if poll.status_code == 200 and poll.json().get("status") in ["exported", "completed"]:
                    result_url = poll.json().get("result_url"); break
            except: pass
        
        if not result_url: status.update(label="⚠️ Timeout", state="error"); return status_map
            
        try:
            f = requests.get(result_url, verify=False)
            if f.status_code == 200:
                try: df = pd.read_excel(io.BytesIO(f.content))
                except: df = pd.read_csv(io.BytesIO(f.content))
                df.columns = [c.lower() for c in df.columns]
                cnt = 0
                for _, r in df.iterrows():
                    ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                    nm = re.sub(r'\D', '', str(r.get('number') or r.get('phone') or ''))
                    if "yes" in ws or "valid" in ws: 
                        status_map[nm] = 'valid'; cnt += 1
                    else: status_map[nm] = 'invalid'
                status.update(label=f"✅ Verified: {cnt} valid.", state="complete")
        except: pass
    return status_map

def get_ai_message_killer(client, shop_name, shop_link, context_info, rep_name):
    # 如果店名无效，置空让AI自己发挥
    if shop_name.lower() in ['seller', 'store', 'shop', 'ozon', 'nan', '']: shop_name = ""
        
    prompt = f"""
    Role: Expert Sales Manager '{rep_name}' at 988 Group (China Supply Chain).
    Target Store Name: "{shop_name}"
    Data Source: {context_info}
    
    MISSION: Write a HIGH-CONVERSION Russian WhatsApp message.
    
    STRATEGY:
    1. **NICHE DETECTION**: Analyze 'Data Source'. 
       - 'fishing' -> "Рыболовные товары"
       - 'auto' -> "Автотовары"
       - 'baby' -> "Детские товары"
       - **UNKNOWN**: Assume 'Top Seller'.
       
    2. **HOOK**: 
       - "Здравствуйте! Увидела ваш магазин на Ozon, отличный выбор [NICHE]!"
       - (If unknown niche): "Здравствуйте! Изучила ваш ассортимент на Ozon..."
       
    3. **OFFER**:
       - "We (988 Group) help source [NICHE] directly from China factories 15-20% cheaper."
       - "We handle Logistics/Customs to Moscow."
       
    4. **CTA**:
       - "Can I send a price calculation?"
    
    Constraint: Native Russian. <50 words.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.8, max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except:
        return f"Здравствуйте! Меня зовут {rep_name} (988 Group). Помогаем селлерам Ozon закупать товары в Китае на 20% дешевле и доставляем в РФ. Сделать расчет?"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# ==========================================
# 🔐 Login & State
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'results' not in st.session_state: st.session_state['results'] = None
if 'unlocked_leads' not in st.session_state: st.session_state['unlocked_leads'] = set()

# Login Page
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<div style='height:10vh;'></div>", unsafe_allow_html=True)
        with st.container():
            if os.path.exists("logo.png"): st.image("logo.png", width=200)
            else: st.markdown("## 🚛 988 Group CRM")
            
            if not supabase:
                st.error("❌ Database Error. Check Secrets.")
                st.stop()
                
            with st.form("login"):
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                if st.form_submit_button("Sign In"):
                    user = login_user(u, p)
                    if user:
                        st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                        st.rerun()
                    else: st.error("Invalid Credentials")
    st.stop()

# --- Internal ---
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=160)
    st.write(f"👤 **{st.session_state['real_name']}**")
    menu = st.radio("Menu", ["🚀 WorkBench", "📂 History", "📊 Admin"] if st.session_state['role']=='admin' else ["🚀 WorkBench", "📂 History"])
    st.divider()
    if st.button("Logout"): st.session_state.clear(); st.rerun()

# 1. WorkBench
if "WorkBench" in str(menu):
    st.title("🚀 Acquisition Workbench")
    
    with st.expander("📂 Import Data", expanded=st.session_state['results'] is None):
        up_file = st.file_uploader("Select Excel/CSV File", type=['xlsx', 'csv'])
        if up_file:
            try:
                if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
                else: df = pd.read_excel(up_file, header=None)
                df = df.astype(str)
                c1, c2 = st.columns(2)
                with c1: s_col = st.selectbox("Store Name", range(len(df.columns)), 1)
                with c2: l_col = st.selectbox("Store Link (Crucial for AI)", range(len(df.columns)), 0)
                
                if st.button("Start Processing"):
                    client = OpenAI(api_key=OPENAI_KEY)
                    
                    # Extract
                    raw_phones = set()
                    row_map = {}
                    bar = st.progress(0)
                    for i, r in df.iterrows():
                        ext = extract_all_numbers(r)
                        for p in ext:
                            raw_phones.add(p)
                            if p not in row_map: row_map[p] = []
                            row_map[p].append(i)
                        bar.progress((i+1)/len(df))
                    
                    if not raw_phones: st.error("No Numbers!"); st.stop()
                    
                    # Verify
                    status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
                    
                    # Filter Valid
                    valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
                    
                    if not valid_phones:
                        st.warning(f"Extracted {len(raw_phones)} numbers, but NONE were valid WhatsApp.")
                        save_leads_to_db(st.session_state['username'], [])
                        st.stop()
                        
                    final_data = []
                    processed_rows = set()
                    st.info(f"🧠 AI is analyzing {len(valid_phones)} shops (Deep Inference)...")
                    ai_bar = st.progress(0)
                    
                    for idx, p in enumerate(valid_phones):
                        indices = row_map[p]
                        for rid in indices:
                            if rid in processed_rows: continue
                            processed_rows.add(rid)
                            row = df.iloc[rid]
                            s_name = row[s_col]
                            s_link = row[l_col]
                            
                            # === 绝杀引擎 ===
                            context = extract_web_content(s_link) 
                            msg = get_ai_message_killer(client, s_name, s_link, context, st.session_state['real_name'])
                            
                            wa_link = make_wa_link(p, msg); tg_link = f"https://t.me/+{p}"
                            final_data.append({"Shop": s_name, "Link": s_link, "Phone": p, "Msg": msg, "WA": wa_link, "TG": tg_link, "Status": "valid"})
                        ai_bar.progress((idx+1)/len(valid_phones))
                    
                    st.session_state['results'] = final_data
                    save_leads_to_db(st.session_state['username'], final_data)
                    st.success(f"✅ Analysis Complete! {len(final_data)} Leads.")
                    st.rerun()
            except Exception as e: st.error(f"Error: {e}")

    # Results
    if st.session_state['results']:
        c_act1, c_act2 = st.columns([3, 1])
        with c_act1: st.markdown(f"### 🎯 Leads ({len(st.session_state['results'])})")
        with c_act2: 
            if st.button("🗑️ Clear"): st.session_state['results'] = None; st.session_state['unlocked_leads'] = set(); st.rerun()

        for i, item in enumerate(st.session_state['results']):
            with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                st.info(item['Msg']) 
                st.caption(f"Source: {item['Link']}") 
                
                lead_id = f"{item['Phone']}_{i}"
                if lead_id in st.session_state['unlocked_leads']:
                    c1, c2 = st.columns(2)
                    with c1: 
                        # HTML Button (Crash Proof)
                        st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-action wa-green">🟢 WhatsApp</a>', unsafe_allow_html=True)
                    with c2: 
                        st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-action tg-blue">🔵 Telegram</a>', unsafe_allow_html=True)
                else:
                    if st.button(f"👆 Unlock Info", key=f"ul_{i}"):
                        log_click_event(st.session_state['username'], item['Shop'], item['Phone'], 'unlock')
                        st.session_state['unlocked_leads'].add(lead_id)
                        st.rerun()

# 2. History
elif "History" in str(menu):
    st.title("📂 My History")
    df_leads = get_user_leads_history(st.session_state['username'])
    if not df_leads.empty:
        st.dataframe(df_leads[['created_at', 'shop_name', 'phone', 'ai_message']], use_container_width=True)
        csv = df_leads.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 Export CSV", csv, "my_leads.csv", "text/csv")
    else: st.info("No history.")

# 3. Admin
elif "Admin" in str(menu) and st.session_state['role'] == 'admin':
    st.title("📊 Admin Panel")
    df_clicks, df_leads = get_admin_stats()
    if not df_clicks.empty:
        k1, k2 = st.columns(2)
        k1.metric("Total Valid Leads", len(df_leads))
        k2.metric("Total Unlocks", len(df_clicks))
        st.subheader("Leaderboard")
        lb = df_clicks['username'].value_counts().reset_index()
        lb.columns=['User', 'Unlocks']
        st.bar_chart(lb.set_index('User'))
        with st.expander("Logs"): st.dataframe(df_clicks)
    else: st.info("No data.")
    st.divider()
    with st.form("new_user"):
        u = st.text_input("User"); p = st.text_input("Pass", type="password"); n = st.text_input("Name")
        if st.form_submit_button("Create"):
            if create_user(u, p, n): st.success("Created"); st.error("Failed")
