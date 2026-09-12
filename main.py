import os
import time
import threading
from flask import Flask
import requests
import telebot

# --- إعدادات البوت وتيليجرام ---
TELEGRAM_BOT_TOKEN = "8558672736:AAEU9XK5GL1WDBr1FzEgV5y_Kj0QeNznbd8"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# قواميس لحفظ الرسائل والمسارات النشطة لكل مستخدم
user_status_messages = {}
active_threads = {}

# --- سيرفر ويب مصغر لإبقاء الاستضافة المجانية نشطة ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running 24/7 for multi-users!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# --- إعدادات لعبة Nutsca ---
tick_url = "https://base.nutsca.com/api/active-earn/tick"
status_url = "https://base.nutsca.com/api/active-earn/status"
state_url = "https://base.nutsca.com/api/game/state"
apiary_url = "https://base.nutsca.com/api/apiary/state"
action_url = "https://base.nutsca.com/api/game/actions"
sell_url = "https://base.nutsca.com/api/apiary/sell"

DEFAULT_HEADERS = {
    "Host": "base.nutsca.com",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
    "accept": "*/*",
    "origin": "https://game.nutsca.com",
    "referer": "https://game.nutsca.com/",
    "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7"
}

LEVEL_PRICES = [
    (7, 6400),
    (6, 3200),
    (5, 1600),
    (4, 800),
    (3, 400),
    (2, 200),
    (1, 100),
]

def get_token_filename(chat_id):
    return f"token_{chat_id}.txt"

def update_or_send_msg(chat_id, text):
    msg_id = user_status_messages.get(chat_id)
    if msg_id is not None:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text)
            return
        except Exception:
            pass

    try:
        sent = bot.send_message(chat_id, text)
        user_status_messages[chat_id] = sent.message_id
    except Exception:
        pass

def send_alert_msg(chat_id, text):
    try:
        bot.send_message(chat_id, text)
    except Exception:
        pass

def load_user_token(chat_id):
    filename = get_token_filename(chat_id)
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                return t
    return None

def reset_and_reenter(headers):
    new_session = requests.Session()
    try:
        new_session.get(status_url, headers=headers, timeout=10)
        new_session.get(state_url, headers=headers, timeout=10)
    except Exception:
        pass
    return new_session

def check_and_sell_basket(session, headers, chat_id):
    try:
        apiary_resp = session.get(apiary_url, headers=headers, timeout=10)
        if apiary_resp.status_code == 200:
            apiary_data = apiary_resp.json()
            
            nuts_amount = 0.0
            for key in ["fullness", "amount", "current", "nuts"]:
                val = apiary_data.get(key)
                if val is not None:
                    try:
                        nuts_amount = float(val)
                        if nuts_amount > 0:
                            break
                    except (ValueError, TypeError):
                        pass

            if nuts_amount == 0 and isinstance(apiary_data.get("sellPreview"), dict):
                try:
                    nuts_amount = float(apiary_data["sellPreview"].get("amount", 0))
                except (ValueError, TypeError):
                    nuts_amount = 0.0

            is_full = apiary_data.get("isFull", False)
            if nuts_amount >= 5000 or is_full:
                sell_resp = session.post(sell_url, headers=headers, json={}, timeout=15)
                if sell_resp.status_code == 200:
                    sell_data = sell_resp.json()
                    sold = sell_data.get("amount", nuts_amount)
                    gained_b = sell_data.get("receiveBalanceB", 0)
                    current_b = sell_data.get("balanceB", 0)
                    update_or_send_msg(chat_id, f"🧺 تم بيع السلة بنجاح!\nالمحصول: {sold:.1f} جوز\nالربح: +{gained_b:.2f}\nالرصيد: {current_b:.2f}")
                    return current_b
    except Exception:
        pass
    return None

def auto_merge_all(session, headers):
    while True:
        try:
            state_resp = session.get(state_url, headers=headers, timeout=10)
            if state_resp.status_code != 200:
                break
                
            state_data = state_resp.json()
            grid = state_data.get("grid", [])
            version = state_data.get("version", 0)
            
            level_positions = {}
            for y, row in enumerate(grid):
                for x, lvl in enumerate(row):
                    if lvl > 0:
                        if lvl not in level_positions:
                            level_positions[lvl] = []
                        level_positions[lvl].append({"x": x, "y": y})
            
            pair_found = None
            for lvl, positions in sorted(level_positions.items()):
                if len(positions) >= 2:
                    pair_found = (positions[0], positions[1])
                    break
                    
            if not pair_found:
                break
                
            pos_from, pos_to = pair_found
            payload = {
                "action": "MOVE",
                "version": version,
                "from": pos_from,
                "to": pos_to
            }
            
            merge_resp = session.post(action_url, headers=headers, json=payload, timeout=15)
            if merge_resp.status_code == 200:
                time.sleep(0.5)
            else:
                break
        except Exception:
            break

def buy_squirrel(session, headers, level, chat_id):
    try:
        state_resp = session.get(state_url, headers=headers, timeout=10)
        if state_resp.status_code != 200:
            return None
        
        state_data = state_resp.json()
        grid = state_data.get("grid", [])
        version = state_data.get("version", 0)
        
        empty_slot = None
        for y, row in enumerate(grid):
            for x, val in enumerate(row):
                if val == 0:
                    empty_slot = {"x": x, "y": y}
                    break
            if empty_slot:
                break
                
        if not empty_slot:
            return None
            
        payload = {
            "action": "PLACE",
            "version": version,
            "slotMode": "BUY",
            "slotLevel": level,
            "to": empty_slot
        }
        
        buy_resp = session.post(action_url, headers=headers, json=payload, timeout=15)
        if buy_resp.status_code == 200:
            buy_data = buy_resp.json()
            new_balance = buy_data.get("balanceB", 0)
            update_or_send_msg(chat_id, f"🛒 تم شراء سنجاب لفل {level}!\nالرصيد المتبقي: {new_balance:.2f}")
            auto_merge_all(session, headers)
            return new_balance
    except Exception:
        pass
    return None

def try_buy_best_squirrel(session, headers, balance, chat_id):
    for level, price in LEVEL_PRICES:
        if balance >= price:
            new_bal = buy_squirrel(session, headers, level=level, chat_id=chat_id)
            if new_bal is not None:
                return new_bal
            break
    return balance

# --- مسار عمل مخصص لكل مستخدم ---
def bot_worker_for_user(chat_id):
    headers = DEFAULT_HEADERS.copy()
    token = load_user_token(chat_id)
    
    if not token:
        send_alert_msg(chat_id, "⚠️ السكربت بانتظار إرسال التوكن  للبدء.")
        while not token:
            time.sleep(5)
            token = load_user_token(chat_id)

    headers["x-telegram-init-data"] = token
    session = reset_and_reenter(headers)
    auto_merge_all(session, headers)
    update_or_send_msg(chat_id, "✅ تم تشغيل السكربت بنجاح والاتصال باللعبة!")

    while True:
        # فحص إذا تم إرسال توكن جديد لتحديثه مباشرة
        fresh_token = load_user_token(chat_id)
        if fresh_token and fresh_token != token:
            token = fresh_token
            headers["x-telegram-init-data"] = token
            session = reset_and_reenter(headers)

        try:
            response = session.post(tick_url, headers=headers, json={}, timeout=15)
            if response.status_code == 200:
                data = response.json()
                seconds = data.get("sessionSeconds", 0)
                balance = data.get("balanceB", 0)
                interval = data.get("tickIntervalSeconds", 10)

                sold_balance = check_and_sell_basket(session, headers, chat_id)
                if sold_balance is not None:
                    balance = sold_balance

                auto_merge_all(session, headers)
                balance = try_buy_best_squirrel(session, headers, balance, chat_id)

                if seconds >= 268:
                    session.close()
                    time.sleep(60)
                    session = reset_and_reenter(headers)
                    auto_merge_all(session, headers)
                    check_and_sell_basket(session, headers, chat_id)
                    continue

                time.sleep(interval)

            elif response.status_code in [400, 401]:
                session.close()
                send_alert_msg(chat_id, "🚨 انتهت صلاحية التوكن! أرسل التوكن الجديد هنا مباشرة في الشات لتحديثه.")
                old_token = token
                while True:
                    time.sleep(5)
                    new_token = load_user_token(chat_id)
                    if new_token and new_token != old_token:
                        token = new_token
                        headers["x-telegram-init-data"] = token
                        session = reset_and_reenter(headers)
                        break
            else:
                time.sleep(10)

        except Exception:
            time.sleep(5)

def start_user_thread(chat_id):
    if chat_id not in active_threads or not active_threads[chat_id].is_alive():
        t = threading.Thread(target=bot_worker_for_user, args=(chat_id,), daemon=True)
        active_threads[chat_id] = t
        t.start()

# --- استقبال التوكن والأوامر من تيليجرام ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    bot.reply_to(message, "أهلاً بك! أرسل كود مباشرة هنا ليتم حفظه وتشغيل اللعبة فوراً.")
    start_user_thread(chat_id)

@bot.message_handler(func=lambda msg: True)
def handle_incoming_token(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if "user=" in text or "hash=" in text:
        if "&tgWebApp" in text:
            text = text.split("&tgWebApp")[0]
        
        # حفظ توكن المستخدم في ملف خاص بآيديه
        with open(get_token_filename(chat_id), "w", encoding="utf-8") as f:
            f.write(text)
            
        bot.reply_to(message, "✅ تم استلام التوكن وتحديثه بنجاح! جاري تشغيل السكربت لحسابك...")
        start_user_thread(chat_id)
    else:
        bot.reply_to(message, "❌ النص المرسل لا يبدو كـ  صالح.")

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # فحص أي ملفات توكن قديمة وتشغيلها تلقائياً عند بدء السيرفر
    for fname in os.listdir("."):
        if fname.startswith("token_") and fname.endswith(".txt"):
            try:
                saved_id = int(fname.replace("token_", "").replace(".txt", ""))
                start_user_thread(saved_id)
            except Exception:
                pass

    bot.infinity_polling()
