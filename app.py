import os
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- ส่วนตั้งค่า (แก้ไขตรงนี้) ---
# ใส่ Token จาก LINE Developers
LINE_CHANNEL_ACCESS_TOKEN = 'lVhohtPhKOMihlJw2qAqDhV7J+lNdDoeGbR9mpW0+lwx2cYnmV+qsKlnlOVXDa+Qo8JeSN8BuCBwg26S2n8VsC0lGd+1sWfO0yh8gkG2IIQGu8uSwDykY7FhYPTP6xcP/q7vcB8iEVdhuKN+UATwoAdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '1e233aeba9151417a68ce59b5e0423e4'

# ชื่อไฟล์ Google Sheet ที่คุณตั้งไว้
GOOGLE_SHEET_NAME = 'ระบบนับจำนวนเคส'

# ชื่อไฟล์กุญแจที่โหลดมาจาก Google (ต้องวางไฟล์นี้ไว้ที่เดียวกับ code)
CREDENTIALS_FILE = 'credentials.json' 

app = Flask(__name__)

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# --- ฟังก์ชันเชื่อมต่อ Google Sheets ---
def get_worksheet(sheet_name):
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(CREDENTIALS_FILE, scope)
    client = gspread.authorize(creds)
    # เปิด Google Sheet ตามชื่อไฟล์
    sheet = client.open(GOOGLE_SHEET_NAME)
    # เลือก Tab ตามชื่อ (Log หรือ Shops)
    return sheet.worksheet(sheet_name)

# --- ฟังก์ชันค้นหาชื่อร้านจาก Group ID ---
def get_shop_name(group_id):
    try:
        sh = get_worksheet('Shops')
        # ค้นหา Group ID ในคอลัมน์แรก (A)
        cell = sh.find(group_id)
        # ถ้าเจอ ให้เอาค่าในคอลัมน์ถัดไป (B - ชื่อร้าน)
        return sh.cell(cell.row, 2).value
    except:
        return "ร้านที่ไม่รู้จัก"

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

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    
    # ทำงานเฉพาะในกลุ่มเท่านั้น
    if event.source.type != 'group':
        return

    group_id = event.source.group_id
    today_str = datetime.date.today().strftime("%Y-%m-%d")

    # -----------------------------------------------------
    # 1. เงื่อนไข: นับยอด (Silent Tracking)
    # -----------------------------------------------------
    if text == "ปล่อยเครื่องได้เลยค่ะ":
        try:
            sh = get_worksheet('Log')
            all_records = sh.get_all_records()
            
            # ค้นหาว่าวันนี้ ร้านนี้ มีข้อมูลหรือยัง
            found_row_index = None
            current_count = 0
            
            # วนลูปเช็คข้อมูล (ถ้าข้อมูลเยอะมากอาจช้า แต่วันละ 100-200 แถวสบายมาก)
            for i, record in enumerate(all_records):
                # ตรวจสอบว่า วันที่ตรงกัน AND GroupID ตรงกัน
                if str(record['Date']) == today_str and str(record['GroupID']) == group_id:
                    found_row_index = i + 2 # +2 เพราะ row ใน list เริ่ม 0 แต่ sheet เริ่ม 1 และมี header 1
                    current_count = record['Count']
                    break
            
            if found_row_index:
                # ถ้ามีแล้ว ให้อัปเดตช่อง Count เพิ่มทีละ 1
                sh.update_cell(found_row_index, 4, int(current_count) + 1)
                print(f"Updated count for {group_id}")
            else:
                # ถ้ายังไม่มี ให้เพิ่มแถวใหม่
                # ไปดึงชื่อร้านมา (ถ้ามีใน Tab Shops)
                shop_name = get_shop_name(group_id)
                if shop_name == "ร้านที่ไม่รู้จัก":
                    shop_name = f"Group_{group_id[-4:]}" # ตั้งชื่อชั่วคราว
                
                # เพิ่มแถวใหม่: [Date, GroupID, ShopName, Count=1]
                sh.append_row([today_str, group_id, shop_name, 1])
                print(f"Created new record for {group_id}")

            # จบการทำงาน (ไม่ Reply กลับ = ประหยัด Token)
            
        except Exception as e:
            print(f"Error writing to sheet: {e}")

    # -----------------------------------------------------
    # 2. เงื่อนไข: ดูรายงาน (Reply Message - ฟรี)
    # -----------------------------------------------------
    elif text == "สรุปยอด" or text == "เช็คยอด":
        try:
            sh = get_worksheet('Log')
            all_records = sh.get_all_records()
            
            count = 0
            shop_name_display = "ร้านนี้"
            
            for record in all_records:
                if str(record['Date']) == today_str and str(record['GroupID']) == group_id:
                    count = record['Count']
                    shop_name_display = record['ShopName']
                    break
            
            msg = f"📊 สรุปยอดวันนี้ ({today_str})\n"
            msg += f"ร้าน: {shop_name_display}\n"
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

    # -----------------------------------------------------
    # 3. เงื่อนไข: ลงทะเบียนร้านค้า (Admin Only)
    # -----------------------------------------------------
    elif text == "ลงทะเบียนร้าน":
        # Bot จะบอก ID ของกลุ่ม เพื่อให้เราเอาไปใส่ใน Sheet 'Shops'
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=f"Group ID ของห้องนี้คือ:\n{group_id}\n\n(ให้ Admin นำ ID นี้ไปใส่ใน Sheet 'Shops' ช่อง A และใส่ชื่อร้านช่อง B)")
        )

if __name__ == "__main__":

    app.run()

