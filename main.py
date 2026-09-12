import os
import time
import threading
from flask import Flask
import requests
import telebot

# --- إعدادات البوت وتيليجرام ---
TELEGRAM_BOT_TOKEN = "8558672736:AAEU9XkSGL1WDbRlkKcca124"
CHAT_ID = "7562398807"
status_message_id = None

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# --- سيرفر ويب لإبقاء الاستضافة محلياً (Web Service) ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# --- إعدادات لعبة Nutsca ---
TOKEN_FILE = "token.txt"

tick_url = "https://base.nutsca.com/api/active/tick"
status_url = "https://base.nutsca.com/api/game/status"
state_url = "https://base.nutsca.com/api/game/state"
apiary_url = "https://base.nutsca.com/api/apiary/state"
action_url = "https://base.nutsca.com/api/game/action"
sell_url = "https://base.nutsca.com/api/apiary/sell"

headers = {
    "host": "base.nutsca.com",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36",
    "x-telegram-init-data": "",
    "accept": "*/*",
    "origin": "https://game.nutsca.com",
    "referer": "https://game.nutsca.com/",
    "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8"
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

def update_or_send_msg(text):
    global status_message_id
    if status_message_id is not None:
        try:
            bot.edit_message_text(chat_id=CHAT_ID, message_id=status_message_id, text=text)
            return
        except Exception:
            pass
    try:
        sent = bot.send_message(CHAT_ID, text)
        status_message_id = sent.message_id
    except Exception:
        pass

def send_alert_msg(text):
    try:
        bot.send_message(CHAT_ID, text)
    except Exception:
        pass

def load_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            t = f.read().strip()
            if t:
                headers["x-telegram-init-data"] = t
                return True
    return False

def reset_and_reenter():
    new_session = requests.Session()
    try:
        new_session.get(status_url, headers=headers, timeout=10)
        time.sleep(1)
        new_session.get(state_url, headers=headers, timeout=10)
    except Exception:
        pass
    return new_session

def check_and_sell_basket(session):
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

            if nuts_amount == 0 and "data" in apiary_data and isinstance(apiary_data["data"], dict):
                sub = apiary_data["data"]
                for key in ["fullness", "amount", "current", "nuts"]:
                    val = sub.get(key)
                    if val is not None:
                        try:
                            nuts_amount = float(val)
                            if nuts_amount > 0:
                                break
                        except (ValueError, TypeError):
                            pass

            is_full = apiary_data.get("isFull", False)

            if nuts_amount >= 5000 or is_full:
                sell_resp = session.post(sell_url, headers=headers, json={}, timeout=10)
                if sell_resp.status_code == 200:
                    sell_data = sell_resp.json()
                    current_b = sell_data.get("balanceB", "غير معروف")
                    update_or_send_msg(f"🧺 تم بيع السلة بنجاح!\nالرصيد الحالي: {current_b}")
                    return current_b
    except Exception:
        pass
    return None

def auto_merge_all(session):
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
                        level_positions[lvl].append({"x": y, "y": x})

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
            merge_resp = session.post(action_url, headers=headers, json=payload, timeout=10)
            if merge_resp.status_code == 200:
                time.sleep(0.5)
            else:
                break
        except Exception:
            break

def buy_squirrel(session, level):
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
                    empty_slot = {"x": y, "y": x}
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
        buy_resp = session.post(action_url, headers=headers, json=payload, timeout=10)
        if buy_resp.status_code == 200:
            buy_data = buy_resp.json()
            new_balance = buy_data.get("balanceB")
            update_or_send_msg(f"🐿️ تم شراء سنجاب لفل {level}!\nالرصيد المتبقي: {new_balance}")
            auto_merge_all(session)
            return new_balance
    except Exception:
        pass
    return None

def try_buy_best_squirrel(session, balance):
    for level, price in LEVEL_PRICES:
        if balance >= price:
            new_bal = buy_squirrel(session, level)
            if new_bal is not None:
                return new_bal
            break
    return balance

# --- دورة العمل الرئيسية ---
def bot_worker():
    if not load_token():
        send_alert_msg("⚠️ السكربت بانتظار إرسال التوكن x-telegram-init-data للبدء.")
        while not load_token():
            time.sleep(20)

    session = reset_and_reenter()
    auto_merge_all(session)
    update_or_send_msg("✅ تم تشغيل السكربت بنجاح والاتصال باللعبة!")

    while True:
        try:
            response = session.post(tick_url, headers=headers, json={}, timeout=15)
            if response.status_code == 200:
                data = response.json()
                seconds = data.get("sessionSeconds", 0)
                balance = data.get("balanceB", 0)
                interval = data.get("tickIntervalSeconds", 10)

                sold_balance = check_and_sell_basket(session)
                if sold_balance is not None:
                    balance = sold_balance

                auto_merge_all(session)
                balance = try_buy_best_squirrel(session, balance)

                if seconds >= 268:
                    session.close()
                    time.sleep(60)
                    session = reset_and_reenter()
                    auto_merge_all(session)
                    check_and_sell_basket(session)
                    continue

                time.sleep(interval)

            elif response.status_code in [400, 401]:
                session.close()
                send_alert_msg("🚨 انتهت صلاحية التوكن! أرسل التوكن الجديد هنا مباشرة في الشات لتحديثه.")
                while not load_token():
                    time.sleep(10)
                session = reset_and_reenter()
            else:
                time.sleep(10)

        except Exception:
            time.sleep(5)

# --- استقبال الأوامر والتوكن من تيليجرام ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    bot.reply_to(message, "أهلاً بك! أرسل كود x-telegram-init-data مباشرة هنا ليتم حفظه وتشغيل اللعبة فوراً.")

@bot.message_handler(func=lambda msg: True)
def handle_incoming_token(message):
    text = message.text.strip()
    if "user=" in text or "hash=" in text:
        if "&tgWebApp" in text:
            text = text.split("&tgWebApp")[0]
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(text)
        headers["x-telegram-init-data"] = text
        bot.reply_to(message, "✅ تم استلام التوكن وتحديثه بنجاح! جاري استئناف العمل...")
    else:
        bot.reply_to(message, "❌ النص المرسل لا يبدو كـ init-data صالح.")

if __name__ == "__main__":
    t_web = threading.Thread(target=run_web_server, daemon=True)
    t_web.start()
    t_worker = threading.Thread(target=bot_worker, daemon=True)
    t_worker.start()
    bot.infinity_polling()
