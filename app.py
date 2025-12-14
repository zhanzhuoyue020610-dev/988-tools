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
    "LOW_STOCK_THRESHOLD": 300,
    "POINTS_PER_TASK": 10
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
        supabase.table('users').insert({"username": u, "password": pwd, "role": role, "real_name": n, "points": 0}).execute()
        return True
    except: return False

def add_user_points(username, amount):
    if not supabase: return
    try:
        user = supabase.table('users').select('points').eq('username', username).single().execute()
        current_points = user.data.get('points', 0) or 0
        supabase.table('users').update({'points': current_points + amount}).eq('username', username).execute()
    except Exception as e: print(e)

def get_user_points(username):
    if not supabase: return 0
    try:
        res = supabase.table('users').select('points').eq('username', username).single().execute()
        return res.data.get('points', 0) or 0
    except: return 0

# --- 🔥 修改：暖心文案生成 ---
def get_daily_motivation(client):
    if "motivation_quote" not in st.session_state:
        try:
            # 修改提示词为“温暖治愈”
            prompt = "你是专业的职场心理咨询师。请生成一句温暖、治愈、给人内心力量的中文短句，不超过25个字。不要带引号，语气要平和高级。"
            res = client.chat.completions.create(
                model="gpt-4o", 
                messages=[{"role":"user","content":prompt}],
                temperature=0.9, max_tokens=60
            )
            st.session_state["motivation_quote"] = res.choices[0].message.content
        except:
            st.session_state["motivation_quote"] = "心有繁星，沐光而行。"
    return st.session_state["motivation_quote"]

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
        return stats.sort_index(ascending=False)
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
            .limit(1000)\
            .execute()
        return total_claimed, total_done, pd.DataFrame(res_list.data)
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
        res = supabase.table('leads').update({'assigned_to': None, 'assigned_at': None}).lt('assigned_at', today_str).eq('is_contacted', False).execute()
        return len(res.data)
    except: return 0

def delete_user_and_recycle(username):
    if not supabase: return False
    try:
        supabase.table('leads').update({'assigned_to': None, 'assigned_at': None, 'is_contacted': False}).eq('assigned_to', username).eq('is_contacted', False).execute()
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

def mark_lead_complete_secure(lead_id, username):
    if not supabase: return
    now_iso = datetime.now().isoformat()
    supabase.table('leads').update({'is_contacted': True, 'completed_at': now_iso}).eq('id', lead_id).execute()
    add_user_points(username, CONFIG["POINTS_PER_TASK"])

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
# 🎨 UI 主题 (Pure Luxury & Clean)
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="⚫")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');

    :root {
        --bg-color: #131314;           
        --surface-color: #1e1f20;      
        --input-bg: #282a2c;           
        --text-primary: #e3e3e3;       
        --text-secondary: #8e8e8e;     
        --accent-gradient: linear-gradient(90deg, #4b90ff, #ff5546); 
        --btn-primary: #1f6feb;        
        --btn-hover: #3b82f6;          
        --btn-text: #ffffff;           
    }

    .stApp { background-color: var(--bg-color) !important; color: var(--text-primary) !important; font-family: 'Inter', 'Noto Sans SC', sans-serif !important; }
    header { visibility: hidden !important; } 
    
    /* 核心：渐变流光文字 (保留给“你好”和Logo) */
    .gemini-header {
        font-weight: 600; font-size: 28px;
        background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        letter-spacing: 1px; margin-bottom: 5px;
    }
    
    /* 暖心文案样式 - 极简灰 */
    .warm-quote {
        font-size: 13px;
        color: #8e8e8e;
        letter-spacing: 0.5px;
        margin-bottom: 25px;
        font-style: normal;
    }

    /* 积分胶囊 - 纯文字，无图标 */
    .points-pill {
        background-color: rgba(255, 255, 255, 0.05);
        color: #e3e3e3;
        border: 1px solid rgba(255, 255, 255, 0.1);
        padding: 6px 16px;
        border-radius: 4px;
        font-size: 13px;
        font-family: 'Inter', monospace;
        letter-spacing: 0.5px;
    }

    div[data-testid="stRadio"] > div { background-color: var(--surface-color); border: none; padding: 6px; border-radius: 50px; gap: 0px; display: inline-flex; }
    div[data-testid="stRadio"] label { background-color: transparent !important; color: var(--text-secondary) !important; padding: 8px 24px; border-radius: 40px; font-size: 15px; transition: all 0.3s ease; border: none; }
    div[data-testid="stRadio"] label[data-checked="true"] { background-color: #3c4043 !important; color: #ffffff !important; font-weight: 500; }

    div[data-testid="stExpander"], div[data-testid="stForm"], div.stDataFrame { background-color: var(--surface-color) !important; border: none !important; border-radius: 12px; padding: 10px; }
    div[data-testid="stExpander"] details { border: none !important; }
    
    /* 按钮 - 深蓝实色 */
    button { color: var(--btn-text) !important; }
    div.stButton > button, div.stFormSubmitButton > button { background-color: var(--btn-primary) !important; color: var(--btn-text) !important; border: none !important; border-radius: 50px !important; padding: 10px 24px !important; font-weight: 500; letter-spacing: 1px; transition: all 0.2s ease; }
    div.stButton > button:hover, div.stFormSubmitButton > button:hover { background-color: var(--btn-hover) !important; transform: translateY(-1px); }

    [data-testid="stFileUploader"] button { background-color: #303134 !important; color: #e3e3e3 !important; border: 1px solid #444746 !important; }
    [data-testid="stFileUploader"] button:hover { background-color: #444746 !important; border-color: #5e5e5e !important; }
    [data-testid="stFileUploader"] div { color: #8e8e8e !important; }

    div[data-baseweb="input"], div[data-baseweb="select"] { background-color: var(--input-bg) !important; border: 1px solid #3c4043 !important; border-radius: 8px; }
    div[data-baseweb="input"]:focus-within { border-color: #4b90ff !important; }
    input[type="text"], input[type="password"], input[type="number"] { color: #ffffff !important; background-color: transparent !important; }
    ::placeholder { color: #5f6368 !important; }

    div[data-testid="stDataFrame"] div[role="grid"] { background-color: var(--surface-color) !important; color: var(--text-secondary); }
    .stProgress > div > div > div > div { background: var(--accent-gradient) !important; height: 4px !important; border-radius: 10px; }
    
    /* 纯色圆点状态 */
    .status-dot { height: 6px; width: 6px; border-radius: 50%; display: inline-block; margin-right: 8px; vertical-align: middle;}
    .dot-green { background-color: #6dd58c; }
    .dot-red { background-color: #ff5f56; }
    
    h1, h2, h3, h4 { color: #ffffff !important; font-weight: 500 !important;}
    p, span, div, label { color: #c4c7c5 !important; }
    .stCaption { color: #8e8e8e !important; }

</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 登录页
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        st.markdown("<br><br><br><br>", unsafe_allow_html=True)
        st.markdown('<div class="gemini-header" style="text-align:center;">988 GROUP CRM</div>', unsafe_allow_html=True)
        st.markdown('<div class="warm-quote" style="text-align:center;">专业 · 高效 · 全球化</div>', unsafe_allow_html=True)
        
        with st.form("login", border=False):
            u = st.text_input("账号", placeholder="请输入用户名")
            p = st.text_input("密码", type="password", placeholder="请输入密码")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("登 录"):
                user = login_user(u, p)
                if user:
                    st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                    st.rerun()
                else: st.error("账号或密码错误")
    st.stop()

# ==========================================
# 🚀 内部主界面
# ==========================================
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

# 顶部栏 (Gradient Header + Warm Quote)
client = OpenAI(api_key=OPENAI_KEY)
quote = get_daily_motivation(client)
points = get_user_points(st.session_state['username'])

# 布局：极简顶部
c_title, c_user = st.columns([4, 2])

with c_title:
    # 核心：保留用户喜欢的渐变打招呼
    st.markdown(f'<div class="gemini-header">你好, {st.session_state["real_name"]}</div>', unsafe_allow_html=True)
    # 暖心文案 (放在下方，极简灰字，不抢视觉)
    st.markdown(f'<div class="warm-quote">{quote}</div>', unsafe_allow_html=True)

with c_user:
    # 右侧：积分 + 退出，极简胶囊风格
    st.markdown(f"""
    <div style="text-align:right; margin-top:5px;">
        <span class="points-pill">积分: {points}</span>
        <span style="color:#3c4043; margin:0 10px;">|</span>
        <span style="font-size:14px; color:#e3e3e3;">{st.session_state['role'].upper()}</span>
    </div>
    """, unsafe_allow_html=True)
    # 退出按钮在下方，利用 streamlit 的 button
    c_null, c_out = st.columns([3, 1])
    with c_out:
        if st.button("退出", key="logout"): st.session_state.clear(); st.rerun()

st.divider()

# 导航
if st.session_state['role'] == 'admin':
    menu_map = {"System": "系统监控", "Logs": "活动日志", "Team": "团队管理", "Import": "批量进货"}
    menu_options = ["System", "Logs", "Team", "Import"]
else:
    menu_map = {"Workbench": "销售工作台"}
    menu_options = ["Workbench"]

selected_nav = st.radio("导航菜单", menu_options, format_func=lambda x: menu_map.get(x, x), horizontal=True, label_visibility="collapsed")
st.markdown("<br>", unsafe_allow_html=True)

# --- 🖥️ SYSTEM MONITOR (Admin) ---
if selected_nav == "System" and st.session_state['role'] == 'admin':
    st.markdown("#### 系统健康状态")
    health = check_api_health(CN_USER, CN_KEY, OPENAI_KEY)
    
    k1, k2, k3 = st.columns(3)
    def status_pill(title, is_active, detail):
        dot = "dot-green" if is_active else "dot-red"
        text = "运行正常" if is_active else "连接异常"
        st.markdown(f"""<div style="background-color:#1e1f20; padding:20px; border-radius:16px;"><div style="font-size:14px; color:#c4c7c5;">{title}</div><div style="margin-top:10px; font-size:16px; color:white; font-weight:500;"><span class="status-dot {dot}"></span>{text}</div><div style="font-size:12px; color:#8e8e8e; margin-top:5px;">{detail}</div></div>""", unsafe_allow_html=True)

    with k1: status_pill("云数据库", health['supabase'], "Supabase")
    with k2: status_pill("验证接口", health['checknumber'], "CheckNumber")
    with k3: status_pill("AI 引擎", health['openai'], "OpenAI GPT-4")
    
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 沙盒模拟")
    sb_file = st.file_uploader("上传测试文件", type=['csv', 'xlsx'])
    if sb_file and st.button("开始模拟"):
        try:
            if sb_file.name.endswith('.csv'): df = pd.read_csv(sb_file)
            else: df = pd.read_excel(sb_file)
            st.caption(f"读取到 {len(df)} 行，正在处理...")
            client = OpenAI(api_key=OPENAI_KEY)
            with st.status("正在运行流水线...", expanded=True) as s:
                s.write("提取号码中..."); nums = []
                for _, r in df.head(5).iterrows(): nums.extend(extract_all_numbers(r))
                s.write(f"提取结果: {nums}")
                s.write("验证号码中..."); res = process_checknumber_task(nums, CN_KEY, CN_USER)
                valid = [p for p in nums if res.get(p)=='valid']; s.write(f"有效号码: {valid}")
                if valid:
                    s.write("生成话术中..."); msg = get_ai_message_sniper(client, "测试", "http://test.com", "管理员")
                    s.write(f"话术演示: {msg}")
                s.update(label="模拟完成", state="complete")
        except Exception as e: st.error(str(e))

# --- 💼 WORKBENCH (Sales) ---
elif selected_nav == "Workbench":
    my_leads = get_todays_leads(st.session_state['username'])
    total, curr = CONFIG["DAILY_QUOTA"], len(my_leads)
    
    c_stat, c_action = st.columns([2, 1])
    with c_stat:
        done = sum(1 for x in my_leads if x.get('is_contacted'))
        st.caption(f"今日进度: {done} / {total}")
        st.progress(min(done/total, 1.0))
        
    with c_action:
        st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
        if curr < total:
            if st.button(f"领取任务 (余 {total-curr})"):
                _, status = claim_daily_tasks(st.session_state['username'])
                if status=="empty": st.error("公池已空")
                else: st.rerun()
        else: st.info("任务已领满")

    st.markdown("#### 任务中心")
    # 纯文字 Tab，无 Emoji
    tabs = st.tabs(["待办事项", "已完成"])
    
    with tabs[0]:
        todos = [x for x in my_leads if not x.get('is_contacted')]
        if not todos: st.caption("暂无待办任务")
        for item in todos:
            with st.expander(f"{item['shop_name']}", expanded=True):
                st.write(item['ai_message'])
                c1, c2 = st.columns(2)
                key = f"clk_{item['id']}"
                if key not in st.session_state: st.session_state[key] = False
                if not st.session_state[key]:
                    if c1.button("获取链接", key=f"btn_{item['id']}"): st.session_state[key] = True; st.rerun()
                    c2.button("标记完成", disabled=True, key=f"dis_{item['id']}")
                else:
                    url = f"https://wa.me/{item['phone']}?text={urllib.parse.quote(item['ai_message'])}"
                    c1.markdown(f"<a href='{url}' target='_blank' style='display:block;text-align:center;background:#1e1f20;color:#e3e3e3;padding:10px;border-radius:20px;text-decoration:none;font-size:14px;'>跳转 WhatsApp ↗</a>", unsafe_allow_html=True)
                    if c2.button("确认完成", key=f"fin_{item['id']}"):
                        mark_lead_complete_secure(item['id'], st.session_state['username'])
                        st.toast(f"积分 +{CONFIG['POINTS_PER_TASK']}")
                        del st.session_state[key]; time.sleep(1); st.rerun()

    with tabs[1]:
        dones = [x for x in my_leads if x.get('is_contacted')]
        if dones:
            df = pd.DataFrame(dones)
            df['time'] = pd.to_datetime(df['completed_at']).dt.strftime('%H:%M')
            st.dataframe(df[['shop_name', 'phone', 'time']].rename(columns={'shop_name':'店铺','phone':'电话','time':'时间'}), use_container_width=True)
        else: st.caption("暂无完成记录")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 全量历史记录")
    _, _, df_history = get_user_historical_data(st.session_state['username'])
    if not df_history.empty:
        st.dataframe(
            df_history,
            column_config={
                "shop_name": "客户店铺",
                "phone": "联系电话",
                "shop_link": st.column_config.LinkColumn("店铺链接"),
                "completed_at": st.column_config.DatetimeColumn("处理时间", format="YYYY-MM-DD HH:mm")
            },
            use_container_width=True
        )
    else: st.caption("暂无历史记录")

# --- 📅 LOGS (Admin) ---
elif selected_nav == "Logs":
    st.markdown("#### 活动日志监控")
    d = st.date_input("选择日期", date.today())
    if d:
        c, f = get_daily_logs(d.isoformat())
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("领取记录")
            if not c.empty: st.dataframe(c, use_container_width=True)
            else: st.caption("无数据")
        with col2:
            st.markdown("完成记录")
            if not f.empty: st.dataframe(f, use_container_width=True)
            else: st.caption("无数据")

# --- 👥 TEAM (Admin) ---
elif selected_nav == "Team":
    users = pd.DataFrame(supabase.table('users').select("*").execute().data)
    c1, c2 = st.columns([1, 2])
    with c1:
        u = st.radio("员工列表", users['username'].tolist(), label_visibility="collapsed")
        st.markdown("---")
        with st.expander("新增员工"):
            with st.form("new"):
                nu = st.text_input("用户名"); np = st.text_input("密码", type="password"); nn = st.text_input("真实姓名")
                if st.form_submit_button("创建账号"): create_user(nu, np, nn); st.rerun()
    with c2:
        if u:
            info = users[users['username']==u].iloc[0]
            tc, td, hist = get_user_historical_data(u)
            perf = get_user_daily_performance(u)
            st.markdown(f"### {info['real_name']}")
            st.caption(f"账号: {info['username']} | 积分: {info.get('points', 0)} | 最后上线: {str(info.get('last_seen','-'))[:16]}")
            k1, k2 = st.columns(2)
            k1.metric("历史领取", tc); k2.metric("历史完成", td)
            t1, t2, t3 = st.tabs(["每日绩效", "详细清单", "账号设置"])
            with t1:
                if not perf.empty: st.bar_chart(perf); st.dataframe(perf, use_container_width=True)
                else: st.caption("暂无数据")
            with t2:
                if not hist.empty: st.dataframe(hist, use_container_width=True)
                else: st.caption("暂无数据")
            with t3:
                if st.button("删除账号并回收任务"): delete_user_and_recycle(u); st.rerun()

# --- 📥 IMPORT (Admin) ---
elif selected_nav == "Import":
    pool = get_public_pool_count()
    if pool < CONFIG["LOW_STOCK_THRESHOLD"]: st.error(f"库存告急：仅剩 {pool} 个客户")
    else: st.metric("公共池库存", pool)
    
    with st.expander("每日归仓工具"):
        if st.button("回收过期任务"):
            n = recycle_expired_tasks(); st.success(f"已回收 {n} 个")
            
    st.markdown("---")
    st.markdown("#### 批量进货")
    f = st.file_uploader("上传文件", type=['csv', 'xlsx'])
    if f:
        df = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
        st.caption(f"解析到 {len(df)} 行数据")
        if st.button("开始清洗入库"):
            client = OpenAI(api_key=OPENAI_KEY)
            with st.status("正在处理...", expanded=True) as s:
                df=df.astype(str); phones = set(); rmap = {}
                for i, r in df.iterrows():
                    for p in extract_all_numbers(r): phones.add(p); rmap.setdefault(p, []).append(i)
                s.write(f"提取到 {len(phones)} 个独立号码")
                plist = list(phones); valid = []
                for i in range(0, len(plist), 500):
                    batch = plist[i:i+500]; res = process_checknumber_task(batch, CN_KEY, CN_USER)
                    valid.extend([p for p in batch if res.get(p)=='valid']); time.sleep(1)
                s.write(f"有效号码 {len(valid)} 个，生成话术中...")
                rows = []; bar = st.progress(0)
                for idx, p in enumerate(valid):
                    r = df.iloc[rmap[p][0]]; lnk = r.iloc[0]; shp = r.iloc[1] if len(r)>1 else "Shop"
                    msg = get_ai_message_sniper(client, shp, lnk, "Sales")
                    rows.append({"Shop":shp, "Link":lnk, "Phone":p, "Msg":msg})
                    if len(rows)>=100: admin_bulk_upload_to_pool(rows); rows=[]
                    bar.progress((idx+1)/len(valid))
                if rows: admin_bulk_upload_to_pool(rows)
                s.update(label="入库完成", state="complete")
            time.sleep(1); st.rerun()
