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

# 尝试导入 supabase
try:
    from supabase import create_client, Client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

# 忽略 SSL 警告
warnings.filterwarnings("ignore")

# ==========================================
# 🔧 988 Group 系统配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# ==========================================
# ☁️ Supabase 连接与初始化
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

# ==========================================
# 💾 数据库操作
# ==========================================
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

def save_task_history(username, fname, total, valid, df_result):
    """保存历史记录到云端"""
    if not supabase: return
    try:
        # 将结果转为 JSON 存入（简化版），或者只存统计数据
        # 这里为了演示，我们只存统计数据，避免超出免费额度
        supabase.table('history').insert({
            "username": username,
            "filename": fname,
            "total_leads": total,
            "valid_wa": valid
        }).execute()
    except Exception as e:
        print(f"Save History Error: {e}")

def get_admin_stats():
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    try:
        clicks = pd.DataFrame(supabase.table('clicks').select("*").execute().data)
        tasks = pd.DataFrame(supabase.table('history').select("*").execute().data)
        return clicks, tasks
    except: return pd.DataFrame(), pd.DataFrame()

# ==========================================
# 🎨 UI 配置
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f0f2f6;}
    
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #ffffff; border-right: 1px solid #e5e7eb;}
    
    div.stButton > button {
        background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
        color: white; border: none; padding: 0.6rem; border-radius: 8px; font-weight: 600; width: 100%;
        box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2);
    }
    
    /* 链接按钮 */
    .btn-link {
        display: block; padding: 10px; color: white !important; text-decoration: none !important;
        border-radius: 8px; font-weight: 600; text-align: center; margin-top: 5px;
    }
    .wa { background-color: #10b981; } 
    .tg { background-color: #0ea5e9; }
    
    /* 登录卡片 */
    .login-card {
        background: white; padding: 2rem; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        text-align: center; border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# === 核心逻辑 ===

def extract_all_numbers(row_series):
    txt = " ".join([str(val) for val in row_series if pd.notna(val)])
    # v32 核弹提取
    matches = re.findall(r'(?:^|\D)([789][\d\s\-\(\)]{9,16})(?:\D|$)', txt)
    candidates = []
    for raw in matches:
        d = re.sub(r'\D', '', raw)
        clean = None
        if len(d) == 11:
            if d.startswith('7'): clean = d
            elif d.startswith('8'): clean = '7' + d[1:]
        elif len(d) == 10 and d.startswith('9'): clean = '7' + d
        if clean: candidates.append(clean)
    
    digs = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', txt)
    for raw in digs:
        if len(raw)==11 and raw.startswith('7'): candidates.append(raw)
        elif len(raw)==11 and raw.startswith('8'): candidates.append('7'+raw[1:])
        elif len(raw)==10 and raw.startswith('9'): candidates.append('7'+raw)
    return list(set(candidates))

def get_proxy_config(): return None

def extract_web_content(url):
    if not url or "http" not in str(url): return None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            return f"Page: {title}"
    except: return None
    return None

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
                status.update(label=f"⚠️ API Error {resp.status_code}", state="error"); return status_map
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

def get_ai_message(client, shop, link, web, rep):
    prompt = f"Role: Manager '{rep}' from 988 Group (China). Target: '{shop}'. Link: {link}. Context: Sourcing+Logistics. Task: Polite Russian WhatsApp intro. <40 words."
    try:
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user", "content":prompt}], temperature=0.7, max_tokens=200)
        return res.choices[0].message.content.strip()
    except: return f"Здравствуйте, {shop}! Меня зовут {rep} (988 Group). Предлагаем закупку и доставку из Китая."

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# ==========================================
# 🔐 Login & State Init
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
# === 关键：初始化数据缓存，防止刷新丢失 ===
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
                st.error("❌ Database Connection Failed. Configure Secrets.")
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
    menu = st.radio("Menu", ["🚀 WorkBench", "📊 Supervision"] if st.session_state['role']=='admin' else ["🚀 WorkBench"])
    st.divider()
    if st.button("Logout"): 
        st.session_state.clear()
        st.rerun()

# 1. WorkBench
if "WorkBench" in str(menu):
    st.title("🚀 Acquisition Workbench")
    
    # 只有当没有结果时，才显示上传框（避免占用空间）
    with st.expander("📂 Upload New File", expanded=st.session_state['results'] is None):
        up_file = st.file_uploader("Select Excel/CSV File", type=['xlsx', 'csv'])
        
        if up_file:
            try:
                if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
                else: df = pd.read_excel(up_file, header=None)
                df = df.astype(str)
                
                raw_preview = set()
                for _, r in df.iterrows():
                    ext = extract_all_numbers(r)
                    for p in ext: raw_preview.add(p)
                st.info(f"📊 Detected {len(raw_preview)} numbers.")
                
                c1, c2 = st.columns(2)
                with c1: s_col = st.selectbox("Store Name", range(len(df.columns)), 1)
                with c2: l_col = st.selectbox("Store Link", range(len(df.columns)), 0)
                
                # === 处理逻辑 ===
                if st.button("Start Processing"):
                    client = OpenAI(api_key=OPENAI_KEY)
                    
                    # 1. 提取
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
                    
                    # 2. 验号
                    status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
                    
                    # 3. 筛选有效
                    valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
                    
                    if not valid_phones:
                        st.warning(f"Extracted {len(raw_phones)} numbers, none valid.")
                        save_task_history(st.session_state['username'], up_file.name, len(raw_phones), 0)
                        st.stop()
                        
                    # 4. 生成
                    final_data = []
                    processed_rows = set()
                    st.info(f"🧠 Generating for {len(valid_phones)} leads...")
                    ai_bar = st.progress(0)
                    
                    for idx, p in enumerate(valid_phones):
                        indices = row_map[p]
                        for rid in indices:
                            if rid in processed_rows: continue
                            processed_rows.add(rid)
                            row = df.iloc[rid]
                            s_name = row[s_col]; s_link = row[l_col]
                            msg = get_ai_message(client, s_name, s_link, extract_web_content(s_link), st.session_state['real_name'])
                            wa_link = make_wa_link(p, msg); tg_link = f"https://t.me/+{p}"
                            final_data.append({"Shop": s_name, "Phone": p, "Msg": msg, "WA": wa_link, "TG": tg_link})
                        ai_bar.progress((idx+1)/len(valid_phones))
                    
                    # === 关键：保存到 Session State，防止刷新丢失 ===
                    st.session_state['results'] = final_data
                    
                    # 存档到数据库
                    save_task_history(st.session_state['username'], up_file.name, len(raw_phones), len(valid_phones))
                    
                    st.success(f"✅ Done! {len(final_data)} leads saved.")
                    st.rerun() # 强制刷新以显示结果
                    
            except Exception as e: st.error(f"Error: {e}")

    # === 结果展示区 (独立于上传逻辑) ===
    if st.session_state['results']:
        
        # 顶部工具栏
        c_act1, c_act2 = st.columns([3, 1])
        with c_act1:
            st.markdown(f"### 🎯 Active Leads ({len(st.session_state['results'])})")
        with c_act2:
            if st.button("🗑️ Clear Results"):
                st.session_state['results'] = None
                st.session_state['unlocked_leads'] = set()
                st.rerun()

        for i, item in enumerate(st.session_state['results']):
            with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                st.write(item['Msg'])
                
                lead_id = f"{item['Phone']}_{i}"
                if lead_id in st.session_state['unlocked_leads']:
                    c1, c2 = st.columns(2)
                    with c1: st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-link wa">🟢 Open WhatsApp</a>', unsafe_allow_html=True)
                    with c2: st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-link tg">🔵 Open Telegram</a>', unsafe_allow_html=True)
                else:
                    # 点击这个按钮会触发 rerun，但因为数据在 session_state 里，所以不会丢
                    if st.button(f"👆 Unlock Contact Info", key=f"ul_{i}"):
                        log_click_event(st.session_state['username'], item['Shop'], item['Phone'], 'unlock')
                        st.session_state['unlocked_leads'].add(lead_id)
                        st.rerun()

# 3. Admin
elif "Supervision" in str(menu) and st.session_state['role'] == 'admin':
    st.title("📊 Admin Panel")
    df_clicks, df_tasks = get_admin_stats()
    if not df_clicks.empty:
        st.metric("Total Contacts Unlocked", len(df_clicks))
        st.subheader("Leaderboard")
        lb = df_clicks['username'].value_counts().reset_index()
        lb.columns=['User', 'Clicks']
        st.dataframe(lb, use_container_width=True)
        st.bar_chart(lb.set_index('User'))
        with st.expander("Logs"): st.dataframe(df_clicks)
    else: st.info("No data.")
    
    st.divider()
    with st.form("new_user"):
        u = st.text_input("User"); p = st.text_input("Pass", type="password"); n = st.text_input("Name")
        if st.form_submit_button("Create"):
            if create_user(u, p, n): st.success("Created")
            else: st.error("Failed")
