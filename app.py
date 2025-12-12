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
# 💾 数据库核心层 (SQLite) - v3.0 强制刷新
# ==========================================
# 修改文件名以强制重建数据库结构
DB_FILE = "crm_988_v3.db"

def init_db():
    """初始化数据库表结构"""
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # 1. 用户表 (确保包含 real_name)
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
        
        # 3. 检查管理员是否存在，不存在则创建
        c.execute("SELECT * FROM users WHERE username='admin'")
        if not c.fetchone():
            # 默认管理员: admin / admin123
            pwd_hash = hashlib.sha256("admin123".encode()).hexdigest()
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ('admin', pwd_hash, 'admin', 'Super Admin'))
            
            # 默认测试员: anna / 123456
            user_hash = hashlib.sha256("123456".encode()).hexdigest()
            c.execute("INSERT INTO users VALUES (?, ?, ?, ?)", ('anna', user_hash, 'sales', 'Anna'))
            
        conn.commit()
    except Exception as e:
        st.error(f"Database Init Error: {e}")
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    c.execute("SELECT role, real_name FROM users WHERE username=? AND password=?", (username, pwd_hash))
    data = c.fetchone()
    conn.close()
    return data # (role, real_name)

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
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        csv_bytes = df_result.to_csv(index=False).encode('utf-8-sig')
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        c.execute("INSERT INTO history (username, upload_filename, total_rows, valid_wa, timestamp, csv_data) VALUES (?, ?, ?, ?, ?, ?)",
                  (username, filename, total, valid, timestamp, csv_bytes))
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"Save Error: {e}")

def get_user_history(username):
    conn = sqlite3.connect(DB_FILE)
    try:
        if username == 'admin':
            # 管理员：查看所有人，关联 users 表获取真实姓名
            # 如果 users 表结构不对，这里会报错，所以加了 try
            query = """
                SELECT h.id, h.username, u.real_name, h.upload_filename, h.total_rows, h.valid_wa, h.timestamp 
                FROM history h 
                LEFT JOIN users u ON h.username = u.username 
                ORDER BY h.id DESC
            """
            df = pd.read_sql_query(query, conn)
        else:
            # 普通用户：只看自己
            df = pd.read_sql_query("SELECT id, upload_filename, total_rows, valid_wa, timestamp FROM history WHERE username=? ORDER BY id DESC", conn, params=(username,))
    except Exception as e:
        # 如果出错，返回空表，防止崩溃
        print(f"DB Read Error: {e}")
        df = pd.DataFrame() 
    finally:
        conn.close()
    return df

def get_history_file(record_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT csv_data, upload_filename FROM history WHERE id=?", (record_id,))
    data = c.fetchone()
    conn.close()
    return data

# 启动时初始化
init_db()

# ==========================================
# 🎨 UI & 业务逻辑
# ==========================================

st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif; background-color: #f8f9fa;}
    
    /* 登录框 */
    .stForm {
        background: white;
        padding: 2rem;
        border-radius: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05);
        border: 1px solid #e2e8f0;
    }
    
    /* 按钮样式 */
    div.stButton > button {
        background: linear-gradient(135deg, #0052cc 0%, #003366 100%);
        color: white; border: none; padding: 0.6rem 1.2rem; border-radius: 8px; width: 100%;
        font-weight: 600;
    }
    div.stButton > button:hover {transform: translateY(-2px); box-shadow: 0 4px 12px rgba(0, 82, 204, 0.2);}
    
    /* HTML 按钮 */
    .custom-wa-btn {
        display: block; padding: 8px; color: white !important; background: #25D366; 
        border-radius: 6px; text-decoration: none; text-align: center; font-weight: 600; margin-bottom: 5px;
    }
    .custom-tg-btn {
        display: block; padding: 8px; color: white !important; background: #0088cc; 
        border-radius: 6px; text-decoration: none; text-align: center; font-weight: 600;
    }
    .custom-disabled {
        display: block; padding: 8px; color: #666 !important; background: #e0e0e0; 
        border-radius: 6px; text-decoration: none; text-align: center; cursor: not-allowed; margin-bottom: 5px;
    }
</style>
""", unsafe_allow_html=True)

# === Session 初始化 ===
if 'logged_in' not in st.session_state:
    st.session_state['logged_in'] = False
if 'username' not in st.session_state:
    st.session_state['username'] = ''

# === 核心工具函数 ===
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

def extract_all_numbers(row_series):
    txt = " ".join([str(val) for val in row_series if pd.notna(val)])
    matches = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', txt)
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
    with st.status("📡 Verifying Numbers...", expanded=True) as status:
        status.write(f"Uploading {len(phone_list)} numbers...")
        files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
        try:
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, timeout=30, verify=False)
            if resp.status_code != 200: status.update(label="❌ Upload Failed", state="error"); return set()
            task_id = resp.json().get("task_id")
        except: status.update(label="❌ Connection Failed", state="error"); return set()

        status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
        result_url = None
        for i in range(40):
            try:
                time.sleep(3)
                poll = requests.get(status_url, headers=headers, params={'user_id': user_id}, timeout=30, verify=False)
                if poll.status_code == 200 and poll.json().get("status") in ["exported", "completed"]:
                    result_url = poll.json().get("result_url"); break
            except: pass
        
        if not result_url: status.update(label="❌ Verification Timeout (Showing all numbers)", state="error"); return set(phone_list)
        
        valid = set()
        try:
            f = requests.get(result_url, verify=False)
            if f.status_code == 200:
                try: df = pd.read_excel(io.BytesIO(f.content))
                except: df = pd.read_csv(io.BytesIO(f.content))
                df.columns = [c.lower() for c in df.columns]
                for _, r in df.iterrows():
                    ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                    nm = re.sub(r'\D', '', str(r.get('number') or r.get('phone') or ''))
                    if "yes" in ws or "valid" in ws: valid.add(nm)
                status.update(label=f"✅ Verified: {len(valid)} active numbers", state="complete")
        except: pass
    return valid

def get_ai_message(client, s_name, s_link, web, rep):
    info = f"Link: {s_link}\nInfo: {web}"
    prompt = f"""
    Role: Sales Manager at "988 Group" (China). Sender: "{rep}". Target: "{s_name}".
    Context: 988 Group = Sourcing + Logistics (China->Russia).
    Source: {info}
    Task: Polite Russian WhatsApp intro. <50 words.
    Structure:
    1. "Здравствуйте, [Name]! Меня зовут {rep} (988 Group)."
    2. "Saw your store..."
    3. "We supply [Niche] + shipping to Russia."
    4. "Catalog?"
    """
    try:
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user", "content":prompt}], temperature=0.7, max_tokens=250)
        return res.choices[0].message.content.strip()
    except: return f"Здравствуйте, {s_name}! Меня зовут {rep} (988 Group)."

# ==========================================
# 🔐 登录逻辑
# ==========================================
if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        if os.path.exists("logo.png"): st.image("logo.png", use_container_width=True)
        st.markdown("<h3 style='text-align: center; color:#666;'>Log in to Dashboard</h3>", unsafe_allow_html=True)
        
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Sign In"):
                user = login_user(u, p)
                if user:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = u
                    st.session_state['role'] = user[0]
                    st.session_state['real_name'] = user[1]
                    st.rerun()
                else:
                    st.error("Invalid credentials")
    st.stop()

# ==========================================
# 🏢 已登录界面
# ==========================================

# 读取 Secrets
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except:
    CN_USER = ""; CN_KEY = ""; OPENAI_KEY = ""

# 侧边栏
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=160)
    st.markdown(f"**👤 {st.session_state['real_name']}**")
    st.caption(f"Role: {st.session_state['role'].upper()}")
    
    menu = st.radio("Menu", ["🚀 New Task", "📂 History", "📊 Dashboard"] if st.session_state['role'] == 'admin' else ["🚀 New Task", "📂 History"])
    
    st.markdown("---")
    if st.button("Logout"):
        st.session_state['logged_in'] = False
        st.rerun()
        
    # 隐藏的重置按钮 (仅供紧急调试)
    with st.expander("⚠️ Danger Zone"):
        if st.button("Reset Database"):
            if os.path.exists(DB_FILE):
                os.remove(DB_FILE)
                st.success("Database deleted. Please refresh page.")

# --- 1. 新任务 ---
if "New Task" in str(menu):
    st.title("🚀 New Task")
    
    uploaded_file = st.file_uploader("Upload Excel/CSV", type=['xlsx', 'csv'])
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
            if not OPENAI_KEY: st.error("No OpenAI Key"); st.stop()
            client = OpenAI(api_key=OPENAI_KEY)
            
            # 提取
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
            
            if not all_raw: st.error("No numbers found"); st.stop()
            
            # 验号
            valid_set = process_checknumber_task(list(all_raw), CN_KEY, CN_USER)
            
            # 结果
            final_data = []
            # 只要有提取到的号码，就生成 TG 链接，不管 WA 是否有效
            target_phones = sorted(list(all_raw))
            
            processed = set()
            ai_bar = st.progress(0)
            
            for idx, p in enumerate(target_phones):
                indices = row_map[p]
                for rid in indices:
                    if rid in processed: continue
                    processed.add(rid)
                    
                    row = df.iloc[rid]
                    s_name = row[shop_col]
                    s_link = row[link_col]
                    
                    web = extract_web_content(s_link)
                    msg = get_ai_message(client, s_name, s_link, web, rep_name)
                    
                    is_wa = p in valid_set
                    # 修正：TG 链接不预填文案
                    tg_link = f"https://t.me/+{p}"
                    wa_link = f"https://wa.me/{p}?text={urllib.parse.quote(msg)}"
                    
                    final_data.append({
                        "Shop": s_name, "Phone": p, "Message": msg,
                        "WA": wa_link, "TG": tg_link, "Is_WA": is_wa
                    })
                ai_bar.progress((idx+1)/len(target_phones))
                
            # 存档
            save_history_record(st.session_state['username'], uploaded_file.name, len(all_raw), len(valid_set), pd.DataFrame(final_data))
            
            # 展示
            st.success("✅ Completed!")
            for item in final_data:
                with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                    st.write(item['Message'])
                    c_a, c_b = st.columns(2)
                    with c_a:
                        if item['Is_WA']:
                            st.markdown(f'<a href="{item["WA"]}" target="_blank" class="custom-wa-btn">🟢 WhatsApp</a>', unsafe_allow_html=True)
                        else:
                            st.markdown('<a class="custom-disabled">⚪ No WhatsApp</a>', unsafe_allow_html=True)
                    with c_b:
                        st.markdown(f'<a href="{item["TG"]}" target="_blank" class="custom-tg-btn">🔵 Telegram</a>', unsafe_allow_html=True)

# --- 2. 历史记录 ---
elif "History" in str(menu):
    st.title("📂 History")
    df_hist = get_user_history(st.session_state['username'])
    
    if not df_hist.empty:
        for _, row in df_hist.iterrows():
            with st.expander(f"📅 {row['timestamp']} - {row['upload_filename']}"):
                st.info(f"Total: {row['total_rows']} | Valid WA: {row['valid_wa']}")
                file_data = get_history_file(row['id'])
                if file_data:
                    st.download_button("📥 Download CSV", file_data[0], f"history_{row['id']}.csv", "text/csv")
    else:
        st.info("No history yet.")

# --- 3. 仪表盘 ---
elif "Dashboard" in str(menu):
    st.title("📊 Admin Dashboard")
    df_all = get_user_history('admin')
    
    if not df_all.empty:
        c1, c2 = st.columns(2)
        c1.metric("Total Tasks", len(df_all))
        c2.metric("Total Valid Leads", df_all['valid_wa'].sum())
        
        st.subheader("Leaderboard")
        # 修复 groupby 报错：先fillna防止空值
        if 'real_name' in df_all.columns:
            perf = df_all.fillna("Unknown").groupby('real_name')[['total_rows', 'valid_wa']].sum().reset_index()
            st.bar_chart(perf.set_index('real_name')['valid_wa'])
            st.dataframe(df_all, use_container_width=True)
        else:
            st.warning("Data schema mismatch. Reset DB.")
    else:
        st.info("No data.")
        
    st.divider()
    st.subheader("Add User")
    with st.form("add_user"):
        u = st.text_input("New Username")
        p = st.text_input("New Password", type="password")
        n = st.text_input("Real Name")
        if st.form_submit_button("Create"):
            if create_user(u, p, n): st.success("Created!")
            else: st.error("Exists!")
