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
import smtplib
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr, parseaddr
from datetime import date, datetime, timedelta
import concurrent.futures
import streamlit.components.v1 as components
from bs4 import BeautifulSoup
from PIL import Image

# 尝试导入 imap_tools
try:
    from imap_tools import MailBox, AND
    IMAP_TOOLS_INSTALLED = True
except ImportError:
    IMAP_TOOLS_INSTALLED = False

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

    .email-card { padding: 15px; background: rgba(255,255,255,0.03); border-radius: 8px; margin-bottom: 10px; border-left: 3px solid #444; backdrop-filter: blur(10px); }
    .email-card.received { border-left-color: #4b90ff; }
    .email-card.sent { border-left-color: #ff5546; }
    .email-meta { font-size: 11px; color: #888; margin-bottom: 5px; display: flex; justify-content: space-between; }
    .email-body { font-size: 13px; color: #e3e3e3; white-space: pre-wrap; line-height: 1.5; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 数据库与用户逻辑
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

# 邮箱配置相关
def get_user_email_config(username):
    if not supabase: return None
    try:
        res = supabase.table('users').select('email_config').eq('username', username).single().execute()
        return res.data.get('email_config')
    except: return None

def update_user_email_config(username, config_dict):
    if not supabase: return False
    try:
        supabase.table('users').update({'email_config': config_dict}).eq('username', username).execute()
        return True
    except: return False

# ==========================================
# 邮件处理核心引擎 (SMTP + IMAP)
# ==========================================
class EmailEngine:
    def __init__(self, config, sender_name="Sales"):
        self.config = config 
        self.sender_name = sender_name

    def send_email(self, to_email, subject, body_text):
        if not self.config: return False, "配置缺失"
        try:
            html_content = body_text.replace("\n", "<br>")
            msg = MIMEText(html_content, 'html', 'utf-8')
            display_from = f"{self.sender_name} | 988 Group"
            msg['From'] = formataddr((Header(display_from, 'utf-8').encode(), self.config['email']))
            msg['To'] = to_email
            msg['Subject'] = Header(subject, 'utf-8')
            server = smtplib.SMTP_SSL(self.config['smtp_server'], int(self.config['smtp_port']))
            server.login(self.config['email'], self.config['password'])
            server.sendmail(self.config['email'], [to_email], msg.as_string())
            server.quit()
            return True, "发送成功"
        except Exception as e:
            return False, str(e)

    def fetch_thread(self, client_email):
        if not self.config or not IMAP_TOOLS_INSTALLED: return []
        emails = []
        try:
            with MailBox(self.config['imap_server']).login(self.config['email'], self.config['password']) as mailbox:
                mailbox.folder.set('INBOX')
                for msg in mailbox.fetch(limit=10, reverse=True):
                    if client_email in msg.from_ or client_email in msg.to:
                        emails.append(self._parse_msg(msg, "Inbox"))
                
                sent_folders = ['Sent Messages', 'Sent Items', 'Sent', '[Gmail]/Sent Mail']
                for f in mailbox.folder.list():
                    if any(s in f['name'] for s in sent_folders):
                        mailbox.folder.set(f['name'])
                        for msg in mailbox.fetch(limit=10, reverse=True):
                             if client_email in msg.to:
                                emails.append(self._parse_msg(msg, "Sent"))
                        break
        except Exception as e:
            print(f"IMAP Error: {e}")
        return sorted(emails, key=lambda x: x['date'], reverse=True)

    def _parse_msg(self, msg, folder):
        return {
            "subject": msg.subject,
            "from": msg.from_,
            "to": msg.to,
            "date": msg.date_str,
            "text": msg.text or msg.html,
            "folder": folder
        }
    
    def sync_inbox_for_replies(self, username):
        if not self.config or not IMAP_TOOLS_INSTALLED: return 0
        count = 0
        try:
            leads = supabase.table('leads').select('id, email').eq('assigned_to', username).eq('is_contacted', True).neq('email', None).execute().data
            if not leads: return 0
            lead_map = {l['email']: l['id'] for l in leads}
            with MailBox(self.config['imap_server']).login(self.config['email'], self.config['password']) as mailbox:
                mailbox.folder.set('INBOX')
                for msg in mailbox.fetch(limit=50, reverse=True):
                    from_email = parseaddr(msg.from_)[1]
                    if from_email in lead_map:
                        supabase.table('leads').update({'has_new_reply': True}).eq('id', lead_map[from_email]).execute()
                        count += 1
        except Exception as e:
            print(f"Sync Error: {e}")
        return count

# 🔥【关键函数】强力清洗电话号码，修复 404 问题
def clean_phone_for_whatsapp(phone_raw):
    if pd.isna(phone_raw) or phone_raw == "" or str(phone_raw).lower() == 'nan': return None
    
    # 1. 强制转字符串并去掉小数点 (处理 Excel 浮点数)
    s = str(phone_raw).split('.')[0].strip()
    
    # 2. 移除所有非数字字符
    s = re.sub(r'\D', '', s)
    
    if not s: return None
    
    # 3. 俄罗斯/哈萨克斯坦号码特殊修正
    # 如果是 11 位且以 8 开头 -> 改为 7
    if len(s) == 11 and s.startswith('8'):
        s = '7' + s[1:]
    # 如果是 10 位 -> 补 7
    elif len(s) == 10:
        s = '7' + s
        
    return s

# ==========================================
# 报价单 & AI 辅助
# ==========================================
def generate_quotation_excel(items, service_fee_percent, total_domestic_freight, company_info):
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet("Sheet1")
    fmt_header_main = workbook.add_format({'bold': True, 'font_size': 16, 'align': 'center', 'valign': 'vcenter'})
    fmt_header_sub = workbook.add_format({'font_size': 11, 'align': 'left', 'valign': 'vcenter', 'text_wrap': True})
    fmt_table_header = workbook.add_format({'bold': True, 'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'bg_color': '#f0f0f0', 'text_wrap': True})
    fmt_cell_center = workbook.add_format({'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
    fmt_cell_left = workbook.add_format({'font_size': 10, 'align': 'left', 'valign': 'vcenter', 'border': 1, 'text_wrap': True})
    fmt_money = workbook.add_format({'font_size': 10, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '¥#,##0.00'})
    fmt_bold_red = workbook.add_format({'bold': True, 'color': 'red', 'font_size': 11})
    fmt_total_row = workbook.add_format({'bold': True, 'font_size': 11, 'align': 'right', 'valign': 'vcenter', 'border': 1, 'bg_color': '#e6e6e6'})
    fmt_total_money = workbook.add_format({'bold': True, 'font_size': 11, 'align': 'center', 'valign': 'vcenter', 'border': 1, 'num_format': '¥#,##0.00', 'bg_color': '#e6e6e6'})
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

    headers = [("序号", 4), ("型号", 15), ("图片", 15), ("名称", 15), ("描述", 25), ("数量", 8), ("EXW 单价", 12), ("货值", 12)]
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
                else: scale = 0.5
                img_byte_stream.seek(0)
                worksheet.insert_image(current_row, 2, "img.png", {'image_data': img_byte_stream, 'x_scale': scale, 'y_scale': scale, 'object_position': 2})
            except Exception as e: worksheet.write(current_row, 2, "Error", fmt_cell_center)
        else: worksheet.write(current_row, 2, "No Image", fmt_cell_center)

        worksheet.write(current_row, 3, item.get('name', ''), fmt_cell_left)
        worksheet.write(current_row, 4, item.get('desc', ''), fmt_cell_left)
        worksheet.write(current_row, 5, qty, fmt_cell_center)
        worksheet.write(current_row, 6, factory_price_unit, fmt_money)
        worksheet.write(current_row, 7, line_total_exw, fmt_money)
        current_row += 1

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
        x1 = max(0, x1); y1 = max(0, y1); x2 = min(width, x2); y2 = min(height, y2)
        if (x2 - x1) < 5 or (y2 - y1) < 5: return original_image_bytes
        cropped_img = img.crop((x1, y1, x2, y2))
        output = io.BytesIO()
        cropped_img.save(output, format=img.format if img.format else 'PNG')
        return output.getvalue()
    except Exception as e: return original_image_bytes

def parse_image_with_ai(image_file, client):
    if not image_file: return None
    base64_image = base64.b64encode(image_file.getvalue()).decode('utf-8')
    prompt = """
    Role: Advanced OCR & Data Extraction engine specialized in Chinese E-commerce.
    CONTEXT: Product list screenshot.
    MISSION:
    1. SCAN VERTICALLY: Extract EVERY variant row.
    2. BOUNDING BOX (STRICT): Return EXACT bounding box for thumbnail. NO whitespace.
       Return `bbox_1000`: `[ymin, xmin, ymax, xmax]` (0-1000 scale).
    DATA:
    - Name: Product name (Russian).
    - Model: Variant spec.
    - Desc: Short summary (max 5 words, Russian).
    - Price: Number only.
    - Qty: Number only.
    Output JSON: { "items": [{ "name_ru": "...", "model": "...", "desc_ru": "...", "price_cny": 0.0, "qty": 0, "bbox_1000": [...] }] }
    """
    try:
        res = client.chat.completions.create(
            model=CONFIG["AI_MODEL"], 
            messages=[{"role": "user", "content": [{"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}]}],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except: return None

def parse_product_info_with_ai(text_content, client):
    if not text_content: return None
    prompt = f"""
    Role: B2B Assistant. Analyze input.
    Output JSON: {{ "name_ru": "...", "model": "...", "price_cny": 0.0, "qty": 0, "desc_ru": "Short summary" }}
    """
    try:
        res = client.chat.completions.create(model=CONFIG["AI_MODEL"], messages=[{"role":"user", "content": prompt}], response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except: return None

def get_daily_motivation(client):
    if "motivation_quote" not in st.session_state:
        local_quotes = ["心有繁星，沐光而行。", "坚持是另一种形式的天赋。", "每一步都算数。"]
        try:
            if not client: raise Exception("No Client")
            prompt = "生成一句简短的中文职场励志语。无表情符号。"
            res = client.chat.completions.create(model=CONFIG["AI_MODEL"], messages=[{"role":"user","content":prompt}], temperature=0.9, max_tokens=60)
            st.session_state["motivation_quote"] = res.choices[0].message.content
        except: st.session_state["motivation_quote"] = random.choice(local_quotes)
    return st.session_state["motivation_quote"]

def ai_generate_email_reply(client, context, user_username, shop_name, customer_name=None):
    greeting = f"Здравствуйте, {customer_name}" if customer_name else f"Здравствуйте, команда {shop_name}"
    prompt = f"""
    Role: Professional Logistics Sales Rep from 988 Group.
    My Name: {user_username}
    Target Client: {shop_name} (Ozon Seller).
    Task: Write a cold email body in Russian.
    Requirements:
    1. Greeting: "{greeting}, я увидел ваш магазин на Ozon и..." (Must use Russian).
    2. Context: Infer what they sell based on the shop name (e.g. if name is "ToyStore", mention toys in Russian).
    3. Offer: We provide fast customs clearance and white tax compliance for their specific products.
    4. Format: PLAIN TEXT only. Use newlines for paragraphs. NO HTML tags (no <br>, no <p>).
    5. Tone: Professional, direct. No emojis.
    Output JSON: {{ "body_text": "..." }}
    """
    try:
        res = client.chat.completions.create(model="gpt-4o", messages=[{"role":"user","content":prompt}], response_format={"type": "json_object"})
        return json.loads(res.choices[0].message.content)
    except: return None

def get_ai_message_sniper(client, shop, link, rep_name):
    offline = f"Здравствуйте! Заметили ваш магазин {shop} на Ozon. {rep_name} из 988 Group на связи. Мы занимаемся поставками из Китая. Можем рассчитать логистику?"
    if not shop or str(shop).lower() in ['nan', 'none', '']: return "数据缺失"
    prompt = f"""
    Role: Supply Chain Manager '{rep_name}' at 988 Group.
    Target: Ozon Seller '{shop}' (Link: {link}).
    Task: Write Russian WhatsApp intro (under 50 words). Professional. No emojis.
    """
    try:
        if not client: return offline
        res = client.chat.completions.create(model=CONFIG["AI_MODEL"],messages=[{"role":"user","content":prompt}])
        return res.choices[0].message.content.strip()
    except: return offline

def get_wechat_maintenance_script(client, customer_code, rep_name):
    offline = f"您好，我是 988 Group 的 {rep_name}。最近生意如何？工厂那边出了一些新品，如果您需要补货或者看新款，随时联系我。"
    prompt = f"""
    Role: Account Manager '{rep_name}'.
    Target: Customer '{customer_code}'.
    Task: Write short Chinese maintenance message. Professional. No emojis.
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
        completion = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "system", "content": "Translate Russian to Chinese. Professional tone."}, {"role": "user", "content": ru_text}])
        cn_text = completion.choices[0].message.content
        return ru_text, cn_text
    except Exception as e: return f"Error: {str(e)}", "翻译失败"

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
        supabase.table('wechat_customers').update({'last_contact_date': today.isoformat(), 'next_contact_date': next_date}).eq('id', task_id).execute()
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
    if not supabase or not rows_to_insert: return 0, "No data"
    success_count = 0
    try:
        incoming = [str(r['phone']) for r in rows_to_insert if r['phone']]
        existing = set()
        chunk_size = 500
        
        if incoming:
            for i in range(0, len(incoming), chunk_size):
                batch = incoming[i:i+chunk_size]
                res = supabase.table('leads').select('phone').in_('phone', batch).execute()
                for item in res.data: existing.add(str(item['phone']))
        
        final_rows = [r for r in rows_to_insert if (not r['phone']) or (str(r['phone']) not in existing)]
        
        if not final_rows: return 0, "重复数据"
        
        for row in final_rows: row['username'] = st.session_state.get('username', 'admin')
        response = supabase.table('leads').insert(final_rows).execute()
        return len(response.data), "Success"
    except Exception as e:
        for row in final_rows:
            try:
                row['username'] = st.session_state.get('username', 'admin')
                supabase.table('leads').insert(row).execute()
                success_count += 1
            except: pass
        return success_count, str(e)

def claim_daily_tasks(username, client):
    today_str = date.today().isoformat()
    existing = supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data
    current_count = len(existing)
    user_max_limit = get_user_limit(username)
    if current_count >= user_max_limit: return existing, "full"
    
    needed = user_max_limit - current_count
    pool_leads = supabase.table('leads').select("id").is_('assigned_to', 'null').eq('is_frozen', False).limit(needed).execute().data
    
    if pool_leads:
        ids_to_update = [x['id'] for x in pool_leads]
        supabase.table('leads').update({'assigned_to': username, 'assigned_at': today_str}).in_('id', ids_to_update).execute()
        fresh_tasks = supabase.table('leads').select("*").in_('id', ids_to_update).execute().data
        with st.status(f"正在为 {username} 生成文案...", expanded=True) as status:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(generate_and_update_task, task, client, username) for task in fresh_tasks]
                concurrent.futures.wait(futures)
            status.update(label="完成", state="complete")
        return supabase.table('leads').select("*").eq('assigned_to', username).eq('assigned_at', today_str).execute().data, "claimed"
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
    if not phone_list: return {}, "空列表", None
    status_map = {p: 'unknown' for p in phone_list}
    headers = {"X-API-Key": api_key}
    try:
        files = {'file': ('input.txt', "\n".join(phone_list), 'text/plain')}
        resp = requests.post(CONFIG["CN_BASE_URL"], headers=headers, files=files, data={'user_id': user_id}, verify=False)
        if resp.status_code != 200: return status_map, f"API 错误: {resp.status_code}", None
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
                    return status_map, "成功", df
        return status_map, "超时", None
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

# 🔥【强力修复】针对 Excel 脏数据和俄罗斯号码
def clean_phone_for_whatsapp(phone_raw):
    # 1. 空值检查
    if pd.isna(phone_raw) or phone_raw == "" or str(phone_raw).lower() == 'nan':
        return None
    
    # 2. 强制转字符串，并按小数点分割 (防止 7925.0 这种情况)
    s = str(phone_raw).split('.')[0].strip()
    
    # 3. 移除所有非数字字符 (+, -, 空格, 括号)
    s = re.sub(r'\D', '', s)
    
    if not s: return None
    
    # 4. 俄罗斯/哈萨克斯坦号码特殊修正
    # 情况A: 11位，以8开头 -> 改为7 (例如 89251234567 -> 79251234567)
    if len(s) == 11 and s.startswith('8'):
        s = '7' + s[1:]
    
    # 情况B: 10位 -> 补7 (例如 9251234567 -> 79251234567)
    elif len(s) == 10:
        s = '7' + s
        
    return s

# ==========================================
# 登录页
# ==========================================
if 'logged_in' not in st.session_state: st.session_state['logged_in'] = False

if not st.session_state['logged_in']:
    c1, c2, c3 = st.columns([1,1.2,1])
    with c2:
        st.markdown("<br><br><br><br>", unsafe_allow_html=True)
        st.markdown('<div class="gemini-header" style="text-align:center;">988 GROUP CRM</div>', unsafe_allow_html=True)
        st.markdown('<div class="warm-quote" style="text-align:center;">专业 · 高效 · 全球化</div>', unsafe_allow_html=True)
        
        with st.form("login", border=False):
            u = st.text_input("账号", placeholder="请输入账号")
            p = st.text_input("密码", type="password", placeholder="请输入密码")
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
    menu_map = {"System": "系统监控", "Logs": "活动日志", "Team": "团队管理", "Import": "批量进货", "WeChat": "微信管理", "Settings": "邮箱配置", "Tools": "实用工具"}
    menu_options = ["System", "Logs", "Team", "Import", "WeChat", "Settings", "Tools"]
else:
    menu_map = {"Workbench": "销售工作台", "WeChat": "微信维护", "Settings": "邮箱配置", "Tools": "实用工具"}
    menu_options = ["Workbench", "WeChat", "Settings", "Tools"]

selected_nav = st.radio("导航菜单", menu_options, format_func=lambda x: menu_map.get(x, x), horizontal=True, label_visibility="collapsed")
st.markdown("<br>", unsafe_allow_html=True)

# ------------------------------------------
# 邮箱配置 (Settings)
# ------------------------------------------
if selected_nav == "Settings":
    st.markdown("#### 个人邮箱配置")
    st.caption("配置您的 SMTP/IMAP 信息以启用邮件营销功能。")
    
    current_config = get_user_email_config(st.session_state['username']) or {}
    
    with st.form("email_config_form"):
        c1, c2 = st.columns(2)
        email_addr = c1.text_input("邮箱地址", value=current_config.get('email', ''))
        email_pass = c2.text_input("授权码/密码", type="password", value=current_config.get('password', ''), help="对于 Gmail/QQ/网易，请使用应用专用密码")
        
        c3, c4 = st.columns(2)
        smtp_srv = c3.text_input("SMTP 服务器", value=current_config.get('smtp_server', 'smtp.gmail.com'))
        smtp_port = c4.text_input("SMTP 端口", value=current_config.get('smtp_port', '465'))
        
        imap_srv = st.text_input("IMAP 服务器", value=current_config.get('imap_server', 'imap.gmail.com'))
        
        if st.form_submit_button("保存配置"):
            cfg = {
                "email": email_addr, "password": email_pass,
                "smtp_server": smtp_srv, "smtp_port": smtp_port,
                "imap_server": imap_srv
            }
            if update_user_email_config(st.session_state['username'], cfg):
                st.success("配置已保存")
            else:
                st.error("保存失败")

# ------------------------------------------
# 销售工作台 (Workbench)
# ------------------------------------------
elif selected_nav == "Workbench":
    # 检查邮箱配置
    user_conf = get_user_email_config(st.session_state['username'])
    # 🔥 修复：传入用户名 (Username) 作为发件人名
    email_engine = EmailEngine(user_conf, st.session_state['username']) if user_conf else None
    
    if not email_engine:
        st.markdown("""<div class="custom-alert alert-error">请先在 [邮箱配置] 中设置您的发件箱信息</div>""", unsafe_allow_html=True)
    
    mode = st.radio("营销通道", ["邮件营销", "WhatsApp 开发"], horizontal=True)
    
    if mode == "邮件营销":
        today_str = date.today().isoformat()
        # 增加一个全局同步按钮
        c_sync, _ = st.columns([1, 4])
        with c_sync:
            if st.button("🔄 同步所有邮件"):
                with st.status("正在同步收件箱...", expanded=True):
                    count = email_engine.sync_inbox_for_replies(st.session_state['username'])
                    st.write(f"发现 {count} 个新回复！")
                st.rerun()

        # 分离出两个列表：所有有回复的 / 所有已领取的
        # 1. 待跟进 (有新回复)
        active_leads = supabase.table('leads').select("*").eq('assigned_to', st.session_state['username']).eq('has_new_reply', True).execute().data
        
        # 2. 公海池 (待开发)
        pending_leads = supabase.table('leads').select("*").eq('assigned_to', st.session_state['username']).eq('has_new_reply', False).neq('email', None).execute().data
        
        c_list, c_work = st.columns([1, 2])
        
        with c_list:
            tab_todo, tab_pool, tab_manual = st.tabs(["🔴 待跟进", "⚪ 待开发", "✏️ 手动录入"])
            
            with tab_todo:
                if not active_leads: st.info("暂无新回复")
                for task in active_leads:
                    if st.button(f"🔴 {task.get('shop_name', 'Unknown')}", key=f"active_{task['id']}", use_container_width=True):
                        st.session_state['selected_mail_lead'] = task
                        st.session_state['is_manual_lead'] = False
                        # 点击即读，清除红点
                        supabase.table('leads').update({'has_new_reply': False}).eq('id', task['id']).execute()
            
            with tab_pool:
                if st.button("领取新邮件客户"):
                    pool = supabase.table('leads').select('id').is_('assigned_to', 'null').neq('email', None).limit(5).execute().data
                    if pool:
                        ids = [x['id'] for x in pool]
                        supabase.table('leads').update({'assigned_to': st.session_state['username'], 'assigned_at': today_str}).in_('id', ids).execute()
                        st.rerun()
                
                for task in pending_leads:
                    status_icon = "🟢" if task.get('is_contacted') else "⚪"
                    if st.button(f"{status_icon} {task.get('shop_name', 'Unknown')}", key=f"pool_{task['id']}", use_container_width=True):
                        st.session_state['selected_mail_lead'] = task
                        st.session_state['is_manual_lead'] = False

            with tab_manual:
                with st.form("manual_lead_form"):
                    m_name = st.text_input("客户称呼 (Name)")
                    m_shop = st.text_input("店铺/公司名 (Shop)")
                    m_email = st.text_input("邮箱 (Email)")
                    if st.form_submit_button("载入工作台"):
                        st.session_state['selected_mail_lead'] = {
                            "id": "manual",
                            "shop_name": m_shop,
                            "email": m_email,
                            "phone": "",
                            "contact_name": m_name 
                        }
                        st.session_state['is_manual_lead'] = True
                        st.rerun()

        with c_work:
            lead = st.session_state.get('selected_mail_lead')
            if lead:
                st.markdown(f"### {lead.get('shop_name')}")
                st.caption(f"邮箱: {lead.get('email')} | 电话: {lead.get('phone')}")
                
                t_compose, t_history = st.tabs(["撰写邮件", "往来记录 & AI"])
                
                with t_compose:
                    if st.button("✨ AI 自动生成俄语开发信"):
                        with st.status("AI 正在撰写...", expanded=True):
                            contact_name = lead.get('contact_name') 
                            draft = ai_generate_email_reply(
                                client, 
                                "Cold Outreach", 
                                st.session_state['username'], 
                                lead.get('shop_name', 'Ozon Seller'),
                                customer_name=contact_name
                            )
                            if draft:
                                st.session_state['mail_subj'] = f"{st.session_state['username']} | 988 Group | China Logistics"
                                st.session_state['mail_body'] = draft.get('body_text')
                    
                    with st.form("send_mail_form"):
                        subj = st.text_input("主题", value=st.session_state.get('mail_subj', ''))
                        body = st.text_area("正文 (纯文本，回车自动换行)", value=st.session_state.get('mail_body', ''), height=300)
                        
                        if st.form_submit_button("发送邮件"):
                            if email_engine:
                                success, msg = email_engine.send_email(lead.get('email'), subj, body)
                                if success:
                                    st.success("发送成功")
                                    if not st.session_state.get('is_manual_lead', False):
                                        supabase.table('leads').update({'is_contacted': True, 'last_email_time': datetime.now().isoformat()}).eq('id', lead['id']).execute()
                                else:
                                    st.error(f"发送失败: {msg}")
                            else:
                                st.error("未配置邮箱")

                with t_history:
                    # 获取该客户的往来邮件
                    emails = email_engine.fetch_thread(lead.get('email'))
                    if emails:
                        for em in emails:
                            css = "sent" if user_conf['email'] in em['from'] else "received"
                            # 简单的 HTML 清洗
                            clean_text = re.sub('<[^<]+?>', '', em['text'])[:300]
                            st.markdown(f"""
                            <div class="email-card {css}">
                                <div class="email-meta">
                                    <span>{em['date']}</span>
                                    <span>{em['folder']}</span>
                                </div>
                                <strong>{em['subject']}</strong>
                                <div class="email-body">{clean_text}...</div>
                            </div>
                            """, unsafe_allow_html=True)
                    else:
                        st.info("暂无往来邮件 (仅显示收件箱和已发送)")
            else:
                st.info("请从左侧选择一个客户")

    elif mode == "WhatsApp 开发":
        my_leads = get_todays_leads(st.session_state['username'], client)
        user_limit = get_user_limit(st.session_state['username'])
        total, curr = user_limit, len(my_leads)
        
        c_stat, c_action = st.columns([2, 1])
        with c_stat:
            done = sum(1 for x in my_leads if x.get('is_contacted'))
            st.metric("今日进度", f"{done} / {total}")
            st.progress(min(done/total, 1.0) if total > 0 else 0)
            
        with c_action:
            st.markdown("<br>", unsafe_allow_html=True)
            if curr < total:
                if st.button(f"领取任务 (余 {total-curr} 个)"):
                    _, status = claim_daily_tasks(st.session_state['username'], client)
                    if status=="empty": st.markdown("""<div class="custom-alert alert-error">公池已空</div>""", unsafe_allow_html=True)
                    else: st.rerun()
            else: st.markdown("""<div class="custom-alert alert-success">今日已领满</div>""", unsafe_allow_html=True)

        st.markdown("#### 任务列表")
        t1, t2 = st.tabs(["待跟进", "已完成"])
        with t1:
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
                            # 🔥 修复：深度清洗电话号码，强制 wa.me 短链接
                            clean_phone = clean_phone_for_whatsapp(item['phone'])
                            
                            if clean_phone:
                                url = f"https://wa.me/{clean_phone}?text={urllib.parse.quote(item['ai_message'])}"
                                
                                c1.caption(f"正在呼叫: +{clean_phone}") # 调试显示
                                c1.markdown(f"<a href='{url}' target='_blank' style='display:block;text-align:center;background:#1e1f20;color:#e3e3e3;padding:10px;border-radius:20px;text-decoration:none;font-size:14px;'>跳转 WhatsApp ↗</a>", unsafe_allow_html=True)
                            else:
                                c1.error("无效号码")

                            if c2.button("确认完成", key=f"fin_{item['id']}"):
                                mark_lead_complete_secure(item['id'], st.session_state['username'])
                                del st.session_state[key]; time.sleep(0.5); st.rerun()
        with t2:
            dones = [x for x in my_leads if x.get('is_contacted')]
            if dones:
                df = pd.DataFrame(dones)
                st.dataframe(df[['shop_name', 'phone', 'completed_at']], use_container_width=True)

# ------------------------------------------
# 实用工具 (Tools) - 包含报价生成器
# ------------------------------------------
elif selected_nav == "Tools":
    tab_quote, tab_trans = st.tabs(["报价生成器", "俄语语音翻译"])
    
    with tab_quote:
        if not XLSXWRITER_INSTALLED:
            st.error("未安装 XlsxWriter 库。")
        else:
            if "quote_items" not in st.session_state: st.session_state["quote_items"] = []

            with st.container():
                st.markdown("#### 添加商品")
                # 默认优先展示 AI 识别
                sub_t1, sub_t2 = st.tabs(["AI 智能识别 (优先)", "人工录入"])
                
                with sub_t1:
                    c_text_ai, c_img_ai = st.columns([2, 1])
                    with c_text_ai:
                        ai_input_text = st.text_area("粘贴文字/链接", height=100, placeholder="例如：1688 链接或聊天记录")
                    with c_img_ai:
                        ai_input_image = st.file_uploader("上传产品图", type=['jpg', 'png', 'jpeg'])
                    
                    if st.button("开始 AI 分析"):
                        with st.status("AI 正在思考中...", expanded=True) as status:
                            new_items = []
                            if ai_input_image:
                                status.write("正在进行多目标视觉分析 & 智能裁剪...")
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
                                status.write("正在理解语义...")
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
                                status.update(label=f"成功添加 {len(new_items)} 个商品", state="complete")
                                time.sleep(1)
                                st.rerun()
                            else:
                                status.update(label="识别失败", state="error")

                with sub_t2:
                    with st.form("manual_add", clear_on_submit=True):
                        c_img, c_main = st.columns([1, 3])
                        with c_img:
                            img_file = st.file_uploader("图片", type=['png', 'jpg', 'jpeg'])
                        with c_main:
                            c1, c2, c3 = st.columns(3)
                            model = c1.text_input("型号")
                            name = c2.text_input("名称 (俄语)")
                            price_exw = c3.number_input("工厂单价 (¥)", min_value=0.0, step=0.1)
                            c4, c5 = st.columns([1, 2])
                            qty = c4.number_input("数量", min_value=1, step=1)
                            desc = c5.text_input("描述 (俄语)")
                        if st.form_submit_button("添加清单"):
                            img_data = img_file.getvalue() if img_file else None
                            st.session_state["quote_items"].append({"model": model, "name": name, "desc": desc, "price_exw": price_exw, "qty": qty, "image_data": img_data})
                            st.success("已添加")
                            st.rerun()

            st.divider()

            col_list, col_setting = st.columns([2, 1])

            with col_list:
                st.markdown("#### 报价清单")
                items = st.session_state["quote_items"]
                if items:
                    df_show = pd.DataFrame(items)
                    st.dataframe(df_show[['model', 'name', 'price_exw', 'qty']], use_container_width=True)
                    if st.button("清空清单"):
                        st.session_state["quote_items"] = []
                        st.rerun()
                else:
                    st.info("暂无商品")

            with col_setting:
                with st.container():
                    st.markdown("#### 全局设置")
                    total_freight = st.number_input("国内总运费 (¥)", min_value=0.0, step=10.0)
                    service_fee = st.slider("服务费率 (%)", 0, 50, 5)
                    
                    with st.expander("表头信息设置"):
                        co_name = st.text_input("公司名称", value="义乌市万昶进出口有限公司")
                        co_tel = st.text_input("电话", value="+86-15157938188")
                        co_wechat = st.text_input("WeChat", value="15157938188")
                        co_email = st.text_input("邮箱", value="CTF1111@163.com")
                        co_addr = st.text_input("地址", value="义乌市工人北路1121号5楼")
                    
                    st.markdown("<br>", unsafe_allow_html=True)
                    
                    if items:
                        product_total_exw = sum(i['price_exw'] * i['qty'] for i in items)
                        service_fee_val = product_total_exw * (service_fee/100)
                        final_val = product_total_exw + total_freight + service_fee_val
                        
                        st.markdown(f"""
                        <div style="padding:15px; border:1px solid #444; border-radius:10px; background:rgba(255,255,255,0.05)">
                            <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e">
                                <span>工厂货值 (EXW):</span> <span>¥ {product_total_exw:,.2f}</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e; margin-top:5px;">
                                <span>+ 国内运费:</span> <span>¥ {total_freight:,.2f}</span>
                            </div>
                            <div style="display:flex; justify-content:space-between; font-size:13px; color:#8e8e8e; margin-top:5px;">
                                <span>+ 服务费 ({service_fee}%):</span> <span>¥ {service_fee_val:,.2f}</span>
                            </div>
                            <div style="height:1px; background:#555; margin:10px 0;"></div>
                            <div style="display:flex; justify-content:space-between; font-size:18px; font-weight:600; color:#fff">
                                <span>总计 (Total):</span> <span>¥ {final_val:,.2f}</span>
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
                        st.download_button("下载 Excel 报价单", data=excel_data, file_name=f"Quotation_{date.today().isoformat()}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")

    with tab_trans:
        st.markdown("#### 俄语语音翻译器")
        uploaded_audio = st.file_uploader("上传语音 (mp3, wav, m4a)", type=['mp3', 'wav', 'm4a', 'ogg', 'webm'])
        if uploaded_audio and st.button("开始翻译"):
            with st.status("正在处理...", expanded=True) as status:
                status.write("正在听写俄语...")
                ru_text, cn_text = transcribe_audio(client, uploaded_audio)
                status.write("正在翻译成中文...")
                time.sleep(1)
                status.update(label="完成", state="complete")
                
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown("**俄语原文**")
                    st.info(ru_text)
                with c2:
                    st.markdown("**中文翻译**")
                    st.success(cn_text)

# ------------------------------------------
# System & Admin
# ------------------------------------------
elif selected_nav == "System" and st.session_state['role'] == 'admin':
    with st.expander("API 调试器"):
        st.code(f"Model: {CONFIG['AI_MODEL']}")
        st.code(f"Key (Last 5): {OPENAI_KEY[-5:] if OPENAI_KEY else 'N/A'}")
        
    frozen_count, frozen_leads = get_frozen_leads_count()
    if frozen_count > 0:
        st.markdown(f"""<div class="custom-alert alert-error">警告：有 {frozen_count} 个任务被冻结</div>""", unsafe_allow_html=True)
        with st.expander("查看冻结详情", expanded=True):
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
            st.info(f"读取到 {len(df)} 行数据")
            with st.status("正在运行流水线...", expanded=True) as s:
                nums = []
                for _, r in df.head(5).iterrows(): nums.extend(extract_all_numbers(r))
                s.write(f"提取结果: {nums}")
                res, _, _ = process_checknumber_task(nums, CN_KEY, CN_USER)
                valid = [p for p in nums if res.get(p)=='valid']
                s.write(f"有效号码: {valid}")
                s.update(label="模拟完成", state="complete")
        except Exception as e: st.error(str(e))

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

elif selected_nav == "Logs":
    st.markdown("#### 活动日志监控")
    d = st.date_input("选择日期", date.today())
    c, f = get_daily_logs(d.isoformat())
    c1, c2 = st.columns(2)
    with c1: st.markdown("领取记录"); st.dataframe(c, use_container_width=True)
    with c2: st.markdown("完成记录"); st.dataframe(f, use_container_width=True)

elif selected_nav == "Team":
    users = pd.DataFrame(supabase.table('users').select("*").neq('role', 'admin').execute().data)
    c1, c2 = st.columns([1, 2])
    with c1:
        u = st.radio("员工列表", users['username'].tolist() if not users.empty else [], label_visibility="collapsed")
        with st.expander("新增员工"):
            with st.form("new_user"):
                nu = st.text_input("用户名"); np = st.text_input("密码", type="password"); nn = st.text_input("真实姓名")
                if st.form_submit_button("创建账号"): create_user(nu, np, nn); st.rerun()
    with c2:
        if u:
            info = users[users['username']==u].iloc[0]
            tc, td, _ = get_user_historical_data(u)
            perf = get_user_daily_performance(u)
            st.markdown(f"### {info['real_name']}")
            st.caption(f"账号: {info['username']} | 积分: {info.get('points', 0)} | 最后上线: {str(info.get('last_seen','-'))[:16]}")
            
            new_limit = st.slider("每日任务上限", 0, 100, int(info.get('daily_limit') or 25))
            if st.button("更新上限"): update_user_limit(u, new_limit); st.toast("已更新"); time.sleep(0.5); st.rerun()
            
            st.bar_chart(perf.head(14))

elif selected_nav == "Import":
    pool = get_public_pool_count()
    st.metric("公海池库存", pool)
    if st.button("回收过期任务"): 
        n = recycle_expired_tasks()
        st.success(f"已回收 {n} 个任务")
            
    st.markdown("#### 批量导入")
    force = st.checkbox("跳过验证（强行入库）")
    f = st.file_uploader("上传 Excel/CSV", type=['csv', 'xlsx'])
    if f and st.button("开始清洗入库"):
        try:
            df = pd.read_csv(f) if f.name.endswith('.csv') else pd.read_excel(f)
            st.info(f"解析到 {len(df)} 行数据")
            with st.status("正在处理...", expanded=True) as s:
                rows = []
                for _, r in df.iterrows():
                    row_str = " ".join([str(x) for x in r.values])
                    emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', row_str)
                    phones = extract_all_numbers(r)
                    
                    if emails or phones:
                        email = emails[0] if emails else None
                        phone = phones[0] if phones else None 
                        
                        if phone and not force:
                            res, _, _ = process_checknumber_task([phone], CN_KEY, CN_USER)
                            if res.get(phone) != 'valid': phone = None
                        
                        if not email and not phone: continue

                        # 智能提取店铺名 (Col 1)
                        shop_name = str(r.iloc[1]) if len(r) > 1 else 'Shop'
                        
                        rows.append({
                            "email": email,
                            "phone": phone,
                            "shop_name": shop_name,
                            "shop_link": str(r.iloc[0]) if len(r) > 0 else '',
                            "ai_message": "",
                            "retry_count": 0, 
                            "is_frozen": False
                        })
                        
                        if len(rows) >= 100:
                            count, msg = admin_bulk_upload_to_pool(rows)
                            s.write(f"批次入库: {count}")
                            rows = []
                
                if rows:
                    count, msg = admin_bulk_upload_to_pool(rows)
                    s.write(f"最终批次入库: {count}")
                
                s.update(label="处理完成", state="complete")
        except Exception as e: st.error(str(e))
