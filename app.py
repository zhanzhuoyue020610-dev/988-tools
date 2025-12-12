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
import cloudscraper
from bs4 import BeautifulSoup 

try:
    from supabase import create_client, Client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

warnings.filterwarnings("ignore")

# ==========================================
# 🔧 配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# ==========================================
# ☁️ 数据库
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

def login_user(u, p):
    if not supabase: return None
    pwd_hash = hashlib.sha256(p.encode()).hexdigest()
    try:
        res = supabase.table('users').select("*").eq('username', u).eq('password', pwd_hash).execute()
        return res.data[0] if res.data else None
    except: return None

def create_user(u, p, n):
    if not supabase: return False
    try:
        pwd = hashlib.sha256(p.encode()).hexdigest()
        supabase.table('users').insert({"username": u, "password": pwd, "role": "sales", "real_name": n}).execute()
        return True
    except: return False

def log_click_event(username, shop, phone, target):
    if not supabase: return
    try:
        supabase.table('clicks').insert({
            "username": username, "shop_name": shop, "phone": phone, "target": target
        }).execute()
    except: pass

def save_leads_to_db(username, leads_data):
    if not supabase or not leads_data: return
    try:
        rows = []
        for item in leads_data:
            rows.append({
                "username": username, "shop_name": item['Shop'], "shop_link": item['Link'],
                "phone": item['Phone'], "ai_message": item['Msg'], "is_valid": (item['Status']=='valid')
            })
        supabase.table('leads').insert(rows).execute()
    except: pass

def get_admin_stats():
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    try:
        c = pd.DataFrame(supabase.table('clicks').select("*").execute().data)
        l = pd.DataFrame(supabase.table('leads').select("username, is_valid, created_at").execute().data)
        return c, l
    except: return pd.DataFrame(), pd.DataFrame()

def get_user_leads_history(username):
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table('leads').select("*").eq('username', username).order('created_at', desc=True).limit(200).execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

# ==========================================
# 🎨 赛博黑金·高对比版 UI (v50.0)
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    /* === 1. 全局背景：深邃流光 === */
    .stApp {
        background: linear-gradient(135deg, #020024 0%, #090979 35%, #00d4ff 100%);
        background-size: 400% 400%;
        animation: gradientBG 15s ease infinite;
        font-family: 'Inter', sans-serif;
    }
    @keyframes gradientBG {
        0% {background-position: 0% 50%;}
        50% {background-position: 100% 50%;}
        100% {background-position: 0% 50%;}
    }
    
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    
    /* === 2. 侧边栏：纯黑磨砂 === */
    section[data-testid="stSidebar"] {
        background-color: #000000 !important;
        border-right: 1px solid rgba(255, 255, 255, 0.15);
    }
    section[data-testid="stSidebar"] h1, h2, h3, p, span, div {
        color: #ffffff !important;
    }
    
    /* === 3. 卡片：深色实底 (保证字看得清) === */
    div[data-testid="stExpander"], div[data-testid="stForm"], .login-card {
        background-color: #0f172a !important; /* 深蓝黑实色 */
        border: 1px solid rgba(56, 189, 248, 0.3); /* 青色边框 */
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.3);
        margin-bottom: 16px;
        color: white !important;
    }
    
    /* 文字颜色强制修正 */
    p, span, div, li, label {
        color: #ffffff !important;
        font-weight: 500;
        text-shadow: 0 1px 1px rgba(0,0,0,0.8); /* 黑色投影，防撞色 */
    }
    h1, h2, h3, h4, strong {
        color: #38bdf8 !important; /* 亮青色标题 */
        font-weight: 800 !important;
    }
    
    /* === 4. 核心修复：按钮样式 (强制高对比) === */
    
    /* Streamlit 原生按钮 (Unlock / Start) */
    div.stButton > button {
        background-color: #2563eb !important; /* 纯蓝实色 */
        color: #ffffff !important;
        border: 1px solid #60a5fa !important;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        font-weight: 700;
        text-transform: uppercase;
        box-shadow: 0 4px 0 #1e40af !important; /* 3D 阴影 */
        transition: all 0.1s;
    }
    div.stButton > button:hover {
        background-color: #3b82f6 !important;
        transform: translateY(2px);
        box-shadow: 0 2px 0 #1e40af !important;
    }
    
    /* HTML 跳转按钮 (WhatsApp / Telegram) */
    .btn-action {
        display: block !important;
        width: 100% !important;
        padding: 12px !important;
        color: #ffffff !important; /* 强制白字 */
        text-decoration: none !important;
        border-radius: 8px;
        font-weight: 700 !important;
        text-align: center;
        margin-top: 8px;
        text-shadow: 0 1px 2px rgba(0,0,0,0.8) !important; /* 文字加黑边 */
        border: 1px solid rgba(255,255,255,0.2);
        transition: all 0.2s;
    }
    
    /* 微信绿：默认深一点，悬停亮一点 */
    .wa-green { 
        background-color: #047857 !important; /* 深绿 (默认) */
        border-bottom: 4px solid #064e3b !important;
    }
    .wa-green:hover { 
        background-color: #10b981 !important; /* 亮绿 (悬停) */
        transform: translateY(2px);
        border-bottom: 2px solid #064e3b !important;
    }
    
    /* 电报蓝：默认深一点，悬停亮一点 */
    .tg-blue { 
        background-color: #0369a1 !important; /* 深蓝 (默认) */
        border-bottom: 4px solid #075985 !important;
    } 
    .tg-blue:hover { 
        background-color: #0ea5e9 !important; /* 亮蓝 (悬停) */
        transform: translateY(2px);
        border-bottom: 2px solid #075985 !important;
    }
    
    /* 输入框 */
    div[data-baseweb="input"] {
        background-color: #1e293b !important;
        border: 1px solid #475569 !important;
        color: white !important;
        border-radius: 6px;
    }
    input { color: white !important; }
    
    /* 状态提示 */
    div[data-testid="stStatusWidget"] {
        background-color: #0f172a; border: 1px solid #38bdf8;
    }
</style>
""", unsafe_allow_html=True)

# === 核心逻辑 ===

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
    digs = re.findall(r'(?:^|\D)([789]\d{9,10})(?:\D|$)', txt)
    for raw in digs:
        if len(raw)==11 and raw.startswith('7'): candidates.append(raw)
        elif len(raw)==11 and raw.startswith('8'): candidates.append('7'+raw[1:])
        elif len(raw)==10 and raw.startswith('9'): candidates.append('7'+raw)
    return list(set(candidates))

def get_proxy_config(): return None

def get_niche_from_url(url):
    if not url or "http" not in str(url): return ""
    try:
        stopwords = ['ozon', 'ru', 'com', 'seller', 'products', 'category', 'catalog', 'detail', 'html', 'https', 'www', 'item']
        path = urllib.parse.urlparse(url).path
        clean_path = re.sub(r'[\/\-\_\.]', ' ', path)
        words = re.findall(r'[a-zA-Z]{3,}', clean_path)
        meaningful = [w for w in words if w.lower() not in stopwords]
        return ", ".join(meaningful[:6])
    except: return ""

def extract_web_content(url):
    content = ""
    try:
        scraper = cloudscraper.create_scraper()
        resp = scraper.get(url, timeout=4)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            if title: content += f"Title: {title}. "
    except: pass
    url_niche = get_niche_from_url(url)
    if url_niche: content += f"URL Keywords: {url_niche}. "
    return content if content else "Unknown"

def process_checknumber_task(phone_list, api_key, user_id):
    if not phone_list: return {}
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    with st.status("📡 正在连接云端验证...", expanded=True) as status:
        status.write(f"正在上传 {len(phone_list)} 个号码...")
        try:
            files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, timeout=30, verify=False)
            if resp.status_code != 200: 
                status.update(label=f"⚠️ API 错误 (跳过验证)", state="error"); return status_map 
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
        if not result_url: status.update(label="⚠️ 验证超时", state="error"); return status_map
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
                    if "yes" in ws or "valid" in ws: status_map[nm] = 'valid'; cnt += 1
                    else: status_map[nm] = 'invalid'
                status.update(label=f"✅ 验证完成! 发现 {cnt} 个有效号码", state="complete")
        except: pass
    return status_map

def get_ai_message_sniper(client, shop_name, shop_link, context_info, rep_name):
    if shop_name.lower() in ['seller', 'store', 'shop', 'ozon', 'nan', '']: shop_name = ""
    prompt = f"""
    Role: Expert Sales Manager '{rep_name}' at 988 Group (China Supply Chain).
    Target Store Name: "{shop_name}"
    Data Source: {context_info}
    MISSION: Write a HIGH-CONVERSION Russian WhatsApp message.
    STRATEGY:
    1. **NICHE DETECTION**: Analyze 'Data Source'. 'fishing'->Fishing Gear, 'auto'->Auto Parts. UNKNOWN->Top Seller.
    2. **HOOK**: "Здравствуйте! Увидела ваш магазин на Ozon, отличный выбор [NICHE]!" (Or "Изучила ваш ассортимент...").
    3. **OFFER**: "We (988 Group) help source [NICHE] directly from China factories 15-20% cheaper + Logistics to Moscow."
    4. **CTA**: "Can I send a price calculation?"
    Constraint: Native Russian. <50 words.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o", messages=[{"role": "user", "content": prompt}], temperature=0.8, max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"⚠️ 系统提示: AI 连接失败，请检查 Key余额。({str(e)})"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# ==========================================
# 🔐 登录界面
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False
if 'results' not in st.session_state: st.session_state['results'] = None
if 'unlocked_leads' not in st.session_state: st.session_state['unlocked_leads'] = set()

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<div style='height:10vh;'></div>", unsafe_allow_html=True)
        # 登录卡片
        with st.container():
            if os.path.exists("logo.png"): st.image("logo.png", width=220)
            else: st.markdown("## 🚛 988 Group CRM")
            
            if not supabase: st.error("❌ 数据库连接失败"); st.stop()
            
            with st.form("login"):
                st.markdown("### 🔐 员工登录")
                u = st.text_input("用户名")
                p = st.text_input("密码", type="password")
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("🚀 进入系统"):
                    user = login_user(u, p)
                    if user:
                        st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                        st.rerun()
                    else: st.error("账号或密码错误")
    st.stop()

# --- Main ---
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=180)
    st.markdown(f"👋 **{st.session_state['real_name']}**")
    
    # 菜单汉化
    menu = st.radio("导航菜单", ["🚀 客户开发 (Workbench)", "📂 历史记录 (History)", "📊 管理后台 (Admin)"] if st.session_state['role']=='admin' else ["🚀 客户开发 (Workbench)", "📂 历史记录 (History)"])
    st.divider()
    if st.button("🚪 退出登录"): st.session_state.clear(); st.rerun()

# 1. Workbench
if "Workbench" in str(menu):
    st.title("🚀 智能获客工作台")
    st.caption("AI 驱动的供应链客户挖掘系统 | v50.0 Pro")
    
    with st.expander("📂 导入数据 (Excel/CSV)", expanded=st.session_state['results'] is None):
        up_file = st.file_uploader("选择文件", type=['xlsx', 'csv'])
        if up_file:
            try:
                if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
                else: df = pd.read_excel(up_file, header=None)
                df = df.astype(str)
                c1, c2 = st.columns(2)
                with c1: s_col = st.selectbox("选择【店铺名称】列", range(len(df.columns)), 1)
                with c2: l_col = st.selectbox("选择【店铺链接】列 (AI分析用)", range(len(df.columns)), 0)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 启动 AI 引擎"):
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
                    
                    if not raw_phones: st.error("❌ 未发现任何号码"); st.stop()
                    
                    # Verify
                    status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
                    valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
                    
                    if not valid_phones:
                        st.warning("⚠️ 提取到号码，但无一通过 WhatsApp 验证。")
                        save_leads_to_db(st.session_state['username'], [])
                        st.stop()
                        
                    final_data = []
                    processed_rows = set()
                    st.info(f"🧠 AI 正在深度分析 {len(valid_phones)} 个潜在客户的选品策略...")
                    ai_bar = st.progress(0)
                    
                    for idx, p in enumerate(valid_phones):
                        indices = row_map[p]
                        for rid in indices:
                            if rid in processed_rows: continue
                            processed_rows.add(rid)
                            row = df.iloc[rid]
                            s_name = row[s_col]
                            s_link = row[l_col]
                            
                            context = extract_web_content(s_link) 
                            msg = get_ai_message_sniper(client, s_name, s_link, context, st.session_state['real_name'])
                            
                            wa_link = make_wa_link(p, msg); tg_link = f"https://t.me/+{p}"
                            final_data.append({"Shop": s_name, "Link": s_link, "Phone": p, "Msg": msg, "WA": wa_link, "TG": tg_link, "Status": "valid"})
                        ai_bar.progress((idx+1)/len(valid_phones))
                    
                    st.session_state['results'] = final_data
                    save_leads_to_db(st.session_state['username'], final_data)
                    st.success(f"✅ 完成！生成 {len(final_data)} 条高潜线索")
                    st.rerun()
            except Exception as e: st.error(f"Error: {e}")

    # Results
    if st.session_state['results']:
        c_act1, c_act2 = st.columns([3, 1])
        with c_act1: st.markdown(f"### 🎯 推荐客户 ({len(st.session_state['results'])})")
        with c_act2: 
            if st.button("🗑️ 清空结果"): st.session_state['results'] = None; st.session_state['unlocked_leads'] = set(); st.rerun()

        for i, item in enumerate(st.session_state['results']):
            with st.expander(f"🏢 {item['Shop']} (+{item['Phone']})"):
                if "AI Connection Error" in item['Msg']:
                    st.error(item['Msg'])
                else:
                    st.info(item['Msg'])
                
                lead_id = f"{item['Phone']}_{i}"
                if lead_id in st.session_state['unlocked_leads']:
                    c1, c2 = st.columns(2)
                    with c1: st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-action wa-green">🟢 打开 WhatsApp</a>', unsafe_allow_html=True)
                    with c2: st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-action tg-blue">🔵 打开 Telegram</a>', unsafe_allow_html=True)
                else:
                    if st.button(f"👆 解锁联系方式 (Unlock)", key=f"ul_{i}"):
                        log_click_event(st.session_state['username'], item['Shop'], item['Phone'], 'unlock')
                        st.session_state['unlocked_leads'].add(lead_id)
                        st.rerun()

# 2. History
elif "History" in str(menu):
    st.title("📂 我的历史记录")
    df_leads = get_user_leads_history(st.session_state['username'])
    if not df_leads.empty:
        st.dataframe(df_leads[['created_at', 'shop_name', 'phone', 'ai_message']], use_container_width=True)
        csv = df_leads.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 导出 CSV", csv, "my_leads.csv", "text/csv")
    else: st.info("暂无记录")

# 3. Admin
elif "Admin" in str(menu) and st.session_state['role'] == 'admin':
    st.title("📊 管理后台")
    df_clicks, df_leads = get_admin_stats()
    if not df_clicks.empty:
        k1, k2 = st.columns(2)
        k1.metric("全网抓取线索", len(df_leads))
        k2.metric("业务员跟进数", len(df_clicks))
        st.subheader("🏆 销冠排行榜")
        lb = df_clicks['username'].value_counts().reset_index()
        lb.columns=['业务员', '解锁次数']
        st.bar_chart(lb.set_index('业务员'))
        with st.expander("📝 详细日志"): st.dataframe(df_clicks)
    else: st.info("暂无数据")
    
    st.divider()
    with st.form("new_user"):
        st.subheader("添加员工账号")
        c1, c2, c3 = st.columns(3)
        u = c1.text_input("用户名")
        p = c2.text_input("密码", type="password")
        n = c3.text_input("真实姓名")
        if st.form_submit_button("创建账号"):
            if create_user(u, p, n): st.success("创建成功")
            else: st.error("创建失败")
