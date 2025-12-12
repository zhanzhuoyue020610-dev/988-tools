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
# 🎨 UI 主题：深空灰·移动端适配版
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="🚛")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
    
    /* === 1. 全局背景 === */
    .stApp {
        background-color: #121212 !important;
        font-family: 'Inter', sans-serif;
    }
    
    /* === 关键修复：允许 Header 显示，否则手机端无法点开侧边栏，但让它透明 === */
    header {
        visibility: visible !important;
        background-color: transparent !important;
    }
    #MainMenu {visibility: visible;} 
    footer {visibility: hidden;} 
    
    /* === 2. 侧边栏 === */
    section[data-testid="stSidebar"] {
        background-color: #181818 !important;
        border-right: 1px solid #333333;
    }
    section[data-testid="stSidebar"] h1, h2, h3, p, span, div, label {
        color: #cccccc !important;
    }
    
    /* === 3. 顶部导航栏 (横向 Radio) === */
    div[data-testid="stRadio"] > div {
        display: flex;
        flex-direction: row;
        gap: 10px;
        background-color: #1e1e1e;
        padding: 5px;
        border-radius: 8px;
        border: 1px solid #333;
    }
    /* 导航按钮样式 */
    div[data-testid="stRadio"] label {
        flex: 1;
        background-color: transparent !important;
        border: 1px solid transparent;
        border-radius: 4px;
        text-align: center;
        padding: 8px 16px;
        color: #888 !important;
        cursor: pointer;
        transition: all 0.2s;
        display: flex;
        justify-content: center;
        align-items: center;
    }
    /* 选中状态 */
    div[data-testid="stRadio"] label[data-checked="true"] {
        background-color: #0078d4 !important;
        color: white !important;
        font-weight: bold;
    }
    /* 鼠标悬停 */
    div[data-testid="stRadio"] label:hover {
        color: white !important;
        background-color: #2d2d2d !important;
    }

    /* === 4. 卡片与容器 === */
    div[data-testid="stExpander"], div[data-testid="stForm"], .login-card {
        background-color: #1e1e1e !important;
        border: 1px solid #333333 !important;
        border-radius: 6px;
        box-shadow: none !important;
        margin-bottom: 16px;
        color: #e0e0e0 !important;
    }
    
    /* === 5. 字体与颜色 === */
    h1, h2, h3 { color: #ffffff !important; font-weight: 600 !important; }
    h4, h5, h6, strong { color: #58a6ff !important; }
    p, div, span, label, li { color: #bbbbbb !important; }
    .stCaption { color: #888888 !important; }

    /* === 6. 按钮系统 === */
    button { color: #ffffff !important; }
    div.stButton > button, div.stDownloadButton > button, .stFormSubmitButton > button {
        background-color: #0078d4 !important; 
        color: white !important;
        border: 1px solid #0078d4 !important;
        border-radius: 4px;
        padding: 0.6rem 1.2rem;
        font-weight: 500;
        width: 100%; /* 手机端按钮全宽，更易点击 */
    }
    div.stButton > button:hover {
        background-color: #006cc1 !important;
        border-color: #66b5ff !important;
    }
    
    /* === 7. 输入框 === */
    div[data-baseweb="input"], div[data-baseweb="select"] {
        background-color: #252526 !important;
        border: 1px solid #3c3c3c !important;
        border-radius: 4px;
    }
    div[data-baseweb="input"] input, div[data-baseweb="select"] div {
        color: #cccccc !important;
    }
    div[data-baseweb="input"]:focus-within {
        border-color: #0078d4 !important;
    }

    /* === 8. 文件上传 === */
    [data-testid="stFileUploader"] {
        padding: 15px;
        border: 1px dashed #444;
        border-radius: 8px;
        background-color: #1e1e1e;
    }
    [data-testid="stFileUploader"] div { color: #bbbbbb !important; }
    [data-testid="stFileUploader"] button {
        background-color: #2d2d2d !important;
        width: auto !important; /* 上传按钮保持自动宽度 */
    }

    /* === 9. 链接按钮 (WhatsApp/TG) === */
    .btn-action {
        display: block !important;
        width: 100% !important;
        padding: 12px !important;
        color: #ffffff !important;
        text-decoration: none !important;
        border-radius: 6px;
        font-weight: 500 !important;
        text-align: center;
        margin-top: 8px;
        font-size: 16px; /* 手机端字体加大 */
    }
    .wa-green { background-color: #128c7e !important; border: 1px solid #128c7e !important; }
    .tg-blue { background-color: #229ED9 !important; border: 1px solid #229ED9 !important; }

    hr { border-color: #333 !important; }
    
</style>
""", unsafe_allow_html=True)

# === 核心逻辑函数 ===

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

# --- 主程序逻辑 ---
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

# 侧边栏：仅保留用户信息和退出按钮（不再放导航，以免手机端找不到）
with st.sidebar:
    if os.path.exists("logo.png"): st.image("logo.png", width=180)
    st.markdown(f"👋 **{st.session_state['real_name']}**")
    st.caption(f"角色: {st.session_state['role']}")
    st.divider()
    if st.button("🚪 退出登录"): 
        st.session_state.clear()
        st.rerun()

# ==========================================
# 🚀 顶部导航栏 (手机端可见性修复核心)
# ==========================================
# 我们将导航从侧边栏移到主页面顶部，这样手机端无需点击汉堡菜单即可切换
menu_options = ["Workbench", "History"]
menu_icons = ["🚀 客户开发", "📂 历史记录"]

if st.session_state['role'] == 'admin':
    menu_options.append("Admin")
    menu_icons.append("📊 管理后台")

# 使用横向 Radio Button 模拟 Tab 栏
selected_nav = st.radio(
    "Nav", 
    menu_icons, 
    horizontal=True, 
    label_visibility="collapsed"
)

st.divider() # 视觉分割线

# 1. Workbench (工作台)
if "客户开发" in selected_nav:
    st.markdown("### 🚀 智能获客工作台")
    st.caption("AI 驱动的供应链客户挖掘系统 | v51.0 Mobile Optimized")
    
    with st.expander("📂 导入数据 (Excel/CSV)", expanded=st.session_state['results'] is None):
        up_file = st.file_uploader("选择文件", type=['xlsx', 'csv'])
        if up_file:
            try:
                if up_file.name.endswith('.csv'): df = pd.read_csv(up_file, header=None)
                else: df = pd.read_excel(up_file, header=None)
                df = df.astype(str)
                c1, c2 = st.columns(2)
                with c1: s_col = st.selectbox("【店铺名称】列", range(len(df.columns)), 1)
                with c2: l_col = st.selectbox("【店铺链接】列", range(len(df.columns)), 0)
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("🚀 启动 AI 引擎"):
                    client = OpenAI(api_key=OPENAI_KEY)
                    
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
                    
                    status_map = process_checknumber_task(list(raw_phones), CN_KEY, CN_USER)
                    valid_phones = [p for p in raw_phones if status_map.get(p) == 'valid']
                    
                    if not valid_phones:
                        st.warning("⚠️ 提取到号码，但无一通过 WhatsApp 验证。")
                        save_leads_to_db(st.session_state['username'], [])
                        st.stop()
                        
                    final_data = []
                    processed_rows = set()
                    st.info(f"🧠 AI 正在分析 {len(valid_phones)} 个潜在客户...")
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
                    st.success(f"✅ 生成 {len(final_data)} 条线索")
                    st.rerun()
            except Exception as e: st.error(f"Error: {e}")

    # Results
    if st.session_state['results']:
        c_act1, c_act2 = st.columns([2, 1])
        with c_act1: st.markdown(f"#### 🎯 推荐客户 ({len(st.session_state['results'])})")
        with c_act2: 
            if st.button("🗑️ 清空"): st.session_state['results'] = None; st.session_state['unlocked_leads'] = set(); st.rerun()

        for i, item in enumerate(st.session_state['results']):
            with st.expander(f"🏢 {item['Shop']}"):
                st.caption(f"Phone: +{item['Phone']}")
                if "AI Connection Error" in item['Msg']: st.error(item['Msg'])
                else: st.info(item['Msg'])
                
                lead_id = f"{item['Phone']}_{i}"
                if lead_id in st.session_state['unlocked_leads']:
                    st.markdown(f'<a href="{item["WA"]}" target="_blank" class="btn-action wa-green">WhatsApp</a>', unsafe_allow_html=True)
                    st.markdown(f'<a href="{item["TG"]}" target="_blank" class="btn-action tg-blue">Telegram</a>', unsafe_allow_html=True)
                else:
                    if st.button(f"👆 解锁联系方式", key=f"ul_{i}"):
                        log_click_event(st.session_state['username'], item['Shop'], item['Phone'], 'unlock')
                        st.session_state['unlocked_leads'].add(lead_id)
                        st.rerun()

# 2. History (历史记录)
elif "历史记录" in selected_nav:
    st.markdown("### 📂 我的历史记录")
    df_leads = get_user_leads_history(st.session_state['username'])
    if not df_leads.empty:
        st.dataframe(df_leads[['created_at', 'shop_name', 'phone', 'ai_message']], use_container_width=True)
        csv = df_leads.to_csv(index=False).encode('utf-8-sig')
        st.download_button("📥 导出 CSV", csv, "my_leads.csv", "text/csv")
    else: st.info("暂无记录")

# 3. Admin (管理后台) - 仅管理员可见
elif "管理后台" in selected_nav and st.session_state['role'] == 'admin':
    st.markdown("### 📊 管理后台")
    df_clicks, df_leads = get_admin_stats()
    if not df_clicks.empty:
        k1, k2 = st.columns(2)
        k1.metric("总线索", len(df_leads))
        k2.metric("总跟进", len(df_clicks))
        
        st.subheader("🏆 销冠排行榜")
        lb = df_clicks['username'].value_counts().reset_index()
        lb.columns=['业务员', '解锁次数']
        st.bar_chart(lb.set_index('业务员'))
        
        with st.expander("📝 详细操作日志"): 
            st.dataframe(df_clicks, use_container_width=True)
    else: st.info("暂无数据")
    
    st.markdown("---")
    with st.form("new_user"):
        st.subheader("添加员工账号")
        u = st.text_input("用户名")
        p = st.text_input("密码", type="password")
        n = st.text_input("真实姓名")
        if st.form_submit_button("创建账号"):
            if create_user(u, p, n): st.success("创建成功")
            else: st.error("创建失败")
