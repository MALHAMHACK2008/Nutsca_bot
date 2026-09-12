import os
import time
import threading
from flask import Flask
import requests
import telebot

# --- إعدادات البوت وتيليجرام ---
# ضع التوكن الخاص ببوتك من BotFather والـ Chat ID الخاص بحسابك
TELEGRAM_BOT_TOKEN = "ضع_توكن_بوت_تيليجرام_هنا"
CHAT_ID = "ضع_معرف_الشات_تبعك_هنا"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

# --- سيرفر ويب مصغر لإبقاء الاستضافة المجانية نشطة ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Bot is running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# --- إعدادات لعبة Nutsca ---
TOKEN_FILE = "token.txt"

tick_url = "https://base.nutsca.com/api/active-earn/tick"
status_url = "https://base.nutsca.com/api/active-earn/status"
state_url = "https://base.nutsca.com/api/game/state"
apiary_url = "https://base.nutsca.com/api/apiary/state"
action_url = "https://base.nutsca.com/api/game/actions"
sell_url = "https://base.nutsca.com/api/apiary/sell"

headers = {
    "Host": "base.nutsca.com",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
    "x-telegram-init-data": "",
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

def send_tg_msg(text):
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
        new_session.get(state_url, headers=headers, timeout=10)
    except Exception:
        pass
    return new_session

def check_and_sell_basket(session):
    try:
        apiary_resp = session.get(apiary_url, headers=headers, timeout=10)
        if apiary_resp.status_code == 200:
            apiary_data = apiary_resp.json()
            nuts_amount = apiary_data.get("fullness", 0)
            if nuts_amount == 0 and isinstance(apiary_data.get("sellPreview"), dict):
                nuts_amount = apiary_data["sellPreview"].get("amount", 0)

            if nuts_amount >= 5000:
                sell_resp = session.post(sell_url, headers=headers, json={}, timeout=15)
                if sell_resp.status_code == 200:
                    sell_data = sell_resp.json()
                    sold = sell_data.get("amount", 0)
                    gained_b = sell_data.get("receiveBalanceB", 0)
                    current_b = sell_data.get("balanceB", 0)
                    send_tg_msg(f"🧺 تم بيع السلة!\nالمحصول: {sold:.1f} جوز\nالربح: +{gained_b:.2f}\nالرصيد: {current_b:.2f}")
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
                        level_positions[lvl].append({"x": x, "y": y})
            
            pair_found = None
            merge_level = None
            for lvl, positions in sorted(level_positions.items()):
                if len(positions) >= 2:
                    pair_found = (positions[0], positions[1])
                    merge_level = lvl
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
            send_tg_msg(f"🛒 تم شراء سنجاب لفل {level}!\nالرصيد المتبقي: {new_balance:.2f}")
            auto_merge_all(session)
            return new_balance
    except Exception:
        pass
    return None

def try_buy_best_squirrel(session, balance):
    for level, price in LEVEL_PRICES:
        if balance >= price:
            new_bal = buy_squirrel(session, level=level)
            if new_bal is not None:
                return new_bal
            break
    return balance

# --- دورة التشغيل الخلفية ---
def bot_worker():
    while not load_token():
        send_tg_msg("⚠️ السكربت بانتظار إرسال التوكن x-telegram-init-data للبدء.")
        time.sleep(20)

    session = reset_and_reenter()
    auto_merge_all(session)
    send_tg_msg("✅ تم تشغيل السكربت بنجاح والاتصال باللعبة!")

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
                try_buy_best_squirrel(session, balance)

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
                send_tg_msg("🚨 انتهت صلاحية التوكن! أرسل التوكن الجديد هنا مباشرة في الشات لتحديثه.")
                while not load_token():
                    time.sleep(10)
                session = reset_and_reenter()
            else:
                time.sleep(10)

        except Exception:
            time.sleep(5)

# --- استقبال التوكن والأوامر من تيليجرام مباشرة ---
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
    # 1. تشغيل سيرفر الويب في خلفية منفصلة
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # 2. تشغيل عامل اللعبة في خلفية منفصلة
    threading.Thread(target=bot_worker, daemon=True).start()
    
    # 3. تشغيل استماع رسائل بوت التيليجرام
    bot.infinity_polling()
