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
    "DAILY_QUOTA": 25,  # 每天限领额度
    "LOW_STOCK_THRESHOLD": 300 # 库存报警阈值
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

# --- 🔥 新增：每日绩效透视逻辑 ---
def get_user_daily_performance(username):
    """
    聚合查询：获取该员工每一天的【领取数】和【完成数】
    """
    if not supabase: return pd.DataFrame()
    try:
        # 1. 拉取该员工所有历史数据的时间戳
        res = supabase.table('leads').select('assigned_at, completed_at').eq('assigned_to', username).execute()
        df = pd.DataFrame(res.data)
        
        if df.empty: return pd.DataFrame()

        # 2. 处理领取数据 (按 assigned_at 聚合)
        df['assign_date'] = pd.to_datetime(df['assigned_at']).dt.date
        daily_claim = df.groupby('assign_date').size().rename("领取量")

        # 3. 处理完成数据 (按 completed_at 聚合)
        # 过滤掉没完成的 (completed_at is null)
        df_done = df[df['completed_at'].notna()].copy()
        df_done['done_date'] = pd.to_datetime(df_done['completed_at']).dt.date
        daily_done = df_done.groupby('done_date').size().rename("完成量")

        # 4. 合并两张表 (Outer Join)，按日期索引
        stats = pd.concat([daily_claim, daily_done], axis=1).fillna(0).astype(int)
        
        # 5. 按日期倒序排列 (最近的在上面)
        stats = stats.sort_index(ascending=False)
        return stats
    except Exception as e:
        print(e)
        return pd.DataFrame()

def get_user_historical_data(username):
    """获取特定业务员的历史总数据和处理清单"""
    if not supabase: return 0, 0, pd.DataFrame()
    try:
        # 1. 历史总领取
        res_claimed = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).execute()
        total_claimed = res_claimed.count

        # 2. 历史总完成
        res_done = supabase.table('leads').select('id', count='exact').eq('assigned_to', username).eq('is_contacted', True).execute()
        total_done = res_done.count

        # 3. 处理过的客户列表
        res_list = supabase.table('leads').select('shop_name, phone, shop_link, completed_at')\
            .eq('assigned_to', username)\
            .eq('is_contacted', True)\
            .order('completed_at', desc=True)\
            .limit(2000)\
            .execute()
        
        df_history = pd.DataFrame(res_list.data)
        return total_claimed, total_done, df_history
    except: return 0, 0, pd.DataFrame()

# --- 库存与回收 ---
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

# --- 业务员逻辑 ---
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

# --- 日志逻辑 ---
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

# ==========================================
# 🎨 UI 主题
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="⚙️")
st.markdown("""
<style>
    .stApp { background-color: #121212 !important; color: #e0e0e0 !important; }
    header { visibility: visible !important; background-color: transparent !important; }
    .stProgress > div > div > div > div { background-color: #4CAF50 !important; }
    @keyframes pulse { 0% { background-color: #ff4b4b; } 50% { background-color: #ff0000; } 100% { background-color: #ff4b4b; } }
    .low-stock-alert { padding: 15px; color: white; font-weight: bold; text-align: center; border-radius: 8px; margin-bottom: 20px; animation: pulse 2s infinite; border: 2px solid #ffcccc; }
    div[data-testid="stExpander"], div[data-testid="stForm"], div[data-testid="stDataFrame"] { background-color: #1e1e1e !important; border: 1px solid #333 !important; border-radius: 6px; }
    button { color: white !important; }
    div.stButton > button { background-color: #0078d4 !important; border: 1px solid #0078d4 !important; width: 100%; font-weight: bold; }
    button:disabled { background-color: #555 !important; border-color: #555 !important; color: #aaa !important; cursor: not-allowed; }
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

st.markdown(f"**👤 {st.session_state['real_name']}** | Role: {st.session_state['role'].upper()}")
if st.button("Logout", key="logout_top"): st.session_state.clear(); st.rerun()

menu_options = ["Workbench"]
if st.session_state['role'] == 'admin':
    menu_options = ["Workbench", "Logs", "Team", "Import"]

selected_nav = st.radio("Nav", menu_options, horizontal=True, label_visibility="collapsed")
st.divider()

# --- 💼 WORKBENCH ---
if selected_nav == "Workbench":
    st.markdown("### 🎯 今日任务看板")
    my_leads = get_todays_leads(st.session_state['username'])
    total_task = CONFIG["DAILY_QUOTA"]
    current_count = len(my_leads)
    
    if current_count < total_task:
        st.warning(f"⚠️ 你的任务未满！今日指标 {total_task} 个，当前持有 {current_count} 个。")
        if st.button(f"📥 立即领取剩余 {total_task - current_count} 个任务"):
            my_leads, status = claim_daily_tasks(st.session_state['username'])
            if status == "empty": st.error("公池已被领空！")
            elif status == "full": st.success("已领满！")
            else: st.success("领取成功！"); st.rerun()
    else: st.success("✅ 今日任务已领满。")

    completed_count = sum([1 for x in my_leads if x.get('is_contacted')])
    st.progress(min(completed_count / total_task, 1.0))
    st.caption(f"进度: {completed_count} / {total_task}")
    
    tab_todo, tab_done = st.tabs(["🔥 待跟进", "✅ 已完成"])
    with tab_todo:
        to_do_items = [x for x in my_leads if not x.get('is_contacted')]
        if not to_do_items:
            if current_count == 0: st.info("请先领取任务。")
            else: st.success("🎉 待办清空！")
        for item in to_do_items:
            with st.expander(f"🏢 {item['shop_name']} (+{item['phone']})", expanded=True):
                st.info(item['ai_message'])
                c1, c2 = st.columns(2)
                link_key = f"clicked_{item['id']}"
                if link_key not in st.session_state: st.session_state[link_key] = False
                
                if not st.session_state[link_key]:
                    if c1.button("🔗 获取 WhatsApp 链接", key=f"lk_{item['id']}"):
                        st.session_state[link_key] = True
                        st.rerun()
                    c2.button("🚫 请先获取链接", disabled=True, key=f"fake_{item['id']}")
                else:
                    wa_url = f"https://wa.me/{item['phone']}?text={urllib.parse.quote(item['ai_message'])}"
                    c1.markdown(f"<a href='{wa_url}' target='_blank' style='display:block;text-align:center;background:#25D366;color:white;padding:10px;border-radius:4px;text-decoration:none;font-weight:bold;'>👉 点击跳转 WhatsApp</a>", unsafe_allow_html=True)
                    if c2.button("✅ 标记完成", key=f"done_{item['id']}"):
                        mark_lead_complete_secure(item['id'])
                        st.session_state.pop(link_key, None)
                        st.rerun()
    with tab_done:
        done_items = [x for x in my_leads if x.get('is_contacted')]
        if done_items:
            df_done = pd.DataFrame(done_items)
            df_done['completed_at'] = pd.to_datetime(df_done['completed_at']).dt.strftime('%H:%M')
            st.dataframe(df_done[['shop_name', 'phone', 'completed_at']], use_container_width=True)

# --- 📅 LOGS ---
elif selected_nav == "Logs" and st.session_state['role'] == 'admin':
    st.markdown("### 📅 每日监控")
    q_date = st.date_input("选择查询日期", date.today())
    if q_date:
        df_claim, df_done = get_daily_logs(q_date.isoformat())
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 📥 领取榜")
            if not df_claim.empty: st.dataframe(df_claim, use_container_width=True)
            else: st.info("无数据")
        with c2:
            st.markdown("#### ✅ 实干榜")
            if not df_done.empty: st.dataframe(df_done, use_container_width=True)
            else: st.info("无数据")

# --- 👥 TEAM (包含每日绩效) ---
elif selected_nav == "Team" and st.session_state['role'] == 'admin':
    st.markdown("### 👥 团队管理")
    users_raw = supabase.table('users').select("*").execute().data
    df_users = pd.DataFrame(users_raw)
    
    c_list, c_detail = st.columns([1, 2])
    with c_list:
        selected_username = st.radio("选择员工", df_users['username'].tolist())
        st.divider()
        with st.form("add_user"):
            st.write("新增员工")
            new_u = st.text_input("用户名")
            new_p = st.text_input("密码", type="password")
            new_n = st.text_input("真实姓名")
            if st.form_submit_button("创建"):
                if create_user(new_u, new_p, new_n): st.success("创建成功"); st.rerun()
                else: st.error("失败")

    with c_detail:
        if selected_username:
            user_info = df_users[df_users['username'] == selected_username].iloc[0]
            
            # 🔥 获取全量数据
            tot_claimed, tot_done, df_history = get_user_historical_data(selected_username)
            # 🔥 获取每日绩效表
            df_daily = get_user_daily_performance(selected_username)

            st.markdown(f"### 👤 {user_info['real_name']}")
            st.info(f"Role: {user_info['role']} | Last Seen: {str(user_info.get('last_seen', 'Never'))[:16]}")
            
            # 统计数据卡片
            k1, k2 = st.columns(2)
            k1.metric("📦 历史总领取", tot_claimed)
            k2.metric("✅ 历史总完成", tot_done)
            
            st.divider()
            
            # --- Tab 区域 ---
            t1, t2, t3 = st.tabs(["📅 每日绩效 (Daily)", "📜 处理明细 (History)", "⚙️ 设置"])
            
            with t1:
                st.markdown("#### 每日领取与完成记录")
                if not df_daily.empty:
                    # 图表展示
                    st.bar_chart(df_daily)
                    # 表格展示
                    st.dataframe(df_daily, use_container_width=True)
                else:
                    st.info("暂无每日活动记录")

            with t2:
                st.markdown("#### 📜 已处理客户列表")
                if not df_history.empty:
                    st.dataframe(
                        df_history,
                        column_config={
                            "shop_link": st.column_config.LinkColumn("店铺链接"),
                            "completed_at": st.column_config.DatetimeColumn("处理时间", format="D MMM YYYY, h:mm a")
                        },
                        use_container_width=True
                    )
                else:
                    st.info("暂无记录")

            with t3:
                with st.expander("🗑️ 删除账号并回收任务"):
                    st.error("警告：删除后，该员工名下【未完成】的任务将自动重置回公共池。")
                    confirm_del = st.text_input(f"请输入 '{selected_username}' 确认删除")
                    if st.button("确认删除"):
                        if confirm_del == selected_username:
                            if delete_user_and_recycle(selected_username):
                                st.success("删除成功，任务已回收！"); time.sleep(1); st.rerun()

# --- 🏭 IMPORT (含报警机制) ---
elif selected_nav == "Import" and st.session_state['role'] == 'admin':
    pool_count = get_public_pool_count()
    if pool_count < CONFIG["LOW_STOCK_THRESHOLD"]:
        st.markdown(f"""<div class="low-stock-alert">🚨 库存告急！公共池仅剩 {pool_count} 个客户！请补充！</div>""", unsafe_allow_html=True)
    else:
        st.metric("公共池剩余库存", f"{pool_count} 个", delta="库存充足", delta_color="normal")
    
    with st.expander("♻️ 每日归仓工具", expanded=True):
        st.info("回收所有“昨天或更早”分配但“未完成”的任务。")
        if st.button("执行归仓回收"):
            count = recycle_expired_tasks()
            if count > 0: st.success(f"成功回收 {count} 个滞留任务！")
            else: st.info("没有需要回收的任务。")
    
    st.divider()
    st.markdown("### 📥 进货操作")
    col_up, col_log = st.columns([1, 1])
    with col_up:
        up_file = st.file_uploader("上传 Excel/CSV", type=['xlsx', 'csv'])
        if up_file:
            if up_file.name.endswith('.csv'): df_raw = pd.read_csv(up_file)
            else: df_raw = pd.read_excel(up_file)
            st.write(f"读取到 {len(df_raw)} 行数据")
            c1, c2 = st.columns(2)
            s_col = c1.selectbox("店铺名列", df_raw.columns, index=1 if len(df_raw.columns)>1 else 0)
            l_col = c2.selectbox("链接/URL列", df_raw.columns, index=0)
            start_btn = st.button("🚀 启动处理")

    with col_log:
        st.markdown("#### ⚙️ 日志")
    if up_file and start_btn:
        client = OpenAI(api_key=OPENAI_KEY)
        with st.status("处理中...", expanded=True) as status:
            df_raw = df_raw.astype(str)
            raw_phones = set()
            row_map = {}
            for i, r in df_raw.iterrows():
                ext = extract_all_numbers(r)
                for p in ext:
                    raw_phones.add(p)
                    if p not in row_map: row_map[p] = []
                    row_map[p].append(i)
            status.write(f"提取到 {len(raw_phones)} 个号码，验证中...")
            valid_phones = []
            phone_list = list(raw_phones)
            batch_size = 500
            for i in range(0, len(phone_list), batch_size):
                batch = phone_list[i:i+batch_size]
                res_map = process_checknumber_task(batch, CN_KEY, CN_USER)
                valid_phones.extend([p for p in batch if res_map.get(p) == 'valid'])
                time.sleep(1)
            status.write(f"验证完成，有效 {len(valid_phones)} 个，AI 生成中...")
            final_rows = []
            bar = st.progress(0)
            for idx, p in enumerate(valid_phones):
                rid = row_map[p][0]
                row = df_raw.iloc[rid]
                msg = get_ai_message_sniper(client, row[s_col], row[l_col], "Sales Team")
                final_rows.append({"Shop": row[s_col], "Link": row[l_col], "Phone": p, "Msg": msg})
                if len(final_rows) >= 100:
                    admin_bulk_upload_to_pool(final_rows)
                    final_rows = []
                bar.progress((idx+1)/len(valid_phones))
            if final_rows: admin_bulk_upload_to_pool(final_rows)
            status.update(label="完成入库！", state="complete")
            time.sleep(1)
            st.rerun()
