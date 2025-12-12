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
# 🔧 系统配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# ==========================================
# ☁️ 数据库连接
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
# 🎨 赛博商务 UI (Cyber Business Theme)
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    /* 引入字体 */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;800&display=swap');
    
    /* 全局深色背景 */
    .stApp {
        background: linear-gradient(135deg, #0f172a 0%, #1e3a8a 100%); /* 深蓝渐变 */
        color: #e2e8f0; /* 浅灰字体 */
        font-family: 'Inter', sans-serif;
    }
    
    /* 隐藏默认组件 */
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    
    /* 侧边栏深色化 */
    section[data-testid="stSidebar"] {
        background-color: #0b1120;
        border-right: 1px solid #1e293b;
    }
    section[data-testid="stSidebar"] h1, h2, h3, p, span {
        color: #e2e8f0 !important;
    }
    
    /* === 核心：炫光按钮 (Shining Button) === */
    @keyframes shine {
        0% {background-position: 0% 50%;}
        50% {background-position: 100% 50%;}
        100% {background-position: 0% 50%;}
    }
    div.stButton > button {
        background-size: 200% auto;
        background-image: linear-gradient(45deg, #2563eb 0%, #3b82f6 51%, #2563eb 100%);
        color: white;
        border: none;
        padding: 0.75rem 1.5rem;
        border-radius: 8px;
        font-weight: 700;
        letter-spacing: 0.5px;
        box-shadow: 0 0 15px rgba(37, 99, 235, 0.5);
        transition: all 0.3s ease;
        animation: shine 3s infinite; /* 流光特效 */
        width: 100%;
        border: 1px solid rgba(255,255,255,0.1);
    }
    div.stButton > button:hover {
        transform: scale(1.02);
        box-shadow: 0 0 25px rgba(37, 99, 235, 0.8);
    }
    
    /* === 玻璃拟态卡片 (Glassmorphism) === */
    div[data-testid="stExpander"], div[data-testid="stForm"] {
        background: rgba(255, 255, 255, 0.05); /* 半透明白 */
        backdrop-filter: blur(10px); /* 毛玻璃 */
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 12px;
        color: white;
    }
    
    /* 输入框美化 */
    div[data-baseweb="input"] {
        background-color: rgba(0, 0, 0, 0.2);
        border: 1px solid #334155;
        color: white;
    }
    input { color: white !important; }
    
    /* 指标卡片 (Metrics) */
    div[data-testid="stMetricValue"] { color: #60a5fa !important; }
    div[data-testid="stMetricLabel"] { color: #94a3b8 !important; }
    
    /* 链接按钮 */
    .btn-action {
        display: block; padding: 10px; color: white !important; text-decoration: none !important;
        border-radius: 6px; font-weight: 600; text-align: center; margin-top: 5px;
        transition: all 0.2s;
    }
    .wa-green { 
        background: linear-gradient(90deg, #10b981, #059669); 
        box-shadow: 0 4px 10px rgba(16, 185, 129, 0.3);
    } 
    .tg-blue { 
        background: linear-gradient(90deg, #0ea5e9, #0284c7); 
        box-shadow: 0 4px 10px rgba(14, 165, 233, 0.3);
    }
    .btn-action:hover { opacity: 0.9; transform: translateY(-1px); }
    
    /* 标题颜色修正 */
    h1, h2, h3, h4, h5, strong { color: white !important; }
    
</style>
""", unsafe_allow_html=True)

# === 核心逻辑 (v42 Sniper Engine) ===

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
    with st.status("📡 Cloud Verification...", expanded=True) as status:
        status.write(f"Checking {len(phone_list)} numbers...")
        try:
            files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
            resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, timeout=30, verify=False)
            if resp.status_code != 200: 
                status.update(label=f"⚠️ API Error (Skip Verify)", state="error"); return status_map 
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
                    if "yes" in ws or "valid" in ws: status_map[nm] = 'valid'; cnt += 1
                    else: status_map[nm] = 'invalid'
                status.update(label=f"✅ Verified: {cnt} valid.", state="complete")
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
        return f"⚠️ AI Connection Error: {str(e)}"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# ==========================================
# 🔐 Login
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
            else: st.markdown("## 🚀 988 Group CRM")
            
            if not supabase: st.error("❌ Database Error. Check Secrets."); st.stop()
            
            with st.form("login"):
                st.markdown("### 🔐 Employee Login")
                u = st.text_input("Username")
                p = st.text_input("Password", type="password")
                st.markdown("<br>", unsafe_allow_html=True)
                if st.form_submit_button("🚀 Enter Workspace"):
                    user = login_user(u, p)
                    if user:
                        st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                        st.rerun()
                    else: st.error("Invalid Credentials")
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
    menu_options = ["🚀 客户开发 (Workbench)", "📂 我的历史 (History)"]
    if st.session_state['role'] == 'admin': 
        menu_options.append("📊 团队管理 (Admin)")
        
    menu = st.radio("导航菜单", menu_options)
    st.divider()
    if st.button("🚪 退出登录"): st.session_state.clear(); st.rerun()

# 1. Workbench
if "Workbench" in str(menu):
    st.title("🚀 客户开发工作台")
    st.caption("AI 驱动的供应链客户挖掘系统")
    
    with st.expander("📂 上传数据 (Import)", expanded=st.session_state['results'] is None):
        up_file = st.file_uploader("选择 Excel/CSV 表格", type=['xlsx', 'csv'])
        if up_file:
            try:
                if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
                else: df = pd.read_excel(up_file, header=None)
                df = df.astype(str)
                c1, c2 = st.columns(2)
                with c1: s_col = st.selectbox("店铺名称列", range(len(df.columns)), 1)
                with c2: l_col = st.selectbox("店铺链接列 (AI分析用)", range(len(df.columns)), 0)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 开始 AI 挖掘 (Start Engine)"):
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
                    with c1: st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-action wa-green">🟢 WhatsApp (Verified)</a>', unsafe_allow_html=True)
                    with c2: st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-action tg-blue">🔵 Telegram</a>', unsafe_allow_html=True)
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
        st.download_button("📥 导出 Excel/CSV", csv, "my_leads.csv", "text/csv")
    else: st.info("暂无记录")

# 3. Admin
elif "Admin" in str(menu) and st.session_state['role'] == 'admin':
    st.title("📊 团队管理看板")
    df_clicks, df_leads = get_admin_stats()
    if not df_clicks.empty:
        k1, k2 = st.columns(2)
        k1.metric("全网抓取有效客户", len(df_leads))
        k2.metric("业务员跟进次数", len(df_clicks))
        st.subheader("🏆 销冠排行榜")
        lb = df_clicks['username'].value_counts().reset_index()
        lb.columns=['User', 'Unlocks']
        st.bar_chart(lb.set_index('User'))
        with st.expander("📝 详细操作日志"): st.dataframe(df_clicks)
    else: st.info("暂无数据")
    st.divider()
    with st.form("new_user"):
        st.subheader("添加新员工")
        c1, c2, c3 = st.columns(3)
        u = c1.text_input("用户名")
        p = c2.text_input("密码", type="password")
        n = c3.text_input("真实姓名")
        if st.form_submit_button("创建账号"):
            if create_user(u, p, n): st.success("创建成功")
            else: st.error("创建失败")
