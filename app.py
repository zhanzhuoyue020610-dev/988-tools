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
from bs4 import BeautifulSoup 

# 忽略 SSL 警告
warnings.filterwarnings("ignore")

# ==========================================
# 🔧 988 Group 云端配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, 
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# 1. 页面配置
st.set_page_config(
    page_title="988 Group - Omni-Channel System", 
    layout="wide", 
    page_icon="🚛",
    initial_sidebar_state="expanded"
)

# 2. UI 美化 (HTML 按钮样式)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    html, body, [class*="css"] {font-family: 'Inter', sans-serif;}
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    section[data-testid="stSidebar"] {background-color: #f4f6f9; border-right: 1px solid #e0e0e0;}
    h1 {color: #003366; font-weight: 700;}
    
    /* 自定义 HTML 按钮样式 */
    .custom-btn {
        display: inline-block;
        padding: 8px 16px;
        color: white !important;
        text-decoration: none !important;
        border-radius: 6px;
        font-weight: 600;
        text-align: center;
        width: 100%;
        transition: all 0.2s;
        margin-top: 5px;
    }
    .btn-wa { background-color: #25D366; } /* WhatsApp 绿 */
    .btn-wa:hover { background-color: #128C7E; }
    
    .btn-tg { background-color: #0088cc; } /* Telegram 蓝 */
    .btn-tg:hover { background-color: #006699; }
    
    .btn-disabled { background-color: #cccccc; cursor: not-allowed; }
</style>
""", unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=180)
    else:
        st.markdown("## 🚛 **988 Group**")
        
    st.markdown("### Omni-Channel System")
    st.caption("v26.0: Bulletproof HTML Edition")
    
    try:
        default_cn_user = st.secrets["CN_USER_ID"]
        default_cn_key = st.secrets["CN_API_KEY"]
        default_openai = st.secrets["OPENAI_KEY"]
        st.caption("✅ Cloud Secrets Loaded")
    except FileNotFoundError:
        default_cn_user = ""
        default_cn_key = ""
        default_openai = ""
        st.caption("⚠️ Local Mode")

    with st.expander("🔧 Settings", expanded=True):
        use_proxy = st.checkbox("Enable Proxy", value=False)
        proxy_port = st.text_input("Proxy URL", value="http://127.0.0.1:10809")
        # 允许用户修改 ID，防止 secrets 里填错
        check_user_id = st.text_input("CN User ID", value=default_cn_user)
        check_key = st.text_input("CN Key", value=default_cn_key, type="password")
        openai_key = st.text_input("OpenAI Key", value=default_openai, type="password")

# === 核心函数 ===

def get_proxy_config():
    if use_proxy and proxy_port: return proxy_port.strip()
    return None

def extract_web_content(url):
    if not url or not isinstance(url, str) or "http" not in url: return None
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else ""
            desc = ""
            meta = soup.find('meta', attrs={'name': 'description'})
            if meta: desc = meta.get('content', '')
            return f"Page Title: {title} | Description: {desc[:200]}"
    except: return None
    return None

def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    # 宽松正则：只要是7,8,9开头的10-11位数字都抓取
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

def process_checknumber_task(phone_list):
    """
    带深度调试功能的验号模块
    """
    if not phone_list: return set()
    valid_numbers_set = set()
    
    api_key = check_key.strip()
    user_id = check_user_id.strip()
    if not api_key or not user_id: st.error("❌ 配置缺失: API Key 或 User ID 为空"); return set()

    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    my_proxy_str = get_proxy_config()
    req_proxies = {"http": my_proxy_str, "https": my_proxy_str} if my_proxy_str else None
    
    status_box = st.status("📡 Connecting to CheckNumber API...", expanded=True)
    status_box.write(f"Uploading {len(phone_list)} numbers...")
    
    # 1. Upload
    file_content = "\n".join(phone_list)
    files = {'file': ('input.txt', file_content, 'text/plain')}
    data_payload = {'user_id': user_id} 
    
    try:
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data=data_payload, proxies=req_proxies, timeout=30, verify=False)
        
        # === 调试点 1: 上传失败 ===
        if resp.status_code != 200:
            status_box.update(label="❌ Upload Failed", state="error")
            st.error(f"API Error Code: {resp.status_code}")
            st.code(resp.text) # 打印报错详情
            return set() # 这里不返回假数据，直接中断，因为需要看报错
            
        task_data = resp.json()
        task_id = task_data.get("task_id")
        if not task_id:
            st.error("No Task ID returned. Response:")
            st.json(task_data)
            return set()
            
    except Exception as e:
        status_box.update(label="❌ Network Error", state="error")
        st.error(f"Connection failed: {e}")
        return set()

    # 2. Polling
    status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
    result_url = None
    
    for i in range(40):
        try:
            time.sleep(3)
            # GET 请求通常不需要 body，user_id 拼在 URL 参数里
            poll_resp = requests.get(status_url, headers=headers, params={'user_id': user_id}, proxies=req_proxies, timeout=30, verify=False)
            
            if poll_resp.status_code == 200:
                p_data = poll_resp.json()
                status = p_data.get("status")
                
                # 进度展示
                done = p_data.get("success", 0) + p_data.get("failure", 0)
                total = p_data.get("total", 1)
                status_box.write(f"Processing... {done}/{total} (Status: {status})")
                
                if status in ["exported", "completed"]:
                    result_url = p_data.get("result_url")
                    break
            elif poll_resp.status_code == 401:
                 st.error("❌ Polling Unauthorized (401). Check User ID.")
                 st.stop()
        except: pass
            
    if not result_url: 
        status_box.update(label="❌ Verification Timeout", state="error")
        # 超时的情况，为了不阻断业务，我们把所有号码当做有效返回（降级策略）
        st.warning("⚠️ 验号超时，系统将显示所有号码供尝试。")
        return set(phone_list)
        
    # 3. Download & Parse
    try:
        status_box.write("Downloading report...")
        f_resp = requests.get(result_url, proxies=req_proxies, verify=False)
        
        if f_resp.status_code == 200:
            # 尝试解析
            try: res_df = pd.read_excel(io.BytesIO(f_resp.content))
            except: res_df = pd.read_csv(io.BytesIO(f_resp.content))
            
            res_df.columns = [c.lower() for c in res_df.columns]
            
            # === 调试点 2: 结果预览 ===
            # st.write("API Result Preview:", res_df.head()) # 调试用
            
            for _, r in res_df.iterrows():
                ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                num = str(r.get('number') or r.get('phone') or '')
                cn = re.sub(r'\D', '', num)
                
                # 宽松匹配
                if "yes" in ws or "valid" in ws or "true" in ws:
                    valid_numbers_set.add(cn)
                    
            status_box.update(label=f"✅ Analysis Complete: Found {len(valid_numbers_set)} valid numbers", state="complete")
        else:
            st.error(f"Download failed: {f_resp.status_code}")
            
    except Exception as e:
        status_box.update(label="❌ Parse Error", state="error")
        st.error(str(e))

    return valid_numbers_set

def get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name):
    if pd.isna(shop_name): shop_name = "Seller"
    if pd.isna(shop_link): shop_link = "Ozon Store"
    
    source_info = f"URL: {shop_link}"
    if web_content: source_info += f"\nScraped Page Content: {web_content}"
    
    prompt = f"""
    Role: Business Manager at "988 Group" (China).
    Sender: "{rep_name}". Target: "{shop_name}".
    Source: {source_info}
    Context: 988 Group = Sourcing + Logistics to Russia.
    Task: Polite Russian WhatsApp intro.
    Structure:
    1. "Здравствуйте, [Name]! Меня зовут {rep_name} (988 Group)."
    2. "Saw your store..."
    3. "We supply [Niche] items + shipping/customs to Russia."
    4. "Catalog?"
    Output: Russian text only.
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, max_tokens=300
        )
        return response.choices[0].message.content.strip()
    except:
        return f"Здравствуйте, {shop_name}! Меня зовут {rep_name} (988 Group). Мы занимаемся поставками из Китая."

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

def make_tg_link(phone):
    return f"https://t.me/+{phone}"

# === 主程序界面 ===

st.markdown("### 🚀 988 Group Omni-Channel System")
st.markdown("Automated Lead Generation (v26.0 HTML Edition)")
st.markdown("---")

uploaded_file = st.file_uploader("📂 Upload Lead List (Excel/CSV)", type=['xlsx', 'csv'])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file, header=None)
        else: df = pd.read_excel(uploaded_file, header=None)
        df = df.astype(str)
    except: st.stop()
        
    with st.container():
        st.info("👇 Configuration")
        c1, c2, c3 = st.columns([1,1,1])
        with c1:
            shop_col_idx = st.selectbox("🏷️ Store Name Column", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2:
            link_col_idx = st.selectbox("🔗 Link Column", range(len(df.columns)), index=0)
        with c3:
            rep_name = st.text_input("👤 Your Name", value="", placeholder="e.g. Anna")

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🚀 START ENGINE", type="primary"):
        if not rep_name: st.error("⚠️ Enter your name!"); st.stop()
        
        my_proxy_str = get_proxy_config()
        if not openai_key: st.error("❌ OpenAI Key Missing"); st.stop()

        client = None
        if my_proxy_str:
            try:
                try: http_client = httpx.Client(proxy=my_proxy_str, verify=False)
                except: http_client = httpx.Client(proxies=my_proxy_str, verify=False)
                client = OpenAI(api_key=openai_key, http_client=http_client)
            except: st.error("Proxy Error"); st.stop()
        else:
            client = OpenAI(api_key=openai_key)

        # 1. 提取
        all_raw_phones = set()
        phone_to_rows = {}
        progress_bar = st.progress(0)
        for i, row in df.iterrows():
            extracted = extract_all_numbers(row)
            for p in extracted:
                all_raw_phones.add(p)
                if p not in phone_to_rows: phone_to_rows[p] = []
                phone_to_rows[p].append(i)
            progress_bar.progress((i+1)/len(df))
            
        if not all_raw_phones: st.error("No numbers found."); st.stop()

        # 2. 验号
        wa_valid_set = process_checknumber_task(list(all_raw_phones))
        
        # 3. AI 生成
        st.markdown("---")
        
        # 如果 WA 验号全挂了，我们还是生成结果（基于提取到的号码），这样至少能发 Telegram
        # 我们把所有提取到的号码都列出来
        target_phones = sorted(list(all_raw_phones))
        
        if not target_phones:
            st.error("Fatal Error: No numbers to process.")
            st.stop()
            
        st.success(f"✅ Processing {len(target_phones)} leads...")
        
        final_results = []
        processed_rows = set()
        ai_bar = st.progress(0)
        
        for idx_step, p in enumerate(target_phones):
            row_indices = phone_to_rows[p]
            for r_idx in row_indices:
                if r_idx in processed_rows: continue
                processed_rows.add(r_idx)
                
                row = df.iloc[r_idx]
                shop_name = row[shop_col_idx]
                shop_link = row[link_col_idx]
                
                web_content = extract_web_content(shop_link)
                ai_msg = get_ai_message_premium(client, shop_name, shop_link, web_content, rep_name)
                
                # 链接生成
                is_wa_valid = p in wa_valid_set
                wa_link = make_wa_link(p, ai_msg)
                tg_link = make_tg_link(p)
                
                final_results.append({
                    "Shop Name": shop_name,
                    "Phone": p,
                    "AI Message": ai_msg,
                    "WA_Link": wa_link,
                    "TG_Link": tg_link,
                    "Is_WA": is_wa_valid
                })
            ai_bar.progress((idx_step+1)/len(target_phones))
            
        st.subheader("🎯 Qualified Leads")
        
        # === 核心：使用 HTML 渲染按钮 (彻底解决 Streamlit 报错) ===
        for item in final_results:
            with st.expander(f"🏢 {item['Shop Name']} (+{item['Phone']})"):
                st.write(f"**Draft:** {item['AI Message']}")
                
                c1, c2 = st.columns(2)
                
                # WhatsApp 按钮
                with c1:
                    if item['Is_WA']:
                        # 绿色可用按钮
                        st.markdown(f'<a href="{item["WA_Link"]}" target="_blank" class="custom-btn btn-wa">🟢 WhatsApp</a>', unsafe_allow_html=True)
                    else:
                        # 灰色禁用按钮
                        st.markdown(f'<a class="custom-btn btn-disabled">⚪ No WhatsApp</a>', unsafe_allow_html=True)
                
                # Telegram 按钮 (永远可用)
                with c2:
                    st.markdown(f'<a href="{item["TG_Link"]}" target="_blank" class="custom-btn btn-tg">🔵 Telegram</a>', unsafe_allow_html=True)
                    st.caption("Copy text first")
