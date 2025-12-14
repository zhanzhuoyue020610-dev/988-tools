import streamlit as st
import pandas as pd
import re
import urllib.parse
from openai import OpenAI
import requests
import warnings
import time
import io
import os
import hashlib
from datetime import date, datetime, timedelta

try:
    from supabase import create_client, Client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

warnings.filterwarnings("ignore")

# ==========================================
# 🔧 系统配置
# ==========================================
CONFIG = {
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks",
    "DAILY_QUOTA": 25,
    "LOW_STOCK_THRESHOLD": 300
}

# ==========================================
# ☁️ 数据库与核心逻辑
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

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def login_user(u, p):
    if not supabase: return None
    pwd_hash = hash_password(p)
    try:
        res = supabase.table('users').select("*").eq('username', u).eq('password', pwd_hash).execute()
        if res.data:
            supabase.table('users').update({'last_seen': datetime.now().isoformat()}).eq('username', u).execute()
            return res.data[0]
        return None
    except: return None

def create_user(u, p, n, role="sales"):
    if not supabase: return False
    try:
        pwd = hash_password(p)
        supabase.table('users').insert({"username": u, "password": pwd, "role": role, "real_name": n}).execute()
        return True
    except: return False

def get_user_daily_performance(username):
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table('leads').select('assigned_at, completed_at').eq('assigned_to', username).execute()
        df = pd.DataFrame(res.data)
        if df.empty: return pd.DataFrame()
        df['assign_date'] = pd.to_datetime(df['assigned_at']).dt.date
        daily_claim = df.groupby('assign_date').size().rename("领取量")
        df_done = df[df['completed_at'].notna()].copy()
        df_done['done_date'] = pd.to_datetime(df_done['completed_at']).dt.date
        daily_done = df_done.groupby('done_date').size().rename("完成量")
        stats = pd.concat([daily_claim, daily_done], axis=1).fillna(0).astype(int)
        stats = stats.sort_index(ascending=False)
        return stats
    except: return pd.DataFrame()

def get_user_historical_data(username):
    if not supabase: return 0, 0, pd.DataFrame()
    try:
        res_claimed = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).execute()
        total_claimed = res_claimed.count
        res_done = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).eq('is_contacted', True).execute()
        total_done = res_done.count
        res_list = supabase.table('leads').select('shop_name, phone, shop_link, completed_at')\
            .eq('assigned_to', username)\
            .eq('is_contacted', True)\
            .order('completed_at', desc=True)\
            .limit(2000)\
            .execute()
        df_history = pd.DataFrame(res_list.data)
        return total_claimed, total_done, df_history
    except: return 0, 0, pd.DataFrame()

def get_public_pool_count():
    if not supabase: return 0
    try:
        res = supabase.table('leads').select('id', count='exact').is_('assigned_to', 'null').execute()
        return res.count
    except: return 0

def recycle_expired_tasks():
    if not supabase: return 0
    today_str = date.today().isoformat()
    try:
        res = supabase.table('leads').update({
            'assigned_to': None, 'assigned_at': None
        }).lt('assigned_at', today_str).eq('is_contacted', False).execute()
        return len(res.data)
    except: return 0

def delete_user_and_recycle(username):
    if not supabase: return False
    try:
        supabase.table('leads').update({
            'assigned_to': None, 'assigned_at': None, 'is_contacted': False
        }).eq('assigned_to', username).eq('is_contacted', False).execute()
        supabase.table('users').delete().eq('username', username).execute()
        return True
    except: return False

def admin_bulk_upload_to_pool(leads_data):
    if not supabase or not leads_data: return False
    try:
        rows = []
        for item in leads_data:
            rows.append({
                "shop_name": item['Shop'], "shop_link": item['Link'],
                "phone": item['Phone'], "ai_message": item['Msg'], 
                "is_valid": True, "assigned_to": None, "assigned_at": None, "is_contacted": False
            })
        chunk_size = 500
        for i in range(0, len(rows), chunk_size):
            supabase.table('leads').insert(rows[i:i+chunk_size]).execute()
        return True
    except: return False

def claim_daily_tasks(username):
    today_str = date.today().isoformat()
    existing = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    current_count = len(existing)
    if current_count >= CONFIG["DAILY_QUOTA"]: return existing, "full"
    needed = CONFIG["DAILY_QUOTA"] - current_count
    pool_leads = supabase.table('leads').select("id").is_('assigned_to', 'null').limit(needed).execute().data
    if pool_leads:
        ids_to_update = [x['id'] for x in pool_leads]
        supabase.table('leads').update({'assigned_to': username, 'assigned_at': today_str}).in_('id', ids_to_update).execute()
        existing = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
        return existing, "claimed"
    else: return existing, "empty"

def get_todays_leads(username):
    today_str = date.today().isoformat()
    return supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data

def mark_lead_complete_secure(lead_id):
    if not supabase: return
    now_iso = datetime.now().isoformat()
    supabase.table('leads').update({'is_contacted': True, 'completed_at': now_iso}).eq('id', lead_id).execute()

def get_daily_logs(query_date):
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    raw_claims = supabase.table('leads').select('assigned_to, assigned_at').eq('assigned_at', query_date).execute().data
    df_claims = pd.DataFrame(raw_claims)
    if not df_claims.empty:
        df_claim_summary = df_claims.groupby('assigned_to').size().reset_index(name='领取数量')
    else: df_claim_summary = pd.DataFrame(columns=['assigned_to', '领取数量'])
    start_dt = f"{query_date}T00:00:00"
    end_dt = f"{query_date}T23:59:59"
    raw_done = supabase.table('leads').select('assigned_to, completed_at').gte('completed_at', start_dt).lte('completed_at', end_dt).execute().data
    df_done = pd.DataFrame(raw_done)
    if not df_done.empty:
        df_done_summary = df_done.groupby('assigned_to').size().reset_index(name='实际处理')
    else: df_done_summary = pd.DataFrame(columns=['assigned_to', '实际处理'])
    return df_claim_summary, df_done_summary

def extract_all_numbers(row_series):
    txt = " ".join([str(val) for val in row_series if pd.notna(val)])
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
    return list(set(candidates))

def process_checknumber_task(phone_list, api_key, user_id):
    if not phone_list: return {}
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key}
    try:
        files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, verify=False)
        if resp.status_code != 200: return status_map
        task_id = resp.json().get("task_id")
        for i in range(60): 
            time.sleep(2)
            poll = requests.get(f"{CONFIG['CN_BASE_URL']}/{task_id}", headers=headers, params={'user_id': user_id}, verify=False)
            if poll.json().get("status") in ["exported", "completed"]:
                result_url = poll.json().get("result_url")
                if result_url:
                    f = requests.get(result_url, verify=False)
                    try: df = pd.read_excel(io.BytesIO(f.content))
                    except: df = pd.read_csv(io.BytesIO(f.content))
                    for _, r in df.iterrows():
                        ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                        nm = re.sub(r'\D', '', str(r.get('number') or r.get('phone') or ''))
                        if "yes" in ws or "valid" in ws: status_map[nm] = 'valid'
                        else: status_map[nm] = 'invalid'
                break
    except: pass
    return status_map

def get_ai_message_sniper(client, shop, link, rep_name):
    prompt = f"Role: Supply Chain Sales '{rep_name}'. Target: {shop}. Link: {link}. Write short Russian WhatsApp intro offering sourcing services."
    try:
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":prompt}])
        return res.choices[0].message.content
    except: return "Здравствуйте, мы можем помочь вам с поставками из Китая."

def check_api_health(cn_user, cn_key, openai_key):
    status = {"supabase": False, "checknumber": False, "openai": False, "msg": []}
    try:
        if supabase:
            supabase.table('users').select('count', count='exact').limit(1).execute()
            status["supabase"] = True
    except Exception as e: status["msg"].append(f"Supabase Error: {str(e)}")
    try:
        headers = {"X-API-Key": cn_key}
        test_url = f"{CONFIG['CN_BASE_URL']}" 
        resp = requests.get(test_url, headers=headers, params={'user_id': cn_user}, timeout=5, verify=False)
        if resp.status_code in [200, 400, 404]: status["checknumber"] = True
        else: status["msg"].append(f"CheckNumber Error: Status {resp.status_code}")
    except Exception as e: status["msg"].append(f"CheckNumber Net Error: {str(e)}")
    try:
        client = OpenAI(api_key=openai_key)
        client.models.list(); status["openai"] = True
    except Exception as e: status["msg"].append(f"OpenAI Error: {str(e)}")
    return status

# ==========================================
# 🎨 GEMINI MINIMALIST DARK THEME
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="⚫")

st.markdown("""
<style>
    /* 引入 Google Fonts: Inter */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

    :root {
        /* Gemini Dark Palette */
        --bg-color: #131314;           /* 极深灰背景 */
        --surface-color: #1e1f20;      /* 悬浮层背景 */
        --input-bg: #282a2c;           /* 输入框背景 */
        --text-primary: #e3e3e3;       /* 主要文字 */
        --text-secondary: #8e8e8e;     /* 次要文字 */
        --accent-gradient: linear-gradient(90deg, #4b90ff, #ff5546); /* Gemini 风格渐变 */
        --border-radius: 16px;         /* 大圆角 */
    }

    /* 1. 基础重置 */
    .stApp {
        background-color: var(--bg-color) !important;
        color: var(--text-primary) !important;
        font-family: 'Inter', sans-serif !important;
    }
    
    header { visibility: hidden !important; } /* 彻底隐藏顶部彩条 */
    
    /* 2. 标题排版 */
    .gemini-header {
        font-weight: 600;
        font-size: 28px;
        background: var(--accent-gradient);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        letter-spacing: -0.5px;
        margin-bottom: 20px;
    }

    /* 3. 导航栏 */
    div[data-testid="stRadio"] > div {
        background-color: var(--surface-color);
        border: none;
        padding: 6px;
        border-radius: 50px; 
        gap: 0px;
        display: inline-flex;
    }
    div[data-testid="stRadio"] label {
        background-color: transparent !important;
        color: var(--text-secondary) !important;
        padding: 8px 24px;
        border-radius: 40px;
        font-size: 14px;
        transition: all 0.3s ease;
        border: none;
    }
    div[data-testid="stRadio"] label[data-checked="true"] {
        background-color: #3c4043 !important; 
        color: #ffffff !important;
        font-weight: 500;
    }

    /* 4. 卡片与容器 */
    div[data-testid="stExpander"], div[data-testid="stForm"], div.stDataFrame {
        background-color: var(--surface-color) !important;
        border: none !important;
        border-radius: var(--border-radius);
        padding: 5px;
    }
    div[data-testid="stExpander"] details {
        border: none !important;
    }
    
    /* 5. 按钮 */
    button { color: white !important; }
    div.stButton > button {
        background-color: #d7e3ff !important; 
        color: #001d35 !important;            
        border: none !important;
        border-radius: 50px !important;       
        padding: 10px 24px !important;
        font-weight: 600;
        transition: transform 0.1s;
    }
    div.stButton > button:hover {
        opacity: 0.9;
        transform: scale(1.02);
    }
    button:disabled {
        background-color: #444746 !important;
        color: #8e8e8e !important;
    }

    /* 6. 输入框 */
    div[data-baseweb="input"], div[data-baseweb="select"] {
        background-color: var(--input-bg) !important;
        border: none !important;
        border-radius: 12px;
    }
    input { color: white !important; }

    /* 7. 表格 */
    div[data-testid="stDataFrame"] div[role="grid"] {
        background-color: var(--surface-color) !important;
        color: var(--text-secondary);
    }

    /* 8. 进度条 */
    .stProgress > div > div > div > div {
        background: var(--accent-gradient) !important;
        height: 6px !important;
        border-radius: 10px;
    }

    /* 9. 状态指示器 */
    .status-dot {
        height: 8px; width: 8px; border-radius: 50%; display: inline-block; margin-right: 6px;
    }
    .dot-green { background-color: #6dd58c; box-shadow: 0 0 8px #6dd58c; }
    .dot-red { background-color: #ff5f56; }
    
    /* 10. 文字层级 */
    h1, h2, h3, h4 { color: #ffffff !important; font-family: 'Inter', sans-serif; font-weight: 500 !important;}
    p, span, div, label { color: #c4c7c5 !important; font-weight: 400; }
    .stCaption { color: #8e8e8e !important; }

</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 极简登录页
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        st.markdown("<br><br><br><br>", unsafe_allow_html=True)
        st.markdown('<div class="gemini-header" style="text-align:center;">988 GROUP CRM</div>', unsafe_allow_html=True)
        st.markdown('<p style="text-align:center; font-size:13px; color:#8e8e8e;">Welcome back. Please sign in to continue.</p>', unsafe_allow_html=True)
        
        with st.form("login", border=False):
            u = st.text_input("Username", placeholder="Enter your ID")
            p = st.text_input("Password", type="password", placeholder="••••••••")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("Sign In →"):
                user = login_user(u, p)
                if user:
                    st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                    st.rerun()
                else: st.error("Incorrect credentials.")
    st.stop()

# ==========================================
# 🚀 内部主界面
# ==========================================
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

# 顶部栏
c_nav, c_user = st.columns([6, 1])
with c_nav:
    st.markdown(f'<div class="gemini-header" style="font-size:20px; margin:0;">Hello, {st.session_state["real_name"]}</div>', unsafe_allow_html=True)
with c_user:
    if st.button("Logout", key="logout"): st.session_state.clear(); st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# 导航
if st.session_state['role'] == 'admin':
    menu_map = {"System": "System", "Logs": "Logs", "Team": "Team", "Import": "Import"}
    menu_options = ["System", "Logs", "Team", "Import"]
else:
    menu_map = {"Workbench": "Tasks"}
    menu_options = ["Workbench"]

selected_nav = st.radio("Nav", menu_options, format_func=lambda x: menu_map.get(x, x), horizontal=True, label_visibility="collapsed")
st.divider()

# --- 🖥️ SYSTEM MONITOR (Admin) ---
if selected_nav == "System" and st.session_state['role'] == 'admin':
    st.markdown("#### System Health")
    health = check_api_health(CN_USER, CN_KEY, OPENAI_KEY)
    
    k1, k2, k3 = st.columns(3)
    
    def status_pill(title, is_active, detail):
        dot = "dot-green" if is_active else "dot-red"
        text = "Operational" if is_active else "Offline"
        st.markdown(f"""
        <div style="background-color:#1e1f20; padding:20px; border-radius:16px;">
            <div style="font-size:14px; color:#c4c7c5;">{title}</div>
            <div style="margin-top:10px; font-size:16px; color:white; font-weight:500;">
                <span class="status-dot {dot}"></span>{text}
            </div>
            <div style="font-size:12px; color:#8e8e8e; margin-top:5px;">{detail}</div>
        </div>
        """, unsafe_allow_html=True)

    with k1: status_pill("Database", health['supabase'], "Supabase PostgreSQL")
    with k2: status_pill("WhatsApp API", health['checknumber'], "CheckNumber.ai")
    with k3: status_pill("AI Engine", health['openai'], "OpenAI GPT-4o")
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### Sandbox Simulation")
    
    sb_file = st.file_uploader("Upload Test CSV", type=['csv', 'xlsx'])
    if sb_file and st.button("Run Simulation"):
        try:
            if sb_file.name.endswith('.csv'): df = pd.read_csv(sb_file)
            else: df = pd.read_excel(sb_file)
            st.info(f"Loaded {len(df)} rows. Processing sample...")
            
            client = OpenAI(api_key=OPENAI_KEY)
            with st.status("Running Pipeline...", expanded=True) as s:
                s.write("Extracting numbers...")
                nums = []
                for _, r in df.head(5).iterrows(): nums.extend(extract_all_numbers(r))
                s.write(f"Found: {nums}")
                
                s.write("Validating WhatsApp...")
                res = process_checknumber_task(nums, CN_KEY, CN_USER)
                valid = [p for p in nums if res.get(p)=='valid']
                s.write(f"Valid: {valid}")
                
                if valid:
                    s.write("Generating AI Draft...")
                    msg = get_ai_message_sniper(client, "Test Store", "http://test.com", "Admin")
                    s.write(f"Draft: {msg}")
                s.update(label="Simulation Complete", state="complete")
        except Exception as e: st.error(str(e))

# --- 💼 WORKBENCH (Sales) ---
elif selected_nav == "Workbench":
    my_leads = get_todays_leads(st.session_state['username'])
    total, curr = CONFIG["DAILY_QUOTA"], len(my_leads)
    
    c_stat, c_action = st.columns([2, 1])
    with c_stat:
        done = sum(1 for x in my_leads if x.get('is_contacted'))
        st.metric("Daily Progress", f"{done} / {total}")
        st.progress(min(done/total, 1.0))
        
    with c_action:
        st.markdown("<br>", unsafe_allow_html=True)
        if curr < total:
            if st.button(f"Fetch Tasks ({total-curr})"):
                _, status = claim_daily_tasks(st.session_state['username'])
                if status=="empty": st.error("Pool Empty")
                else: st.rerun()
        else:
            st.success("Quota Full")

    st.markdown("#### Task List")
    tabs = st.tabs(["Active", "Completed"])
    
    with tabs[0]:
        todos = [x for x in my_leads if not x.get('is_contacted')]
        if not todos: st.caption("No active tasks.")
        for item in todos:
            with st.expander(f"{item['shop_name']}", expanded=True):
                st.write(item['ai_message'])
                c1, c2 = st.columns(2)
                
                key = f"clk_{item['id']}"
                if key not in st.session_state: st.session_state[key] = False
                
                if not st.session_state[key]:
                    if c1.button("Get Link", key=f"btn_{item['id']}"):
                        st.session_state[key] = True; st.rerun()
                    c2.button("Complete", disabled=True, key=f"dis_{item['id']}")
                else:
                    url = f"https://wa.me/{item['phone']}?text={urllib.parse.quote(item['ai_message'])}"
                    c1.markdown(f"<a href='{url}' target='_blank' style='display:block;text-align:center;background:#1e1f20;color:#e3e3e3;padding:10px;border-radius:20px;text-decoration:none;'>Open WhatsApp ↗</a>", unsafe_allow_html=True)
                    if c2.button("Mark Done", key=f"fin_{item['id']}"):
                        mark_lead_complete_secure(item['id'])
                        del st.session_state[key]; st.rerun()

    with tabs[1]:
        dones = [x for x in my_leads if x.get('is_contacted')]
        if dones:
            df = pd.DataFrame(dones)
            df['time'] = pd.to_datetime(df['completed_at']).dt.strftime('%H:%M')
            st.dataframe(df[['shop_name', 'phone', 'time']], use_container_width=True)
        else: st.caption("No completed tasks.")

# --- 📅 LOGS (Admin) ---
elif selected_nav == "Logs":
    st.markdown("#### Activity Logs")
    d = st.date_input("Date", date.today())
    if d:
        c, f = get_daily_logs(d.isoformat())
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("Claimed")
            if not c.empty: st.dataframe(c, use_container_width=True)
            else: st.caption("No Data")
        with col2:
            st.markdown("Finished")
            if not f.empty: st.dataframe(f, use_container_width=True)
            else: st.caption("No Data")

# --- 👥 TEAM (Admin) ---
elif selected_nav == "Team":
    users = pd.DataFrame(supabase.table('users').select("*").execute().data)
    c1, c2 = st.columns([1, 2])
    with c1:
        u = st.radio("Staff", users['username'].tolist(), label_visibility="collapsed")
        st.markdown("---")
        with st.expander("New User"):
            with st.form("new"):
                nu = st.text_input("Username"); np = st.text_input("Password", type="password"); nn = st.text_input("Name")
                if st.form_submit_button("Create"): create_user(nu, np, nn); st.rerun()
    
    with c2:
        if u:
            info = users[users['username']==u].iloc[0]
            tc, td, hist = get_user_historical_data(u)
            perf = get_user_daily_performance(u)
            
            st.markdown(f"### {info['real_name']}")
            st.caption(f"Last Active: {str(info.get('last_seen','-'))[:16]}")
            
            k1, k2 = st.columns(2)
            k1.metric("Total Claimed", tc)
            k2.metric("Total Done", td)
            
            t1, t2, t3 = st.tabs(["Performance", "History", "Settings"])
            
            # --- 修复的三元表达式逻辑 ---
            with t1:
                if not perf.empty:
                    st.bar_chart(perf)
                else:
                    st.caption("No Data")
            
            with t2:
                if not hist.empty:
                    st.dataframe(hist, use_container_width=True)
                else:
                    st.caption("No Data")
            
            with t3:
                if st.button("Delete User & Recycle Tasks"):
                    delete_user_and_recycle(u); st.rerun()

# --- 📥 IMPORT (Admin) ---
elif selected_nav == "Import":
    pool = get_public_pool_count()
    if pool < CONFIG["LOW_STOCK_THRESHOLD"]:
        st.error(f"Low Stock Warning: Only {pool} leads remaining.")
    else:
        st.metric("Public Pool", pool)
    
    with st.expander("Recycle Tool"):
        if st.button("Recycle Expired Tasks"):
            n = recycle_expired_tasks()
            st.success(f"Recycled {n}")
            
    st.markdown("---")
    st.markdown("#### Upload Data")
    f = st.file_uploader("CSV/Excel", type=['csv', 'xlsx'])
    if f:
        df = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
        st.caption(f"{len(df)} rows")
        if st.button("Process & Import"):
            client = OpenAI(api_key=OPENAI_KEY)
            with st.status("Processing...", expanded=True) as s:
                df=df.astype(str)
                phones = set()
                rmap = {}
                for i, r in df.iterrows():
                    for p in extract_all_numbers(r): phones.add(p); rmap.setdefault(p, []).append(i)
                
                s.write(f"Extracted {len(phones)} numbers")
                plist = list(phones); valid = []
                for i in range(0, len(plist), 500):
                    batch = plist[i:i+500]
                    res = process_checknumber_task(batch, CN_KEY, CN_USER)
                    valid.extend([p for p in batch if res.get(p)=='valid'])
                
                s.write(f"Valid: {len(valid)}. Generating AI...")
                rows = []
                for idx, p in enumerate(valid):
                    r = df.iloc[rmap[p][0]]
                    # 容错处理
                    lnk = r.iloc[0]; shp = r.iloc[1] if len(r)>1 else "Shop"
                    msg = get_ai_message_sniper(client, shp, lnk, "Sales")
                    rows.append({"Shop":shp, "Link":lnk, "Phone":p, "Msg":msg})
                    if len(rows)>=100: admin_bulk_upload_to_pool(rows); rows=[]
                if rows: admin_bulk_upload_to_pool(rows)
                s.update(label="Done", state="complete")
            time.sleep(1); st.rerun()
