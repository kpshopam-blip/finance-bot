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

# --- ฟังก์ชันค้นหาชื่อร้านจาก Group ID ---
def get_shop_name(group_id):
    try:
        sh = get_worksheet('Shops')
        cell = sh.find(group_id)
        return sh.cell(cell.row, 2).value
    except:
        return None

# ==========================================
# 🔧 ฟังก์ชันตรวจสอบและแยกประเภทข้อความ (Smart Filter)
# ==========================================
def classify_message(text):
    # ทำให้เป็นตัวเล็กทั้งหมด และตัดช่องว่าง
    text = text.lower().strip()

    # 1. เช็คคำถาม (Negative Check) -> ถ้าเจอคำพวกนี้ ให้หยุดทันที
    question_words = [
        "ไหม", "มั้ย", "มั๊ย", "ยัง", "หรอ", "รึเปล่า", "หรือเปล่า",
        "ได้ปะ", "ได้ป่ะ", "รึยัง", "หรือยัง", "?", "สอบถาม"
    ]
    for word in question_words:
        if word in text:
            return None # เป็นคำถาม ไม่นับ

    # 2. เช็คคำอนุมัติ (Approval) -> คอลัมน์ D
    approve_keywords = [
        "อนุมัติ", "อนุมัติครับ", "อนุมัติค่ะ"
    ]
    for word in approve_keywords:
        if word in text:
            return 'approve' # ประเภทอนุมัติ

    # 3. เช็คคำปล่อยเครื่อง (Release) -> คอลัมน์ E (ของเดิม)
    release_keywords = [
        "ปล่อยเครื่อง", "ปล่อยได้", "ปล่อยเลย", "ปล่อยเคส", "ปล่อย", "ปล่่อย"
    ]
    for word in release_keywords:
        if word in text:
            return 'release' # ประเภทปล่อยเครื่อง

    return None # ไม่เข้าเงื่อนไข

# ==========================================
# Route หน้าแรก (สำหรับ UptimeRobot)
# ==========================================
@app.route("/")
def home():
    return "Hello, Boss! I am awake and working."

# ==========================================
# Webhook Callback
# ==========================================
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ==========================================
# Handle Join Event
# ==========================================
@handler.add(JoinEvent)
def handle_join(event):
    group_id = event.source.group_id
    try:
        summary = line_bot_api.get_group_summary(group_id)
        group_name = summary.group_name
    except:
        group_name = f"NewGroup_{group_id[-4:]}"

    try:
        sh = get_worksheet('Shops')
        try:
            existing_cell = sh.find(group_id)
        except:
            existing_cell = None

        if existing_cell:
            sh.update_cell(existing_cell.row, 2, group_name)
            reply_msg = f"✅ อัปเดตข้อมูลร้านค้าเรียบร้อย:\n{group_name}"
        else:
            sh.append_row([group_id, group_name])
            reply_msg = f"🎉 ขออนุญาตเชิญ Bot_IT4 เข้ากลุ่ม:\n{group_name}\n\nครับ!"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))
    except Exception as e:
        print(f"Error registering: {e}")

# ==========================================
# Handle Text Message
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    
    if event.source.type != 'group':
        return

    group_id = event.source.group_id
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # แยกประเภทข้อความ: 'approve', 'release', หรือ None
    msg_type = classify_message(text)

    # -----------------------------------------------------
    # 1. ถ้าเป็นข้อความนับยอด (Approve หรือ Release)
    # -----------------------------------------------------
    if msg_type:
        try:
            sh = get_worksheet('Log')
            # ใช้ get_all_values เพื่อระบุตำแหน่งคอลัมน์ได้แม่นยำกว่า (ไม่สนชื่อ Header)
            all_rows = sh.get_all_values()
            
            found_row_index = None
            current_approve = 0
            current_release = 0
            
            # วนลูปหาแถวที่ตรงกับ วันนี้ และ ร้านนี้ (ข้าม Header แถวที่ 0)
            for i, row in enumerate(all_rows[1:]): 
                # row[0] = Date, row[1] = GroupID
                if str(row[0]) == today_str and str(row[1]) == group_id:
                    found_row_index = i + 2 # +2 เพราะข้าม header และ index เริ่ม 0
                    
                    # ป้องกันกรณีข้อมูลว่าง ให้ถือเป็น 0
                    try: current_approve = int(row[3]) if row[3] else 0 # Column D (Index 3)
                    except: current_approve = 0
                    
                    try: current_release = int(row[4]) if row[4] else 0 # Column E (Index 4)
                    except: current_release = 0
                    break
            
            if found_row_index:
                # เจอแถวเดิม -> อัปเดตยอด
                if msg_type == 'approve':
                    sh.update_cell(found_row_index, 4, current_approve + 1) # Col D
                    print(f"Approve updated for {group_id}")
                elif msg_type == 'release':
                    sh.update_cell(found_row_index, 5, current_release + 1) # Col E
                    print(f"Release updated for {group_id}")
            else:
                # ไม่เจอ -> สร้างแถวใหม่
                shop_name = get_shop_name(group_id)
                if not shop_name:
                    try:
                        summary = line_bot_api.get_group_summary(group_id)
                        shop_name = summary.group_name
                    except:
                        shop_name = f"Group_{group_id[-4:]}"
                
                # สร้างแถวใหม่: [Date, GroupID, ShopName, Approve, Release]
                if msg_type == 'approve':
                    sh.append_row([today_str, group_id, shop_name, 1, 0])
                elif msg_type == 'release':
                    sh.append_row([today_str, group_id, shop_name, 0, 1])
                
                print(f"New record created for {group_id}")

        except Exception as e:
            print(f"Error writing to sheet: {e}")

    # -----------------------------------------------------
    # 2. เงื่อนไข: ดูรายงาน
    # -----------------------------------------------------
    elif text in ["สรุปยอด", "เช็คยอด", "ยอดวันนี้"]:
        try:
            sh = get_worksheet('Log')
            all_rows = sh.get_all_values()
            
            approve_count = 0
            release_count = 0
            shop_name_display = "ร้านนี้"
            
            # ดึงชื่อร้านที่บันทึกไว้
            stored_name = get_shop_name(group_id)
            if stored_name:
                shop_name_display = stored_name

            for row in all_rows[1:]:
                if str(row[0]) == today_str and str(row[1]) == group_id:
                    # แปลงค่าเป็น int เพื่อความชัวร์
                    try: approve_count = int(row[3]) if row[3] else 0
                    except: approve_count = 0
                    try: release_count = int(row[4]) if row[4] else 0
                    except: release_count = 0
                    break
            
            msg = f"📊 สรุปยอดวันนี้ ({today_str})\n"
            msg += f"🏠 {shop_name_display}\n"
            msg += f"------------------\n"
            msg += f"✅ อนุมัติ: {approve_count} เคส\n"
            msg += f"📦 ปล่อยเครื่อง: {release_count} เครื่อง"
            
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
        except Exception as e:
             print(e)
             line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดในการดึงข้อมูลครับ"))

if __name__ == "__main__":
    app.run()
