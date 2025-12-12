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
# 💾 数据库层
# ==========================================
DB_FILE = "crm_988_v5.db"

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
# 🎨 UI
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f8f9fa;}
    div.stButton > button {background: linear-gradient(135deg, #0052cc 0%, #003366 100%); color: white; border: none; font-weight: 600;}
    .btn-wa-valid {display: block; padding: 8px; color: white !important; background: #25D366; border-radius: 6px; text-decoration: none; text-align: center; font-weight: 600; margin-bottom: 5px;}
    .btn-wa-risky {display: block; padding: 8px; color: #333 !important; background: #FFD700; border-radius: 6px; text-decoration: none; text-align: center; font-weight: 600; margin-bottom: 5px; border: 1px solid #e0c000;}
    .btn-tg {display: block; padding: 8px; color: white !important; background: #0088cc; border-radius: 6px; text-decoration: none; text-align: center; font-weight: 600;}
</style>
""", unsafe_allow_html=True)

# === 核心函数：核弹级提取 ===

def extract_all_numbers(row_series):
    """
    v32.0 终极提取算法：
    不依赖特定格式，先把所有非数字字符变成空，然后重新拼凑。
    解决：8 (926) 123-45 67 这种支离破碎的号码
    """
    # 1. 把这一行转成一个大字符串
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    
    candidates = []
    
    # 2. 策略A：寻找包含分隔符的宽泛模式
    # 匹配规则：7或8或9开头，后面跟着 9-15 个字符（允许数字、空格、横杠、括号）
    # 例子：8 (926) 123-45-67
    broad_matches = re.findall(r'(?:^|\D)([789][\d\s\-\(\)]{9,16})(?:\D|$)', full_text)
    
    for raw in broad_matches:
        # 清洗：只留数字
        digits = re.sub(r'\D', '', raw)
        
        # 验证长度和开头
        clean_num = None
        if len(digits) == 11:
            if digits.startswith('7'): clean_num = digits
            elif digits.startswith('8'): clean_num = '7' + digits[1:]
        elif len(digits) == 10 and digits.startswith('9'):
            clean_num = '7' + digits
            
        if clean_num:
            candidates.append(clean_num)
            
    # 3. 策略B：如果策略A漏了，尝试更暴力的连续数字匹配
    # 有时候 Excel 会把号码存成纯数字：79261234567.0
    digits_only_matches = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', full_text)
    for raw in digits_only_matches:
        if len(raw) == 11 and raw.startswith('7'): candidates.append(raw)
        elif len(raw) == 11 and raw.startswith('8'): candidates.append('7' + raw[1:])
        elif len(raw) == 10 and raw.startswith('9'): candidates.append('7' + raw)

    return list(set(candidates))

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

def get_ai_message(client, shop, link, rep):
    try:
        prompt = f"Role: Manager '{rep}' from 988 Group (China). Target: '{shop}'. Link: {link}. Write short Russian WhatsApp intro offering sourcing & logistics. <40 words."
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
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        if os.path.exists("logo.png"): st.image("logo.png", use_container_width=True)
        st.markdown("<h3 style='text-align:center;'>CRM Login</h3>", unsafe_allow_html=True)
        with st.form("login"):
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
    if os.path.exists("logo.png"): st.image("logo.png", width=160)
    st.write(f"👤 **{st.session_state['real_name']}**")
    menu = st.radio("Menu", ["🚀 WorkBench", "📂 History", "📊 Admin"] if st.session_state['role']=='admin' else ["🚀 WorkBench", "📂 History"])
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
        
        # === 数据预检 (Data Preview) ===
        # 在用户点 Start 之前，先告诉他我们发现了多少号码
        # 这样用户就知道是不是提取逻辑有问题
        preview_phones = set()
        for _, r in df.iterrows():
            ext = extract_all_numbers(r)
            for p in ext: preview_phones.add(p)
            
        st.info(f"📊 **Data Preview:** Detected {len(preview_phones)} unique numbers from {len(df)} rows.")
        if len(preview_phones) < 5:
            st.warning("⚠️ Warning: Very few numbers detected. Please check if the file format is correct.")
        
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
            
            # Verify
            status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
            
            # Generate
            final_data = []
            phones_list = sorted(list(raw_phones))
            processed_rows = set()
            
            ai_bar = st.progress(0)
            for idx, p in enumerate(phones_list):
                indices = row_map[p]
                for rid in indices:
                    if rid in processed_rows: continue
                    processed_rows.add(rid)
                    
                    row = df.iloc[rid]
                    s_name = row[s_col]
                    s_link = row[l_col]
                    msg = get_ai_message(client, s_name, s_link, st.session_state['real_name'])
                    wa_link = make_wa_link(p, msg)
                    tg_link = f"https://t.me/+{p}"
                    status = status_map.get(p, 'unknown')
                    
                    final_data.append({
                        "Shop": s_name, "Phone": p, "Msg": msg,
                        "WA": wa_link, "TG": tg_link, "Status": status
                    })
                ai_bar.progress((idx+1)/len(phones_list))
            
            valid_count = sum(1 for v in status_map.values() if v == 'valid')
            save_history(st.session_state['username'], up_file.name, len(raw_phones), valid_count, pd.DataFrame(final_data))
            
            st.success("✅ Done!")
            for i, item in enumerate(final_data):
                with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                    st.write(item['Msg'])
                    c1, c2, c3 = st.columns([2, 2, 1])
                    with c1:
                        if item['Status'] == 'valid':
                            st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-wa-valid">🟢 WhatsApp (Verified)</a>', unsafe_allow_html=True)
                        else:
                            st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-wa-risky">⚠️ WhatsApp (Unverified)</a>', unsafe_allow_html=True)
                    with c2:
                        st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-tg">🔵 Telegram</a>', unsafe_allow_html=True)
                    with c3:
                        if st.button("✅ Done", key=f"d_{i}"):
                            log_action(st.session_state['username'], item['Shop'])
                            st.toast("Logged!")

# 2. History
elif "History" in str(menu):
    st.title("📂 History")
    df_hist = get_user_history(st.session_state['username'])
    if not df_hist.empty:
        for _, row in df_hist.iterrows():
            with st.expander(f"📅 {row['timestamp']} - {row['filename']}"):
                st.info(f"Leads: {row['total_leads']} | Verified: {row['verified_wa']}")
                file_data = get_history_file(row['id'])
                if file_data: st.download_button("📥 CSV", file_data[0], f"hist_{row['id']}.csv", "text/csv")
    else: st.info("No records.")

# 3. Admin
elif "Admin" in str(menu):
    st.title("📊 Admin Panel")
    stats = get_stats()
    if not stats.empty:
        st.dataframe(stats, use_container_width=True)
        st.bar_chart(stats.set_index('username')['contacted'])
    else: st.info("No data.")
    
    st.divider()
    with open(DB_FILE, "rb") as f:
        st.download_button("📥 Backup Database", f, "crm_backup.db", type="primary")
    
    st.subheader("Add User")
    with st.form("new"):
        u = st.text_input("User"); p = st.text_input("Pass", type="password"); n = st.text_input("Name")
        if st.form_submit_button("Create"):
            if create_user(u, p, n): st.success("Created")
            else: st.error("Error")
