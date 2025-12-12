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
# 🔧 988 Group 云端配置
# ==========================================
CONFIG = {
    "PROXY_URL": None, # 云端无需代理
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks"
}

# 1. 页面配置
st.set_page_config(
    page_title="988 Group - 智能获客系统", 
    layout="wide", 
    page_icon="🚛"
)

# 2. CSS 美化
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
    
    /* 数据指标卡片 */
    div[data-testid="stMetricValue"] {
        font-size: 24px;
        color: #004aad;
    }
</style>
""", unsafe_allow_html=True)

# === 侧边栏 ===
with st.sidebar:
    if os.path.exists("logo.png"):
        st.image("logo.png", width=200)
    else:
        st.markdown("## 🚛 988 Group")
        
    st.markdown("### Intelligent Acquisition System")
    st.caption("Status: Cloud Online v20.0 🟢")
    st.divider()
    
    # 密钥读取逻辑
    try:
        default_cn_user = st.secrets["CN_USER_ID"]
        default_cn_key = st.secrets["CN_API_KEY"]
        default_openai = st.secrets["OPENAI_KEY"]
    except FileNotFoundError:
        default_cn_user = ""
        default_cn_key = ""
        default_openai = ""

    with st.expander("⚙️ Admin Settings", expanded=False):
        use_proxy = st.checkbox("开启代理 (本地调试)", value=False)
        proxy_port = st.text_input("代理地址", value="http://127.0.0.1:10809")
        check_user_id = st.text_input("User ID", value=default_cn_user)
        check_key = st.text_input("CN Key", value=default_cn_key, type="password")
        openai_key = st.text_input("OpenAI Key", value=default_openai, type="password")

# === 核心函数 ===

def get_proxy_config():
    if use_proxy and proxy_port: return proxy_port.strip()
    return None

def extract_all_numbers(row_series):
    """
    v20.0 升级版提取算法：
    使用正则模式匹配，而不是简单的 split。
    能够识别带空格、括号、横杠的号码。
    """
    # 1. 拼接整行
    full_text = " ".join([str(val) for val in row_series if pd.notna(val)])
    
    candidates = []
    
    # 2. 正则模式 A: 匹配 7 或 8 开头，后面跟着10个数字（允许中间有分隔符）
    matches_standard = re.findall(r'(\+?(?:7|8)(?:[\s\-\(\)]*\d){10})', full_text)
    
    # 3. 正则模式 B: 匹配 9 开头的10位数字 (这是常见的简写)
    matches_short = re.findall(r'(?:\D|^)(9(?:[\s\-\(\)]*\d){9})(?:\D|$)', full_text)
    
    # 合并结果
    all_raw_matches = matches_standard + matches_short
    
    for raw in all_raw_matches:
        # 统一清洗：去掉所有非数字
        if isinstance(raw, tuple): raw = raw[0] # 处理正则分组
        digits = re.sub(r'\D', '', str(raw))
        
        clean_num = None
        if len(digits) == 11:
            if digits.startswith('7'): clean_num = digits
            elif digits.startswith('8'): clean_num = '7' + digits[1:]
        elif len(digits) == 10 and digits.startswith('9'):
            clean_num = '7' + digits
            
        if clean_num:
            candidates.append(clean_num)
            
    return list(set(candidates))

def process_checknumber_task(phone_list):
    if not phone_list: return set()
    valid_numbers_set = set()
    
    api_key = check_key.strip()
    user_id = check_user_id.strip()
    
    if not api_key or not user_id:
        st.error("❌ 缺少 API Key 或 User ID。")
        return set()

    headers = {"X-API-Key": api_key, "User-Agent": "Mozilla/5.0"}
    my_proxy_str = get_proxy_config()
    req_proxies = {"http": my_proxy_str, "https": my_proxy_str} if my_proxy_str else None
    
    # === 创建任务 ===
    status_box = st.status("📡 正在连接验证服务器...", expanded=True)
    status_box.write(f"正在提交 {len(phone_list)} 个号码进行检测...")
    
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
        return set()

    # === 轮询 ===
    status_url = f"{CONFIG['CN_BASE_URL']}/{task_id}"
    result_url = None
    
    for i in range(80): # 增加等待时间到 400秒，防止大文件超时
        try:
            time.sleep(5)
            poll_resp = requests.get(status_url, headers=headers, params={'user_id': user_id}, proxies=req_proxies, timeout=30, verify=False)
            if poll_resp.status_code == 200:
                p_data = poll_resp.json()
                status = p_data.get("status")
                done = p_data.get("success", 0) + p_data.get("failure", 0)
                total = p_data.get("total", 1)
                
                status_box.write(f"CheckNumber 正在验证... 进度: {done}/{total} (Status: {status})")
                
                if status in ["exported", "completed"]:
                    result_url = p_data.get("result_url")
                    break
        except: pass
            
    if not result_url:
        status_box.update(label="❌ 验证超时", state="error")
        return set()
        
    # === 下载 ===
    try:
        status_box.write("正在下载并分析报告...")
        f_resp = requests.get(result_url, proxies=req_proxies, verify=False)
        if f_resp.status_code == 200:
            try: res_df = pd.read_excel(io.BytesIO(f_resp.content))
            except: res_df = pd.read_csv(io.BytesIO(f_resp.content))
            res_df.columns = [c.lower() for c in res_df.columns]
            
            for _, r in res_df.iterrows():
                ws = str(r.get('whatsapp') or r.get('status') or '').lower()
                num = str(r.get('number') or r.get('phone') or '')
                cn = re.sub(r'\D', '', num)
                # 只要显示有效/存在/yes
                if "yes" in ws or "valid" in ws:
                    valid_numbers_set.add(cn)
            status_box.update(label=f"✅ 验证完成！发现 {len(valid_numbers_set)} 个 WA 活跃账号", state="complete")
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
            shop_col_idx = st.selectbox("🏷️ 店名列", range(len(df.columns)), index=1 if len(df.columns)>1 else 0)
        with c2:
            link_col_idx = st.selectbox("🔗 链接列", range(len(df.columns)), index=0)

    st.markdown("---")

    if st.button("🚀 开始自动化作业 (988 Cloud)", type="primary"):
        
        # 1. 初始化 AI
        my_proxy_str = get_proxy_config()
        if not openai_key:
            st.error("❌ 未配置 OpenAI Key"); st.stop()

        client = None
        if my_proxy_str:
            try:
                try: http_client = httpx.Client(proxy=my_proxy_str, verify=False)
                except: http_client = httpx.Client(proxies=my_proxy_str, verify=False)
                client = OpenAI(api_key=openai_key, http_client=http_client)
            except: st.error("代理配置失败"); st.stop()
        else:
            client = OpenAI(api_key=openai_key)

        # 2. 增强版提取
        all_raw_phones = set()
        phone_to_rows = {}
        
        st.caption("🔍 正在扫描表格中的每一个数字...")
        scan_bar = st.progress(0)
        
        for i, row in df.iterrows():
            extracted = extract_all_numbers(row)
            for p in extracted:
                all_raw_phones.add(p)
                if p not in phone_to_rows: phone_to_rows[p] = []
                phone_to_rows[p].append(i)
            scan_bar.progress((i+1)/len(df))
            
        if not all_raw_phones:
            st.error("表格中未发现号码。")
            st.stop()
            
        # 3. 验号
        valid_phones_set = process_checknumber_task(list(all_raw_phones))
        
        # 4. 生成结果
        if valid_phones_set:
            col1, col2, col3 = st.columns(3)
            col1.metric("原始抓取", len(all_raw_phones))
            col2.metric("✅ WA 有效", len(valid_phones_set))
            rate = len(valid_phones_set)/len(all_raw_phones)*100
            col3.metric("转化率", f"{rate:.1f}%")
            
            st.success("✅ 正在生成 988 Group 专属方案...")
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
            st.warning("处理完成，但 CheckNumber 反馈所有号码均无效。")
