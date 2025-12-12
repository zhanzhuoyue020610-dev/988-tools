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
import cloudscraper
from bs4 import BeautifulSoup 

try:
    from supabase import create_client, Client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

warnings.filterwarnings("ignore")

CONFIG = {"PROXY_URL": None, "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"}

@st.cache_resource
def init_supabase():
    if not SUPABASE_INSTALLED: return None
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except: return None

supabase = init_supabase()

# --- DB Functions ---
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
        supabase.table('clicks').insert({"username": username, "shop_name": shop, "phone": phone, "target": target}).execute()
    except: pass

def save_leads_to_db(username, leads_data):
    if not supabase or not leads_data: return
    try:
        rows = [{"username": username, "shop_name": i['Shop'], "shop_link": i['Link'], "phone": i['Phone'], "ai_message": i['Msg'], "is_valid": (i['Status']=='valid')} for i in leads_data]
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

# --- UI Config ---
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f8f9fc;}
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #ffffff; border-right: 1px solid #e5e7eb;}
    div.stButton > button {
        background: linear-gradient(135deg, #0052cc 0%, #003366 100%);
        color: white; border: none; padding: 0.75rem 1.5rem; border-radius: 8px; 
        font-weight: 600; width: 100%; box-shadow: 0 4px 12px rgba(0, 82, 204, 0.2);
    }
    .btn-action {
        display: block; padding: 8px 12px; color: white !important; text-decoration: none !important;
        border-radius: 6px; font-weight: 500; text-align: center; font-size: 14px; margin-bottom: 4px;
    }
    .wa-green { background-color: #10b981; } 
    .tg-blue { background-color: #0ea5e9; } 
    div[data-testid="stExpander"] {background: white; border: 1px solid #e2e8f0; border-radius: 10px; margin-bottom: 10px;}
</style>
""", unsafe_allow_html=True)

# --- Core Logic ---
def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    matches = re.findall(r'(?:^|\D)([789][\d\s\-\(\)]{9,16})(?:\D|$)', full_text)
    candidates = []
    for raw in matches:
        d = re.sub(r'\D', '', raw)
        clean = None
        if len(d) == 11:
            if d.startswith('7'): clean = d
            elif d.startswith('8'): clean = '7' + d[1:]
        elif len(d) == 10 and d.startswith('9'): clean = '7' + d
        if clean: candidates.append(clean)
    digs = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', full_text)
    for raw in digs:
        if len(raw)==11 and raw.startswith('7'): candidates.append(raw)
        elif len(raw)==11 and raw.startswith('8'): candidates.append('7'+raw[1:])
        elif len(raw)==10 and raw.startswith('9'): candidates.append('7'+raw)
    return list(set(candidates))

def get_proxy_config(): return None

def get_niche_from_url(url):
    if not url or "http" not in str(url): return ""
    try:
        stopwords = ['ozon', 'ru', 'com', 'seller', 'products', 'category', 'catalog', 'detail', 'html', 'https', 'www', 'item']
        path = urllib.parse.urlparse(url).path
        clean_path = re.sub(r'[\/\-\_\.]', ' ', path)
        words = re.findall(r'[a-zA-Z]{3,}', clean_path)
        meaningful = [w for w in words if w.lower() not in stopwords]
        return ", ".join(meaningful[:6])
    except: return ""

def extract_web_content(url):
    content = ""
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            if title: content += f"Page Title: {title}. "
    except: pass
    url_niche = get_niche_from_url(url)
    if url_niche: content += f"URL Keywords: {url_niche}. "
    return content if content else "Unknown"

def process_checknumber_task(phone_list, api_key, user_id):
    if not phone_list: return {}
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    with st.status("📡 Verification...", expanded=True) as status:
        status.write(f"Checking {len(phone_list)} numbers...")
        try:
            files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, timeout=30, verify=False)
            if resp.status_code != 200: return status_map
            task_id = resp.json().get("task_id")
        except: return status_map
        for i in range(60):
            try:
                time.sleep(3)
                poll = requests.get(f"{CONFIG['CN_BASE_URL']}/{task_id}", headers=headers, params={'user_id': user_id}, timeout=30, verify=False)
                if poll.status_code == 200 and poll.json().get("status") in ["exported", "completed"]:
                    result_url = poll.json().get("result_url"); break
            except: pass
        if not result_url: return status_map
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
                    if "yes" in ws or "valid" in ws: status_map[nm] = 'valid'; cnt += 1
                    else: status_map[nm] = 'invalid'
                status.update(label=f"✅ Verified: {cnt} valid.", state="complete")
        except: pass
    return status_map

# === 🚨 v43.0 诊断版 AI 引擎 ===
def get_ai_message_debug(client, shop_name, shop_link, context_info, rep_name, model_choice="gpt-4o-mini"):
    if shop_name.lower() in ['seller', 'store', 'shop', 'ozon', 'nan', '']: shop_name = ""
    
    # 强制 System Prompt
    system_prompt = f"""
    You are {rep_name}, Sales Manager at 988 Group (China).
    GOAL: Write a customized Russian WhatsApp message based on the user's niche.
    NO GENERIC "We are a factory" intros.
    NO "Меня зовут Super Admin". Use "{rep_name}".
    """
    
    user_prompt = f"""
    Target Shop: "{shop_name}"
    Scraped Data: "{context_info}"
    
    INSTRUCTIONS:
    1. If Scraped Data contains keywords (e.g. 'fishing', 'dress', 'auto'), mention them explicitly!
       Example: "Saw your [Fishing Rods]..."
    2. If Data is empty, say: "I analyzed your Ozon store and saw great potential."
    3. Pitch: 988 Group sources goods + handles logistics to Russia.
    4. Ask: "Send catalog?"
    
    Output: Russian text only. Under 50 words.
    """
    
    # === 关键修改：取消 Try-Except，直接暴露错误 ===
    # 这样我们才能知道为什么 AI 没跑通
    try:
        response = client.chat.completions.create(
            model=model_choice, # 使用变量控制模型
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.7, 
            max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        # 如果报错，直接返回错误信息展示在卡片里
        return f"⚠️ AI ERROR: {str(e)}"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# ==========================================
# Login & Session
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'results' not in st.session_state: st.session_state['results'] = None
if 'unlocked_leads' not in st.session_state: st.session_state['unlocked_leads'] = set()

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<div style='height:10vh;'></div>", unsafe_allow_html=True)
        with st.container():
            if os.path.exists("logo.png"): st.image("logo.png", width=200)
            else: st.markdown("## 🚛 988 Group CRM")
            if not supabase: st.error("❌ Database Error."); st.stop()
            with st.form("login"):
                u = st.text_input("Username"); p = st.text_input("Password", type="password")
                if st.form_submit_button("Sign In"):
                    user = login_user(u, p)
                    if user: st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']}); st.rerun()
                    else: st.error("Invalid Credentials")
    st.stop()

try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=160)
    st.write(f"👤 **{st.session_state['real_name']}**")
    menu = st.radio("Menu", ["🚀 WorkBench", "📂 History", "📊 Admin"] if st.session_state['role']=='admin' else ["🚀 WorkBench", "📂 History"])
    
    # === 调试面板 ===
    with st.expander("🛠️ Debug AI"):
        ai_model_select = st.selectbox("AI Model", ["gpt-4o-mini", "gpt-3.5-turbo", "gpt-4o"], index=0, help="如果 gpt-4o 报错，请尝试 mini")
        st.caption("Default: gpt-4o-mini (Faster/Cheaper/Safer)")
        
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
                with c2: l_col = st.selectbox("Store Link", range(len(df.columns)), 0)
                
                if st.button("Start Processing"):
                    client = OpenAI(api_key=OPENAI_KEY)
                    
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
                    
                    status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
                    valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
                    
                    if not valid_phones:
                        st.warning("No valid WhatsApp found.")
                        st.stop()
                        
                    final_data = []
                    processed_rows = set()
                    st.info(f"🧠 AI ({ai_model_select}) is analyzing {len(valid_phones)} leads...")
                    ai_bar = st.progress(0)
                    
                    # 调试信息容器
                    debug_container = st.empty()
                    
                    for idx, p in enumerate(valid_phones):
                        indices = row_map[p]
                        for rid in indices:
                            if rid in processed_rows: continue
                            processed_rows.add(rid)
                            row = df.iloc[rid]
                            s_name = row[s_col]; s_link = row[l_col]
                            
                            # 获取上下文
                            context = extract_web_content(s_link)
                            
                            # 实时显示正在分析的内容（Debug）
                            debug_container.text(f"Analyzing: {s_link}\nExtracted: {context[:50]}...")
                            
                            # 调用 AI (不隐藏错误)
                            msg = get_ai_message_debug(client, s_name, s_link, context, st.session_state['real_name'], ai_model_select)
                            
                            wa_link = make_wa_link(p, msg); tg_link = f"https://t.me/+{p}"
                            final_data.append({"Shop": s_name, "Link": s_link, "Phone": p, "Msg": msg, "WA": wa_link, "TG": tg_link, "Status": "valid"})
                        ai_bar.progress((idx+1)/len(valid_phones))
                    
                    st.session_state['results'] = final_data
                    save_leads_to_db(st.session_state['username'], final_data)
                    st.success(f"✅ Analysis Complete! {len(final_data)} Leads.")
                    st.rerun()
            except Exception as e: st.error(f"Error: {e}")

    if st.session_state['results']:
        c_act1, c_act2 = st.columns([3, 1])
        with c_act1: st.markdown(f"### 🎯 Leads ({len(st.session_state['results'])})")
        with c_act2: 
            if st.button("🗑️ Clear"): st.session_state['results'] = None; st.rerun()

        for i, item in enumerate(st.session_state['results']):
            with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                # 如果 AI 报错，显示红色
                if "AI ERROR" in item['Msg']:
                    st.error(item['Msg'])
                    st.caption("Tip: Check your OpenAI Key or Model Name in Sidebar.")
                else:
                    st.info(item['Msg'])
                    st.caption(f"Source: {item['Link']}") 
                
                lead_id = f"{item['Phone']}_{i}"
                if lead_id in st.session_state['unlocked_leads']:
                    c1, c2 = st.columns(2)
                    with c1: st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-action wa-green">🟢 Open WhatsApp</a>', unsafe_allow_html=True)
                    with c2: st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-action tg-blue">🔵 Open Telegram</a>', unsafe_allow_html=True)
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
        k1.metric("Total Leads", len(df_leads))
        k2.metric("Total Unlocks", len(df_clicks))
        st.bar_chart(df_clicks['username'].value_counts())
        with st.expander("Logs"): st.dataframe(df_clicks)
    else: st.info("No data.")
    st.divider()
    with st.form("new_user"):
        u = st.text_input("User"); p = st.text_input("Pass", type="password"); n = st.text_input("Name")
        if st.form_submit_button("Create"):
            if create_user(u, p, n): st.success("Created"); st.error("Failed")
