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
from supabase import create_client, Client

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
# ☁️ Supabase 云数据库连接
# ==========================================
@st.cache_resource
def init_supabase():
    # 尝试从 Secrets 读取，如果没有则报错
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
        return create_client(url, key)
    except:
        return None

supabase: Client = init_supabase()

# --- 数据库操作函数 ---

def login_user(u, p):
    if not supabase: return None
    pwd_hash = hashlib.sha256(p.encode()).hexdigest()
    try:
        response = supabase.table('users').select("*").eq('username', u).eq('password', pwd_hash).execute()
        if response.data:
            return response.data[0] # 返回用户字典
    except: pass
    return None

def create_user(u, p, n):
    if not supabase: return False
    pwd_hash = hashlib.sha256(p.encode()).hexdigest()
    try:
        data = {"username": u, "password": pwd_hash, "role": "sales", "real_name": n}
        supabase.table('users').insert(data).execute()
        return True
    except: return False

def log_click_event(username, shop, phone, target):
    """记录每一次点击行为 (监控核心)"""
    if not supabase: return
    try:
        data = {
            "username": username,
            "shop_name": shop,
            "phone": phone,
            "target": target # 'whatsapp' or 'telegram'
        }
        supabase.table('clicks').insert(data).execute()
    except Exception as e:
        print(f"Log Error: {e}")

def save_task_history(username, fname, total, valid):
    if not supabase: return
    try:
        data = {
            "username": username,
            "filename": fname,
            "total_leads": total,
            "valid_wa": valid
        }
        supabase.table('history').insert(data).execute()
    except: pass

def get_admin_stats():
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    
    # 获取点击数据
    try:
        clicks = supabase.table('clicks').select("*").execute()
        df_clicks = pd.DataFrame(clicks.data)
        
        # 获取任务数据
        tasks = supabase.table('history').select("*").execute()
        df_tasks = pd.DataFrame(tasks.data)
        
        return df_clicks, df_tasks
    except:
        return pd.DataFrame(), pd.DataFrame()

# ==========================================
# 🎨 UI Style
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f0f2f6;}
    
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #ffffff; border-right: 1px solid #e5e7eb;}
    
    /* 核心交互按钮 */
    div.stButton > button {
        background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
        color: white; border: none; padding: 0.6rem; border-radius: 8px; font-weight: 600; width: 100%;
        box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2);
    }
    
    /* 链接按钮样式 */
    .btn-link {
        display: block; padding: 10px; color: white !important; text-decoration: none !important;
        border-radius: 8px; font-weight: 600; text-align: center; margin-top: 5px;
        transition: opacity 0.2s;
    }
    .wa { background-color: #10b981; } 
    .tg { background-color: #0ea5e9; }
    
    /* 警告框 */
    .metric-card {
        background: white; padding: 15px; border-radius: 10px; border: 1px solid #e2e8f0;
        text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-num { font-size: 24px; font-weight: bold; color: #1e40af; }
    .metric-label { font-size: 14px; color: #64748b; }
</style>
""", unsafe_allow_html=True)

# === 核心逻辑 ===

def extract_all_numbers(row_series):
    # v32 核弹级提取
    txt = " ".join([str(val) for val in row_series if pd.notna(val)])
    # 宽泛匹配 7,8,9 开头
    matches = re.findall(r'(?:^|\D)([789][\d\s\-\(\)]{9,16})(?:\D|$)', txt)
    candidates = []
    for raw in matches:
        d = re.sub(r'\D', '', raw)
        clean = None
        if len(d) == 11:
            if d.startswith('7'): clean = d
            elif d.startswith('8'): clean = '7' + d[1:]
        elif len(d) == 10 and d.startswith('9'):
            clean = '7' + d
        if clean: candidates.append(clean)
    
    # 补漏纯数字
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
                        status_map[nm] = 'valid'
                        cnt += 1
                    else:
                        status_map[nm] = 'invalid'
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
# 🔐 Login & Main
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<div style='height:10vh;'></div>", unsafe_allow_html=True)
        with st.container():
            if os.path.exists("logo.png"): st.image("logo.png", width=200)
            else: st.markdown("## 🚛 988 Group CRM")
            
            if not supabase:
                st.error("❌ Database Connection Failed. Please configure Secrets.")
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
except:
    CN_USER=""; CN_KEY=""; OPENAI_KEY=""

with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=160)
    st.write(f"👤 **{st.session_state['real_name']}**")
    
    menu = st.radio("Menu", ["🚀 WorkBench", "📊 Supervision"] if st.session_state['role']=='admin' else ["🚀 WorkBench"])
    
    st.divider()
    if st.button("Logout"): st.session_state['logged_in']=False; st.rerun()

# 1. WorkBench
if "WorkBench" in str(menu):
    st.title("🚀 Acquisition Workbench")
    
    up_file = st.file_uploader("Upload Excel/CSV", type=['xlsx', 'csv'])
    
    if up_file:
        try:
            if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
            else: df = pd.read_excel(up_file, header=None)
            df = df.astype(str)
        except: st.stop()
        
        # 预览
        raw_preview = set()
        for _, r in df.iterrows():
            ext = extract_all_numbers(r)
            for p in ext: raw_preview.add(p)
        st.info(f"📊 Preview: Detected {len(raw_preview)} numbers.")
        
        c1, c2 = st.columns(2)
        with c1: s_col = st.selectbox("Store Name", range(len(df.columns)), 1)
        with c2: l_col = st.selectbox("Store Link", range(len(df.columns)), 0)
        
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
            
            # Filter Valid Only
            valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
            
            if not valid_phones:
                st.warning(f"Extracted {len(raw_phones)} numbers, but NONE were valid WhatsApp.")
                save_task_history(st.session_state['username'], up_file.name, len(raw_phones), 0)
                st.stop()
                
            # AI Gen
            final_data = []
            processed_rows = set()
            st.info(f"🧠 Generating for {len(valid_phones)} valid leads...")
            ai_bar = st.progress(0)
            
            for idx, p in enumerate(valid_phones):
                indices = row_map[p]
                for rid in indices:
                    if rid in processed_rows: continue
                    processed_rows.add(rid)
                    
                    row = df.iloc[rid]
                    s_name = row[s_col]
                    s_link = row[l_col]
                    msg = get_ai_message(client, s_name, s_link, extract_web_content(s_link), st.session_state['real_name'])
                    wa_link = make_wa_link(p, msg)
                    tg_link = f"https://t.me/+{p}"
                    
                    final_data.append({
                        "Shop": s_name, "Phone": p, "Msg": msg,
                        "WA": wa_link, "TG": tg_link
                    })
                ai_bar.progress((idx+1)/len(valid_phones))
            
            # Save History to Supabase
            save_task_history(st.session_state['username'], up_file.name, len(raw_phones), len(valid_phones))
            
            # Display
            st.success(f"✅ Ready! {len(final_data)} High-Quality Leads.")
            
            # Session State storage for buttons state
            if 'unlocked_leads' not in st.session_state:
                st.session_state['unlocked_leads'] = set()

            for i, item in enumerate(final_data):
                with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                    st.write(item['Msg'])
                    
                    # === 核心逻辑：解锁机制 (Click-to-Reveal) ===
                    lead_id = f"{item['Phone']}_{i}"
                    
                    if lead_id in st.session_state['unlocked_leads']:
                        # 已解锁状态：显示绿色按钮
                        c1, c2 = st.columns(2)
                        with c1:
                            st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-link wa">🟢 Open WhatsApp</a>', unsafe_allow_html=True)
                        with c2:
                            st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-link tg">🔵 Open Telegram</a>', unsafe_allow_html=True)
                    else:
                        # 未解锁状态：显示“获取联系方式”按钮
                        if st.button(f"👆 Unlock Contact Info", key=f"unlock_{i}"):
                            # 记录点击到 Supabase
                            log_click_event(st.session_state['username'], item['Shop'], item['Phone'], 'unlock')
                            # 标记为已解锁
                            st.session_state['unlocked_leads'].add(lead_id)
                            st.rerun() # 刷新页面显示按钮

# 3. Supervision (Admin Only)
elif "Supervision" in str(menu) and st.session_state['role'] == 'admin':
    st.title("📊 Team Performance")
    
    df_clicks, df_tasks = get_admin_stats()
    
    if not df_clicks.empty and not df_tasks.empty:
        # 1. KPI Cards
        total_leads = df_tasks['total_leads'].sum()
        total_valid = df_tasks['valid_wa'].sum()
        total_clicks = len(df_clicks)
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Scanned", total_leads)
        k2.metric("Valid Leads", total_valid)
        k3.metric("Actual Contacts (Clicks)", total_clicks)
        
        st.divider()
        
        # 2. 员工业绩榜 (Leaderboard)
        st.subheader("🏆 Sales Leaderboard")
        # 统计每个人的点击数
        leaderboard = df_clicks['username'].value_counts().reset_index()
        leaderboard.columns = ['Sales Rep', 'Customers Contacted']
        st.dataframe(leaderboard, use_container_width=True)
        st.bar_chart(leaderboard.set_index('Sales Rep'))
        
        # 3. 详细日志
        with st.expander("📝 Detailed Click Logs"):
            st.dataframe(df_clicks[['created_at', 'username', 'shop_name', 'phone']].sort_values('created_at', ascending=False), use_container_width=True)
            
    else:
        st.info("No data yet.")
        
    st.divider()
    st.subheader("User Management")
    with st.form("new_user"):
        c1, c2, c3 = st.columns(3)
        u = c1.text_input("Username")
        p = c2.text_input("Password", type="password")
        n = c3.text_input("Real Name")
        if st.form_submit_button("Create User"):
            if create_user(u, p, n): st.success(f"User {u} created!")
            else: st.error("Failed")
