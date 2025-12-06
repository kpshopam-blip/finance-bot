import os
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- ส่วนตั้งค่า (แก้ไขตรงนี้เหมือนเดิม) ---
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
        return None  # ส่งคืน None ถ้าหาไม่เจอ

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

# ==========================================
# ส่วนที่เพิ่มมาใหม่: ทำงานเมื่อบอทถูกดึงเข้ากลุ่ม
# ==========================================
@handler.add(JoinEvent)
def handle_join(event):
    group_id = event.source.group_id
    
    # พยายามดึงชื่อกลุ่มจาก LINE
    try:
        summary = line_bot_api.get_group_summary(group_id)
        group_name = summary.group_name
    except LineBotApiError:
        # กรณีดึงชื่อไม่ได้ (อาจเกิดจากสิทธิ์หรือเน็ตหลุด) ให้ตั้งชื่อสำรอง
        group_name = f"NewGroup_{group_id[-4:]}"

    try:
        sh = get_worksheet('Shops')
        
        # เช็คว่ามี Group ID นี้หรือยัง
        existing_cell = None
        try:
            existing_cell = sh.find(group_id)
        except:
            pass

        if existing_cell:
            # ถ้ามีแล้ว ให้อัปเดตชื่อกลุ่มใหม่ (เผื่อเขาเปลี่ยนชื่อกลุ่ม)
            sh.update_cell(existing_cell.row, 2, group_name)
            reply_msg = f"✅ อัปเดตข้อมูลร้านค้าเรียบร้อย:\n{group_name}"
        else:
            # ถ้ายังไม่มี ให้บันทึกใหม่
            sh.append_row([group_id, group_name])
            reply_msg = f"🎉 ลงทะเบียนร้านค้าใหม่เรียบร้อย:\n{group_name}\n\nพร้อมเริ่มนับยอดได้เลยครับ!"

        # ส่งข้อความทักทาย
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_msg)
        )
        print(f"Auto-registered: {group_name} ({group_id})")

    except Exception as e:
        print(f"Error registering group: {e}")

# ==========================================
# ส่วนเดิม: รับข้อความ (Text)
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    
    if event.source.type != 'group':
        return

    group_id = event.source.group_id
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # 1. เงื่อนไข: นับยอด (Silent Tracking)
    if text == "ปล่อยเครื่องได้เลยค่ะ":
        try:
            sh = get_worksheet('Log')
            all_records = sh.get_all_records()
            
            found_row_index = None
            current_count = 0
            
            for i, record in enumerate(all_records):
                if str(record['Date']) == today_str and str(record['GroupID']) == group_id:
                    found_row_index = i + 2
                    current_count = record['Count']
                    break
            
            if found_row_index:
                sh.update_cell(found_row_index, 4, int(current_count) + 1)
            else:
                # ดึงชื่อร้านจาก Sheet Shops (ซึ่งตอนนี้เรา Auto Save แล้ว)
                shop_name = get_shop_name(group_id)
                if not shop_name:
                    # ถ้าหาไม่เจอจริงๆ (เช่น บอท error ตอนเข้ากลุ่ม) ให้ดึงชื่อสดๆ อีกรอบ
                    try:
                        summary = line_bot_api.get_group_summary(group_id)
                        shop_name = summary.group_name
                    except:
                        shop_name = f"Group_{group_id[-4:]}"
                
                sh.append_row([today_str, group_id, shop_name, 1])

        except Exception as e:
            print(f"Error writing to sheet: {e}")

    # 2. เงื่อนไข: ดูรายงาน
    elif text == "สรุปยอด" or text == "เช็คยอด":
        try:
            sh = get_worksheet('Log')
            all_records = sh.get_all_records()
            
            count = 0
            shop_name_display = "ร้านนี้"
            
            # พยายามดึงชื่อร้านมาโชว์
            stored_name = get_shop_name(group_id)
            if stored_name:
                shop_name_display = stored_name

            for record in all_records:
                if str(record['Date']) == today_str and str(record['GroupID']) == group_id:
                    count = record['Count']
                    break
            
            msg = f"📊 สรุปยอดวันนี้ ({today_str})\n"
            msg += f"🏠 {shop_name_display}\n"
            msg += f"✅ อนุมัติแล้ว: {count} เคส"
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=msg)
            )
        except Exception as e:
             line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="เกิดข้อผิดพลาดในการดึงข้อมูลครับ")
            )
            @app.route("/")
            def home():
                return "Hello, Boss! I am awake and working."

            if __name__ == "__main__":
                app.run()

