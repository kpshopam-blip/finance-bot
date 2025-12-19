import os
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- ส่วนตั้งค่า (แก้ไขตรงนี้) ---
LINE_CHANNEL_ACCESS_TOKEN = 'lVhohtPhKOMihlJw2qAqDhV7J+lNdDoeGbR9mpW0+lwx2cYnmV+qsKlnlOVXDa+Qo8JeSN8BuCBwg26S2n8VsC0lGd+1sWfO0yh8gkG2IIQGu8uSwDykY7FhYPTP6xcP/q7vcB8iEVdhuKN+UATwoAdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '1e233aeba9151417a68ce59b5e0423e4'
GOOGLE_SHEET_NAME = 'ระบบนับจำนวนเคส'
CREDENTIALS_FILE = 'credentials.json'

app = Flask(__name__)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- ฟังก์ชันเชื่อมต่อ Google Sheets ---
def get_worksheet(sheet_name):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    sheet = client.open(GOOGLE_SHEET_NAME)
    return sheet.worksheet(sheet_name)

# ==========================================
# 🔧 ฟังก์ชันใหม่: ดึงชื่อกลุ่มจาก LINE และอัปเดตลง Sheet อัตโนมัติ
# ==========================================
def sync_group_name(group_id):
    # 1. ดึงชื่อปัจจุบันจริงๆ จาก LINE API
    try:
        summary = line_bot_api.get_group_summary(group_id)
        current_line_name = summary.group_name
    except:
        # ถ้าดึงไม่ได้ (เช่น เน็ตหลุด) ให้ใช้ชื่อสำรอง
        current_line_name = f"Group_{group_id[-4:]}"

    # 2. เช็คใน Google Sheet (Shops) ว่าชื่อตรงกันไหม
    try:
        sh = get_worksheet('Shops')
        try:
            cell = sh.find(group_id)
            # เจอ ID เดิม -> เช็คชื่อซิว่าเปลี่ยนไหม?
            stored_name = sh.cell(cell.row, 2).value
            
            if stored_name != current_line_name:
                # ถ้าชื่อไม่ตรง (เปลี่ยนชื่อกลุ่มมา) -> อัปเดตเลย!
                sh.update_cell(cell.row, 2, current_line_name)
                print(f"Updated name change: {stored_name} -> {current_line_name}")
            
            return current_line_name

        except:
            # ไม่เจอ ID นี้ (ร้านใหม่) -> เพิ่มลงไปใหม่
            sh.append_row([group_id, current_line_name])
            print(f"Registered new shop: {current_line_name}")
            return current_line_name

    except Exception as e:
        print(f"Error syncing group name: {e}")
        return current_line_name

# ==========================================
# ฟังก์ชันแยกประเภทข้อความ (เหมือนเดิม)
# ==========================================
def classify_message(text):
    text = text.lower().strip()

    # 1. เช็คคำถาม (ไม่นับ)
    question_words = [
        "ไหม", "มั้ย", "มั๊ย", "ยัง", "หรอ", "รึเปล่า", "หรือเปล่า",
        "ได้ปะ", "ได้ป่ะ", "รึยัง", "หรือยัง", "?", "สอบถาม","ขอ",
        "ด้วย","หน่อย","ป่ะ","ปะ","หรือไม่","ใช่ไหม","แจ้ง","ขอบคุณ","รอผล"
    ]
    for word in question_words:
        if word in text:
            return None 

    # 2. เช็คคำอนุมัติ -> คอลัมน์ D
    approve_keywords = [
        "อนุมัติ", "อนุมัติครับ", "อนุมัติค่ะ","อนุมัต","อนมัติ"
    ]
    for word in approve_keywords:
        if word in text:
            return 'approve' 

    # 3. เช็คคำปล่อยเครื่อง -> คอลัมน์ E
    release_keywords = [
        "ปล่อยเครื่อง", "ปล่อยได้", "ปล่อยเลย", "ปล่อยเคส", "ปล่อย", "ปล่่อย","ปลอย"
    ]
    for word in release_keywords:
        if word in text:
            return 'release' 

    return None

# ==========================================
# Route
# ==========================================
@app.route("/")
def home():
    return "Hello, Boss! I am awake and working."

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(JoinEvent)
def handle_join(event):
    group_id = event.source.group_id
    # ใช้ฟังก์ชันใหม่ sync_group_name ทีเดียวจบ (มันจะ save ลง sheet ให้เอง)
    group_name = sync_group_name(group_id)
    
    reply_msg = f"✅ บันทึกชื่อร้านเรียบร้อย:\n{group_name}\n\nเริ่มงานได้เลยครับ!"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    
    if event.source.type != 'group':
        return

    group_id = event.source.group_id
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    msg_type = classify_message(text)

    # -----------------------------------------------------
    # ถ้าเป็นคำสั่งนับยอด หรือ สรุปยอด -> ให้ Sync ชื่อร้านก่อนเสมอ
    # -----------------------------------------------------
    if msg_type or text in ["สรุปยอด", "เช็คยอด", "ยอดวันนี้"]:
        # 🔥 นี่คือจุดสำคัญ: บอทจะเช็คชื่อกลุ่มล่าสุดทุกครั้งที่ทำงาน
        current_shop_name = sync_group_name(group_id)

        # 1. ถ้าเป็นข้อความนับยอด
        if msg_type:
            try:
                sh = get_worksheet('Log')
                all_rows = sh.get_all_values()
                
                found_row_index = None
                current_approve = 0
                current_release = 0
                
                for i, row in enumerate(all_rows[1:]): 
                    if str(row[0]) == today_str and str(row[1]) == group_id:
                        found_row_index = i + 2
                        
                        # อัปเดตชื่อร้านใน Log ให้ตรงกับปัจจุบันด้วย (เผื่อเปลี่ยนชื่อวันนี้)
                        if row[2] != current_shop_name:
                             sh.update_cell(found_row_index, 3, current_shop_name)

                        try: current_approve = int(row[3]) if row[3] else 0
                        except: current_approve = 0
                        try: current_release = int(row[4]) if row[4] else 0
                        except: current_release = 0
                        break
                
                if found_row_index:
                    if msg_type == 'approve':
                        sh.update_cell(found_row_index, 4, current_approve + 1)
                    elif msg_type == 'release':
                        sh.update_cell(found_row_index, 5, current_release + 1)
                else:
                    # สร้างแถวใหม่
                    if msg_type == 'approve':
                        sh.append_row([today_str, group_id, current_shop_name, 1, 0])
                    elif msg_type == 'release':
                        sh.append_row([today_str, group_id, current_shop_name, 0, 1])

            except Exception as e:
                print(f"Error writing to sheet: {e}")

        # 2. ถ้าขอดูรายงาน
        elif text in ["สรุปยอด", "เช็คยอด", "ยอดวันนี้"]:
            try:
                sh = get_worksheet('Log')
                all_rows = sh.get_all_values()
                
                approve_count = 0
                release_count = 0
                
                for row in all_rows[1:]:
                    if str(row[0]) == today_str and str(row[1]) == group_id:
                        try: approve_count = int(row[3]) if row[3] else 0
                        except: approve_count = 0
                        try: release_count = int(row[4]) if row[4] else 0
                        except: release_count = 0
                        break
                
                msg = f"📊 สรุปยอดวันนี้ ({today_str})\n"
                msg += f"🏠 {current_shop_name}\n" # ใช้ชื่อล่าสุดที่ดึงมาโชว์
                msg += f"------------------\n"
                msg += f"✅ อนุมัติ: {approve_count} เคส\n"
                msg += f"📦 ปล่อยเครื่อง: {release_count} เครื่อง"
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            except:
                 line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดในการดึงข้อมูลครับ"))

if __name__ == "__main__":
    app.run()

