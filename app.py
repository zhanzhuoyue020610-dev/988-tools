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
# 依赖库检查
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
# UI 主题 & 核心配置
# ==========================================
st.set_page_config(page_title="988 Group CRM", layout="wide", page_icon="G")

# 读取本地 logo_b64.txt 文件
def load_logo_b64():
    try:
        with open("logo_b64.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return ""

COMPANY_LOGO_B64 = load_logo_b64()

CONFIG = {
    "CN_BASE_URL": "https://api.checknumber.ai/wa/api/simple/tasks",
    "DAILY_QUOTA": 25,
    "LOW_STOCK_THRESHOLD": 300,
    "POINTS_PER_TASK": 10,
    "POINTS_WECHAT_TASK": 5,
    "AI_MODEL": "gpt-4o" 
}

# 注入时钟 HTML (去除装饰性样式)
st.markdown("""
<div id="clock-container" style="
    position: fixed; top: 15px; left: 50%; transform: translateX(-50%);
    font-family: 'Inter', sans-serif; font-size: 14px; color: rgba(255,255,255,0.8);
    z-index: 999999; background: rgba(0,0,0,0.8); padding: 4px 16px; border-radius: 4px;
    border: 1px solid rgba(255,255,255,0.1); pointer-events: none;
">Loading...</div>
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

# 注入 CSS (极简商务风)
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600&display=swap');
    @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&display=swap');

    :root {
        --text-primary: #e0e0e0;
        --text-secondary: #a0a0a0;
        --bg-dark: #121212;
        --bg-panel: #1e1e1e;
        --accent: #4a90e2; 
    }

    .stApp, [data-testid="stAppViewContainer"] { background-color: var(--bg-dark) !important; color: var(--text-primary) !important; font-family: 'Inter', 'Noto Sans SC', sans-serif !important; }
    
    .block-container { padding-top: 2rem !important; }
    [data-testid="stHeader"] { background-color: transparent !important; }
    
    .main-header { font-weight: 600; font-size: 24px; color: #ffffff; letter-spacing: 0.5px; margin-bottom: 4px; }
    .sub-header { font-size: 12px; color: var(--text-secondary); margin-bottom: 20px; }
    
    /* 组件样式重置 */
    div[data-testid="stRadio"] > div { background-color: transparent !important; border: none; gap: 20px; }
    div[data-testid="stRadio"] label { background-color: var(--bg-panel) !important; color: var(--text-secondary) !important; padding: 6px 16px; border-radius: 4px; border: 1px solid #333; transition: all 0.2s; }
    div[data-testid="stRadio"] label[data-checked="true"] { background-color: var(--accent) !important; color: white !important; border-color: var(--accent); }
    
    div[data-testid="stExpander"], div[data-testid="stForm"], div.stDataFrame { background-color: var(--bg-panel) !important; border: 1px solid #333 !important; border-radius: 6px; padding: 16px; }
    
    button { border-radius: 4px !important; }
    div.stButton > button { background-color: var(--accent) !important; color: white !important; border: none !important; padding: 8px 20px !important; font-weight: 500; }
    div.stButton > button:hover { opacity: 0.9; }
    
    input, textarea, select { background-color: #2d2d2d !important; border: 1px solid #444 !important; color: white !important; border-radius: 4px !important; }
    
    .status-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
    .status-ok { background: rgba(76, 175, 80, 0.2); color: #81c784; border: 1px solid #2e7d32; }
    .status-err { background: rgba(244, 67, 54, 0.2); color: #e57373; border: 1px solid #c62828; }
    
    /* 表格样式 */
    div[data-testid="stDataFrame"] div[role="grid"] { background-color: var(--bg-panel) !important; color: var(--text-secondary); }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 数据库与核心逻辑
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
            supabase.table('leads').update({'assigned_to': new_username}).eq('assigned_to', new_username).execute()
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

# --- 报价单生成引擎 (XlsxWriter) ---
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

    # 1. 表头 & Logo
    worksheet.merge_range('B1:H2', company_info.get('name', "义乌市万昶进出口有限公司"), fmt_header_main)
    
    logo_b64 = company_info.get('logo_b64')
    if logo_b64 and len(logo_b64) > 100:
        try:
            logo_data = base64.b64decode(logo_b64)
            logo_io = io.BytesIO(logo_data)
            img = Image.open(logo_io)
            width, height = img.size
            if height > 0:
                scale = 60 / height 
                logo_io.seek(0)
                worksheet.insert_image('A1', 'logo.png', {'image_data': logo_io, 'x_scale': scale, 'y_scale': scale})
        except Exception as e:
            pass

    tel = company_info.get('tel', '')
    email = company_info.get('email', '')
    wechat = company_info.get('wechat', '')
    contact_text = f"TEL: {tel}    WeChat: {wechat}\nE-mail: {email}"
    
    worksheet.merge_range('A3:H4', contact_text, fmt_header_sub)
    worksheet.merge_range('A5:H5', f"Address: {company_info.get('addr', '')}", fmt_header_sub)
    worksheet.merge_range('A7:H7', "* This price is valid for 10 days / Эта цена действительна в течение 10 дней", fmt_bold_red)

    # 2. 表格列名
    headers = [
        ("No.", 4), 
        ("Articul", 15), 
        ("Photo", 15), 
        ("Name", 15), 
        ("Description", 25), 
        ("Qty", 8), 
        ("EXW Price", 12), 
        ("Total Value", 12)
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
    worksheet.merge_range(current_row, 0, current_row, 6, "Subtotal (EXW)", fmt_total_row)
    worksheet.write(current_row, 7, total_exw_value, fmt_total_money)
    current_row += 1

    if total_domestic_freight > 0:
        worksheet.merge_range(current_row, 0, current_row, 6, "Domestic Freight", fmt_total_row)
        worksheet.write(current_row, 7, total_domestic_freight, fmt_total_money)
        current_row += 1
    
    service_fee_amount = total_exw_value * (service_fee_percent / 100.0)
    if service_fee_amount > 0:
        worksheet.merge_range(current_row, 0, current_row, 6, f"Service Fee ({service_fee_percent}%)", fmt_total_row)
        worksheet.write(current_row, 7, service_fee_amount, fmt_total_money)
        current_row += 1

    grand_total = total_exw_value + total_domestic_freight + service_fee_amount
    
    worksheet.merge_range(current_row, 0, current_row, 6, "GRAND TOTAL", fmt_total_row)
    worksheet.write(current_row, 7, grand_total, fmt_total_money)

    workbook.close()
    output.seek(0)
    return output

# --- 图片裁剪算法 ---
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
        return original_image_bytes

# --- AI 解析 ---
def parse_image_with_ai(image_file, client):
    if not image_file: return None
    
    base64_image = base64.b64encode(image_file.getvalue()).decode('utf-8')
    
    prompt = """
    Role: Advanced OCR engine for Chinese E-commerce (1688/Taobao).
    Task: Extract product variants from the image.
    
    RULES:
    1. Scan vertically. Extract EACH variant row as a separate item.
    2. BOUNDING BOX: Return the EXACT bounding box for the thumbnail. Do not include whitespace.
       Return `bbox_1000`: `[ymin, xmin, ymax, xmax]` (0-1000 scale).
    3. Name: Product name (Russian).
    4. Model: Variant spec (e.g. 500ml White).
    5. Desc: Summary max 5 words (Russian).
    6. Price: Number only.
    7. Qty: Number only.
    
    JSON Output:
    {
        "items": [
            { 
              "name_ru": "...", 
              "model": "...", 
              "desc_ru": "...", 
              "price_cny": 0.0, 
              "qty": 0,
              "bbox_1000": [0, 0, 0, 0] 
            }
        ]
    }
    """
    
    try:
        res = client.chat.completions.create(
            model=CONFIG["AI_MODEL"],
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
        return None

def parse_product_info_with_ai(text_content, client):
    if not text_content: return None
    
    prompt = f"""
    Role: B2B Trade Assistant.
    Task: Extract product info.
    Output JSON:
    {{
        "name_ru": "...",
        "model": "...",
        "price_cny": 0.0,
        "qty": 0,
        "desc_ru": "Max 5 words"
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

# --- 其他 AI 逻辑 ---
def get_daily_motivation(client):
    if "motivation_quote" not in st.session_state:
        local_quotes = ["Keep pushing forward.", "Focus on the goal.", "Every step counts."]
        try:
            if not client: raise Exception("No Client")
            prompt = "Generate a short, professional, encouraging quote for a salesperson. No emojis."
            res = client.chat.completions.create(
                model=CONFIG["AI_MODEL"], messages=[{"role":"user","content":prompt}], temperature=0.9, max_tokens=60
            )
            st.session_state["motivation_quote"] = res.choices[0].message.content
        except:
            st.session_state["motivation_quote"] = random.choice(local_quotes)
    return st.session_state["motivation_quote"]

def get_ai_message_sniper(client, shop, link, rep_name):
    offline_template = f"Здравствуйте! Заметили ваш магазин {shop} на Ozon. {rep_name} из 988 Group на связи. Мы занимаемся поставками из Китая. Можем рассчитать логистику?"
    if not shop or str(shop).lower() in ['nan', 'none', '']: return "Missing Data"
    prompt = f"""
    Role: Supply Chain Manager '{rep_name}' at 988 Group.
    Target: Ozon Seller '{shop}' (Link: {link}).
    Task: Write a Russian WhatsApp intro (under 50 words). Professional tone. No emojis.
    """
    try:
        if not client: return offline_template
        res = client.chat.completions.create(model=CONFIG["AI_MODEL"],messages=[{"role":"user","content":prompt}])
        return res.choices[0].message.content.strip()
    except: return offline_template

def get_wechat_maintenance_script(client, customer_code, rep_name):
    offline = f"您好，我是 988 Group 的 {rep_name}。最近生意如何？工厂那边出了一些新品，如果您需要补货或者看新款，随时联系我。"
    prompt = f"""
    Role: Account Manager '{rep_name}'.
    Target: Customer '{customer_code}'.
    Task: Write a short Chinese maintenance message. Professional. No emojis.
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
                {"role": "system", "content": "Translate Russian to Chinese. Professional tone."},
                {"role": "user", "content": ru_text}
            ]
        )
        cn_text = completion.choices[0].message.content
        return ru_text, cn_text
    except Exception as e:
        return f"Error: {str(e)}", "Translation Failed"

# --- 业务逻辑 (WeChat/WA) ---
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

def get_user_daily_performance(username):
    if not supabase: return pd.DataFrame()
    try:
        res = supabase.table('leads').select('assigned_at, completed_at').eq('assigned_to', username).execute()
        df = pd.DataFrame(res.data)
        if df.empty: return pd.DataFrame()
        df['assign_date'] = pd.to_datetime(df['assigned_at']).dt.date
        daily_claim = df.groupby('assign_date').size().rename("Assigned")
        df_done = df[df['completed_at'].notna()].copy()
        df_done['done_date'] = pd.to_datetime(df_done['completed_at']).dt.date
        daily_done = df_done.groupby('done_date').size().rename("Completed")
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
    if not supabase or not rows_to_insert: return 0, "No data"
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
        if not final_rows: return 0, f"All {len(rows_to_insert)} numbers exist."
        
        for row in final_rows: row['username'] = st.session_state.get('username', 'admin')

        response = supabase.table('leads').insert(final_rows).execute()
        if len(response.data) == 0: return 0, "RLS Error"
        return len(response.data), "Success"

    except Exception as e:
        for row in final_rows:
            try:
                row['username'] = st.session_state.get('username', 'admin')
                supabase.table('leads').insert(row).execute()
                success_count += 1
            except: pass
        if success_count > 0: return success_count, f"Partial success: {success_count}"
        else: return 0, f"Failed: {str(e)}"

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
        
        with st.status(f"Processing tasks for {username}...", expanded=True) as status:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(generate_and_update_task, task, client, username) for task in fresh_tasks]
                concurrent.futures.wait(futures)
            status.update(label="Tasks ready", state="complete")
        
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
            df_claim_summary = df_claims.groupby('assigned_to').size().reset_index(name='Claimed')
        else: df_claim_summary = pd.DataFrame(columns=['assigned_to', 'Claimed'])
        
        start_dt = f"{query_date}T00:00:00"
        end_dt = f"{query_date}T23:59:59"
        raw_done = supabase.table('leads').select('assigned_to, completed_at').gte('completed_at', start_dt).lte('completed_at', end_dt).execute().data
        df_done = pd.DataFrame(raw_done)
        if not df_done.empty:
            df_done = df_done[df_done['assigned_to'] != 'admin']
            df_done_summary = df_done.groupby('assigned_to').size().reset_index(name='Completed')
        else: df_done_summary = pd.DataFrame(columns=['assigned_to', 'Completed'])
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
        if resp.status_code != 200: return status_map, f"API Error: {resp.status_code}", None
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
        if not openai_key or "sk-" not in openai_key: status["msg"].append("OpenAI: Format Error")
        else:
            client = OpenAI(api_key=openai_key)
            client.chat.completions.create(model=CONFIG["AI_MODEL"], messages=[{"role":"user","content":"Hi"}], max_tokens=1)
            status["openai"] = True
    except Exception as e: status["msg"].append(f"OpenAI: {str(e)}")
    return status

# ==========================================
# 登录页
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        st.markdown("<br><br><br><br>", unsafe_allow_html=True)
        st.markdown('<div class="main-header" style="text-align:center;">988 GROUP CRM</div>', unsafe_allow_html=True)
        st.markdown('<div class="sub-header" style="text-align:center;">Professional Global Logistics</div>', unsafe_allow_html=True)
        
        with st.form("login", border=False):
            u = st.text_input("Account ID", placeholder="Username")
            p = st.text_input("Password", type="password", placeholder="Password")
            st.markdown("<br>", unsafe_allow_html=True)
            if st.form_submit_button("LOGIN"):
                user = login_user(u, p)
                if user:
                    st.session_state.update({'logged_in':True, 'username':u, 'role':user['role'], 'real_name':user['real_name']})
                    st.rerun()
                else:
                    st.markdown('<div class="status-badge status-err">Invalid Credentials</div>', unsafe_allow_html=True)
    st.stop()

# ==========================================
# 内部主界面
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
    st.markdown(f'<div class="main-header">Hello, {st.session_state["real_name"]}</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sub-header">{quote}</div>', unsafe_allow_html=True)

with c_user:
    st.markdown(f"""
    <div style="text-align:right; margin-top:5px;">
        <span class="status-badge status-ok">Points: {points}</span>
        <span style="color:#666; margin:0 10px;">|</span>
        <span style="font-size:14px; color:#e0e0e0;">{st.session_state['role'].upper()}</span>
    </div>
    """, unsafe_allow_html=True)
    c_null, c_out = st.columns([3, 1])
    with c_out:
        if st.button("Logout", key="logout"): st.session_state.clear(); st.rerun()

st.divider()

if st.session_state['role'] == 'admin':
    menu_map = {"System": "System", "Logs": "Logs", "Team": "Team", "Import": "Import", "WeChat": "WeChat", "Tools": "Tools"}
    menu_options = ["System", "Logs", "Team", "Import", "WeChat", "Tools"]
else:
    menu_map = {"Workbench": "Workbench", "WeChat": "WeChat", "Tools": "Tools"}
    menu_options = ["Workbench", "WeChat", "Tools"]

selected_nav = st.radio("Navigation", menu_options, format_func=lambda x: menu_map.get(x, x), horizontal=True, label_visibility="collapsed")
st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------------
# TOOLS (包含 Quotation Generator)
# ------------------------------------------
if selected_nav == "Tools":
    
    # 子菜单 Tab
    tab_quote, tab_trans = st.tabs(["Quotation Generator", "Voice Translator"])
    
    # --- Quotation Generator ---
    with tab_quote:
        if not XLSXWRITER_INSTALLED:
            st.error("Missing dependency: XlsxWriter")
        else:
            if "quote_items" not in st.session_state: st.session_state["quote_items"] = []

            # 1. 输入区域
            with st.container():
                st.markdown("#### Add Items")
                # 默认优先展示 AI 识别 (Tab 1)
                sub_t1, sub_t2 = st.tabs(["AI Auto-Scan (Priority)", "Manual Entry"])
                
                with sub_t1:
                    c_text_ai, c_img_ai = st.columns([2, 1])
                    with c_text_ai:
                        ai_input_text = st.text_area("Paste Text / Link", height=100, placeholder="Example: 1688 Link or text description")
                    with c_img_ai:
                        ai_input_image = st.file_uploader("Upload Product Image", type=['jpg', 'png', 'jpeg'])
                    
                    if st.button("Start AI Analysis"):
                        with st.status("Analyzing...", expanded=True) as status:
                            new_items = []
                            if ai_input_image:
                                status.write("Scanning image for products...")
                                original_bytes = ai_input_image.getvalue()
                                ai_res = parse_image_with_ai(ai_input_image, client)
                                if ai_res and "items" in ai_res:
                                    for raw_item in ai_res["items"]:
                                        cropped_bytes = original_bytes
                                        if "bbox_1000" in raw_item:
                                            cropped_bytes = crop_image_exact(original_bytes, raw_item["bbox_1000"])
                                        new_items.append({
                                            "model": raw_item.get('model', ''), 
                                            "name": raw_item.get('name_ru', 'Item'), 
                                            "desc": raw_item.get('desc_ru', ''), 
                                            "price_exw": float(raw_item.get('price_cny', 0)), 
                                            "qty": int(raw_item.get('qty', 1)), 
                                            "image_data": cropped_bytes 
                                        })
                            elif ai_input_text:
                                status.write("Analyzing text...")
                                ai_res = parse_product_info_with_ai(ai_input_text, client)
                                if ai_res:
                                     new_items.append({
                                        "model": ai_res.get('model', ''), 
                                        "name": ai_res.get('name_ru', 'Item'), 
                                        "desc": ai_res.get('desc_ru', ''), 
                                        "price_exw": float(ai_res.get('price_cny', 0)), 
                                        "qty": int(ai_res.get('qty', 1)), 
                                        "image_data": None
                                    })
                            
                            if new_items:
                                st.session_state["quote_items"].extend(new_items)
                                status.update(label=f"Added {len(new_items)} items", state="complete")
                                time.sleep(1)
                                st.rerun()
                            else:
                                status.update(label="Analysis failed", state="error")

                with sub_t2:
                    with st.form("manual_add", clear_on_submit=True):
                        c_img, c_main = st.columns([1, 3])
                        with c_img:
                            img_file = st.file_uploader("Image", type=['png', 'jpg', 'jpeg'])
                        with c_main:
                            c1, c2, c3 = st.columns(3)
                            model = c1.text_input("Articul")
                            name = c2.text_input("Name (RU)")
                            price_exw = c3.number_input("Factory Price", min_value=0.0, step=0.1)
                            c4, c5 = st.columns([1, 2])
                            qty = c4.number_input("Qty", min_value=1, step=1)
                            desc = c5.text_input("Desc (RU)")
                        if st.form_submit_button("Add Item"):
                            img_data = img_file.getvalue() if img_file else None
                            st.session_state["quote_items"].append({"model": model, "name": name, "desc": desc, "price_exw": price_exw, "qty": qty, "image_data": img_data})
                            st.success("Item Added")
                            st.rerun()

            st.divider()

            # 2. 清单与设置区域
            col_list, col_setting = st.columns([2, 1])

            with col_list:
                st.markdown("#### Items List")
                items = st.session_state["quote_items"]
                if items:
                    df_show = pd.DataFrame(items)
                    st.dataframe(df_show[['model', 'name', 'price_exw', 'qty']], use_container_width=True, hide_index=True)
                    if st.button("Clear List"):
                        st.session_state["quote_items"] = []
                        st.rerun()
                else:
                    st.info("List is empty.")

            with col_setting:
                with st.container():
                    st.markdown("#### Settings")
                    total_freight = st.number_input("Domestic Freight (CNY)", min_value=0.0, step=10.0)
                    service_fee = st.slider("Service Fee (%)", 0, 50, 5)
                    
                    with st.expander("Header Info"):
                        co_name = st.text_input("Company Name", value="义乌市万昶进出口有限公司")
                        co_tel = st.text_input("Tel", value="+86-15157938188")
                        co_wechat = st.text_input("WeChat", value="15157938188")
                        co_email = st.text_input("Email", value="CTF1111@163.com")
                        co_addr = st.text_input("Address", value="义乌市工人北路1121号5楼")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    if items:
                        product_total_exw = sum(i['price_exw'] * i['qty'] for i in items)
                        service_fee_val = product_total_exw * (service_fee/100)
                        final_val = product_total_exw + total_freight + service_fee_val
                        
                        st.markdown(f"""
                        <div style="padding:10px; border:1px solid #444; border-radius:4px; background:#222;">
                            <div style="display:flex; justify-content:space-between; font-size:12px; color:#aaa">
                                <span>EXW Total:</span> <span>¥ {product_total_exw:,.2f}</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:12px; color:#aaa;">
                                <span>Freight:</span> <span>¥ {total_freight:,.2f}</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:12px; color:#aaa;">
                                <span>Service Fee:</span> <span>¥ {service_fee_val:,.2f}</span>
                            </div>
                            <div style="border-top:1px solid #444; margin:5px 0;"></div>
                            <div style="display:flex; justify-content:space-between; font-weight:bold; color:#fff">
                                <span>Total:</span> <span>¥ {final_val:,.2f}</span>
                            </div>
                        </div>
                        """, unsafe_allow_html=True)

                        excel_data = generate_quotation_excel(
                            items, service_fee, total_freight, 
                            {
                                "name":co_name, "tel":co_tel, "wechat":co_wechat, 
                                "email":co_email, "addr":co_addr, "logo_b64": COMPANY_LOGO_B64
                            }
                        )
                        st.download_button("Download Excel", data=excel_data, file_name=f"Quotation_{date.today().isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

    # --- Voice Translator ---
    with tab_trans:
        st.markdown("#### Russian Voice Translator")
        uploaded_audio = st.file_uploader("Upload Audio (mp3, wav, m4a)", type=['mp3', 'wav', 'm4a', 'ogg', 'webm'])
        if uploaded_audio and st.button("Translate"):
            with st.status("Processing...", expanded=True) as status:
                status.write("Transcribing...")
                ru_text, cn_text = transcribe_audio(client, uploaded_audio)
                status.write("Translating...")
                time.sleep(1)
                status.update(label="Done", state="complete")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**Russian**")
                    st.info(ru_text)
                with c2:
                    st.markdown("**Chinese**")
                    st.success(cn_text)

# ------------------------------------------
# System & Admin (No Emojis)
# ------------------------------------------
elif selected_nav == "System" and st.session_state['role'] == 'admin':
    with st.expander("API Debugger"):
        st.code(f"Model: {CONFIG['AI_MODEL']}")
        st.code(f"Key: {OPENAI_KEY[-5:] if OPENAI_KEY else 'N/A'}")
        
    frozen_count, frozen_leads = get_frozen_leads_count()
    if frozen_count > 0:
        st.warning(f"Frozen Tasks: {frozen_count}")
        with st.expander("Details"):
            st.dataframe(pd.DataFrame(frozen_leads))
            if st.button("Clear Frozen"):
                supabase.table('leads').delete().eq('is_frozen', True).execute()
                st.rerun()

    st.markdown("#### System Health")
    health = check_api_health(CN_USER, CN_KEY, OPENAI_KEY)
    
    c1, c2, c3 = st.columns(3)
    def status_card(title, active):
        color = "#4caf50" if active else "#f44336"
        st.markdown(f"""<div style="border-left:4px solid {color}; padding:10px; background:#222;">{title}</div>""", unsafe_allow_html=True)

    with c1: status_card("Database", health['supabase'])
    with c2: status_card("Validation API", health['checknumber'])
    with c3: status_card("AI Engine", health['openai'])
    
    if health['msg']:
        st.error(f"Errors: {'; '.join(health['msg'])}")

    st.markdown("#### Sandbox")
    sb_file = st.file_uploader("Test File", type=['csv', 'xlsx'])
    if sb_file and st.button("Run Simulation"):
        try:
            df = pd.read_csv(sb_file) if sb_file.name.endswith('.csv') else pd.read_excel(sb_file)
            st.info(f"Rows: {len(df)}")
            with st.status("Running...", expanded=True) as s:
                nums = []
                for _, r in df.head(5).iterrows(): nums.extend(extract_all_numbers(r))
                s.write(f"Found: {nums}")
                res = process_checknumber_task(nums, CN_KEY, CN_USER)
                valid = [p for p in nums if res[0].get(p)=='valid']
                s.write(f"Valid: {valid}")
                s.update(label="Done", state="complete")
        except Exception as e: st.error(str(e))

elif selected_nav == "WeChat":
    if st.session_state['role'] == 'admin':
        st.markdown("#### WeChat Management")
        wc_file = st.file_uploader("Import Excel", type=['xlsx', 'csv'])
        if wc_file and st.button("Import"):
            df = pd.read_csv(wc_file) if wc_file.name.endswith('.csv') else pd.read_excel(wc_file)
            if admin_import_wechat_customers(df):
                st.success(f"Imported {len(df)} customers")
            else: st.error("Import failed")
    else:
        st.markdown("#### WeChat Tasks")
        wc_tasks = get_wechat_tasks(st.session_state['username'])
        if not wc_tasks:
            st.info("No tasks today.")
        else:
            for task in wc_tasks:
                with st.expander(f"Customer: {task['customer_code']}"):
                    script = get_wechat_maintenance_script(client, task['customer_code'], st.session_state['username'])
                    st.code(script)
                    if st.button("Mark Done", key=f"wc_{task['id']}"):
                        complete_wechat_task(task['id'], task['cycle_days'], st.session_state['username'])
                        st.toast("Points Added")
                        time.sleep(1); st.rerun()

elif selected_nav == "Workbench":
    my_leads = get_todays_leads(st.session_state['username'], client)
    user_limit = get_user_limit(st.session_state['username'])
    done = sum(1 for x in my_leads if x.get('is_contacted'))
    
    c_stat, c_action = st.columns([2, 1])
    with c_stat:
        st.metric("Daily Progress", f"{done} / {user_limit}")
        st.progress(min(done/user_limit, 1.0) if user_limit > 0 else 0)
        
    with c_action:
        st.markdown("<br>", unsafe_allow_html=True)
        if len(my_leads) < user_limit:
            if st.button("Get Tasks"):
                _, status = claim_daily_tasks(st.session_state['username'], client)
                if status=="empty": st.warning("Pool Empty")
                else: st.rerun()
        else: st.success("Limit Reached")

    st.markdown("#### Tasks")
    t1, t2 = st.tabs(["Pending", "Completed"])
    with t1:
        todos = [x for x in my_leads if not x.get('is_contacted')]
        if not todos: st.info("No pending tasks.")
        for item in todos:
            with st.expander(f"{item['shop_name']}"):
                if not item['ai_message']: st.warning("Generating script...")
                else:
                    st.write(item['ai_message'])
                    c1, c2 = st.columns(2)
                    key = f"clk_{item['id']}"
                    if key not in st.session_state: st.session_state[key] = False
                    if not st.session_state[key]:
                        if c1.button("Get Link", key=f"btn_{item['id']}"): st.session_state[key] = True; st.rerun()
                    else:
                        url = f"https://wa.me/{item['phone']}?text={urllib.parse.quote(item['ai_message'])}"
                        c1.markdown(f"<a href='{url}' target='_blank' style='display:block;text-align:center;background:#2e7d32;color:white;padding:8px;border-radius:4px;text-decoration:none;'>Open WhatsApp</a>", unsafe_allow_html=True)
                        if c2.button("Complete", key=f"fin_{item['id']}"):
                            mark_lead_complete_secure(item['id'], st.session_state['username'])
                            del st.session_state[key]; time.sleep(0.5); st.rerun()
    with t2:
        dones = [x for x in my_leads if x.get('is_contacted')]
        if dones:
            df = pd.DataFrame(dones)
            st.dataframe(df[['shop_name', 'phone', 'completed_at']], use_container_width=True)

    st.markdown("#### History")
    _, _, df_hist = get_user_historical_data(st.session_state['username'])
    if not df_hist.empty: st.dataframe(df_hist, use_container_width=True)

elif selected_nav == "Logs":
    st.markdown("#### Activity Logs")
    d = st.date_input("Date", date.today())
    c, f = get_daily_logs(d.isoformat())
    c1, c2 = st.columns(2)
    with c1: st.markdown("##### Claims"); st.dataframe(c, use_container_width=True)
    with c2: st.markdown("##### Completed"); st.dataframe(f, use_container_width=True)

elif selected_nav == "Team":
    users = pd.DataFrame(supabase.table('users').select("*").neq('role', 'admin').execute().data)
    c1, c2 = st.columns([1, 2])
    with c1:
        u = st.radio("Staff", users['username'].tolist() if not users.empty else [])
        with st.expander("Add User"):
            with st.form("new_user"):
                nu = st.text_input("Username"); np = st.text_input("Password"); nn = st.text_input("Name")
                if st.form_submit_button("Create"): create_user(nu, np, nn); st.rerun()
    with c2:
        if u:
            info = users[users['username']==u].iloc[0]
            tc, td, _ = get_user_historical_data(u)
            perf = get_user_daily_performance(u)
            st.markdown(f"### {info['real_name']}")
            st.caption(f"ID: {info['username']} | Points: {info.get('points', 0)}")
            
            new_limit = st.slider("Daily Limit", 0, 100, int(info.get('daily_limit') or 25))
            if st.button("Update Limit"): update_user_limit(u, new_limit); st.toast("Updated"); time.sleep(0.5); st.rerun()
            
            st.bar_chart(perf.head(14))

elif selected_nav == "Import":
    pool = get_public_pool_count()
    st.metric("Public Pool", pool)
    if st.button("Recycle Expired"): 
        n = recycle_expired_tasks()
        st.success(f"Recycled {n} tasks")
            
    st.markdown("#### Bulk Import")
    force = st.checkbox("Skip Verification")
    f = st.file_uploader("Upload CSV/Excel", type=['csv', 'xlsx'])
    if f and st.button("Process"):
        try:
            df = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
            st.info(f"Rows: {len(df)}")
            with st.status("Processing...", expanded=True) as s:
                df=df.astype(str); phones = set(); rmap = {}
                for i, r in df.iterrows():
                    for p in extract_all_numbers(r): phones.add(p); rmap.setdefault(p, []).append(i)
                
                plist = list(phones); valid = []
                if force: valid = plist
                else:
                    for i in range(0, len(plist), 500):
                        batch = plist[i:i+500]
                        res, _, _ = process_checknumber_task(batch, CN_KEY, CN_USER)
                        valid.extend([p for p in batch if res.get(p)=='valid'])
                
                rows = []
                for p in valid:
                    r = df.iloc[rmap[p][0]]; lnk = r.iloc[0]; shp = r.iloc[1] if len(r)>1 else "Shop"
                    rows.append({"shop_name":shp, "shop_link":lnk, "phone":p, "ai_message":"", "retry_count": 0, "is_frozen": False})
                    if len(rows)>=100: 
                        admin_bulk_upload_to_pool(rows); rows=[]
                if rows: admin_bulk_upload_to_pool(rows)
                s.update(label="Done", state="complete")
        except Exception as e: st.error(str(e))
