import os
import time
import threading
import urllib.parse
from flask import Flask
import requests
import telebot

# --- إعدادات البوت وتيليجرام ---
TELEGRAM_BOT_TOKEN = "8681823633:AAHTWPwD-kado7dG265IO7s7sN54WhWXSv0"
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

user_status_messages = {}
active_threads = {}
user_withdraw_stats = {}  # لتخزين إجمالي المسحوبات وعدد العمليات لكل مستخدم

# --- سيرفر ويب مصغر لإبقاء الاستضافة نشطة 24/7 ---
server = Flask(__name__)

@server.route('/')
def home():
    return "Nutsca Pro Multi-User Bot is Running 24/7!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server.run(host="0.0.0.0", port=port)

# --- روابط واجهات برمجة اللعبة ---
tick_url = "https://base.nutsca.com/api/active-earn/tick"
status_url = "https://base.nutsca.com/api/active-earn/status"
state_url = "https://base.nutsca.com/api/game/state"
apiary_url = "https://base.nutsca.com/api/apiary/state"
action_url = "https://base.nutsca.com/api/game/actions"
sell_url = "https://base.nutsca.com/api/apiary/sell"
withdraw_url = "https://base.nutsca.com/api/payments/crypto-withdrawal"

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
    (20, 52428800), (19, 26214400), (18, 13107200), (17, 6553600),
    (16, 3276800), (15, 1638400), (14, 819200), (13, 409600),
    (12, 204800), (11, 102400), (10, 51200),
]

DEFAULT_WALLET = "UQC0JgWF8Z5U5BKhZyB1TshqDVC3NreiEo23bWyQWBP_4fJ1"

def get_token_filename(chat_id): return f"token_{chat_id}.txt"
def get_wallet_filename(chat_id): return f"wallet_{chat_id}.txt"

def load_user_token(chat_id):
    if os.path.exists(get_token_filename(chat_id)):
        try:
            with open(get_token_filename(chat_id), "r", encoding="utf-8") as f: return f.read().strip() or None
        except Exception: pass
    return None

def load_user_wallet(chat_id):
    if os.path.exists(get_wallet_filename(chat_id)):
        try:
            with open(get_wallet_filename(chat_id), "r", encoding="utf-8") as f: return f.read().strip() or DEFAULT_WALLET
        except Exception: pass
    return DEFAULT_WALLET

def make_progress_bar(percent, total_blocks=10):
    filled = int(round(total_blocks * (percent / 100.0)))
    filled = max(0, min(total_blocks, filled))
    return "▰" * filled + "▱" * (total_blocks - filled)

def format_uptime(seconds):
    mins, sec = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours} س و {mins} د" if hours > 0 else f"{mins} د و {sec} ث"

# --- دالة استخراج الأرصدة الصحيحة ---
def extract_balances(data):
    b_balance = float(data.get("balanceB", 0))
    n_balance = 0.0
    for key in ["nuts", "totalNuts", "balanceNuts", "userNuts"]:
        if key in data and data[key] is not None:
            try: n_balance = float(data[key]); break
            except Exception: pass
    if n_balance == 0.0 and isinstance(data.get("user"), dict):
        for key in ["nuts", "totalNuts", "balanceNuts"]:
            if key in data["user"] and data["user"][key] is not None:
                try: n_balance = float(data["user"][key]); break
                except Exception: pass
    return b_balance, n_balance

def build_dashboard_text(balance, total_nuts, total_profit, highest_level, basket_nuts, basket_percent, uptime_sec, total_withdrawn, withdraw_count, status_text):
    hours_run = max(uptime_sec / 3600.0, 0.001)
    rate_per_hour = total_profit / hours_run
    basket_bar = make_progress_bar(basket_percent)
    
    # نسبة التقدم نحو السحب التالي (50 بندق) بناءً على رصيد الجوز الفعلي
    next_withdraw_percent = min(100.0, (total_nuts / 50.0) * 100.0)
    withdraw_bar = make_progress_bar(next_withdraw_percent)

    withdraw_str = f"+{total_withdrawn} بندق ({withdraw_count} سحب)" if withdraw_count > 0 else "0 بندق"

    return (
        "╔══════════════════════╗\n"
        "       🐿️ لوحة تحكم NUTSCA PRO 🐿️       \n"
        "╚══════════════════════╝\n\n"
        f"🥜 رصيد الجوز (Nuts): {total_nuts:.1f}\n"
        f"💰 رصيد العملات (B): {balance:.2f} B\n"
        f"💎 إجمالي المسحوب: {withdraw_str}\n"
        f"🎯 نحو السحب القادم: [{withdraw_bar}] {next_withdraw_percent:.0f}%\n"
        f"📈 إجمالي الأرباح: +{total_profit:.2f} B\n"
        f"⚡ السرعة التقديرية: ~{rate_per_hour:.2f} B / س\n"
        f"👑 أعلى سنجاب: لفل {highest_level}\n\n"
        f"🧺 حمولة السلة: {basket_nuts:.1f} / 5000\n"
        f"[{basket_bar}] {basket_percent:.1f}%\n\n"
        f"⏱️ مدة التشغيل: {format_uptime(uptime_sec)}\n"
        f"📊 الحالة: {status_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 التحديث: يتم تعديل هذه اللوحة تلقائياً"
    )

def update_or_send_msg(chat_id, text):
    msg_id = user_status_messages.get(chat_id)
    if msg_id:
        try: bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text); return
        except Exception: pass
    try:
        sent = bot.send_message(chat_id, text)
        user_status_messages[chat_id] = sent.message_id
    except Exception: pass

def send_alert_msg(chat_id, text):
    try: bot.send_message(chat_id, text)
    except Exception: pass

def reset_and_reenter(headers):
    new_session = requests.Session()
    try:
        new_session.get(status_url, headers=headers, timeout=8)
        new_session.get(state_url, headers=headers, timeout=8)
    except Exception: pass
    return new_session

def execute_crypto_withdrawal(session, headers, wallet_address, amount=50):
    try:
        ts_now = int(time.time() * 1000)
        req_key = f"TON_CONNECT:{amount}:{ts_now}"
        payload = {"pid": "TON_CONNECT", "amount": amount, "wallet": wallet_address, "requestKey": req_key}
        res = session.post(withdraw_url, headers=headers, json=payload, timeout=12)
        if res.status_code == 200: return True, res.json()
        return False, res.text
    except Exception as e: return False, str(e)

def get_highest_squirrel_level(grid):
    max_lvl = 0
    if not isinstance(grid, list): return 0
    for row in grid:
        if isinstance(row, list):
            for val in row:
                if isinstance(val, int) and val > max_lvl: max_lvl = val
    return max_lvl

def get_basket_info(session, headers):
    try:
        resp = session.get(apiary_url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            nuts = 0.0
            for key in ["fullness", "amount", "current", "nuts"]:
                if data.get(key) is not None:
                    try: 
                        nuts = float(data[key])
                        if nuts > 0: break
                    except Exception: pass
            if nuts == 0 and isinstance(data.get("sellPreview"), dict):
                nuts = float(data["sellPreview"].get("amount", 0))
            return nuts, min(100.0, (nuts / 5000.0) * 100.0), data.get("isFull", False)
    except Exception: pass
    return 0.0, 0.0, False

def execute_sell(session, headers):
    try:
        resp = session.post(sell_url, headers=headers, json={}, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            return float(data.get("balanceB", 0)), float(data.get("receiveBalanceB", 0)), True
    except Exception: pass
    return None, 0.0, False

def auto_merge_all(session, headers):
    grid_out = []
    for _ in range(25):
        try:
            resp = session.get(state_url, headers=headers, timeout=8)
            if resp.status_code != 200: break
            data = resp.json()
            grid_out, version = data.get("grid", []), data.get("version", 0)
            positions = {}
            for y, row in enumerate(grid_out):
                for x, lvl in enumerate(row):
                    if isinstance(lvl, int) and lvl > 0:
                        positions.setdefault(lvl, []).append({"x": x, "y": y})
            
            pair = next(((pos[0], pos[1]) for lvl, pos in sorted(positions.items()) if len(pos) >= 2), None)
            if not pair: break
            
            p_from, p_to = pair
            m_resp = session.post(action_url, headers=headers, json={"action": "MOVE", "version": version, "from": p_from, "to": p_to}, timeout=8)
            if m_resp.status_code == 200 and "grid" in m_resp.json():
                grid_out = m_resp.json()["grid"]
            time.sleep(0.35)
        except Exception: break
    return grid_out

def buy_squirrel(session, headers, level):
    try:
        resp = session.get(state_url, headers=headers, timeout=8)
        if resp.status_code != 200: return None, None
        data = resp.json()
        grid, version = data.get("grid", []), data.get("version", 0)
        
        empty_slot = next(({"x": x, "y": y} for y, row in enumerate(grid) for x, val in enumerate(row) if val == 0), None)
        if not empty_slot: return None, grid

        b_resp = session.post(action_url, headers=headers, json={"action": "PLACE", "version": version, "slotMode": "BUY", "slotLevel": level, "to": empty_slot}, timeout=10)
        if b_resp.status_code == 200:
            return float(b_resp.json().get("balanceB", 0)), auto_merge_all(session, headers)
    except Exception: pass
    return None, None

def try_buy_best_squirrel(session, headers, balance):
    for level, price in LEVEL_PRICES:
        if balance >= price:
            new_bal, grid = buy_squirrel(session, headers, level=level)
            if new_bal is not None: return new_bal, grid, level
            break
    return balance, None, None

# --- مسار عمل البوت لكل مستخدم ---
def bot_worker_for_user(chat_id):
    headers = DEFAULT_HEADERS.copy()
    current_token = load_user_token(chat_id)

    while not current_token:
        time.sleep(3)
        current_token = load_user_token(chat_id)

    headers["x-telegram-init-data"] = current_token
    session = requests.Session()

    try:
        if session.post(tick_url, headers=headers, json={}, timeout=8).status_code in [400, 401]:
            send_alert_msg(chat_id, "❌ التوكن منتهي الصلاحية أو غير صالح!\nيرجى فتح اللعبة ونسخ init-data جديد وإرساله هنا.")
            return
    except Exception: pass

    session = reset_and_reenter(headers)
    grid = auto_merge_all(session, headers)
    highest_lvl = get_highest_squirrel_level(grid)
    basket_nuts, percent, _ = get_basket_info(session, headers)

    total_profit = 0.0
    last_balance = None
    global_total_nuts = 0.0
    start_time = time.time()
    
    if chat_id not in user_withdraw_stats: user_withdraw_stats[chat_id] = {"total": 0, "count": 0}

    update_or_send_msg(chat_id, build_dashboard_text(0.0, global_total_nuts, total_profit, highest_lvl, basket_nuts, percent, 0, user_withdraw_stats[chat_id]["total"], user_withdraw_stats[chat_id]["count"], "تم بدء التجميع ودمج السناجب! 🚀"))

    while True:
        fresh_token = load_user_token(chat_id)
        if fresh_token and fresh_token != current_token:
            current_token = fresh_token
            headers["x-telegram-init-data"] = current_token
            session.close()
            session = reset_and_reenter(headers)

        try:
            uptime_sec = time.time() - start_time
            response = session.post(tick_url, headers=headers, json={}, timeout=12)

            if response.status_code == 200:
                data = response.json()
                seconds = data.get("sessionSeconds", 0)
                current_balance, extracted_nuts = extract_balances(data)
                
                if extracted_nuts > 0: global_total_nuts = extracted_nuts
                interval = data.get("tickIntervalSeconds", 10)

                if last_balance is not None and current_balance > last_balance:
                    total_profit += (current_balance - last_balance)
                last_balance = current_balance

                basket_nuts, percent, is_full = get_basket_info(session, headers)
                status_text = "تجميع النقاط جاري... ⚡"

                if basket_nuts >= 5000 or is_full:
                    sold_bal, earned_from_b, was_sold = execute_sell(session, headers)
                    if was_sold and sold_bal is not None:
                        total_profit += earned_from_b
                        current_balance = sold_bal
                        last_balance = current_balance
                        basket_nuts, percent = 0.0, 0.0
                        status_text = f"تم تفريغ وبيع السلة (+{earned_from_b:.2f} B)! 🧺✨"

                # تم التصحيح: السحب يعتمد على رصيد الجوز الفعلي وبكمية 50
                if global_total_nuts >= 50:
                    wallet = load_user_wallet(chat_id)
                    success, res_data = execute_crypto_withdrawal(session, headers, wallet_address=wallet, amount=50)
                    if success:
                        global_total_nuts -= 50
                        user_withdraw_stats[chat_id]["total"] += 50
                        user_withdraw_stats[chat_id]["count"] += 1
                        tot = user_withdraw_stats[chat_id]["total"]
                        status_text = f"💎 تم سحب 50 بندق بنجاح (المجموع: {tot})!"

                merged_grid = auto_merge_all(session, headers)
                if merged_grid: grid = merged_grid

                new_balance, buy_grid, bought_lvl = try_buy_best_squirrel(session, headers, current_balance)
                if buy_grid: grid = buy_grid
                if bought_lvl:
                    status_text = f"تم شراء سنجاب لفل {bought_lvl} ودمجه! 🐿️"
                    current_balance = new_balance
                    last_balance = current_balance

                highest_lvl = get_highest_squirrel_level(grid)
                update_or_send_msg(chat_id, build_dashboard_text(current_balance, global_total_nuts, total_profit, highest_lvl, basket_nuts, percent, uptime_sec, user_withdraw_stats[chat_id]["total"], user_withdraw_stats[chat_id]["count"], status_text))

                if seconds >= 268:
                    session.close()
                    time.sleep(60)
                    session = reset_and_reenter(headers)
                    continue
                time.sleep(interval)

            elif response.status_code in [400, 401]:
                session.close()
                send_alert_msg(chat_id, "🚨 انتهت صلاحية التوكن! يرجى إرسال الرابط الجديد هنا لاستئناف التجميع.")
                old_token = current_token
                while True:
                    time.sleep(4)
                    new_token = load_user_token(chat_id)
                    if new_token and new_token != old_token:
                        current_token = new_token
                        headers["x-telegram-init-data"] = current_token
                        session = reset_and_reenter(headers)
                        break
            else: time.sleep(8)
        except Exception: time.sleep(4)

def start_user_thread(chat_id):
    if chat_id not in active_threads or not active_threads[chat_id].is_alive():
        t = threading.Thread(target=bot_worker_for_user, args=(chat_id,), daemon=True)
        active_threads[chat_id] = t
        t.start()

# --- استقبال رسائل تيليجرام ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    user_status_messages[chat_id] = None
    bot.reply_to(message, "🐿️ مرحباً بك!\n🔑 أرسل رابط اللعبة كاملاً أو التوكن للبدء.\n💡 لتغيير محفظة السحب، أرسل: `wallet:عنوان_محفظتك`", parse_mode="Markdown")
    if load_user_token(chat_id): start_user_thread(chat_id)

@bot.message_handler(func=lambda msg: True)
def handle_incoming_messages(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if text.startswith("wallet:"):
        new_wallet = text.replace("wallet:", "").strip()
        with open(get_wallet_filename(chat_id), "w", encoding="utf-8") as f: f.write(new_wallet)
        bot.reply_to(message, f"✅ تم حفظ محفظة السحب الخاصة بك بنجاح:\n`{new_wallet}`", parse_mode="Markdown")
        return

    # تم إضافة فك التشفير التلقائي للتوكن (URL Decoding)
    if "user=" in text or "hash=" in text:
        raw_text = text
        if "#tgWebAppData=" in raw_text: raw_text = raw_text.split("#tgWebAppData=")[1]
        if "&tgWebAppVersion=" in raw_text: raw_text = raw_text.split("&tgWebAppVersion=")[0]
        
        clean_token = urllib.parse.unquote(raw_text)

        with open(get_token_filename(chat_id), "w", encoding="utf-8") as f:
            f.write(clean_token)
        
        bot.reply_to(message, "✅ تم التحقق واستلام التوكن بنجاح!\n🚀 جاري الاتصال بخوادم اللعبة وتشغيل نظام التجميع...")
        user_status_messages[chat_id] = None
        start_user_thread(chat_id)
    else:
        bot.reply_to(message, "❌ النص المرسل غير صالح. تأكد من إرسال رابط اللعبة كاملاً.")

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    for fname in os.listdir("."):
        if fname.startswith("token_") and fname.endswith(".txt"):
            try: start_user_thread(int(fname.replace("token_", "").replace(".txt", "")))
            except Exception: pass

    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception: time.sleep(3)
