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

# 忽略 SSL 警告
warnings.filterwarnings("ignore")

# ==========================================
# 🔧 988 Group 企业云端配置 (安全版)
# ==========================================
# 这里不再写死 Key，而是从 Streamlit 云端保险箱读取
# 这样代码上传到 GitHub 就是安全的
CONFIG = {
    "PROXY_URL": None, # 云端无需代理
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# 1. 页面基础设置
st.set_page_config(
    page_title="988 Group - 智能获客系统", 
    layout="wide", 
    page_icon="🚛"
)

# 2. 自定义 CSS
st.markdown("""
<style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    h1 {color: #0e1117; font-family: 'Helvetica', sans-serif;}
    section[data-testid="stSidebar"] {background-color: #f8f9fa;}
    div.stButton > button {
        background-color: #004aad; 
        color: white; 
        border-radius: 8px; 
        font-weight: bold; 
        border: none;
    }
    div.stButton > button:hover {background-color: #003380; color: white;}
    div[data-testid="stExpander"] {border: 1px solid #e0e0e0; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);}
</style>
""", unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)
    else:
        st.markdown("## 🚛 988 Group")
        
    st.markdown("### Intelligent Acquisition System")
    st.caption("Status: Cloud Online 🟢")
    
    st.divider()
    
    # 获取密钥的逻辑：优先从云端 secrets 读取，读取不到则显示输入框
    try:
        default_cn_user = st.secrets["CN_USER_ID"]
        default_cn_key = st.secrets["CN_API_KEY"]
        default_openai = st.secrets["OPENAI_KEY"]
        is_configured = True
    except FileNotFoundError:
        # 如果是本地运行且没配置 secrets.toml，留空
        default_cn_user = ""
        default_cn_key = ""
        default_openai = ""
        is_configured = False

    with st.expander("⚙️ 开发者选项 (Admin)", expanded=False):
        use_proxy = st.checkbox("开启网络代理 (本地调试用)", value=False)
        proxy_port = st.text_input("代理地址", value="http://127.0.0.1:10809")
        
        # 如果云端配置了，这里就显示星号或隐藏
        check_user_id = st.text_input("User ID", value=default_cn_user)
        check_key = st.text_input("CN Key", value=default_cn_key, type="password")
        openai_key = st.text_input("OpenAI Key", value=default_openai, type="password")

# === 核心函数 ===

def get_proxy_config():
    if use_proxy and proxy_port: return proxy_port.strip()
    return None

def extract_all_numbers(row_series):
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    full_text = re.sub(r'[;,\t\n/]+', ' ', full_text)
    digits_only = re.sub(r'[^\d]', ' ', full_text)
    tokens = digits_only.split()
    candidates = []
    for token in tokens:
        clean_num = None
        if len(token) == 11:
            if token.startswith('7'): clean_num = token
            elif token.startswith('8'): clean_num = '7' + token[1:]
        elif len(token) == 10 and token.startswith('9'):
            clean_num = '7' + token  
        if clean_num:
            candidates.append(clean_num)
    return list(set(candidates))

def process_checknumber_task(phone_list):
    if not phone_list: return set()
    valid_numbers_set = set()
    
    api_key = check_key.strip()
    user_id = check_user_id.strip()
    
    if not api_key or not user_id:
        st.error("❌ 缺少 API Key 或 User ID，请检查后台配置。")
        return set()

    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    my_proxy_str = get_proxy_config()
    req_proxies = {"http": my_proxy_str, "https": my_proxy_str} if my_proxy_str else None
    
    status_box = st.status("📡 正在连接验证服务器...", expanded=True)
    status_box.write(f"正在提交 {len(phone_list)} 个号码...")
    
    file_content = "\n".join(phone_list)
    files = {'file': ('input.txt', file_content, 'text/plain')}
    data_payload = {'user_id': user_id} 
    
    try:
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data=data_payload, proxies=req_proxies, timeout=30, verify=False)
        if resp.status_code != 200:
            status_box.update(label="❌ 任务创建失败", state="error")
            st.error(resp.text)
            return set()
        task_id = resp.json().get("task_id")
    except Exception as e:
        status_box.update(label="❌ 网络连接错误", state="error")
        st.error(str(e))
        return set()

    # Polling
    status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
    result_url = None
    
    for i in range(60):
        try:
            time.sleep(4)
            poll_resp = requests.get(status_url, headers=headers, params={'user_id': user_id}, proxies=req_proxies, timeout=30, verify=False)
            if poll_resp.status_code == 200:
                p_data = poll_resp.json()
                status = p_data.get("status")
                done = p_data.get("success", 0) + p_data.get("failure", 0)
                total = p_data.get("total", 1)
                
                status_box.write(f"验证进行中... 进度: {done}/{total} (Status: {status})")
                
                if status in ["exported", "completed"]:
                    result_url = p_data.get("result_url")
                    break
        except: pass
            
    if not result_url:
        status_box.update(label="❌ 验证超时", state="error")
        return set()
        
    try:
        status_box.write("正在下载分析报告...")
        f_resp = requests.get(result_url, proxies=req_proxies, verify=False)
        if f_resp.status_code == 200:
            try: res_df = pd.read_excel(io.BytesIO(f_resp.content))
            except: res_df = pd.read_csv(io.BytesIO(f_resp.content))
            res_df.columns = [c.lower() for c in res_df.columns]
            
            for _, r in res_df.iterrows():
                ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                num = str(r.get('number') or r.get('phone') or '')
                cn = re.sub(r'\D', '', num)
                if "yes" in ws or "valid" in ws:
                    valid_numbers_set.add(cn)
            status_box.update(label=f"✅ 验证完成！发现 {len(valid_numbers_set)} 个有效客户", state="complete")
    except Exception as e:
        status_box.update(label="❌ 解析错误", state="error")

    return valid_numbers_set

def get_ai_message_988(client, shop_name, shop_link):
    if pd.isna(shop_name): shop_name = "Seller"
    if pd.isna(shop_link): shop_link = "Ozon Store"
    
    # 988 Group Prompt
    prompt = f"""
    Role: Senior Manager at "988 Group" (China).
    Target: Ozon Seller "{shop_name}".
    Link: "{shop_link}"
    
    Company: 988 Group - Supply Chain Partner (Sourcing + Logistics to Russia).
    
    Task:
    1. Infer product niche from link.
    2. Write Russian WhatsApp message.
    
    Structure:
    - Hook: Saw your [Niche] store on Ozon.
    - Value: We source these cheaper + handle shipping/customs to Russia.
    - CTA: Quote?
    
    Constraint: Native Russian, <40 words.
    Output: Russian text only.
    """
    
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7, 
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        return f"Здравствуйте, {shop_name}! Мы компания 988 Group. Занимаемся закупкой и доставкой. Интересно?"

def make_wa_link(phone, text):
    return f"https://wa.me/{phone}?text={urllib.parse.quote(text)}"

# === 主程序 ===

st.title("988 Group 客户开发系统")
st.markdown("##### 🚀 全自动采购与物流客户挖掘引擎")

uploaded_file = st.file_uploader("📂 上传表格 (Excel/CSV)", type=['xlsx', 'csv'])

if uploaded_file:
    try:
        if uploaded_file.name.endswith('.csv'): df = pd.read_csv(uploaded_file, header=None)
        else: df = pd.read_excel(uploaded_file, header=None)
        df = df.astype(str)
    except:
        st.stop()
        
    with st.container():
        st.info("👇 请帮助 AI 理解表格结构")
        c1, c2 = st.columns(2)
        with c1:
            shop_col_idx = st.selectbox("🏷️ 店名在第几列?", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2:
            link_col_idx = st.selectbox("🔗 链接在第几列?", range(len(df.columns)), index=0)

    st.markdown("---")

    if st.button("🚀 开始自动化作业 (988 Cloud)", type="primary"):
        my_proxy_str = get_proxy_config()
        
        if not openai_key:
            st.error("❌ 未配置 OpenAI Key，请联系管理员在后台 Secrets 添加。")
            st.stop()

        client = None
        if my_proxy_str:
            try:
                try: http_client = httpx.Client(proxy=my_proxy_str, verify=False)
                except: http_client = httpx.Client(proxies=my_proxy_str, verify=False)
                client = OpenAI(api_key=openai_key, http_client=http_client)
            except: st.error("代理配置失败"); st.stop()
        else:
            client = OpenAI(api_key=openai_key)

        # 1. 提取
        all_raw_phones = set()
        phone_to_rows = {}
        for i, row in df.iterrows():
            extracted = extract_all_numbers(row)
            for p in extracted:
                all_raw_phones.add(p)
                if p not in phone_to_rows: phone_to_rows[p] = []
                phone_to_rows[p].append(i)
        
        if not all_raw_phones:
            st.error("未发现号码")
            st.stop()

        # 2. 验号
        valid_phones_set = process_checknumber_task(list(all_raw_phones))
        
        # 3. 生成
        if valid_phones_set:
            st.success("✅ 号码清洗完成，正在生成文案...")
            final_results = []
            valid_rows_indices = set()
            for p in valid_phones_set:
                for r in phone_to_rows.get(p, []): valid_rows_indices.add(r)
            sorted_indices = sorted(list(valid_rows_indices))
            
            bar = st.progress(0)
            for idx_step, row_idx in enumerate(sorted_indices):
                row = df.iloc[row_idx]
                row_phones = extract_all_numbers(row)
                row_valid = [p for p in row_phones if p in valid_phones_set]
                
                if row_valid:
                    shop_name = row[shop_col_idx]
                    shop_link = row[link_col_idx]
                    ai_msg = get_ai_message_988(client, shop_name, shop_link)
                    links = [make_wa_link(p, ai_msg) for p in row_valid]
                    final_results.append({
                        "店铺名": shop_name,
                        "店铺链接": shop_link,
                        "电话": ", ".join(row_valid),
                        "988定制文案": ai_msg,
                        "WhatsApp链接": " | ".join(links)
                    })
                bar.progress((idx_step+1)/len(sorted_indices))
            
            res_df = pd.DataFrame(final_results)
            st.markdown("### ✅ 结果列表")
            for _, item in res_df.head(50).iterrows():
                with st.expander(f"🏢 {item['店铺名']}"):
                    st.write(item['988定制文案'])
                    for l in item['WhatsApp链接'].split(" | "): 
                        st.link_button("📲 发送", l)
            
            csv = res_df.to_csv(index=False).encode('utf-8-sig')
            st.download_button("📥 下载 Excel", csv, "988_leads.csv", "text/csv")
        else:
            st.warning("未发现有效号码")