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
# 💾 数据库核心层 (SQLite)
# ==========================================
DB_FILE = "crm_988.db"

def init_db():
    """初始化数据库表结构"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # 1. 用户表
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (username TEXT PRIMARY KEY, password TEXT, role TEXT, real_name TEXT)''')
    
    # 2. 历史记录表
    c.execute('''CREATE TABLE IF NOT EXISTS history
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT, 
                  upload_filename TEXT, 
                  total_rows INTEGER, 
                  valid_wa INTEGER, 
                  timestamp DATETIME,
                  csv_data BLOB)''')
    
    # 3. 只有第一次运行时创建默认管理员
    c.execute("SELECT * FROM users WHERE username='admin'")
    if not c.fetchone():
        # 默认密码 admin123 (SHA256加密)
        pwd_hash = hashlib.sha256("admin123".encode()).hexdigest()
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ('admin', pwd_hash, 'admin', 'Super Admin'))
        # 创建一个测试业务员
        user_hash = hashlib.sha256("123456".encode()).hexdigest()
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ('anna', user_hash, 'sales', 'Anna'))
        
    conn.commit()
    conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    c.execute("SELECT role, real_name FROM users WHERE username=? AND password=?", (username, pwd_hash))
    data = c.fetchone()
    conn.close()
    return data # (role, real_name) or None

def create_user(username, password, real_name):
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (username, pwd_hash, 'sales', real_name))
        conn.commit()
        conn.close()
        return True
    except:
        return False

def save_history_record(username, filename, total, valid, df_result):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    # 将 DataFrame 转为 CSV 字节流存入数据库
    csv_bytes = df_result.to_csv(index=False).encode('utf-8-sig')
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute("INSERT INTO history (username, upload_filename, total_rows, valid_wa, timestamp, csv_data) VALUES (?, ?, ?, ?, ?, ?)",
              (username, filename, total, valid, timestamp, csv_bytes))
    conn.commit()
    conn.close()

def get_user_history(username):
    conn = sqlite3.connect(DB_FILE)
    if username == 'admin':
        # 管理员看所有
        df = pd.read_sql_query("SELECT id, username, real_name, upload_filename, total_rows, valid_wa, timestamp FROM history JOIN users ON history.username = users.username ORDER BY id DESC", conn)
    else:
        # 业务员看自己
        df = pd.read_sql_query("SELECT id, upload_filename, total_rows, valid_wa, timestamp FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
    conn.close()
    return df

def get_history_file(record_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT csv_data, upload_filename FROM history WHERE id=?", (record_id,))
    data = c.fetchone()
    conn.close()
    return data

# 初始化数据库
init_db()

# ==========================================
# 🎨 UI & 业务逻辑
# ==========================================

st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

# CSS 美化
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f8f9fa;}
    h1 {color: #003366; font-weight: 800;}
    
    /* 登录框样式 */
    .login-box {
        padding: 2rem; background: white; border-radius: 10px; 
        box-shadow: 0 4px 12px rgba(0,0,0,0.1); margin-top: 2rem;
    }
    
    /* 按钮 */
    div.stButton > button {
        background: linear-gradient(135deg, #0052cc 0%, #003366 100%);
        color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 8px; width: 100%;
    }
    
    /* 结果按钮 */
    .custom-wa-btn {
        display: inline-block; padding: 6px 12px; color: white !important;
        background: #25D366; border-radius: 5px; text-decoration: none; width:100%; text-align:center;
    }
    .custom-tg-btn {
        display: inline-block; padding: 6px 12px; color: white !important;
        background: #0088cc; border-radius: 5px; text-decoration: none; width:100%; text-align:center;
    }
    
    /* 侧边栏 */
    section[data-testid="stSidebar"] {background-color: #ffffff; border-right: 1px solid #ddd;}
</style>
""", unsafe_allow_html=True)

# === Session 状态管理 ===
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
    st.session_state['username'] = ''
    st.session_state['role'] = ''
    st.session_state['real_name'] = ''

# === 核心处理函数 (保持 v28 逻辑) ===
def get_proxy_config():
    # 这里演示用，实际可从 secrets 读取
    return None 

def extract_web_content(url):
    if not url or "http" not in str(url): return None
    try:
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=4)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            desc = soup.find('meta', attrs={'name': 'description'})
            desc_content = desc.get('content', '') if desc else ""
            return f"Title: {title} | Desc: {desc_content[:150]}"
    except: return None
    return None

def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    matches = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', full_text)
    candidates = []
    for raw in matches:
        digits = re.sub(r'\D', '', str(raw))
        clean_num = None
        if len(digits) == 11:
            if digits.startswith('7'): clean_num = digits
            elif digits.startswith('8'): clean_num = '7' + digits[1:]
        elif len(digits) == 10 and digits.startswith('9'):
            clean_num = '7' + digits
        if clean_num: candidates.append(clean_num)
    return list(set(candidates))

def process_checknumber_task(phone_list, api_key, user_id):
    if not phone_list: return set()
    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    
    with st.status("📡 Server Verification...", expanded=True) as status:
        status.write(f"Uploading {len(phone_list)} numbers...")
        file_content = "\n".join(phone_list)
        files = {'file': ('input.txt', file_content, 'text/plain')}
        try:
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, timeout=30, verify=False)
            if resp.status_code != 200: status.update(label="❌ Upload Failed", state="error"); return set()
            task_id = resp.json().get("task_id")
        except: status.update(label="❌ Connection Error", state="error"); return set()

        status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
        result_url = None
        for i in range(40):
            try:
                time.sleep(3)
                poll = requests.get(status_url, headers=headers, params={'user_id': user_id}, timeout=30, verify=False)
                if poll.status_code == 200 and poll.json().get("status") in ["exported", "completed"]:
                    result_url = poll.json().get("result_url"); break
            except: pass
        
        if not result_url: status.update(label="❌ Timeout", state="error"); return set()
        
        valid_set = set()
        try:
            status.write("Downloading report...")
            f_resp = requests.get(result_url, verify=False)
            if f_resp.status_code == 200:
                try: df_res = pd.read_excel(io.BytesIO(f_resp.content))
                except: df_res = pd.read_csv(io.BytesIO(f_resp.content))
                df_res.columns = [c.lower() for c in df_res.columns]
                for _, r in df_res.iterrows():
                    ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                    nm = re.sub(r'\D', '', str(r.get('number') or r.get('phone') or ''))
                    if "yes" in ws or "valid" in ws: valid_set.add(nm)
                status.update(label=f"✅ Done! {len(valid_set)} valid.", state="complete")
        except: pass
    return valid_set

def get_ai_message(client, shop_name, shop_link, web_content, rep_name):
    source_info = f"Link: {shop_link}\nContent: {web_content}"
    prompt = f"""
    Role: Sales Manager at "988 Group" (China). Sender: "{rep_name}". Target: "{shop_name}".
    Source: {source_info}
    Context: 988 Group = Sourcing + Logistics to Russia.
    Task: Russian WhatsApp intro.
    Structure:
    1. "Здравствуйте, [Name]! Меня зовут {rep_name} (988 Group)."
    2. "Saw your store..."
    3. "We supply [Niche] items + shipping to Russia."
    4. "Catalog?"
    Output: Russian text only.
    """
    try:
        response = client.chat.completions.create(model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.7, max_tokens=250)
        return response.choices[0].message.content.strip()
    except: return f"Здравствуйте, {shop_name}! Меня зовут {rep_name} (988 Group)."

# ==========================================
# 🔐 登录界面逻辑
# ==========================================
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        if os.path.exists("logo.png"): st.image("logo.png", use_container_width=True)
        st.markdown("<h2 style='text-align: center;'>Login to CRM</h2>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            user_input = st.text_input("Username")
            pass_input = st.text_input("Password", type="password")
            submit = st.form_submit_button("Login")
            
            if submit:
                user_data = login_user(user_input, pass_input)
                if user_data:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = user_input
                    st.session_state['role'] = user_data[0]
                    st.session_state['real_name'] = user_data[1]
                    st.rerun()
                else:
                    st.error("Invalid username or password")
    st.stop() # 停止渲染后续内容

# ==========================================
# 🏢 已登录：主界面
# ==========================================

# 读取密钥
try:
    default_cn_user = st.secrets["CN_USER_ID"]
    default_cn_key = st.secrets["CN_API_KEY"]
    default_openai = st.secrets["OPENAI_KEY"]
except:
    default_cn_user = ""; default_cn_key = ""; default_openai = ""

# --- 侧边栏导航 ---
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=160)
    st.write(f"👋 Welcome, **{st.session_state['real_name']}**")
    
    menu = st.radio("Menu", ["🚀 New Task", "📂 History", "📊 Dashboard" if st.session_state['role'] == 'admin' else None])
    
    if st.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()

# --- 页面 1: 新任务 (New Task) ---
if "New Task" in str(menu):
    st.title("🚀 New Acquisition Task")
    
    uploaded_file = st.file_uploader("Upload Excel/CSV", type=['xlsx', 'csv'])
    
    # 获取业务员名字作为 rep_name
    rep_name = st.session_state['real_name']
    
    if uploaded_file:
        try:
            if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file, header=None)
            else: df = pd.read_excel(uploaded_file, header=None)
            df = df.astype(str)
        except: st.stop()
        
        c1, c2 = st.columns(2)
        with c1: shop_col = st.selectbox("Store Name Col", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2: link_col = st.selectbox("Link Col", range(len(df.columns)), index=0)
        
        if st.button("Start Processing"):
            if not default_openai: st.error("No API Config"); st.stop()
            client = OpenAI(api_key=default_openai)
            
            # 1. Extract
            all_raw = set()
            row_map = {}
            bar = st.progress(0)
            for i, r in df.iterrows():
                ext = extract_all_numbers(r)
                for p in ext: 
                    all_raw.add(p)
                    if p not in row_map: row_map[p] = []
                    row_map[p].append(i)
                bar.progress((i+1)/len(df))
                
            if not all_raw: st.error("No numbers"); st.stop()
            
            # 2. Verify
            valid_set = process_checknumber_task(list(all_raw), default_cn_key, default_cn_user)
            
            # 3. AI & Results
            if valid_set:
                final_data = []
                st.info("🧠 Generating AI content...")
                
                # 重新遍历整理结果
                processed_rows = set()
                phones_list = sorted(list(all_raw)) # 遍历所有提取到的号码，不仅仅是 WA 有效的 (为了 TG)
                
                ai_bar = st.progress(0)
                for idx, p in enumerate(phones_list):
                    indices = row_map[p]
                    for rid in indices:
                        if rid in processed_rows: continue
                        processed_rows.add(rid)
                        
                        row = df.iloc[rid]
                        s_name = row[shop_col]
                        s_link = row[link_col]
                        
                        web = extract_web_content(s_link)
                        msg = get_ai_message(client, s_name, s_link, web, rep_name)
                        
                        is_wa = p in valid_set
                        wa_link = f"https://wa.me/{p}?text={urllib.parse.quote(msg)}"
                        tg_link = f"https://t.me/+{p}"
                        
                        final_data.append({
                            "Shop": s_name, "Phone": p, "Message": msg, 
                            "WA_Link": wa_link, "TG_Link": tg_link, "Is_WA": is_wa
                        })
                    ai_bar.progress((idx+1)/len(phones_list))
                
                # === 存档到数据库 ===
                res_df = pd.DataFrame(final_data)
                save_history_record(st.session_state['username'], uploaded_file.name, len(all_raw), len(valid_set), res_df)
                st.success("✅ Task Completed & Archived!")
                
                # === 展示 ===
                for item in final_data:
                    with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                        st.write(item['Message'])
                        c_a, c_b = st.columns(2)
                        with c_a:
                            if item['Is_WA']:
                                st.markdown(f'<a href="{item["WA_Link"]}" target="_blank" class="custom-wa-btn">🟢 WhatsApp</a>', unsafe_allow_html=True)
                            else:
                                st.markdown(f'<a class="custom-wa-btn" style="background:#ccc">⚪ No WhatsApp</a>', unsafe_allow_html=True)
                        with c_b:
                            st.markdown(f'<a href="{item["TG_Link"]}" target="_blank" class="custom-tg-btn">🔵 Telegram</a>', unsafe_allow_html=True)

# --- 页面 2: 历史记录 (History) ---
elif "History" in str(menu):
    st.title("📂 My Task History")
    
    df_hist = get_user_history(st.session_state['username'])
    
    if not df_hist.empty:
        for i, row in df_hist.iterrows():
            with st.expander(f"📅 {row['timestamp']} - {row['upload_filename']}"):
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Scanned", row['total_rows'])
                c2.metric("Valid WA", row['valid_wa'])
                
                # 下载旧文件
                file_data = get_history_file(row['id'])
                if file_data:
                    st.download_button("📥 Download Results", file_data[0], f"archive_{row['id']}.csv", "text/csv", key=f"dl_{i}")
    else:
        st.info("No history found.")

# --- 页面 3: 管理员后台 (Dashboard) ---
elif "Dashboard" in str(menu) and st.session_state['role'] == 'admin':
    st.title("📊 Admin Dashboard (Supervision)")
    
    # 1. 概览数据
    all_hist = get_user_history('admin')
    if not all_hist.empty:
        k1, k2, k3 = st.columns(3)
        k1.metric("Total Tasks", len(all_hist))
        k2.metric("Total Leads Processed", all_hist['total_rows'].sum())
        k3.metric("Valid WA Leads", all_hist['valid_wa'].sum())
        
        st.markdown("### 🏆 Sales Performance")
        
        # 统计每个人的工作量
        perf_df = all_hist.groupby('real_name')[['total_rows', 'valid_wa']].sum().reset_index()
        st.dataframe(perf_df, use_container_width=True)
        st.bar_chart(perf_df.set_index('real_name')['total_rows'])
        
        st.markdown("### 📝 Detailed Activity Log")
        st.dataframe(all_hist[['timestamp', 'real_name', 'upload_filename', 'total_rows', 'valid_wa']], use_container_width=True)
    else:
        st.info("No data yet.")
        
    st.divider()
    st.subheader("👥 Create New User")
    with st.form("new_user"):
        new_u = st.text_input("Username")
        new_p = st.text_input("Password", type="password")
        new_n = st.text_input("Real Name (e.g. David)")
        if st.form_submit_button("Create User"):
            if create_user(new_u, new_p, new_n):
                st.success(f"User {new_u} created!")
            else:
                st.error("User already exists.")
