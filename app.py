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
from PIL import Image

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

# 🔥 修复方案：从外部文件读取 Logo Base64，避免代码报错
def get_company_logo_base64():
    try:
        # 尝试读取同目录下的 logo.txt 文件
        with open("logo.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        # 如果找不到文件，返回空，不会报错，只是不显示 Logo
        return ""

COMPANY_LOGO_B64 = get_company_logo_base64()

CONFIG = {
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks",
    "DAILY_QUOTA": 25,
    "LOW_STOCK_THRESHOLD": 300,
    "POINTS_PER_TASK": 10,
    "POINTS_WECHAT_TASK": 5,
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
# 🔥 核心更新：直接使用 Base64 Logo
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

    # 1. 写入表头信息 & Logo
    worksheet.merge_range('B1:H2', company_info.get('name', "义乌市万昶进出口有限公司"), fmt_header_main)
    
    # 🔥 插入内置的 Base64 Logo
    logo_b64 = company_info.get('logo_b64')
    if logo_b64 and len(logo_b64) > 100: # 确保有内容
        try:
            # 解码
            logo_data = base64.b64decode(logo_b64)
            logo_io = io.BytesIO(logo_data)
            
            # 计算缩放
            img = Image.open(logo_io)
            width, height = img.size
            if height > 0:
                scale = 60 / height # 目标高度 60px
                logo_io.seek(0)
                worksheet.insert_image('A1', 'logo.png', {'image_data': logo_io, 'x_scale': scale, 'y_scale': scale})
        except Exception as e:
            print(f"Logo error: {e}")

    # 联系方式
    tel = company_info.get('tel', '')
    email = company_info.get('email', '')
    wechat = company_info.get('wechat', '')
    contact_text = f"TEL: {tel}    WeChat: {wechat}\nE-mail: {email}"
    
    worksheet.merge_range('A3:H4', contact_text, fmt_header_sub)
    worksheet.merge_range('A5:H5', f"Address: {company_info.get('addr', '')}", fmt_header_sub)
    worksheet.merge_range('A7:H7', "* This price is valid for 10 days / Эта цена действительна в течение 10 дней", fmt_bold_red)

    # 2. 写入表格列名
    headers = [
        ("序号\nNo.", 4), 
        ("型号\nArticul", 15), 
        ("图片\nPhoto", 15), 
        ("名称\nName", 15), 
        ("产品描述\nDescription", 25), 
        ("数量\nQty", 8), 
        ("EXW 单价 ￥\nFactory Price", 12), 
        ("货值 ￥\nTotal Value", 12)
    ]
    
    start_row = 8 
    for col, (h_text, width) in enumerate(headers):
        worksheet.write(start_row, col, h_text, fmt_table_header)
        worksheet.set_column(col, col, width)

    current_row = start_row + 1
    total_exw_value = 0
    
    TARGET_HEIGHT = 100
    TARGET_WIDTH = 100

    for idx, item in enumerate(items, 1):
        qty = float(item.get('qty', 0))
        factory_price_unit = float(item.get('price_exw', 0))
        
        line_total_exw = factory_price_unit * qty
        total_exw_value += line_total_exw

        worksheet.set_row(current_row, 80)
        worksheet.write(current_row, 0, idx, fmt_cell_center)
        worksheet.write(current_row, 1, item.get('model', ''), fmt_cell_center)
        
        if item.get('image_data'):
            try:
                img_byte_stream = io.BytesIO(item['image_data'])
                pil_img = Image.open(img_byte_stream)
                img_width, img_height = pil_img.size
                
                if img_width > 0 and img_height > 0:
                    x_scale = TARGET_WIDTH / img_width
                    y_scale = TARGET_HEIGHT / img_height
                    scale = min(x_scale, y_scale)
                else:
                    scale = 0.5

                img_byte_stream.seek(0)
                worksheet.insert_image(current_row, 2, "img.png", {
                    'image_data': img_byte_stream, 
                    'x_scale': scale, 
                    'y_scale': scale, 
                    'object_position': 2 
                })
            except Exception as e:
                worksheet.write(current_row, 2, "Error", fmt_cell_center)
        else:
            worksheet.write(current_row, 2, "No Image", fmt_cell_center)

        worksheet.write(current_row, 3, item.get('name', ''), fmt_cell_left)
        worksheet.write(current_row, 4, item.get('desc', ''), fmt_cell_left)
        worksheet.write(current_row, 5, qty, fmt_cell_center)
        worksheet.write(current_row, 6, factory_price_unit, fmt_money)
        worksheet.write(current_row, 7, line_total_exw, fmt_money)
        
        current_row += 1

    # 4. 底部合计
    worksheet.merge_range(current_row, 0, current_row, 6, "Subtotal (EXW) / 工厂货值小计", fmt_total_row)
    worksheet.write(current_row, 7, total_exw_value, fmt_total_money)
    current_row += 1

    if total_domestic_freight > 0:
        worksheet.merge_range(current_row, 0, current_row, 6, "Domestic Freight / 国内运费", fmt_total_row)
        worksheet.write(current_row, 7, total_domestic_freight, fmt_total_money)
        current_row += 1
    
    service_fee_amount = total_exw_value * (service_fee_percent / 100.0)
    if service_fee_amount > 0:
        worksheet.merge_range(current_row, 0, current_row, 6, f"Service Fee / 服务费 ({service_fee_percent}%)", fmt_total_row)
        worksheet.write(current_row, 7, service_fee_amount, fmt_total_money)
        current_row += 1

    grand_total = total_exw_value + total_domestic_freight + service_fee_amount
    
    worksheet.merge_range(current_row, 0, current_row, 6, "GRAND TOTAL / 总计", fmt_total_row)
    worksheet.write(current_row, 7, grand_total, fmt_total_money)

    workbook.close()
    output.seek(0)
    return output

# --- 🔥 智能图片裁剪 (Exact/Strict Crop) ---
def crop_image_exact(original_image_bytes, bbox_1000):
    try:
        if not bbox_1000 or len(bbox_1000) != 4: return original_image_bytes
        
        img = Image.open(io.BytesIO(original_image_bytes))
        width, height = img.size
        
        ymin_rel, xmin_rel, ymax_rel, xmax_rel = bbox_1000
        
        y1 = int(ymin_rel / 1000 * height)
        x1 = int(xmin_rel / 1000 * width)
        y2 = int(ymax_rel / 1000 * height)
        x2 = int(xmax_rel / 1000 * width)
        
        x1 = max(0, x1); y1 = max(0, y1)
        x2 = min(width, x2); y2 = min(height, y2)
        
        if (x2 - x1) < 5 or (y2 - y1) < 5:
            return original_image_bytes

        cropped_img = img.crop((x1, y1, x2, y2))
        
        output = io.BytesIO()
        cropped_img.save(output, format=img.format if img.format else 'PNG')
        return output.getvalue()
        
    except Exception as e:
        print(f"Crop Error: {e}")
        return original_image_bytes

# --- AI Parsing Logic ---
def parse_image_with_ai(image_file, client):
    if not image_file: return None
    
    base64_image = base64.b64encode(image_file.getvalue()).decode('utf-8')
    
    prompt = """
    Role: You are an advanced OCR & Data Extraction engine specialized in Chinese E-commerce Order Forms (1688/Taobao).
    
    CONTEXT: The screenshot contains a list of product variants.
    
    YOUR MISSION:
    1. **SCAN VERTICALLY**: Extract EVERY single variant row (e.g. 500ml, 1000ml) as a separate item.
    2. **BOUNDING BOX (STRICT)**: Return the **EXACT** bounding box for the product thumbnail image.
       - **DO NOT** include any whitespace/background outside the image.
       - **DO NOT** try to make it square.
       - Return `bbox_1000`: `[ymin, xmin, ymax, xmax]` (0-1000 scale).
    
    DATA EXTRACTION RULES:
    - **Name**: Main product name (Translate to Russian).
    - **Model/Spec**: The variant text (e.g., "500ml White").
    - **Desc**: ULTRA SHORT summary (max 5 words). E.g., "Cup 500ml". Translate to Russian.
    - **Price**: Extract the price for this row.
    - **Qty**: Extract quantity for this row.
    
    Output Format (JSON):
    {
        "items": [
            { 
              "name_ru": "...", 
              "model": "500ml", 
              "desc_ru": "...", 
              "price_cny": 5.5, 
              "qty": 100,
              "bbox_1000": [100, 10, 200, 60] 
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
                ai_input_text = st.text_area("📄 方式一：粘贴文字/链接", height=120, placeholder="例如
