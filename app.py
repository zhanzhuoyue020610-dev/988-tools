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
import random
import json
import base64
from datetime import date, datetime, timedelta
import concurrent.futures
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image # 引入图片处理库

# ==========================================
# 📦 依赖库检查
# ==========================================
try:
    from supabase import create_client, Client
    SUPABASE_INSTALLED = True
except ImportError:
    SUPABASE_INSTALLED = False

try:
    import xlsxwriter
    XLSXWRITER_INSTALLED = True
except ImportError:
    XLSXWRITER_INSTALLED = False

warnings.filterwarnings("ignore")

# ==========================================
# 🎨 UI 主题 & 核心配置
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="G")

CONFIG = {
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks",
    "DAILY_QUOTA": 25,
    "LOW_STOCK_THRESHOLD": 300,
    "POINTS_PER_TASK": 10,
    "POINTS_WECHAT_TASK": 5,
    # 必须使用 gpt-4o，因为只有它具备较好的 spatial coordinates (空间坐标) 能力
    "AI_MODEL": "gpt-4o" 
}

# 注入时钟 HTML
st.markdown("""
<div id="clock-container" style="
    position: fixed; top: 15px; left: 50%; transform: translateX(-50%);
    font-family: 'Inter', monospace; font-size: 15px; color: rgba(255,255,255,0.9);
    z-index: 999999; background: rgba(0,0,0,0.6); padding: 6px 20px; border-radius: 30px;
    backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.15);
    box-shadow: 0 4px 15px rgba(0,0,0,0.3); pointer-events: none; letter-spacing: 1px;
    font-weight: 600; text-shadow: none; display: block !important;
">Initialize...</div>
""", unsafe_allow_html=True)

# 注入 JS
components.html("""
    <script>
        function updateClock() {
            var now = new Date();
            var timeStr = now.getFullYear() + "/" + 
                       String(now.getMonth() + 1).padStart(2, '0') + "/" + 
                       String(now.getDate()).padStart(2, '0') + " " + 
                       String(now.getHours()).padStart(2, '0') + ":" + 
                       String(now.getMinutes()).padStart(2, '0');
            var clock = window.parent.document.getElementById('clock-container');
            if (clock) { clock.innerHTML = timeStr; }
        }
        setInterval(updateClock, 1000);
    </script>
""", height=0)

# 注入 CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');

    :root {
        --text-primary: #e3e3e3;
        --text-secondary: #8e8e8e;
        --accent-gradient: linear-gradient(90deg, #4b90ff, #ff5546); 
        --btn-primary: linear-gradient(90deg, #6366f1, #818cf8);
        --btn-hover: linear-gradient(90deg, #818cf8, #a5b4fc);
        --btn-text: #ffffff;
    }

    * { text-shadow: none !important; -webkit-text-stroke: 0px !important; box-shadow: none !important; -webkit-font-smoothing: antialiased !important; }
    .stApp, [data-testid="stAppViewContainer"] { background-color: #09090b !important; background-image: linear-gradient(135deg, #0f172a 0%, #09090b 100%) !important; color: var(--text-primary) !important; font-family: 'Inter', 'Noto Sans SC', sans-serif !important; }
    [data-testid="stAppViewContainer"]::after { content: ""; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: linear-gradient(115deg, transparent 40%, rgba(255,255,255,0.03) 50%, transparent 60%); background-size: 200% 100%; animation: shimmer 8s infinite linear; pointer-events: none; z-index: 0; }
    @keyframes shimmer { 0% { background-position: 200% 0; } 100% { background-position: -200% 0; } }
    .block-container { position: relative; z-index: 10 !important; }
    [data-testid="stHeader"] { background-color: transparent !important; }
    p, h1, h2, h3, h4, h5, h6, span, label, div[data-testid="stMarkdownContainer"] { background-color: transparent !important; }
    .gemini-header { font-weight: 600; font-size: 28px; background: var(--accent-gradient); -webkit-background-clip: text; -webkit-text-fill-color: transparent; letter-spacing: 1px; margin-bottom: 5px; }
    .warm-quote { font-size: 13px; color: #8e8e8e; letter-spacing: 0.5px; margin-bottom: 25px; font-style: normal; }
    .points-pill { background-color: rgba(255, 255, 255, 0.05) !important; color: #e3e3e3; border: 1px solid rgba(255, 255, 255, 0.1); padding: 6px 16px; border-radius: 20px; font-size: 13px; font-family: 'Inter', monospace; }
    div[data-testid="stRadio"] > div { background-color: rgba(30, 31, 32, 0.6) !important; backdrop-filter: blur(10px); border: 1px solid rgba(255,255,255,0.1); padding: 6px; border-radius: 50px; gap: 0px; display: inline-flex; }
    div[data-testid="stRadio"] label { background-color: transparent !important; color: var(--text-secondary) !important; padding: 8px 24px; border-radius: 40px; font-size: 15px; transition: all 0.3s ease; border: none; }
    div[data-testid="stRadio"] label[data-checked="true"] { background-color: #3c4043 !important; color: #ffffff !important; font-weight: 500; }
    div[data-testid="stExpander"], div[data-testid="stForm"], div.stDataFrame { background-color: rgba(30, 31, 32, 0.6) !important; backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.08) !important; border-radius: 12px; padding: 15px; }
    div[data-testid="stExpander"] details { border: none !important; }
    div[data-testid="stExpander"] summary { color: white !important; background-color: transparent !important; }
    div[data-testid="stExpander"] summary:hover { color: #6366f1 !important; }
    button { color: var(--btn-text) !important; }
    div.stButton > button, div.stFormSubmitButton > button { background: var(--btn-primary) !important; color: var(--btn-text) !important; border: none !important; border-radius: 50px !important; padding: 10px 24px !important; font-weight: 600; letter-spacing: 1px; transition: all 0.2s ease; box-shadow: 0 4px 15px rgba(99, 102, 241, 0.2) !important; }
    div.stButton > button:hover, div.stFormSubmitButton > button:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(99, 102, 241, 0.4) !important; }
    div[data-baseweb="input"], div[data-baseweb="select"] { background-color: rgba(45, 46, 51, 0.8) !important; border: 1px solid #444 !important; border-radius: 8px !important; color: white !important; }
    input { color: white !important; caret-color: #6366f1; background-color: transparent !important; }
    ::placeholder { color: #5f6368 !important; }
    [data-testid="stFileUploader"] { background-color: transparent !important; }
    [data-testid="stFileUploader"] section { background-color: rgba(45, 46, 51, 0.5) !important; border: 1px dashed #555 !important; }
    [data-testid="stFileUploader"] button { background-color: #303134 !important; color: #e3e3e3 !important; border: 1px solid #444 !important; }
    .custom-alert { padding: 12px 16px; border-radius: 8px; font-size: 14px; margin-bottom: 12px; color: #e3e3e3; display: flex; align-items: center; background-color: rgba(255, 255, 255, 0.05); border: 1px solid #444; }
    .alert-error { background-color: rgba(255, 85, 70, 0.15) !important; border-color: #ff5f56 !important; color: #ff5f56 !important; }
    .alert-success { background-color: rgba(63, 185, 80, 0.15) !important; border-color: #3fb950 !important; color: #3fb950 !important; }
    .alert-info { background-color: rgba(56, 139, 253, 0.15) !important; border-color: #58a6ff !important; color: #58a6ff !important; }
    div[data-testid="stDataFrame"] div[role="grid"] { background-color: rgba(30, 31, 32, 0.6) !important; color: var(--text-secondary); }
    .stProgress > div > div > div > div { background: var(--accent-gradient) !important; height: 4px !important; border-radius: 10px; }
    h1, h2, h3, h4 { color: #ffffff !important; font-weight: 500 !important;}
    .stCaption { color: #8e8e8e !important; }
</style>
""", unsafe_allow_html=True)

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
            if res.data[0]['role'] != 'admin':
                supabase.table('users').update({'last_seen': datetime.now().isoformat()}).eq('username', u).execute()
            return res.data[0]
        return None
    except: return None

def create_user(u, p, n, role="sales"):
    if not supabase: return False
    try:
        pwd = hash_password(p)
        supabase.table('users').insert({"username": u, "password": pwd, "role": role, "real_name": n, "points": 0, "daily_limit": CONFIG["DAILY_QUOTA"]}).execute()
        return True
    except: return False

def update_user_profile(old_username, new_username, new_password=None, new_realname=None):
    if not supabase: return False
    try:
        update_data = {}
        if new_password: update_data['password'] = hash_password(new_password)
        if new_realname: update_data['real_name'] = new_realname
        if new_username and new_username != old_username:
            update_data['username'] = new_username
            supabase.table('users').update(update_data).eq('username', old_username).execute()
            supabase.table('leads').update({'assigned_to': new_username}).eq('assigned_to', old_username).execute()
            supabase.table('wechat_customers').update({'assigned_to': new_username}).eq('assigned_to', old_username).execute()
        else:
            supabase.table('users').update(update_data).eq('username', old_username).execute()
        return True
    except: return False

def add_user_points(username, amount):
    if not supabase: return
    try:
        user = supabase.table('users').select('points').eq('username', username).single().execute()
        current_points = user.data.get('points', 0) or 0
        supabase.table('users').update({'points': current_points + amount}).eq('username', username).execute()
    except: pass

def get_user_points(username):
    if not supabase: return 0
    try:
        res = supabase.table('users').select('points').eq('username', username).single().execute()
        return res.data.get('points', 0) or 0
    except: return 0

def get_user_limit(username):
    if not supabase: return CONFIG["DAILY_QUOTA"]
    try:
        res = supabase.table('users').select('daily_limit').eq('username', username).single().execute()
        return res.data.get('daily_limit') or CONFIG["DAILY_QUOTA"]
    except: return CONFIG["DAILY_QUOTA"]

def update_user_limit(username, new_limit):
    if not supabase: return False
    try:
        supabase.table('users').update({'daily_limit': new_limit}).eq('username', username).execute()
        return True
    except: return False

# --- 🚀 报价单生成引擎 (XlsxWriter) ---
def generate_quotation_excel(items, service_fee_percent, total_domestic_freight, company_info):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet("Sheet1")

    # 样式定义
    fmt_header_main = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
    fmt_header_sub = workbook.add_format({'font_size': 11, 'align': 'left', 'valign': 'vcenter', 'text_wrap': True})
    fmt_table_header = workbook.add_format({'bold': True, 'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#f0f0f0', 'text_wrap': True})
    fmt_cell_center = workbook.add_format({'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
    fmt_cell_left = workbook.add_format({'font_size': 10, 'align': 'left', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
    fmt_money = workbook.add_format({'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '¥#,##0.00'})
    fmt_bold_red = workbook.add_format({'bold': True, 'color': 'red', 'font_size': 11})
    fmt_total_row = workbook.add_format({'bold': True, 'font_size': 11, 'align': 'right', 'valign': 'vcenter', 'border': 1, 'bg_color': '#e6e6e6'})
    fmt_total_money = workbook.add_format({'bold': True, 'font_size': 11, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '¥#,##0.00', 'bg_color': '#e6e6e6'})

    # 1. 写入表头信息
    worksheet.merge_range('A1:H2', company_info.get('name', "义乌市万昶进出口有限公司"), fmt_header_main)
    contact_text = f"TEL: {company_info.get('tel', '')}    E-mail: {company_info.get('email', '')}"
    worksheet.merge_range('A3:H3', contact_text, fmt_header_sub)
    worksheet.merge_range('A4:H4', f"Address: {company_info.get('addr', '')}", fmt_header_sub)
    worksheet.merge_range('A6:H6', "* This price is valid for 10 days / Эта цена действительна в течение 10 дней", fmt_bold_red)

    # 2. 写入表格列名
    headers = [
        ("序号\nNo.", 4), 
        ("型号\nArticul", 15), 
        ("图片\nPhoto", 15), 
        ("名称\nName", 15), 
        ("产品描述\nDescription", 25), 
        ("数量\nQty", 8), 
        ("单价 ￥\nPrice", 12), 
        ("货值 ￥\nTotal Value", 12)
    ]
    
    start_row = 8 
    for col, (h_text, width) in enumerate(headers):
        worksheet.write(start_row, col, h_text, fmt_table_header)
        worksheet.set_column(col, col, width)

    current_row = start_row + 1
    total_product_value = 0

    for idx, item in enumerate(items, 1):
        qty = float(item.get('qty', 0))
        factory_price_unit = float(item.get('price_exw', 0))
        
        final_unit_price = factory_price_unit * (1 + service_fee_percent / 100.0)
        line_total = final_unit_price * qty
        total_product_value += line_total

        worksheet.set_row(current_row, 80)
        worksheet.write(current_row, 0, idx, fmt_cell_center)
        worksheet.write(current_row, 1, item.get('model', ''), fmt_cell_center)
        
        if item.get('image_data'):
            img_data = io.BytesIO(item['image_data'])
            worksheet.insert_image(current_row, 2, "img.png", {'image_data': img_data, 'x_scale': 0.5, 'y_scale': 0.5, 'object_position': 1})
        else:
            worksheet.write(current_row, 2, "No Image", fmt_cell_center)

        worksheet.write(current_row, 3, item.get('name', ''), fmt_cell_left)
        worksheet.write(current_row, 4, item.get('desc', ''), fmt_cell_left)
        worksheet.write(current_row, 5, qty, fmt_cell_center)
        worksheet.write(current_row, 6, final_unit_price, fmt_money)
        worksheet.write(current_row, 7, line_total, fmt_money)
        
        current_row += 1

    # 4. 底部合计
    if total_domestic_freight > 0:
        worksheet.merge_range(current_row, 0, current_row, 6, "Domestic Freight (China) / 中国国内运费", fmt_total_row)
        worksheet.write(current_row, 7, total_domestic_freight, fmt_total_money)
        current_row += 1
    
    grand_total = total_product_value + total_domestic_freight
    
    worksheet.merge_range(current_row, 0, current_row, 6, "GRAND TOTAL / 合计总额", fmt_total_row)
    worksheet.write(current_row, 7, grand_total, fmt_total_money)

    workbook.close()
    output.seek(0)
    return output

# --- 图片裁剪辅助函数 ---
def crop_image_by_bbox(original_image_bytes, bbox_1000):
    """
    根据 AI 返回的 0-1000 坐标系裁剪图片
    bbox_1000: [ymin, xmin, ymax, xmax]
    """
    try:
        if not bbox_1000 or len(bbox_1000) != 4: return original_image_bytes
        
        # 转换为 PIL Image
        img = Image.open(io.BytesIO(original_image_bytes))
        width, height = img.size
        
        # 解析相对坐标
        ymin, xmin, ymax, xmax = bbox_1000
        
        # 转换为绝对像素坐标
        left = int(xmin / 1000 * width)
        top = int(ymin / 1000 * height)
        right = int(xmax / 1000 * width)
        bottom = int(ymax / 1000 * height)
        
        # 边界检查
        left = max(0, left); top = max(0, top)
        right = min(width, right); bottom = min(height, bottom)
        
        # 如果裁剪区域太小（可能是 AI 幻觉），返回原图或不做裁剪
        if (right - left) < 10 or (bottom - top) < 10:
            return original_image_bytes

        # 执行裁剪
        cropped_img = img.crop((left, top, right, bottom))
        
        # 转回 BytesIO
        output = io.BytesIO()
        cropped_img.save(output, format=img.format if img.format else 'PNG')
        return output.getvalue()
    except Exception as e:
        print(f"Crop Failed: {e}")
        return original_image_bytes

# --- AI Parsing Logic ---
# 🔥 终极升级：表格扫描 + 坐标定位 (Table Scanning + Bounding Box)
def parse_image_with_ai(image_file, client):
    if not image_file: return None
    
    base64_image = base64.b64encode(image_file.getvalue()).decode('utf-8')
    
    # 核心指令：要求 AI 不仅提取文字，还要返回缩略图的坐标
    prompt = """
    Role: You are an advanced OCR & Data Extraction engine specialized in Chinese E-commerce Order Forms (1688/Taobao).
    
    CONTEXT: The user has uploaded a screenshot of a product list (Order Manifest).
    
    YOUR MISSION:
    1. **SCAN FOR TEXT ROWS**: Extract EACH variant row (e.g., "500ml" row, "1000ml" row) as a separate item.
    2. **EXTRACT THUMBNAIL COORDINATES**: For EACH row, identify the location of the small product thumbnail image on the left.
       - Return coordinates as `bbox_1000`: `[ymin, xmin, ymax, xmax]` on a 0-1000 normalized scale.
       - This is critical for cropping the correct image.
    
    DATA EXTRACTION RULES:
    - **Name**: Main product name (Translate to Russian).
    - **Model/Spec**: The specific variant text (e.g., "500ml White").
    - **Desc**: ULTRA SHORT summary (max 5 words). E.g., "Plastic Cup 500ml". Translate to Russian.
    - **Price**: Extract the price for *this specific row*.
    - **Qty**: Extract quantity for *this specific row*.
    
    Output Format (JSON):
    {
        "items": [
            { 
              "name_ru": "...", 
              "model": "500ml", 
              "desc_ru": "...", 
              "price_cny": 5.5, 
              "qty": 100,
              "bbox_1000": [150, 10, 250, 150]  // [ymin, xmin, ymax, xmax]
            },
            ...
        ]
    }
    """
    
    vision_model = "gpt-4o" 
    
    try:
        res = client.chat.completions.create(
            model=vision_model, 
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]
                }
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        print(f"Vision Error: {e}")
        return None

def parse_product_info_with_ai(text_content, client):
    if not text_content: return None
    
    prompt = f"""
    You are a professional B2B trade assistant.
    Analyze the user input.
    
    Output Format:
    Return ONLY a JSON object:
    {{
        "name_ru": "...",
        "model": "...",
        "price_cny": 0.0,
        "qty": 0,
        "desc_ru": "Short summary (under 5 words)"
    }}
    """
    try:
        res = client.chat.completions.create(
            model=CONFIG["AI_MODEL"],
            messages=[{"role":"user", "content": prompt}],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        return None

# --- AI Logic (Generic) ---
def get_daily_motivation(client):
    if "motivation_quote" not in st.session_state:
        local_quotes = ["心有繁星，沐光而行。", "坚持是另一种形式的天赋。", "沉稳是职场最高级的修养。", "每一步都算数。", "保持专注，未来可期。"]
        try:
            if not client: raise Exception("No Client")
            prompt = "你是专业的职场心理咨询师。请生成一句温暖、治愈的中文短句，不超过25字。不要带引号，不要使用任何表情符号。"
            res = client.chat.completions.create(
                model=CONFIG["AI_MODEL"], messages=[{"role":"user","content":prompt}], temperature=0.9, max_tokens=60
            )
            st.session_state["motivation_quote"] = res.choices[0].message.content
        except:
            st.session_state["motivation_quote"] = random.choice(local_quotes)
    return st.session_state["motivation_quote"]

def get_ai_message_sniper(client, shop, link, rep_name):
    offline_template = f"Здравствуйте! Заметили ваш магазин {shop} на Ozon. {rep_name} из 988 Group на связи. Мы занимаемся поставками из Китая. Можем рассчитать логистику?"
    if not shop or str(shop).lower() in ['nan', 'none', '']: return "数据缺失"
    prompt = f"""
    Role: Supply Chain Manager '{rep_name}' at 988 Group.
    Target: Ozon Seller '{shop}' (Link: {link}).
    Task: Write a Russian WhatsApp intro (under 50 words).
    RULES:
    1. Introduce yourself exactly as: "{rep_name} (988 Group)".
    2. NO placeholders like [Name]. NO Emojis.
    3. Mention sourcing + logistics benefits.
    4. Ask if they want a calculation.
    """
    try:
        if not client: return offline_template
        res = client.chat.completions.create(model=CONFIG["AI_MODEL"],messages=[{"role":"user","content":prompt}])
        content = res.choices[0].message.content.strip()
        if "[" in content or "]" in content: return offline_template
        return content
    except: return offline_template

def get_wechat_maintenance_script(client, customer_code, rep_name):
    offline = f"您好，我是 988 Group 的 {rep_name}。最近生意如何？工厂那边出了一些新品，如果您需要补货或者看新款，随时联系我。"
    prompt = f"""
    Role: Key Account Manager '{rep_name}' at 988 Group.
    Target: Existing Customer '{customer_code}' on WeChat.
    Task: Write a short, warm, Chinese maintenance message.
    RULES:
    1. Tone: Professional and warm.
    2. NO placeholders. NO Emojis.
    3. Keep it under 50 words.
    """
    try:
        if not client: return offline
        res = client.chat.completions.create(model=CONFIG["AI_MODEL"],messages=[{"role":"user","content":prompt}])
        return res.choices[0].message.content.strip()
    except: return offline

def generate_and_update_task(lead, client, rep_name):
    try:
        msg = get_ai_message_sniper(client, lead['shop_name'], lead['shop_link'], rep_name)
        supabase.table('leads').update({'ai_message': msg}).eq('id', lead['id']).execute()
        return True
    except: return False

def transcribe_audio(client, audio_file):
    try:
        transcript = client.audio.transcriptions.create(model="whisper-1", file=audio_file, language="ru")
        ru_text = transcript.text
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a professional translator. Translate the following Russian business inquiry into clear, professional Chinese."},
                {"role": "user", "content": ru_text}
            ]
        )
        cn_text = completion.choices[0].message.content
        return ru_text, cn_text
    except Exception as e:
        return f"Error: {str(e)}", "Translation Failed"

# --- WeChat Logic ---
def get_wechat_tasks(username):
    if not supabase: return []
    today = date.today().isoformat()
    try:
        res = supabase.table('wechat_customers').select("*").eq('assigned_to', username).lte('next_contact_date', today).execute()
        return res.data
    except: return []

def complete_wechat_task(task_id, cycle_days, username):
    if not supabase: return
    today = date.today()
    next_date = (today + timedelta(days=cycle_days)).isoformat()
    try:
        supabase.table('wechat_customers').update({
            'last_contact_date': today.isoformat(),
            'next_contact_date': next_date
        }).eq('id', task_id).execute()
        add_user_points(username, CONFIG["POINTS_WECHAT_TASK"])
    except: pass

def admin_import_wechat_customers(df_raw):
    if not supabase: return False
    try:
        rows = []
        for _, row in df_raw.iterrows():
            code = str(row.get('客户编号', 'Unknown'))
            user = str(row.get('业务员', 'admin'))
            cycle = int(row.get('周期', 7))
            rows.append({"customer_code": code, "assigned_to": user, "cycle_days": cycle, "next_contact_date": date.today().isoformat()})
        if rows: supabase.table('wechat_customers').insert(rows).execute()
        return True
    except: return False

# --- WA Logic ---
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
        res_list = supabase.table('leads').select('shop_name, phone, shop_link, completed_at').eq('assigned_to', username).eq('is_contacted', True).order('completed_at', desc=True).limit(1000).execute()
        return total_claimed, total_done, pd.DataFrame(res_list.data)
    except: return 0, 0, pd.DataFrame()

def get_public_pool_count():
    if not supabase: return 0
    try:
        res = supabase.table('leads').select('id', count='exact').is_('assigned_to', 'null').execute()
        return res.count
    except: return 0

def get_frozen_leads_count():
    if not supabase: return 0, []
    try:
        res = supabase.table('leads').select('id, shop_name, error_log, retry_count').eq('is_frozen', True).execute()
        return len(res.data), res.data
    except: return 0, []

def recycle_expired_tasks():
    if not supabase: return 0
    today_str = date.today().isoformat()
    try:
        res = supabase.table('leads').update({'assigned_to': None, 'assigned_at': None, 'ai_message': None}).lt('assigned_at', today_str).eq('is_contacted', False).execute()
        return len(res.data)
    except: return 0

def delete_user_and_recycle(username):
    if not supabase: return False
    try:
        supabase.table('leads').update({'assigned_to': None, 'assigned_at': None, 'is_contacted': False, 'ai_message': None}).eq('assigned_to', username).eq('is_contacted', False).execute()
        supabase.table('wechat_customers').update({'assigned_to': None}).eq('assigned_to', username).execute()
        supabase.table('users').delete().eq('username', username).execute()
        return True
    except: return False

def admin_bulk_upload_to_pool(rows_to_insert):
    if not supabase or not rows_to_insert: return 0, "No data to insert"
    success_count = 0
    incoming_phones = [str(r['phone']) for r in rows_to_insert]
    try:
        existing_phones = set()
        chunk_size = 500
        for i in range(0, len(incoming_phones), chunk_size):
            batch = incoming_phones[i:i+chunk_size]
            res = supabase.table('leads').select('phone').in_('phone', batch).execute()
            for item in res.data: existing_phones.add(str(item['phone']))
        
        final_rows = [r for r in rows_to_insert if str(r['phone']) not in existing_phones]
        if not final_rows: return 0, f"所有 {len(rows_to_insert)} 个号码均已存在。"
        
        for row in final_rows: row['username'] = st.session_state.get('username', 'admin')

        response = supabase.table('leads').insert(final_rows).execute()
        if len(response.data) == 0: return 0, "⚠️ RLS 权限拒绝，请检查 Supabase 策略。"
        return len(response.data), "Success"

    except Exception as e:
        err_msg = str(e)
        for row in final_rows:
            try:
                row['username'] = st.session_state.get('username', 'admin')
                supabase.table('leads').insert(row).execute()
                success_count += 1
            except: pass
        if success_count > 0: return success_count, f"批量失败，逐条成功 {success_count} 个"
        else: return 0, f"入库失败: {err_msg}"

def claim_daily_tasks(username, client):
    today_str = date.today().isoformat()
    existing = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    current_count = len(existing)
    
    user_max_limit = get_user_limit(username)
    
    if current_count >= user_max_limit: 
        return existing, "full"
    
    needed = user_max_limit - current_count
    pool_leads = supabase.table('leads').select("id").is_('assigned_to', 'null').eq('is_frozen', False).limit(needed).execute().data
    
    if pool_leads:
        ids_to_update = [x['id'] for x in pool_leads]
        supabase.table('leads').update({'assigned_to': username, 'assigned_at': today_str}).in_('id', ids_to_update).execute()
        fresh_tasks = supabase.table('leads').select("*").in_('id', ids_to_update).execute().data
        
        with st.status(f"正在为 {username} 生成专属文案...", expanded=True) as status:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(generate_and_update_task, task, client, username) for task in fresh_tasks]
                concurrent.futures.wait(futures)
            status.update(label="文案生成完毕", state="complete")
        
        final_list = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
        return final_list, "claimed"
    else: return existing, "empty"

def get_todays_leads(username, client):
    today_str = date.today().isoformat()
    leads = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    to_heal = [l for l in leads if not l['ai_message']]
    if to_heal:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            [executor.submit(generate_and_update_task, t, client, username) for t in to_heal]
        leads = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    return leads

def mark_lead_complete_secure(lead_id, username):
    if not supabase: return
    now_iso = datetime.now().isoformat()
    supabase.table('leads').update({'is_contacted': True, 'completed_at': now_iso}).eq('id', lead_id).execute()
    add_user_points(username, CONFIG["POINTS_PER_TASK"])

def get_daily_logs(query_date):
    if not supabase: return pd.DataFrame(), pd.DataFrame()
    try:
        raw_claims = supabase.table('leads').select('assigned_to, assigned_at').eq('assigned_at', query_date).execute().data
        df_claims = pd.DataFrame(raw_claims)
        if not df_claims.empty:
            df_claims = df_claims[df_claims['assigned_to'] != 'admin'] 
            df_claim_summary = df_claims.groupby('assigned_to').size().reset_index(name='领取数量')
        else: df_claim_summary = pd.DataFrame(columns=['assigned_to', '领取数量'])
        
        start_dt = f"{query_date}T00:00:00"
        end_dt = f"{query_date}T23:59:59"
        raw_done = supabase.table('leads').select('assigned_to, completed_at').gte('completed_at', start_dt).lte('completed_at', end_dt).execute().data
        df_done = pd.DataFrame(raw_done)
        if not df_done.empty:
            df_done = df_done[df_done['assigned_to'] != 'admin']
            df_done_summary = df_done.groupby('assigned_to').size().reset_index(name='实际处理')
        else: df_done_summary = pd.DataFrame(columns=['assigned_to', '实际处理'])
        return df_claim_summary, df_done_summary
    except Exception: return pd.DataFrame(), pd.DataFrame()

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
    if not phone_list: return {}, "Empty List", None
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key}
    try:
        files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, verify=False)
        if resp.status_code != 200: return status_map, f"API Upload Error: {resp.status_code}", None
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
                        ws = str(r.get('whatsapp') or r.get('status') or r.get('Status') or '').lower()
                        nm_col = next((c for c in df.columns if 'number' in c.lower() or 'phone' in c.lower()), None)
                        if nm_col:
                            nm = re.sub(r'\D', '', str(r[nm_col]))
                            if any(x in ws for x in ['yes', 'valid', 'active', 'true', 'ok']): status_map[nm] = 'valid'
                            else: status_map[nm] = 'invalid'
                    return status_map, "Success", df
        return status_map, "Timeout", None
    except Exception as e: return status_map, str(e), None

def check_api_health(cn_user, cn_key, openai_key):
    status = {"supabase": False, "checknumber": False, "openai": False, "msg": []}
    try:
        if supabase:
            supabase.table('users').select('count', count='exact').limit(1).execute()
            status["supabase"] = True
    except Exception as e: status["msg"].append(f"Supabase: {str(e)}")
    try:
        headers = {"X-API-Key": cn_key}
        test_url = f"{CONFIG['CN_BASE_URL']}" 
        resp = requests.get(test_url, headers=headers, params={'user_id': cn_user}, timeout=5, verify=False)
        if resp.status_code in [200, 400, 404, 405]: status["checknumber"] = True
        else: status["msg"].append(f"CheckNumber: {resp.status_code}")
    except Exception as e: status["msg"].append(f"CheckNumber: {str(e)}")
    try:
        if not openai_key or "sk-" not in openai_key: status["msg"].append("OpenAI: 格式错误")
        else:
            client = OpenAI(api_key=openai_key)
            client.chat.completions.create(model=CONFIG["AI_MODEL"], messages=[{"role":"user","content":"Hi"}], max_tokens=1)
            status["openai"] = True
    except Exception as e: status["msg"].append(f"OpenAI: {str(e)}")
    return status

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
            u = st.text_input("Account ID", placeholder="请输入账号")
            p = st.text_input("Password", type="password", placeholder="请输入密码")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("登 录"):
                user = login_user(u, p)
                if user:
                    st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                    st.rerun()
                else:
                    st.markdown('<div class="custom-alert alert-error">账号或密码错误</div>', unsafe_allow_html=True)
    st.stop()

# ==========================================
# 🚀 内部主界面
# ==========================================
try:
    CN_USER = st.secrets["CN_USER_ID"]
    CN_KEY = st.secrets["CN_API_KEY"]
    OPENAI_KEY = st.secrets["OPENAI_KEY"]
except: CN_USER=""; CN_KEY=""; OPENAI_KEY=""

client = None
try:
    if OPENAI_KEY: client = OpenAI(api_key=OPENAI_KEY)
except: pass

quote = get_daily_motivation(client)
points = get_user_points(st.session_state['username'])

# 顶部栏
c_title, c_user = st.columns([4, 2])
with c_title:
    st.markdown(f'<div class="gemini-header">你好, {st.session_state["real_name"]}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="warm-quote">{quote}</div>', unsafe_allow_html=True)

with c_user:
    st.markdown(f"""
    <div style="text-align:right; margin-top:5px;">
        <span class="points-pill">积分: {points}</span>
        <span style="color:#3c4043; margin:0 10px;">|</span>
        <span style="font-size:14px; color:#e3e3e3;">{st.session_state['role'].upper()}</span>
    </div>
    """, unsafe_allow_html=True)
    c_null, c_out = st.columns([3, 1])
    with c_out:
        if st.button("退出", key="logout"): st.session_state.clear(); st.rerun()

st.divider()

if st.session_state['role'] == 'admin':
    menu_map = {"System": "系统监控", "Logs": "活动日志", "Team": "团队管理", "Import": "批量进货", "Quotation": "报价生成器", "WeChat": "微信管理", "Tools": "实用工具"}
    menu_options = ["System", "Logs", "Team", "Import", "Quotation", "WeChat", "Tools"]
else:
    menu_map = {"Workbench": "销售工作台", "Quotation": "报价生成器", "WeChat": "微信维护", "Tools": "实用工具"}
    menu_options = ["Workbench", "Quotation", "WeChat", "Tools"]

selected_nav = st.radio("导航菜单", menu_options, format_func=lambda x: menu_map.get(x, x), horizontal=True, label_visibility="collapsed")
st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------------
# 💰 Quotation (报价生成器) - 核心修改部分
# ------------------------------------------
if selected_nav == "Quotation":
    if not XLSXWRITER_INSTALLED:
        st.error("未安装 XlsxWriter 库。请联系管理员运行 `pip install XlsxWriter`")
    else:
        if "quote_items" not in st.session_state: st.session_state["quote_items"] = []

        # 双模式 TAB
        tab_manual, tab_ai = st.tabs(["✍️ 人工录入", "🤖 AI 智能识别 (支持图片/链接)"])

        # --- 模式1：人工录入 ---
        with tab_manual:
            with st.form("add_item_form_manual", clear_on_submit=True):
                c_img, c_main = st.columns([1, 4])
                with c_img:
                    img_file = st.file_uploader("商品图片", type=['png', 'jpg', 'jpeg'])
                with c_main:
                    c1, c2, c3 = st.columns(3)
                    model = c1.text_input("型号 (Articul)")
                    name = c2.text_input("俄语名称 (Name RU)")
                    price_exw = c3.number_input("工厂单价 (¥)", min_value=0.0, step=0.1)
                    
                    c4, c5 = st.columns([1, 2])
                    qty = c4.number_input("数量 (Qty)", min_value=1, step=1)
                    desc = c5.text_input("产品描述 (选填)")
                
                if st.form_submit_button("➕ 添加到清单"):
                    img_data = img_file.getvalue() if img_file else None
                    item = {"model": model, "name": name, "desc": desc, "price_exw": price_exw, "qty": qty, "image_data": img_data}
                    st.session_state["quote_items"].append(item)
                    st.success("已添加")
                    st.rerun()

        # --- 模式2：AI 智能识别 (升级版) ---
        with tab_ai:
            st.info("💡 提示：支持两种方式\n1. 复制 1688 链接/聊天文字\n2. 直接上传产品图片 (AI 会自动看图填表，支持多商品)")
            
            c_text_ai, c_img_ai = st.columns([2, 1])
            with c_text_ai:
                ai_input_text = st.text_area("📄 方式一：粘贴文字/链接", height=120, placeholder="例如：这款黑色的包，价格25元，我要100个")
            with c_img_ai:
                ai_input_image = st.file_uploader("🖼️ 方式二：上传产品图", type=['jpg', 'png', 'jpeg'])
            
            # AI 处理逻辑
            if st.button("✨ 开始 AI 识别"):
                with st.status("正在唤醒 AI 引擎...", expanded=True) as status:
                    new_items = []
                    
                    # 优先处理图片
                    if ai_input_image:
                        status.write("👁️ 正在进行多目标视觉分析 & 自动裁剪...")
                        
                        original_bytes = ai_input_image.getvalue()
                        ai_res = parse_image_with_ai(ai_input_image, client)
                        
                        # 处理返回的列表 (支持多商品)
                        if ai_res and "items" in ai_res:
                            for raw_item in ai_res["items"]:
                                
                                # 核心：根据 AI 返回的 bbox 裁剪图片
                                cropped_bytes = original_bytes # 默认使用原图
                                if "bbox_1000" in raw_item:
                                    cropped_bytes = crop_image_by_bbox(original_bytes, raw_item["bbox_1000"])
                                
                                new_items.append({
                                    "model": raw_item.get('model', ''), 
                                    "name": raw_item.get('name_ru', 'Товар'), 
                                    "desc": raw_item.get('desc_ru', ''), 
                                    "price_exw": float(raw_item.get('price_cny', 0)), 
                                    "qty": int(raw_item.get('qty', 1)), 
                                    "image_data": cropped_bytes # 使用裁剪后的图
                                })
                        
                    # 其次处理文字
                    elif ai_input_text:
                        status.write("🧠 正在理解语义...")
                        ai_res = parse_product_info_with_ai(ai_input_text, client)
                        if ai_res:
                             new_items.append({
                                "model": ai_res.get('model', ''), 
                                "name": ai_res.get('name_ru', 'Товар'), 
                                "desc": ai_res.get('desc_ru', ''), 
                                "price_exw": float(ai_res.get('price_cny', 0)), 
                                "qty": int(ai_res.get('qty', 1)), 
                                "image_data": None
                            })
                    
                    if new_items:
                        st.session_state["quote_items"].extend(new_items)
                        status.update(label=f"成功识别 {len(new_items)} 个商品 (已自动裁剪)", state="complete")
                        time.sleep(1)
                        st.rerun()
                    else:
                        status.update(label="识别失败", state="error")
                        st.error("无法提取有效信息，请确保图片清晰")

        st.divider()

        # --- 下方：全局设置 & 预览 ---
        col_list, col_setting = st.columns([2.5, 1.5])

        with col_list:
            st.markdown("#### 📋 待报价商品清单")
            items = st.session_state["quote_items"]
            if items:
                df_show = pd.DataFrame(items)
                if not df_show.empty:
                    st.dataframe(df_show[['model', 'name', 'desc', 'price_exw', 'qty']], use_container_width=True, 
                                 column_config={"model":"型号", "name":"俄语品名", "desc":"简述", "price_exw":"工厂价", "qty":"数量"})
                
                if st.button("🗑️ 清空所有商品"):
                    st.session_state["quote_items"] = []
                    st.rerun()
            else:
                st.caption("暂无商品，请在上方添加")

        with col_setting:
            st.markdown("#### ⚙️ 报价单全局设置")
            
            # 运费逻辑变更：独立行
            total_freight = st.number_input("🚛 国内总运费 (Total Freight ¥)", min_value=0.0, step=10.0, help="这笔费用将单独列示在报价单底部，不会分摊到单价中")
            service_fee = st.slider("💰 服务费率 (Profit %)", 0, 50, 5)
            
            with st.expander("🏢 公司表头信息"):
                co_name = st.text_input("公司名称", value="义乌市万昶进出口有限公司")
                co_tel = st.text_input("电话", value="+86-15157938188")
                co_email = st.text_input("邮箱", value="CTF1111@163.com")
                co_addr = st.text_input("地址", value="义乌市工人北路1121号5楼")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if items:
                # 预览最终价格
                product_total = sum(i['price_exw'] * i['qty'] * (1 + service_fee/100) for i in items)
                final_val = product_total + total_freight
                
                st.markdown(f"""
                <div style="padding:15px; border:1px solid #444; border-radius:10px; background:rgba(255,255,255,0.05)">
                    <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e">
                        <span>商品总额 (含服务费):</span> <span>¥ {product_total:,.2f}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e; margin-top:5px;">
                        <span>+ 国内运费:</span> <span>¥ {total_freight:,.2f}</span>
                    </div>
                    <div style="height:1px; background:#555; margin:10px 0;"></div>
                    <div style="display:flex; justify-content:space-between; font-size:18px; font-weight:600; color:#fff">
                        <span>总计 (Grand Total):</span> <span>¥ {final_val:,.2f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                excel_data = generate_quotation_excel(items, service_fee, total_freight, {"name":co_name, "tel":co_tel, "email":co_email, "addr":co_addr})
                st.download_button(
                    label="📥 导出 Excel 报价单",
                    data=excel_data,
                    file_name=f"Quotation_{date.today().isoformat()}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    type="primary"
                )

# ------------------------------------------
# (其他模块保持不变)
# ------------------------------------------
elif selected_nav == "System" and st.session_state['role'] == 'admin':
    
    with st.expander("API Key 调试器", expanded=False):
        st.write("如报错请在 Secrets 更新 Key 并重启")
        st.code(f"Model: {CONFIG['AI_MODEL']}", language="text")
        st.code(f"Key (Last 5): {OPENAI_KEY[-5:] if OPENAI_KEY else 'N/A'}", language="text")
        
    frozen_count, frozen_leads = get_frozen_leads_count()
    if frozen_count > 0:
        st.markdown(f"""<div class="custom-alert alert-error">警告：有 {frozen_count} 个任务被冻结</div>""", unsafe_allow_html=True)
        with st.expander(f"查看冻结详情", expanded=True):
            st.dataframe(pd.DataFrame(frozen_leads))
            if st.button("清除所有冻结"):
                supabase.table('leads').delete().eq('is_frozen', True).execute()
                st.success("已清除"); time.sleep(1); st.rerun()

    st.markdown("#### 系统健康状态")
    health = check_api_health(CN_USER, CN_KEY, OPENAI_KEY)
    
    k1, k2, k3 = st.columns(3)
    def status_pill(title, is_active, detail):
        dot = "dot-green" if is_active else "dot-red"
        text = "运行正常" if is_active else "连接异常"
        st.markdown(f"""<div style="background-color:rgba(30, 31, 32, 0.6); backdrop-filter:blur(10px); padding:20px; border-radius:16px;"><div style="font-size:14px; color:#c4c7c5;">{title}</div><div style="margin-top:10px; font-size:16px; color:white; font-weight:500;"><span class="status-dot {dot}"></span>{text}</div><div style="font-size:12px; color:#8e8e8e; margin-top:5px;">{detail}</div></div>""", unsafe_allow_html=True)

    with k1: status_pill("云数据库", health['supabase'], "Supabase")
    with k2: status_pill("验证接口", health['checknumber'], "CheckNumber")
    with k3: status_pill("AI 引擎", health['openai'], f"OpenAI ({CONFIG['AI_MODEL']})")
    
    if health['msg']:
        st.markdown(f"""<div class="custom-alert alert-error">诊断报告: {'; '.join(health['msg'])}</div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 沙盒模拟")
    sb_file = st.file_uploader("上传测试文件", type=['csv', 'xlsx'])
    if sb_file and st.button("开始模拟"):
        try:
            if sb_file.name.endswith('.csv'): df = pd.read_csv(sb_file)
            else: df = pd.read_excel(sb_file)
            st.info(f"读取到 {len(df)} 行，正在处理...")
            with st.status("正在运行流水线...", expanded=True) as s:
                s.write("正在提取号码..."); nums = []
                for _, r in df.head(5).iterrows(): nums.extend(extract_all_numbers(r))
                s.write(f"提取结果: {nums}"); res = process_checknumber_task(nums, CN_KEY, CN_USER)
                valid = [p for p in nums if res.get(p)=='valid']; s.write(f"有效号码: {valid}")
                if valid:
                    s.write("正在生成 AI 话术..."); msg = get_ai_message_sniper(client, "测试", "http://test.com", "管理员")
                    s.write(f"生成结果: {msg}")
                s.update(label="模拟完成", state="complete")
        except Exception as e: st.error(str(e))

# --- 📱 WECHAT SCRM ---
elif selected_nav == "WeChat":
    if st.session_state['role'] == 'admin':
        st.markdown("#### 微信客户管理")
        with st.expander("导入微信客户", expanded=True):
            st.caption("格式：客户编号 | 业务员 | 周期")
            wc_file = st.file_uploader("上传 Excel", type=['xlsx', 'csv'], key="wc_up")
            if wc_file and st.button("开始导入"):
                try:
                    df = pd.read_csv(wc_file) if wc_file.name.endswith('.csv') else pd.read_excel(wc_file)
                    if admin_import_wechat_customers(df):
                        st.markdown(f"""<div class="custom-alert alert-success">成功导入 {len(df)} 个客户</div>""", unsafe_allow_html=True)
                    else: st.markdown("""<div class="custom-alert alert-error">导入失败</div>""", unsafe_allow_html=True)
                except Exception as e: st.error(str(e))
    else:
        st.markdown("#### 微信维护助手")
        try:
            wc_tasks = get_wechat_tasks(st.session_state['username'])
            if not wc_tasks:
                st.markdown("""<div class="custom-alert alert-info">今日无维护任务</div>""", unsafe_allow_html=True)
            else:
                st.markdown(f"**今日需维护：{len(wc_tasks)} 人**")
                for task in wc_tasks:
                    with st.expander(f"客户编号：{task['customer_code']}", expanded=True):
                        script = get_wechat_maintenance_script(client, task['customer_code'], st.session_state['username'])
                        st.code(script, language="text")
                        c1, c2 = st.columns([3, 1])
                        with c1: st.caption(f"上次联系：{task['last_contact_date']}")
                        with c2:
                            if st.button("完成打卡", key=f"wc_done_{task['id']}"):
                                complete_wechat_task(task['id'], task['cycle_days'], st.session_state['username'])
                                st.toast(f"积分 +{CONFIG['POINTS_WECHAT_TASK']}")
                                time.sleep(1); st.rerun()
        except Exception as e:
            st.markdown(f"""<div class="custom-alert alert-error">数据加载失败: {str(e)} (请检查 RLS)</div>""", unsafe_allow_html=True)

# --- 🎙️ TOOLS (Voice Translator) ---
elif selected_nav == "Tools":
    st.markdown("#### 🎙️ 俄语语音翻译器 (Whisper)")
    
    with st.expander("📝 使用说明 (必读)", expanded=True):
        st.markdown("""
        1. **获取语音：** 从微信/WhatsApp 长按语音消息 -> 保存为文件（支持 mp3, wav, m4a）。
        2. **上传：** 点击下方按钮上传。
        3. **查看：** AI 会自动识别俄语内容，并翻译成中文。
        """)
        
    uploaded_audio = st.file_uploader("上传语音文件", type=['mp3', 'wav', 'm4a', 'ogg', 'webm'])
    
    if uploaded_audio:
        if st.button("开始识别与翻译"):
            with st.status("正在呼叫 AI 大脑...", expanded=True) as status:
                status.write("👂 正在听写俄语...")
                ru_text, cn_text = transcribe_audio(client, uploaded_audio)
                
                status.write("🧠 正在翻译成中文...")
                time.sleep(1)
                status.update(label="处理完成", state="complete")
                
                st.markdown("---")
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**🇷🇺 俄语原文**")
                    st.info(ru_text)
                with c2:
                    st.markdown("**🇨🇳 中文翻译**")
                    st.success(cn_text)

# --- 💼 WORKBENCH (Sales) ---
elif selected_nav == "Workbench":
    my_leads = get_todays_leads(st.session_state['username'], client)
    
    user_limit = get_user_limit(st.session_state['username'])
    total, curr = user_limit, len(my_leads)
    
    c_stat, c_action = st.columns([2, 1])
    with c_stat:
        done = sum(1 for x in my_leads if x.get('is_contacted'))
        st.metric("今日进度", f"{done} / {total}")
        if total > 0: st.progress(min(done/total, 1.0))
        else: st.progress(0)
        
    with c_action:
        st.markdown("<br>", unsafe_allow_html=True)
        force_import = st.checkbox("跳过验证（强行入库）", help="如 API 故障，请勾选此项强制导入", key="force_import")
        
        if curr < total:
            if st.button(f"领取任务 (余 {total-curr} 个)"):
                _, status = claim_daily_tasks(st.session_state['username'], client)
                if status=="empty": st.markdown("""<div class="custom-alert alert-error">公池已空</div>""", unsafe_allow_html=True)
                else: st.rerun()
        else: st.markdown("""<div class="custom-alert alert-success">今日已领满</div>""", unsafe_allow_html=True)

    st.markdown("#### 任务列表")
    tabs = st.tabs(["待跟进", "已完成"])
    with tabs[0]:
        todos = [x for x in my_leads if not x.get('is_contacted')]
        if not todos: st.caption("没有待办任务")
        for item in todos:
            with st.expander(f"{item['shop_name']}", expanded=True):
                if not item['ai_message']:
                    st.markdown("""<div class="custom-alert alert-info">文案生成中...</div>""", unsafe_allow_html=True)
                else:
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
            df_display = df[['shop_name', 'phone', 'time']].rename(columns={'shop_name':'店铺名', 'phone':'电话', 'time':'时间'})
            st.dataframe(df_display, use_container_width=True)
        else: st.caption("暂无完成记录")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### 全量历史记录")
    _, _, df_history = get_user_historical_data(st.session_state['username'])
    if not df_history.empty:
        st.dataframe(df_history, column_config={"shop_name": "客户店铺", "phone": "联系电话", "shop_link": st.column_config.LinkColumn("店铺链接"), "completed_at": st.column_config.DatetimeColumn("处理时间", format="YYYY-MM-DD HH:mm")}, use_container_width=True)
    else: st.caption("暂无历史记录")

# --- 📅 LOGS (Admin) ---
elif selected_nav == "Logs":
    st.markdown("#### 活动日志监控")
    d = st.date_input("选择日期", date.today())
    
    try:
        if d:
            c, f = get_daily_logs(d.isoformat())
            col1, col2 = st.columns(2)
            with col1:
                st.markdown("领取记录")
                if not c.empty: st.dataframe(c, use_container_width=True)
                else: st.markdown("""<div class="custom-alert alert-info">无数据</div>""", unsafe_allow_html=True)
            with col2:
                st.markdown("完成记录")
                if not f.empty: st.dataframe(f, use_container_width=True)
                else: st.markdown("""<div class="custom-alert alert-info">无数据</div>""", unsafe_allow_html=True)
    except Exception as e:
        st.markdown(f"""<div class="custom-alert alert-error">日志加载失败: {str(e)}</div>""", unsafe_allow_html=True)

# --- 👥 TEAM (Admin) ---
elif selected_nav == "Team":
    try:
        users = pd.DataFrame(supabase.table('users').select("*").neq('role', 'admin').execute().data)
        c1, c2 = st.columns([1, 2])
        with c1:
            if not users.empty: u = st.radio("员工列表", users['username'].tolist(), label_visibility="collapsed")
            else: u = None; st.markdown("""<div class="custom-alert alert-info">暂无员工</div>""", unsafe_allow_html=True)
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
                
                # 获取当前限额
                current_limit = info.get('daily_limit') or CONFIG["DAILY_QUOTA"]

                st.markdown(f"### {info['real_name']}")
                st.caption(f"账号: {info['username']} | 积分: {info.get('points', 0)} | 最后上线: {str(info.get('last_seen','-'))[:16]}")
                
                # 🔥 动态调整上限功能
                with st.container():
                    st.markdown("#### ⚙️ 账号风控设置")
                    col_lim, col_btn = st.columns([3, 1])
                    with col_lim:
                        new_daily_limit = st.slider(
                            "每日最大任务分配上限", 
                            min_value=0, max_value=100, 
                            value=int(current_limit),
                            help="调整此数值可控制该员工每天能领取的最大任务数，用于防止封号。"
                        )
                    with col_btn:
                        st.markdown("<br>", unsafe_allow_html=True)
                        if st.button("保存设置"):
                            if update_user_limit(u, new_daily_limit):
                                st.toast(f"已更新 {info['real_name']} 的每日上限为 {new_daily_limit}")
                                time.sleep(1); st.rerun()
                            else: st.error("更新失败")
                
                st.divider()

                k1, k2 = st.columns(2)
                k1.metric("历史总领取", tc); k2.metric("历史总完成", td)
                
                t1, t2, t3 = st.tabs(["📊 每日绩效", "📋 详细清单", "🛡️ 账号管理"])
                with t1:
                    if not perf.empty: 
                        st.markdown("#### 近 14 天绩效趋势")
                        chart_data = perf.head(14)
                        st.bar_chart(chart_data, color=["#4b90ff", "#ff5546"]) 
                        with st.expander("查看详细数据表"):
                            st.dataframe(perf, use_container_width=True)
                    else: st.caption("暂无绩效数据")
                with t2:
                    if not hist.empty: st.dataframe(hist, use_container_width=True)
                    else: st.caption("暂无数据")
                with t3:
                    st.markdown("**修改资料**")
                    with st.form("edit_user"):
                        new_u = st.text_input("新用户名 (留空则不改)", value=u)
                        new_n = st.text_input("新真实姓名 (留空则不改)", value=info['real_name'])
                        new_p = st.text_input("新密码 (留空则不改)", type="password")
                        if st.form_submit_button("保存修改"):
                            if update_user_profile(u, new_u, new_p if new_p else None, new_n): st.success("资料已更新"); time.sleep(1); st.rerun()
                            else: st.error("更新失败")
                    st.markdown("---")
                    st.markdown("**危险操作**")
                    if st.button("删除账号并回收任务"): delete_user_and_recycle(u); st.rerun()
    except Exception as e:
        st.markdown(f"""<div class="custom-alert alert-error">无法读取团队数据: {str(e)} <br>请确认已执行 SQL: ALTER TABLE users ADD COLUMN daily_limit INTEGER DEFAULT 25;</div>""", unsafe_allow_html=True)

# --- 📥 IMPORT (Admin) ---
elif selected_nav == "Import":
    pool = get_public_pool_count()
    if pool < CONFIG["LOW_STOCK_THRESHOLD"]: st.markdown(f"""<div class="custom-alert alert-error">库存告急：仅剩 {pool} 个</div>""", unsafe_allow_html=True)
    else: st.metric("公共池库存", pool)
    
    with st.expander("每日归仓工具"):
        if st.button("一键回收过期任务"): n = recycle_expired_tasks(); st.success(f"已回收 {n} 个任务")
            
    st.markdown("---")
    st.markdown("#### 批量进货")
    
    force_import = st.checkbox("跳过 WhatsApp 验证 (强行入库)", help="如 API 故障，请勾选此项强制导入", key="force_import_admin")

    f = st.file_uploader("上传文件 (CSV/Excel)", type=['csv', 'xlsx'])
    if f:
        df = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
        st.caption(f"解析到 {len(df)} 行数据")
        if st.button("开始清洗入库"):
            with st.status("正在处理...", expanded=True) as s:
                df=df.astype(str); phones = set(); rmap = {}
                for i, r in df.iterrows():
                    for p in extract_all_numbers(r): phones.add(p); rmap.setdefault(p, []).append(i)
                s.write(f"提取到 {len(phones)} 个独立号码")
                plist = list(phones); valid = []
                
                if force_import:
                    s.write("已跳过验证，所有号码视为有效...")
                    valid = plist
                else:
                    for i in range(0, len(plist), 500):
                        batch = plist[i:i+500]
                        res, err, df_debug = process_checknumber_task(batch, CN_KEY, CN_USER)
                        if err != "Success" and err != "Empty List":
                            s.write(f"❌ 验证失败 ({err})")
                            if df_debug is not None:
                                s.write("API 返回数据预览：")
                                st.dataframe(df_debug.head())
                        valid.extend([p for p in batch if res.get(p)=='valid'])
                        time.sleep(1)
                
                s.write(f"最终有效入库: {len(valid)} 个")
                
                rows = []
                for idx, p in enumerate(valid):
                    r = df.iloc[rmap[p][0]]; lnk = r.iloc[0]; shp = r.iloc[1] if len(r)>1 else "Shop"
                    rows.append({"shop_name":shp, "shop_link":lnk, "phone":p, "ai_message":"", "retry_count": 0, "is_frozen": False, "error_log": None})
                    if len(rows)>=100: 
                        count, msg = admin_bulk_upload_to_pool(rows)
                        if count == 0 and len(rows) > 0: s.write(f"⚠️ 批次警告: {msg}")
                        rows=[]
                if rows: 
                    count, msg = admin_bulk_upload_to_pool(rows)
                    if count == 0 and len(rows) > 0: s.write(f"⚠️ 批次警告: {msg}")
                    
                s.update(label="操作完成", state="complete")
            time.sleep(1); st.rerun()
