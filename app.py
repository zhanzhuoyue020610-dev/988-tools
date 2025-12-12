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
import sqlite3
import hashlib
import datetime
from bs4 import BeautifulSoup 

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
# 💾 数据库核心
# ==========================================
DB_FILE = "crm_988_v7.db" # 升级版本号

def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password TEXT, role TEXT, real_name TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, filename TEXT, total_leads INTEGER, verified_wa INTEGER, timestamp DATETIME, csv_data BLOB)''')
    c.execute('''CREATE TABLE IF NOT EXISTS actions (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, shop_name TEXT, action_type TEXT, timestamp DATETIME)''')
    
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        pwd = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ('admin', pwd, 'admin', 'Super Admin'))
    conn.commit(); conn.close()

def login_user(u, p):
    conn = sqlite3.connect(DB_FILE)
    pwd = hashlib.sha256(p.encode()).hexdigest()
    res = conn.cursor().execute("SELECT role, real_name FROM users WHERE username=? AND password=?", (u, pwd)).fetchone()
    conn.close(); return res

def create_user(u, p, n):
    try:
        conn = sqlite3.connect(DB_FILE)
        pwd = hashlib.sha256(p.encode()).hexdigest()
        conn.cursor().execute("INSERT INTO users VALUES (?, ?, ?, ?)", (u, pwd, 'sales', n))
        conn.commit(); conn.close(); return True
    except: return False

def log_action(username, shop_name):
    conn = sqlite3.connect(DB_FILE)
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.cursor().execute("INSERT INTO actions (username, shop_name, action_type, timestamp) VALUES (?, ?, ?, ?)", (username, shop_name, 'contacted', ts))
    conn.commit(); conn.close()

def get_stats():
    conn = sqlite3.connect(DB_FILE)
    df_tasks = pd.read_sql_query("SELECT username, COUNT(*) as tasks, SUM(total_leads) as leads FROM history GROUP BY username", conn)
    df_actions = pd.read_sql_query("SELECT username, COUNT(*) as contacted FROM actions GROUP BY username", conn)
    conn.close()
    if not df_tasks.empty: return pd.merge(df_tasks, df_actions, on='username', how='outer').fillna(0)
    return pd.DataFrame()

def save_history(username, fname, total, valid, df):
    conn = sqlite3.connect(DB_FILE)
    blob = df.to_csv(index=False).encode('utf-8-sig')
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.cursor().execute("INSERT INTO history (username, filename, total_leads, verified_wa, timestamp, csv_data) VALUES (?, ?, ?, ?, ?, ?)", (username, fname, total, valid, ts, blob))
    conn.commit(); conn.close()

def get_user_history(username):
    conn = sqlite3.connect(DB_FILE)
    try:
        if username == 'admin':
            q = "SELECT h.id, h.username, u.real_name, h.filename, h.total_leads, h.verified_wa, h.timestamp FROM history h LEFT JOIN users u ON h.username = u.username ORDER BY h.id DESC"
            df = pd.read_sql_query(q, conn)
        else:
            df = pd.read_sql_query("SELECT id, filename, total_leads, verified_wa, timestamp FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
    except: df = pd.DataFrame()
    finally: conn.close()
    return df

def get_history_file(rid):
    conn = sqlite3.connect(DB_FILE)
    data = conn.cursor().execute("SELECT csv_data, filename FROM history WHERE id=?", (rid,)).fetchone()
    conn.close(); return data

init_db()

# ==========================================
# 🎨 UI Style
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f0f2f6;}
    
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    section[data-testid="stSidebar"] {background-color: #ffffff; border-right: 1px solid #e5e7eb;}
    
    div.stButton > button {
        background: linear-gradient(135deg, #2563eb 0%, #1e40af 100%);
        color: white; border: none; padding: 0.6rem 1.5rem; border-radius: 8px; font-weight: 600;
        box-shadow: 0 4px 6px rgba(37, 99, 235, 0.2); width: 100%;
    }
    div.stButton > button:hover {transform: translateY(-2px);}
    
    div[data-testid="stExpander"] {
        background: white; border: 1px solid #e2e8f0; border-radius: 10px; margin-bottom: 10px;
    }
    
    /* HTML Buttons */
    .btn-action {
        display: block; padding: 8px 12px; color: white !important; text-decoration: none !important;
        border-radius: 6px; font-weight: 500; text-align: center; font-size: 14px; margin-bottom: 4px;
    }
    .wa-green { background-color: #10b981; } 
    .tg-blue { background-color: #0ea5e9; } 
</style>
""", unsafe_allow_html=True)

# === Core Logic ===

def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    # v32 强力提取逻辑
    broad_matches = re.findall(r'(?:^|\D)([789][\d\s\-\(\)]{9,16})(?:\D|$)', full_text)
    candidates = []
    for raw in broad_matches:
        digits = re.sub(r'\D', '', raw)
        clean_num = None
        if len(digits) == 11:
            if digits.startswith('7'): clean_num = digits
            elif digits.startswith('8'): clean_num = '7' + digits[1:]
        elif len(digits) == 10 and digits.startswith('9'):
            clean_num = '7' + digits
        if clean_num: candidates.append(clean_num)
    
    # 补漏纯数字
    digits_only = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', full_text)
    for raw in digits_only:
        if len(raw) == 11 and raw.startswith('7'): candidates.append(raw)
        elif len(raw) == 11 and raw.startswith('8'): candidates.append('7' + raw[1:])
        elif len(raw) == 10 and raw.startswith('9'): candidates.append('7' + raw)
        
    return list(set(candidates))

def get_proxy_config(): return None

def extract_web_content(url):
    if not url or "http" not in str(url): return None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=3)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            desc = soup.find('meta', attrs={'name': 'description'})
            d_txt = desc.get('content', '') if desc else ""
            return f"Title: {title} | {d_txt[:100]}"
    except: return None
    return None

def process_checknumber_task(phone_list, api_key, user_id):
    if not phone_list: return {}
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    
    with st.status("📡 API Verification...", expanded=True) as status:
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
        
        if not result_url: 
            status.update(label="⚠️ Timeout", state="error"); return status_map
            
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
                status.update(label=f"✅ Verified: {cnt} valid numbers.", state="complete")
        except: pass
    return status_map

def get_ai_message(client, shop, link, web, rep):
    info = f"Link: {link}\nInfo: {web}"
    prompt = f"""
    Role: Sales Manager at "988 Group" (China). Sender: "{rep}". Target: "{shop}".
    Context: 988 Group = Sourcing + Logistics (China->Russia).
    Source: {info}
    Task: Polite Russian WhatsApp intro. <40 words.
    Structure:
    1. "Здравствуйте, [Name]! Меня зовут {rep} (988 Group)."
    2. "Saw your store..."
    3. "We supply [Niche] + shipping to Russia."
    4. "Catalog?"
    """
    try:
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user", "content":prompt}], temperature=0.7, max_tokens=250)
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
        st.markdown("<div style='height:5vh;'></div>", unsafe_allow_html=True)
        with st.container():
            if os.path.exists("logo.png"): st.image("logo.png", width=200)
            else: st.markdown("## 🚛 988 Group CRM")
            st.markdown("#### Login to Workspace")
            with st.form("login_form"):
                u = st.text_input("Username"); p = st.text_input("Password", type="password")
                if st.form_submit_button("Sign In"):
                    user = login_user(u, p)
                    if user:
                        st.session_state.update({'logged_in':True, 'username':u, 'role':user[0], 'real_name':user[1]})
                        st.rerun()
                    else: st.error("Invalid credentials")
    st.stop()

# --- Internal ---
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except:
    CN_USER=""; CN_KEY=""; OPENAI_KEY=""

with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=180)
    st.markdown(f"**Hi, {st.session_state['real_name']}**")
    menu = st.radio("Navigation", ["🚀 WorkBench", "📂 History", "📊 Admin"] if st.session_state['role']=='admin' else ["🚀 WorkBench", "📂 History"])
    st.divider()
    if st.button("Logout", type="secondary"): st.session_state['logged_in']=False; st.rerun()

# 1. WorkBench
if "WorkBench" in str(menu):
    st.title("🚀 Acquisition Workbench")
    
    with st.expander("📂 Import Data", expanded=True):
        up_file = st.file_uploader("Select Excel/CSV File", type=['xlsx', 'csv'])
    
    if up_file:
        try:
            if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
            else: df = pd.read_excel(up_file, header=None)
            df = df.astype(str)
        except: st.stop()
        
        c1, c2 = st.columns(2)
        with c1: s_col = st.selectbox("Store Name", range(len(df.columns)), 1)
        with c2: l_col = st.selectbox("Store Link", range(len(df.columns)), 0)
        
        st.markdown("<br>", unsafe_allow_html=True)
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
            
            if not raw_phones: st.error("No Numbers Found"); st.stop()
            
            # 2. 验号
            status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
            
            # 3. 生成 (严格过滤：只处理 Valid)
            final_data = []
            valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
            
            if not valid_phones:
                st.warning(f"Extracted {len(raw_phones)} numbers, but NONE were valid WhatsApp.")
                st.stop()
                
            processed_rows = set()
            
            st.info(f"🧠 Generating messages for {len(valid_phones)} verified leads...")
            ai_bar = st.progress(0)
            
            # 只遍历有效号码
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
            
            # 存档
            save_history(st.session_state['username'], up_file.name, len(raw_phones), len(valid_phones), pd.DataFrame(final_data))
            
            # 展示
            st.success(f"✅ Processing Done! {len(final_data)} VALID leads ready.")
            
            for i, item in enumerate(final_data):
                with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                    st.info(item['Msg'])
                    
                    c1, c2, c3 = st.columns([2, 2, 1])
                    
                    with c1:
                        # 只有这一种绿色按钮了
                        st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-action wa-green">🟢 WhatsApp (Verified)</a>', unsafe_allow_html=True)
                    with c2:
                        st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-action tg-blue">🔵 Telegram</a>', unsafe_allow_html=True)
                    with c3:
                        if st.button("✅ Done", key=f"d_{i}"):
                            log_action(st.session_state['username'], item['Shop'])
                            st.toast("Logged!")

# 2. History
elif "History" in str(menu):
    st.title("📂 Task History")
    df_hist = get_user_history(st.session_state['username'])
    if not df_hist.empty:
        for _, row in df_hist.iterrows():
            with st.expander(f"📅 {row['timestamp']} - {row['filename']}"):
                c1, c2 = st.columns(2)
                c1.metric("Leads", row['total_leads'])
                c2.metric("Verified WA", row['verified_wa'])
                file_data = get_history_file(row['id'])
                if file_data: st.download_button("📥 Download CSV", file_data[0], f"hist_{row['id']}.csv", "text/csv")
    else: st.info("No records.")

# 3. Admin
elif "Admin" in str(menu):
    st.title("📊 Admin Panel")
    stats = get_stats()
    if not stats.empty:
        st.subheader("Performance Overview")
        st.dataframe(stats, use_container_width=True)
        st.bar_chart(stats.set_index('username')['contacted'])
    else: st.info("No data available.")
    
    st.divider()
    with open(DB_FILE, "rb") as f:
        st.download_button("📥 Backup Database", f, "crm_backup.db")
        
    st.subheader("User Management")
    with st.form("new"):
        c1, c2, c3 = st.columns(3)
        u = c1.text_input("Username")
        p = c2.text_input("Password", type="password")
        n = c3.text_input("Real Name")
        if st.form_submit_button("Create User"):
            if create_user(u, p, n): st.success("User Created")
            else: st.error("Failed")
