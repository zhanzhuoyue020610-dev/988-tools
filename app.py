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

# 🔥 请将您第一步生成的 Base64 长字符串完整粘贴在双引号中间
# 为了演示，这里我放了一个极其简短的占位符，您必须替换它才能显示您的蓝色 Logo
COMPANY_LOGO_B64 = "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
" 

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
                ai_input_text = st.text_area("📄 方式一：粘贴文字/链接", height=120, placeholder="例如：这款黑色的包，价格25元，我要100个")
            with c_img_ai:
                ai_input_image = st.file_uploader("🖼️ 方式二：上传产品图", type=['jpg', 'png', 'jpeg'])
            
            # AI 处理逻辑
            if st.button("✨ 开始 AI 识别"):
                with st.status("正在唤醒 AI 引擎...", expanded=True) as status:
                    new_items = []
                    
                    # 优先处理图片
                    if ai_input_image:
                        status.write("👁️ 正在进行多目标视觉分析 & 智能裁剪 (Fit-to-Cell)...")
                        
                        original_bytes = ai_input_image.getvalue()
                        ai_res = parse_image_with_ai(ai_input_image, client)
                        
                        # 处理返回的列表 (支持多商品)
                        if ai_res and "items" in ai_res:
                            for raw_item in ai_res["items"]:
                                
                                # 核心：智能裁剪 (Exact/Strict Crop)
                                cropped_bytes = original_bytes
                                if "bbox_1000" in raw_item:
                                    cropped_bytes = crop_image_exact(original_bytes, raw_item["bbox_1000"])
                                
                                new_items.append({
                                    "model": raw_item.get('model', ''), 
                                    "name": raw_item.get('name_ru', 'Товар'), 
                                    "desc": raw_item.get('desc_ru', ''), 
                                    "price_exw": float(raw_item.get('price_cny', 0)), 
                                    "qty": int(raw_item.get('qty', 1)), 
                                    "image_data": cropped_bytes 
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
                        status.update(label=f"成功识别 {len(new_items)} 个商品", state="complete")
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
            
            with st.expander("🏢 公司表头信息 (含 Logo & WeChat)", expanded=True):
                co_name = st.text_input("公司名称", value="义乌市万昶进出口有限公司")
                # co_logo = st.file_uploader("公司 Logo (可选)", type=['png', 'jpg', 'jpeg'], key="co_logo")
                co_tel = st.text_input("电话", value="+86-15157938188")
                co_wechat = st.text_input("WeChat ID", value="15157938188") # 新增 WeChat
                co_email = st.text_input("邮箱", value="CTF1111@163.com")
                co_addr = st.text_input("地址", value="义乌市工人北路1121号5楼")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if items:
                # 预览最终价格
                product_total_exw = sum(i['price_exw'] * i['qty'] for i in items)
                service_fee_val = product_total_exw * (service_fee/100)
                final_val = product_total_exw + total_freight + service_fee_val
                
                st.markdown(f"""
                <div style="padding:15px; border:1px solid #444; border-radius:10px; background:rgba(255,255,255,0.05)">
                    <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e">
                        <span>工厂货值 (EXW Total):</span> <span>¥ {product_total_exw:,.2f}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e; margin-top:5px;">
                        <span>+ 国内运费:</span> <span>¥ {total_freight:,.2f}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e; margin-top:5px;">
                        <span>+ 服务费 ({service_fee}%):</span> <span>¥ {service_fee_val:,.2f}</span>
                    </div>
                    <div style="height:1px; background:#555; margin:10px 0;"></div>
                    <div style="display:flex; justify-content:space-between; font-size:18px; font-weight:600; color:#fff">
                        <span>总计 (Grand Total):</span> <span>¥ {final_val:,.2f}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)

                # logo_bytes = co_logo.getvalue() if co_logo else None
                
                excel_data = generate_quotation_excel(
                    items, service_fee, total_freight, 
                    {
                        "name":co_name, "tel":co_tel, "wechat":co_wechat, 
                        "email":co_email, "addr":co_addr, "logo_b64": COMPANY_LOGO_B64
                    }
                )
                
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

