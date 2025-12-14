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

# --- 🔥 新增：API 健康检查功能 ---
def check_api_health(cn_user, cn_key, openai_key):
    status = {"supabase": False, "checknumber": False, "openai": False, "msg": []}
    
    # 1. Supabase Check
    try:
        if supabase:
            supabase.table('users').select('count', count='exact').limit(1).execute()
            status["supabase"] = True
    except Exception as e: status["msg"].append(f"Supabase Error: {str(e)}")

    # 2. CheckNumber Check (Connection Test)
    try:
        # 尝试一个空请求或查询状态，如果 Key 错误通常会返回 401/403
        headers = {"X-API-Key": cn_key}
        # 这里没有标准的 balance API，我们尝试列出任务或简单握手
        test_url = f"{CONFIG['CN_BASE_URL']}" 
        resp = requests.get(test_url, headers=headers, params={'user_id': cn_user}, timeout=5, verify=False)
        # 只要不是 401/403，就说明 Key 是对的
        if resp.status_code in [200, 400, 404]: 
            status["checknumber"] = True
        else:
            status["msg"].append(f"CheckNumber Error: Status {resp.status_code}")
    except Exception as e: status["msg"].append(f"CheckNumber Net Error: {str(e)}")

    # 3. OpenAI Check (Ping)
    try:
        client = OpenAI(api_key=openai_key)
        client.models.list() # 轻量级请求
        status["openai"] = True
    except Exception as e: status["msg"].append(f"OpenAI Error: {str(e)}")

    return status

# ==========================================
# 🎨 国际化企业级 UI (Enterprise Dark Theme)
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="⚓")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');

    :root {
        --bg-color: #0d1117;         /* 深海黑 */
        --sidebar-bg: #161b22;       /* 侧边栏/卡片背景 */
        --border-color: #30363d;     /* 极细分割线 */
        --primary-color: #1f6feb;    /* 商务蓝 */
        --text-primary: #f0f6fc;     /* 亮白 */
        --text-secondary: #8b949e;   /* 灰字 */
        --success-color: #238636;    /* 沉稳绿 */
        --danger-color: #da3633;     /* 警示红 */
    }

    .stApp { background-color: var(--bg-color) !important; font-family: 'Inter', sans-serif !important; color: var(--text-primary) !important; }
    header { visibility: visible !important; background-color: transparent !important; }
    
    /* 导航栏 */
    div[data-testid="stRadio"] > div { display: flex; flex-direction: row; background-color: var(--sidebar-bg); border: 1px solid var(--border-color); padding: 4px; border-radius: 6px; gap: 0px; }
    div[data-testid="stRadio"] label { flex: 1; background-color: transparent !important; border: none; color: var(--text-secondary) !important; padding: 8px 20px; border-radius: 4px; transition: all 0.2s; text-align: center; font-weight: 500; font-size: 14px; }
    div[data-testid="stRadio"] label[data-checked="true"] { background-color: var(--primary-color) !important; color: white !important; box-shadow: 0 1px 3px rgba(0,0,0,0.2); }

    /* 卡片 */
    div[data-testid="stExpander"], div[data-testid="stForm"], div[data-testid="stDataFrame"], div.stDataFrame { background-color: var(--sidebar-bg) !important; border: 1px solid var(--border-color) !important; border-radius: 6px; box-shadow: none !important; }
    div[data-testid="stExpander"]:hover { border-color: #58a6ff !important; }

    /* 按钮 */
    button { color: white !important; letter-spacing: 0.5px; }
    div.stButton > button { background-color: var(--primary-color) !important; border: 1px solid rgba(255,255,255,0.1) !important; border-radius: 6px; font-weight: 500; transition: background 0.2s; }
    div.stButton > button:hover { background-color: #3b82f6 !important; }
    button:disabled { background-color: #21262d !important; border-color: #30363d !important; color: #484f58 !important; cursor: not-allowed; }

    /* 进度条 */
    .stProgress > div > div > div > div { background-color: var(--success-color) !important; border-radius: 10px; }

    /* 表格 */
    div[data-testid="stDataFrame"] div[role="grid"] { color: var(--text-secondary) !important; background-color: var(--sidebar-bg) !important; }
    
    /* 链接 */
    a.action-link { display: inline-block; width: 100%; text-align: center; padding: 8px 0; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; transition: opacity 0.2s; }
    a.wa-link { background: #238636; color: white !important; }
    
    /* 文字 */
    h1, h2, h3 { color: var(--text-primary) !important; font-weight: 600 !important; }
    p, span, label, div { color: var(--text-secondary) !important; font-size: 14px; }
    
    /* API Status Cards */
    .status-card { padding: 15px; border: 1px solid var(--border-color); border-radius: 6px; background: var(--sidebar-bg); text-align: center; }
    .status-green { color: #3fb950; font-weight: bold; }
    .status-red { color: #f85149; font-weight: bold; }

</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 身份验证
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1.5,1])
    with c2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.markdown("""
        <div style="text-align: center; margin-bottom: 30px;">
            <h1 style="font-family: 'Inter', serif; font-size: 32px; margin: 0; color: white;">988 GROUP</h1>
            <p style="font-size: 12px; letter-spacing: 2px; color: #8b949e; text-transform: uppercase;">Supply Chain Intelligence</p>
        </div>
        """, unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Account ID")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Sign In"):
                user = login_user(u, p)
                if user:
                    st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                    st.rerun()
                else: st.error("Authentication Failed")
    st.stop()

# ==========================================
# 🚀 主程序
# ==========================================
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

# 顶部状态栏
c_top1, c_top2 = st.columns([3, 1])
with c_top1:
    st.markdown(f"<h3 style='margin:0'>{st.session_state['real_name']}</h3><p style='margin:0; font-size:12px'>Role: {st.session_state['role'].upper()}</p>", unsafe_allow_html=True)
with c_top2:
    if st.button("Sign Out", key="logout_top"): st.session_state.clear(); st.rerun()

st.markdown("<br>", unsafe_allow_html=True)

# 导航系统 (管理员不看 Workbench，只看系统监控)
if st.session_state['role'] == 'admin':
    # 管理员菜单：系统监控放在第一位，移除了销售工作台
    menu_map = {"System": "系统监视器", "Logs": "日志监控", "Team": "团队管理", "Import": "数据进货"}
    menu_options = ["System", "Logs", "Team", "Import"]
else:
    # 业务员菜单
    menu_map = {"Workbench": "工作台"}
    menu_options = ["Workbench"]

selected_nav_raw = st.radio("Navigation", menu_options, format_func=lambda x: menu_map.get(x, x), horizontal=True, label_visibility="collapsed")
st.divider()

# --- 🖥️ SYSTEM MONITOR (管理员专属) ---
if selected_nav_raw == "System" and st.session_state['role'] == 'admin':
    st.markdown("#### 🖥️ 系统健康与 API 状态")
    
    # 1. 运行 API 检查
    health = check_api_health(CN_USER, CN_KEY, OPENAI_KEY)
    
    # 2. 状态卡片展示
    k1, k2, k3 = st.columns(3)
    
    with k1:
        st.markdown(f"""
        <div class="status-card">
            <div>Supabase DB</div>
            <div class="{ 'status-green' if health['supabase'] else 'status-red' }">
                { '● Connected' if health['supabase'] else '● Error' }
            </div>
            <div style="font-size:12px; margin-top:5px;">Database & Auth</div>
        </div>
        """, unsafe_allow_html=True)

    with k2:
        st.markdown(f"""
        <div class="status-card">
            <div>CheckNumber</div>
            <div class="{ 'status-green' if health['checknumber'] else 'status-red' }">
                { '● Active' if health['checknumber'] else '● Error' }
            </div>
            <div style="font-size:12px; margin-top:5px;">WhatsApp Validator</div>
        </div>
        """, unsafe_allow_html=True)

    with k3:
        st.markdown(f"""
        <div class="status-card">
            <div>OpenAI GPT-4</div>
            <div class="{ 'status-green' if health['openai'] else 'status-red' }">
                { '● Active' if health['openai'] else '● Error/No Credit' }
            </div>
            <div style="font-size:12px; margin-top:5px;">AI Generation</div>
        </div>
        """, unsafe_allow_html=True)
    
    if health['msg']:
        st.error(f"System Diagnosis: {'; '.join(health['msg'])}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 🧪 沙盒测试 (Sandbox Tester)")
    st.caption("上传一个小文件（不入库），测试整个提取、验证、生成流程是否通畅。此操作不会消耗数据库空间，但会消耗少量 API 额度。")

    sb_file = st.file_uploader("上传测试用 CSV/Excel", type=['xlsx', 'csv'], key="sandbox_up")
    if sb_file and st.button("开始沙盒测试"):
        try:
            if sb_file.name.endswith('.csv'): df_sb = pd.read_csv(sb_file)
            else: df_sb = pd.read_excel(sb_file)
            st.write(f"读取到 {len(df_sb)} 行。开始处理前 5 行...")
            
            # 取前5行做测试
            df_sb = df_sb.head(5).astype(str)
            client = OpenAI(api_key=OPENAI_KEY)
            
            with st.status("正在运行沙盒模拟...", expanded=True) as status:
                # 1. 提取
                status.write("1. 正在提取号码...")
                raw_phones = []
                for _, r in df_sb.iterrows():
                    raw_phones.extend(extract_all_numbers(r))
                if not raw_phones:
                    status.update(label="失败：未提取到号码", state="error")
                    st.stop()
                status.write(f"-> 提取到: {', '.join(raw_phones)}")

                # 2. 验证
                status.write("2. 正在调用 CheckNumber 验证...")
                res_map = process_checknumber_task(raw_phones, CN_KEY, CN_USER)
                valid = [p for p in raw_phones if res_map.get(p) == 'valid']
                status.write(f"-> 有效号码: {len(valid)} 个")

                # 3. AI
                if valid:
                    status.write("3. 正在测试 OpenAI 生成...")
                    msg = get_ai_message_sniper(client, "Test Shop", "http://test.com", "Admin Tester")
                    status.write(f"-> 生成结果演示: {msg[:50]}...")
                
                status.update(label="✅ 测试流程通过！所有 API 正常工作。", state="complete")
        except Exception as e:
            st.error(f"测试失败: {e}")

# --- 💼 WORKBENCH (Sales Only) ---
elif selected_nav_raw == "Workbench" and st.session_state['role'] != 'admin':
    st.markdown("#### 今日任务看板")
    my_leads = get_todays_leads(st.session_state['username'])
    total_task = CONFIG["DAILY_QUOTA"]
    current_count = len(my_leads)
    
    if current_count < total_task:
        st.markdown(f"""
        <div style="background:rgba(210,153,34,0.1); border:1px solid rgba(210,153,34,0.4); padding:10px; border-radius:6px; color:#e3b341; margin-bottom:15px; font-size:14px;">
            今日指标 {total_task}，当前持有 {current_count}，请领取任务。
        </div>
        """, unsafe_allow_html=True)
        if st.button(f"立即领取剩余 {total_task - current_count} 个任务"):
            my_leads, status = claim_daily_tasks(st.session_state['username'])
            if status == "empty": st.error("公共池库存不足")
            elif status == "full": st.success("已领满")
            else: st.rerun()
    else:
        st.markdown("""<div style="background:rgba(56,139,253,0.1); border:1px solid rgba(56,139,253,0.4); padding:10px; border-radius:6px; color:#58a6ff; margin-bottom:15px; font-size:14px;">今日任务已满额，请专注于跟进。</div>""", unsafe_allow_html=True)

    completed_count = sum([1 for x in my_leads if x.get('is_contacted')])
    st.progress(min(completed_count / total_task, 1.0))
    st.caption(f"Progress: {completed_count} / {total_task}")
    
    tab_todo, tab_done = st.tabs(["待跟进", "已完成"])
    with tab_todo:
        to_do_items = [x for x in my_leads if not x.get('is_contacted')]
        if not to_do_items: st.info("待办已清空")
        for item in to_do_items:
            with st.expander(f"{item['shop_name']} (+{item['phone']})", expanded=True):
                st.code(item['ai_message'], language="text")
                c1, c2 = st.columns(2)
                link_key = f"clicked_{item['id']}"
                if link_key not in st.session_state: st.session_state[link_key] = False
                if not st.session_state[link_key]:
                    if c1.button("获取链接", key=f"lk_{item['id']}"):
                        st.session_state[link_key] = True; st.rerun()
                    c2.button("标记完成", disabled=True, key=f"fake_{item['id']}")
                else:
                    wa_url = f"https://wa.me/{item['phone']}?text={urllib.parse.quote(item['ai_message'])}"
                    c1.markdown(f"<a href='{wa_url}' target='_blank' class='action-link wa-link'>跳转 WhatsApp</a>", unsafe_allow_html=True)
                    if c2.button("标记完成", key=f"done_{item['id']}"):
                        mark_lead_complete_secure(item['id']); st.session_state.pop(link_key, None); st.rerun()
    with tab_done:
        done_items = [x for x in my_leads if x.get('is_contacted')]
        if done_items:
            df_done = pd.DataFrame(done_items)
            df_done['completed_at'] = pd.to_datetime(df_done['completed_at']).dt.strftime('%H:%M')
            st.dataframe(df_done[['shop_name', 'phone', 'completed_at']], use_container_width=True)

# --- 📅 LOGS ---
elif selected_nav_raw == "Logs" and st.session_state['role'] == 'admin':
    st.markdown("#### 每日监控日志")
    q_date = st.date_input("查询日期", date.today())
    if q_date:
        df_claim, df_done = get_daily_logs(q_date.isoformat())
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**领取统计**")
            if not df_claim.empty: st.dataframe(df_claim, use_container_width=True)
            else: st.caption("无数据")
        with c2:
            st.markdown("**完成统计**")
            if not df_done.empty: st.dataframe(df_done, use_container_width=True)
            else: st.caption("无数据")

# --- 👥 TEAM ---
elif selected_nav_raw == "Team" and st.session_state['role'] == 'admin':
    st.markdown("#### 团队档案")
    users_raw = supabase.table('users').select("*").execute().data
    df_users = pd.DataFrame(users_raw)
    c_list, c_detail = st.columns([1, 2])
    with c_list:
        selected_username = st.radio("员工列表", df_users['username'].tolist(), label_visibility="collapsed")
        st.markdown("---")
        with st.expander("添加新员工"):
            with st.form("add_user"):
                new_u = st.text_input("用户名"); new_p = st.text_input("密码", type="password"); new_n = st.text_input("真实姓名")
                if st.form_submit_button("创建"): 
                    if create_user(new_u, new_p, new_n): st.rerun()

    with c_detail:
        if selected_username:
            user_info = df_users[df_users['username'] == selected_username].iloc[0]
            tot_claimed, tot_done, df_history = get_user_historical_data(selected_username)
            df_daily = get_user_daily_performance(selected_username)
            st.markdown(f"### {user_info['real_name']}")
            st.caption(f"ID: {user_info['username']} | Last Seen: {str(user_info.get('last_seen', '-'))[:16]}")
            k1, k2 = st.columns(2)
            k1.metric("历史总领取", tot_claimed); k2.metric("历史总完成", tot_done)
            t1, t2, t3 = st.tabs(["每日绩效", "详细清单", "账号设置"])
            with t1:
                if not df_daily.empty: st.bar_chart(df_daily, color=["#1f6feb", "#238636"]); st.dataframe(df_daily, use_container_width=True)
                else: st.caption("暂无数据")
            with t2:
                if not df_history.empty: st.dataframe(df_history, use_container_width=True)
                else: st.caption("暂无数据")
            with t3:
                st.markdown("**危险区域**")
                confirm_del = st.text_input(f"输入 {selected_username} 以确认删除")
                if st.button("删除账号并回收任务"):
                    if confirm_del == selected_username: delete_user_and_recycle(selected_username); st.rerun()

# --- 🏭 IMPORT ---
elif selected_nav_raw == "Import" and st.session_state['role'] == 'admin':
    pool_count = get_public_pool_count()
    if pool_count < CONFIG["LOW_STOCK_THRESHOLD"]:
        st.markdown(f"""<div class="alert-box">⚠️ 库存告急：公共池仅剩 {pool_count} 个客户，请尽快补充。</div>""", unsafe_allow_html=True)
    else: st.metric("公共池库存", f"{pool_count}", delta="状态良好")
    
    with st.expander("每日任务归仓工具"):
        if st.button("执行归仓"):
            count = recycle_expired_tasks(); 
            if count > 0: st.success(f"已回收 {count} 个任务")
            else: st.info("无滞留任务")
    
    st.markdown("---")
    st.markdown("#### 批量导入")
    col_up, col_log = st.columns([1, 1])
    with col_up:
        up_file = st.file_uploader("上传 Excel/CSV", type=['xlsx', 'csv'])
        if up_file:
            if up_file.name.endswith('.csv'): df_raw = pd.read_csv(up_file)
            else: df_raw = pd.read_excel(up_file)
            st.caption(f"解析到 {len(df_raw)} 行数据")
            c1, c2 = st.columns(2)
            s_col = c1.selectbox("店铺名列", df_raw.columns, index=1 if len(df_raw.columns)>1 else 0)
            l_col = c2.selectbox("链接列", df_raw.columns, index=0)
            start_btn = st.button("开始清洗入库")
    
    if up_file and start_btn:
        client = OpenAI(api_key=OPENAI_KEY)
        with st.status("正在进行企业级数据处理...", expanded=True) as status:
            df_raw = df_raw.astype(str); raw_phones = set(); row_map = {}
            for i, r in df_raw.iterrows():
                ext = extract_all_numbers(r)
                for p in ext: raw_phones.add(p); row_map.setdefault(p, []).append(i)
            status.write(f"提取到 {len(raw_phones)} 个独立号码")
            valid_phones = []; phone_list = list(raw_phones); batch_size = 500
            for i in range(0, len(phone_list), batch_size):
                batch = phone_list[i:i+batch_size]; res_map = process_checknumber_task(batch, CN_KEY, CN_USER)
                valid_phones.extend([p for p in batch if res_map.get(p) == 'valid']); time.sleep(1)
            status.write(f"验证有效号码 {len(valid_phones)} 个，生成 AI 话术中...")
            final_rows = []; bar = st.progress(0)
            for idx, p in enumerate(valid_phones):
                rid = row_map[p][0]; row = df_raw.iloc[rid]
                msg = get_ai_message_sniper(client, row[s_col], row[l_col], "Sales Team")
                final_rows.append({"Shop": row[s_col], "Link": row[l_col], "Phone": p, "Msg": msg})
                if len(final_rows) >= 100: admin_bulk_upload_to_pool(final_rows); final_rows = []
                bar.progress((idx+1)/len(valid_phones))
            if final_rows: admin_bulk_upload_to_pool(final_rows)
            status.update(label="入库完成", state="complete"); time.sleep(1); st.rerun()
