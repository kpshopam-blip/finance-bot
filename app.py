import os
import datetime
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import MessageEvent, TextMessage, TextSendMessage, JoinEvent, FileMessage
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
    try:
        summary = line_bot_api.get_group_summary(group_id)
        current_line_name = summary.group_name
    except:
        current_line_name = f"Group_{group_id[-4:]}"

    try:
        sh = get_worksheet('Shops')
        try:
            cell = sh.find(group_id)
            stored_name = sh.cell(cell.row, 2).value
            
            if stored_name != current_line_name:
                sh.update_cell(cell.row, 2, current_line_name)
            
            return current_line_name

        except:
            sh.append_row([group_id, current_line_name])
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
        "ด้วย","หน่อย","ป่ะ","ปะ","หรือไม่","ใช่ไหม","แจ้ง","ขอบคุณ",
        "รอผล","รอ","การ","ไม่","ก่อน","เช็ค","จาก","หลัง","ไม่อนุมัติ"
        ,"นะคะ","นะค่ะ","แล้ว"
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
    group_name = sync_group_name(group_id)
    reply_msg = f"✅ บันทึกชื่อร้านเรียบร้อย:\n{group_name}\n\nเริ่มงานได้เลยครับ!"
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply_msg))

# ==========================================
# 🔥 ส่วนใหม่: จัดการไฟล์ (FileMessage) สำหรับนับสัญญา PDF
# ==========================================
@handler.add(MessageEvent, message=FileMessage)
def handle_file(event):
    if event.source.type != 'group':
        return

    file_name = event.message.file_name
    
    # 1. เช็คว่าเป็นไฟล์ PDF หรือไม่
    if not file_name.lower().endswith('.pdf'):
        return

    # 2. 🔥 เพิ่มการกรอง: ถ้าชื่อไฟล์มีคำเหล่านี้ ให้ข้ามทันที (ไม่นับ)
    ignore_keywords = ["IT4", "หนังสือให้ความยินยอม", "ขั้นตอนการส่งเคสของพาร์ทเนอร์", "โปรแกรมใหม่และรายละเอียดการสมัครDL+", "ร้านค้า"]
    for keyword in ignore_keywords:
        if keyword in file_name:
            print(f"Ignored file (Blacklist): {file_name}")
            return # จบการทำงาน ไม่ทำต่อ

    # ตัดชื่อไฟล์เอาเฉพาะชื่อคนทำสัญญา (แยกด้วย _ )
    if '_' in file_name:
        contract_name = file_name.split('_')[0].strip()
    else:
        # กรณีไม่มี _ ให้เอาชื่อไฟล์ทั้งหมดตัด .pdf ออก
        contract_name = os.path.splitext(file_name)[0].strip()

    group_id = event.source.group_id
    record_contract(group_id, contract_name)
    
# ==========================================
# ฟังก์ชันบันทึกยอดสัญญาและชื่อลูกค้า
# ==========================================
def record_contract(group_id, contract_name):
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    current_shop_name = sync_group_name(group_id)

    try:
        sh = get_worksheet('Log')
        all_rows = sh.get_all_values()
        
        found_row_index = None
        current_contract_count = 0
        existing_names = []
        
        for i, row in enumerate(all_rows[1:]): 
            if str(row[0]) == today_str and str(row[1]) == group_id:
                found_row_index = i + 2
                
                # อ่านยอดสัญญาปัจจุบัน (Column F -> index 5)
                try: current_contract_count = int(row[5]) if len(row) > 5 and row[5] else 0
                except: current_contract_count = 0
                
                # อ่านรายชื่อคนที่เคยส่งแล้ว (Column G -> index 6)
                try: 
                    raw_names = str(row[6]) if len(row) > 6 else ""
                    existing_names = [n.strip() for n in raw_names.split(',') if n.strip()]
                except: existing_names = []
                
                break
        
        # --- ตรวจสอบว่าชื่อนี้เคยนับไปหรือยัง (De-duplicate) ---
        if contract_name in existing_names:
            print(f"Duplicate contract ignored: {contract_name}")
            return # จบการทำงานทันที ถ้านับไปแล้ว

        # ถ้ายอมให้ผ่าน (ชื่อใหม่) -> เพิ่มชื่อลง list และ +1
        existing_names.append(contract_name)
        new_names_str = ",".join(existing_names)
        
        if found_row_index:
            # อัปเดตแถวเดิม: Col F (Count) และ Col G (NameList)
            sh.update_cell(found_row_index, 6, current_contract_count + 1)
            sh.update_cell(found_row_index, 7, new_names_str)
            print(f"Contract updated: {contract_name}")
        else:
            # สร้างแถวใหม่ (เรียง: Date, ID, Shop, Approve(0), Release(0), Contract(1), NameList)
            sh.append_row([today_str, group_id, current_shop_name, 0, 0, 1, new_names_str])
            print(f"New contract record: {contract_name}")

    except Exception as e:
        print(f"Error handling contract: {e}")


# ==========================================
# ส่วนจัดการข้อความ Text (นับอนุมัติ/ปล่อย)
# ==========================================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()
    
    if event.source.type != 'group':
        return

    group_id = event.source.group_id
    
    # 🔥 จัดการเคส: "ปิดเคส"
    if text.startswith("ปิดเคส"):
        lines = text.split('\n')
        # ฟอร์แมตคือ
        # 1. ปิดเคส
        # 2. ชื่อสาขา
        # 3. ชื่อลูกค้า
        if len(lines) >= 3:
            contract_name = lines[2].strip()
            if contract_name:
                record_contract(group_id, contract_name)
        return # ให้จบการทำงานตรงนี้เลย ไม่ต้องเช็คคำอื่นต่อ

    today_str = datetime.date.today().strftime("%Y-%m-%d")

    msg_type = classify_message(text)

    if msg_type or text in ["สรุปยอด", "เช็คยอด", "ยอดวันนี้"]:
        current_shop_name = sync_group_name(group_id)

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
                    # สร้างแถวใหม่ (ระวังเรื่องจำนวนคอลัมน์ให้ครบ)
                    if msg_type == 'approve':
                        sh.append_row([today_str, group_id, current_shop_name, 1, 0, 0, ""])
                    elif msg_type == 'release':
                        sh.append_row([today_str, group_id, current_shop_name, 0, 1, 0, ""])

            except Exception as e:
                print(f"Error writing to sheet: {e}")

        elif text in ["สรุปยอด", "เช็คยอด", "ยอดวันนี้"]:
            try:
                sh = get_worksheet('Log')
                all_rows = sh.get_all_values()
                
                approve_count = 0
                release_count = 0
                contract_count = 0
                
                for row in all_rows[1:]:
                    if str(row[0]) == today_str and str(row[1]) == group_id:
                        try: approve_count = int(row[3]) if row[3] else 0
                        except: approve_count = 0
                        try: release_count = int(row[4]) if row[4] else 0
                        except: release_count = 0
                        # อ่านยอดสัญญาเพิ่ม
                        try: contract_count = int(row[5]) if len(row) > 5 and row[5] else 0
                        except: contract_count = 0
                        break
                
                msg = f"📊 สรุปยอดวันนี้ ({today_str})\n"
                msg += f"🏠 {current_shop_name}\n"
                msg += f"------------------\n"
                msg += f"✅ อนุมัติ: {approve_count} เคส\n"
                msg += f"📦 ปล่อยเครื่อง: {release_count} เครื่อง\n"
                msg += f"📝 สัญญา: {contract_count} ฉบับ"
                
                line_bot_api.reply_message(event.reply_token, TextSendMessage(text=msg))
            except:
                 line_bot_api.reply_message(event.reply_token, TextSendMessage(text="เกิดข้อผิดพลาดในการดึงข้อมูลครับ"))

if __name__ == "__main__":
    app.run()
