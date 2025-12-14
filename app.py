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
import cloudscraper
from bs4 import BeautifulSoup 
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
    "DAILY_QUOTA": 25  # 🔥 硬性指标：每天25个
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
            # 🔥 登录成功，更新最后上线时间
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

def admin_update_user_password(username, new_password):
    """管理员强制修改密码"""
    if not supabase: return False
    try:
        pwd = hash_password(new_password)
        supabase.table('users').update({"password": pwd}).eq("username", username).execute()
        return True
    except: return False

def admin_bulk_upload_to_pool(leads_data):
    if not supabase or not leads_data: return False
    try:
        rows = []
        for item in leads_data:
            rows.append({
                "shop_name": item['Shop'], 
                "shop_link": item['Link'],
                "phone": item['Phone'], 
                "ai_message": item['Msg'], 
                "is_valid": True,
                "assigned_to": None,
                "assigned_at": None,
                "is_contacted": False
            })
        # 批量插入，分片处理防止超时
        chunk_size = 500
        for i in range(0, len(rows), chunk_size):
            supabase.table('leads').insert(rows[i:i+chunk_size]).execute()
        return True
    except Exception as e:
        print(e)
        return False

def fetch_daily_leads(username):
    today_str = date.today().isoformat()
    # 1. 查询今日已拥有的任务
    existing = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    current_count = len(existing)
    needed = CONFIG["DAILY_QUOTA"] - current_count
    
    # 2. 如果不够25个，去池子里抓
    if needed > 0:
        pool_leads = supabase.table('leads').select("id").is_('assigned_to', 'null').limit(needed).execute().data
        if pool_leads:
            ids_to_update = [x['id'] for x in pool_leads]
            supabase.table('leads').update({'assigned_to': username, 'assigned_at': today_str}).in_('id', ids_to_update).execute()
            existing = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    return existing

def mark_lead_as_contacted(lead_id):
    if not supabase: return
    supabase.table('leads').update({'is_contacted': True}).eq('id', lead_id).execute()

# --- 统计与分析函数 ---
def get_user_stats(username):
    """获取单个用户的详细统计数据"""
    if not supabase: return {}
    # 总分配
    total = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).execute().count
    # 总完成
    done = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).eq('is_contacted', True).execute().count
    # 最近7天记录
    last_7_days = (datetime.now() - timedelta(days=7)).isoformat()
    recent = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).eq('is_contacted', True).gte('assigned_at', last_7_days).execute().count
    
    return {"total": total, "done": done, "recent_7_days": recent}

def get_user_recent_leads(username, limit=10):
    """获取用户最近处理的客户列表"""
    if not supabase: return []
    res = supabase.table('leads').select('shop_name, phone, is_contacted, assigned_at').eq('assigned_to', username).order('assigned_at', desc=True).limit(limit).execute()
    return res.data

# --- Helper Functions ---
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
        
        # 轮询直到完成
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
                        # 宽松匹配
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

# ==========================================
# 🎨 UI 主题
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="⚙️")
st.markdown("""
<style>
    .stApp { background-color: #121212 !important; color: #e0e0e0 !important; }
    header { visibility: visible !important; background-color: transparent !important; }
    
    /* 进度条 */
    .stProgress > div > div > div > div { background-color: #4CAF50 !important; }
    
    /* 卡片与容器 */
    div[data-testid="stExpander"], div[data-testid="stForm"], div[data-testid="stDataFrame"] {
        background-color: #1e1e1e !important; border: 1px solid #333 !important; border-radius: 6px;
    }
    
    /* 按钮 */
    button { color: white !important; }
    div.stButton > button {
        background-color: #0078d4 !important; border: 1px solid #0078d4 !important;
        width: 100%; font-weight: bold;
    }
    
    /* 表格样式修正 */
    div[data-testid="stDataFrame"] div[role="grid"] { color: #e0e0e0 !important; }
    
    h1, h2, h3 { color: #fff !important; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 🔐 Auth
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<br><br><h2 style='text-align:center'>🚛 988 CRM 登录</h2>", unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.form_submit_button("Login"):
                user = login_user(u, p)
                if user:
                    st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                    st.rerun()
                else: st.error("Login Failed")
    st.stop()

# ==========================================
# 🚀 Main
# ==========================================
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

# Navigation
st.markdown(f"**👤 {st.session_state['real_name']}** | Role: {st.session_state['role'].upper()}")
if st.button("Logout", key="logout_top"): st.session_state.clear(); st.rerun()

# 顶部导航
menu_options = ["Workbench"]
if st.session_state['role'] == 'admin':
    menu_options = ["Workbench", "Team", "Import"]

selected_nav = st.radio("Nav", menu_options, horizontal=True, label_visibility="collapsed")
st.divider()

# --- 💼 WORKBENCH (业务员 & 管理员都可见) ---
if selected_nav == "Workbench":
    st.markdown("### 🎯 今日任务看板")
    
    # 1. 自动领任务
    my_leads = fetch_daily_leads(st.session_state['username'])
    
    total_task = CONFIG["DAILY_QUOTA"]
    completed_count = sum([1 for x in my_leads if x.get('is_contacted')])
    
    st.markdown(f"**今日硬性指标: {completed_count} / {total_task}**")
    st.progress(min(completed_count / total_task, 1.0))
    
    tab_todo, tab_done = st.tabs(["🔥 待跟进", "✅ 已完成"])
    
    with tab_todo:
        to_do_items = [x for x in my_leads if not x.get('is_contacted')]
        if not to_do_items:
            if len(my_leads) > 0: st.success("🎉 今日任务全部完成！")
            else: st.info("暂无分配任务，请等待管理员进货。")
            
        for item in to_do_items:
            with st.expander(f"🏢 {item['shop_name']} (+{item['phone']})", expanded=True):
                st.info(item['ai_message'])
                c1, c2 = st.columns(2)
                wa_url = f"https://wa.me/{item['phone']}?text={urllib.parse.quote(item['ai_message'])}"
                c1.markdown(f"<a href='{wa_url}' target='_blank' style='display:block;text-align:center;background:#25D366;color:white;padding:8px;border-radius:4px;text-decoration:none;'>WhatsApp</a>", unsafe_allow_html=True)
                if c2.button("✅ 标记完成", key=f"d_{item['id']}"):
                    mark_lead_as_contacted(item['id'])
                    st.rerun()
                    
    with tab_done:
        done_items = [x for x in my_leads if x.get('is_contacted')]
        st.table(pd.DataFrame(done_items, columns=['shop_name', 'phone', 'assigned_at']))

# --- 👥 TEAM MANAGEMENT (管理员专属) ---
elif selected_nav == "Team" and st.session_state['role'] == 'admin':
    st.markdown("### 👥 团队全景档案")
    
    # 1. 获取所有用户列表
    users_raw = supabase.table('users').select("*").execute().data
    df_users = pd.DataFrame(users_raw)
    
    # 左侧列表，右侧详情
    c_list, c_detail = st.columns([1, 2])
    
    with c_list:
        st.markdown("#### 员工列表")
        selected_username = st.radio("选择员工查看详情", df_users['username'].tolist())
        
        if st.button("➕ 添加新员工"):
            with st.form("add_user"):
                new_u = st.text_input("用户名")
                new_p = st.text_input("密码", type="password")
                new_n = st.text_input("真实姓名")
                if st.form_submit_button("创建"):
                    if create_user(new_u, new_p, new_n): st.success("创建成功")
                    else: st.error("失败")

    with c_detail:
        if selected_username:
            user_info = df_users[df_users['username'] == selected_username].iloc[0]
            stats = get_user_stats(selected_username)
            
            st.markdown(f"### 👤 {user_info['real_name']} ({user_info['role']})")
            
            # 状态卡片
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("最后上线", str(user_info.get('last_seen', 'Never'))[:16])
            k2.metric("总分配任务", stats.get('total', 0))
            k3.metric("总完成", stats.get('done', 0))
            k4.metric("7天完成", stats.get('recent_7_days', 0))
            
            st.divider()
            
            t1, t2 = st.tabs(["📜 历史客户", "🔐 账号管理"])
            
            with t1:
                st.markdown("#### 最近处理的 20 个客户")
                recent_leads = get_user_recent_leads(selected_username, 20)
                if recent_leads:
                    st.dataframe(pd.DataFrame(recent_leads), use_container_width=True)
                else:
                    st.info("暂无记录")
            
            with t2:
                st.warning("⚠️ 管理员强制修改密码区域")
                with st.form("change_pwd"):
                    new_pass = st.text_input("输入新密码", type="password")
                    if st.form_submit_button("确认修改密码"):
                        if admin_update_user_password(selected_username, new_pass):
                            st.success(f"已更新 {selected_username} 的密码")
                        else:
                            st.error("修改失败")

# --- 🏭 IMPORT (管理员专属 - 智能进货) ---
elif selected_nav == "Import" and st.session_state['role'] == 'admin':
    st.markdown("### 🏭 智能进货中心")
    st.caption("支持 2000+ 条数据的大批量处理，系统自动去重、清洗、验证。")
    
    col_up, col_log = st.columns([1, 1])
    
    with col_up:
        up_file = st.file_uploader("上传 Excel/CSV", type=['xlsx', 'csv'])
        if up_file:
            if up_file.name.endswith('.csv'): df_raw = pd.read_csv(up_file)
            else: df_raw = pd.read_excel(up_file)
            st.write(f"读取到 {len(df_raw)} 行数据")
            
            # 映射列
            c1, c2 = st.columns(2)
            s_col = c1.selectbox("店铺名列", df_raw.columns, index=1 if len(df_raw.columns)>1 else 0)
            l_col = c2.selectbox("链接/URL列", df_raw.columns, index=0)
            
            start_btn = st.button("🚀 启动智能清洗与入库")

    with col_log:
        st.markdown("#### ⚙️ 处理日志")
        log_container = st.container()
        
    if up_file and start_btn:
        client = OpenAI(api_key=OPENAI_KEY)
        
        with st.status("正在进行大规模数据处理...", expanded=True) as status:
            # 1. 提取号码
            status.write("🔍 正在扫描所有行提取手机号...")
            df_raw = df_raw.astype(str)
            raw_phones = set()
            row_map = {}
            
            progress_bar = st.progress(0)
            
            for i, r in df_raw.iterrows():
                ext = extract_all_numbers(r)
                for p in ext:
                    raw_phones.add(p)
                    if p not in row_map: row_map[p] = []
                    row_map[p].append(i)
                if i % 100 == 0: progress_bar.progress(min((i+1)/len(df_raw), 1.0))
            
            status.write(f"✅ 提取结束：发现 {len(raw_phones)} 个独立号码。")
            
            # 2. 批量验证 (分批次，避免 API 超时)
            status.write("📡 正在连接 CheckNumber 进行 WhatsApp 验证...")
            valid_phones = []
            
            # 将号码分批，每批 500 个
            phone_list = list(raw_phones)
            batch_size = 500
            for i in range(0, len(phone_list), batch_size):
                batch = phone_list[i:i+batch_size]
                status.write(f"正在验证第 {i+1} - {min(i+batch_size, len(phone_list))} 个号码...")
                res_map = process_checknumber_task(batch, CN_KEY, CN_USER)
                valid_batch = [p for p in batch if res_map.get(p) == 'valid']
                valid_phones.extend(valid_batch)
                time.sleep(1) # 稍微歇一下
            
            status.write(f"✅ 验证结束：其中 {len(valid_phones)} 个号码有效 (开通了 WhatsApp)。")
            
            # 3. 生成 AI 数据 & 入库
            status.write("🧠 AI 正在生成营销话术并入库...")
            final_rows = []
            
            ai_progress = st.progress(0)
            for idx, p in enumerate(valid_phones):
                # 找到原始数据
                rid = row_map[p][0]
                row = df_raw.iloc[rid]
                s_name = row[s_col]
                s_link = row[l_col]
                
                # 生成话术
                msg = get_ai_message_sniper(client, s_name, s_link, "Sales Team")
                
                final_rows.append({
                    "Shop": s_name, "Link": s_link, "Phone": p, "Msg": msg
                })
                
                # 每 100 条入一次库，防止积压
                if len(final_rows) >= 100:
                    admin_bulk_upload_to_pool(final_rows)
                    final_rows = [] # 清空缓冲
                
                ai_progress.progress((idx+1)/len(valid_phones))
            
            # 处理剩余的
            if final_rows:
                admin_bulk_upload_to_pool(final_rows)
            
            status.update(label="🎉 处理完成！所有有效数据已进入公共池。", state="complete")
            st.success(f"成功入库 {len(valid_phones)} 条任务，等待自动分配。")
