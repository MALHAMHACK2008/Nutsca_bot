import os
import time
import threading
from flask import Flask
import requests
import telebot

# --- إعدادات البوت وتيليجرام ---
TELEGRAM_BOT_TOKEN = "8558672736:AAEU9XK5GL1WDBr1FzEgV5y_Kj0QeNznbd8"
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

user_status_messages = {}
active_threads = {}

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

def load_user_token(chat_id):
    filename = get_token_filename(chat_id)
    if os.path.exists(filename):
        try:
            with open(filename, "r", encoding="utf-8") as f:
                t = f.read().strip()
                if t:
                    return t
        except Exception:
            pass
    return None

def make_progress_bar(percent, total_blocks=10):
    filled = int(round(total_blocks * (percent / 100.0)))
    filled = max(0, min(total_blocks, filled))
    return "▰" * filled + "▱" * (total_blocks - filled)

def format_uptime(seconds):
    mins, sec = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    if hours > 0:
        return f"{hours} س و {mins} د"
    return f"{mins} د و {sec} ث"

def build_dashboard_text(balance, total_profit, highest_level, basket_nuts, basket_percent, uptime_sec, status_text="تجميع النقاط جاري... ⚡"):
    hours_run = max(uptime_sec / 3600.0, 0.001)
    rate_per_hour = total_profit / hours_run
    bar = make_progress_bar(basket_percent)

    return (
        "╔══════════════════════╗\n"
        "       🐿️ لوحة تحكم NUTSCA PRO 🐿️       \n"
        "╚══════════════════════╝\n\n"
        f"💰 الرصيد الحالي: {balance:.2f} B\n"
        f"📈 إجمالي الأرباح: +{total_profit:.2f} B\n"
        f"⚡ السرعة التقديرية: ~{rate_per_hour:.2f} B / ساعة\n"
        f"👑 أعلى سنجاب: لفل {highest_level}\n\n"
        f"🧺 حمولة السلة: {basket_nuts:.1f} / 5000\n"
        f"[{bar}] {basket_percent:.1f}%\n\n"
        f"⏱️ مدة التشغيل: {format_uptime(uptime_sec)}\n"
        f"📊 الحالة: {status_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 التحديث: يتم تعديل هذه اللوحة تلقائياً"
    )

def update_or_send_msg(chat_id, text):
    msg_id = user_status_messages.get(chat_id)
    if msg_id:
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

def reset_and_reenter(headers):
    new_session = requests.Session()
    try:
        new_session.get(status_url, headers=headers, timeout=8)
        new_session.get(state_url, headers=headers, timeout=8)
    except Exception:
        pass
    return new_session

def get_highest_squirrel_level(grid):
    max_lvl = 0
    if not isinstance(grid, list):
        return 0
    for row in grid:
        if isinstance(row, list):
            for val in row:
                if isinstance(val, int) and val > max_lvl:
                    max_lvl = val
    return max_lvl

def get_basket_info(session, headers):
    try:
        apiary_resp = session.get(apiary_url, headers=headers, timeout=8)
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
            percent = min(100.0, (nuts_amount / 5000.0) * 100.0)
            return nuts_amount, percent, is_full
    except Exception:
        pass
    return 0.0, 0.0, False

def execute_sell(session, headers):
    try:
        sell_resp = session.post(sell_url, headers=headers, json={}, timeout=10)
        if sell_resp.status_code == 200:
            sell_data = sell_resp.json()
            current_b = sell_data.get("balanceB", 0)
            earned = sell_data.get("receiveBalanceB", 0)
            return float(current_b), float(earned), True
    except Exception:
        pass
    return None, 0.0, False

def auto_merge_all(session, headers):
    grid_out = []
    max_cycles = 25
    cycle = 0

    while cycle < max_cycles:
        cycle += 1
        try:
            state_resp = session.get(state_url, headers=headers, timeout=8)
            if state_resp.status_code != 200:
                break

            state_data = state_resp.json()
            grid = state_data.get("grid", [])
            grid_out = grid
            version = state_data.get("version", 0)

            # تجميع مواقع السناجب المتشابهة في المستوى
            level_positions = {}
            for y_idx, row in enumerate(grid):
                for x_idx, lvl in enumerate(row):
                    if isinstance(lvl, int) and lvl > 0:
                        if lvl not in level_positions:
                            level_positions[lvl] = []
                        level_positions[lvl].append({"x": x_idx, "y": y_idx})

            # البحث عن زوج متطابق للدمج
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

            merge_resp = session.post(action_url, headers=headers, json=payload, timeout=8)
            if merge_resp.status_code == 200:
                resp_json = merge_resp.json()
                if "grid" in resp_json:
                    grid_out = resp_json["grid"]
                time.sleep(0.35)
            else:
                # محاولة عكس الإحداثيات إذا كان ترتيب السيرفر معكوساً
                payload_alt = {
                    "action": "MOVE",
                    "version": version,
                    "from": {"x": pos_from["y"], "y": pos_from["x"]},
                    "to": {"x": pos_to["y"], "y": pos_to["x"]}
                }
                session.post(action_url, headers=headers, json=payload_alt, timeout=8)
                time.sleep(0.35)
                break

        except Exception:
            break

    return grid_out

def buy_squirrel(session, headers, level):
    try:
        state_resp = session.get(state_url, headers=headers, timeout=8)
        if state_resp.status_code != 200:
            return None, None

        state_data = state_resp.json()
        grid = state_data.get("grid", [])
        version = state_data.get("version", 0)

        empty_slot = None
        for y_idx, row in enumerate(grid):
            for x_idx, val in enumerate(row):
                if val == 0:
                    empty_slot = {"x": x_idx, "y": y_idx}
                    break
            if empty_slot:
                break

        if not empty_slot:
            return None, grid

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
            new_balance = buy_data.get("balanceB", 0)
            latest_grid = auto_merge_all(session, headers)
            return float(new_balance), latest_grid
    except Exception:
        pass
    return None, None

def try_buy_best_squirrel(session, headers, balance):
    latest_grid = None
    bought_level = None
    for level, price in LEVEL_PRICES:
        if balance >= price:
            new_bal, grid = buy_squirrel(session, headers, level=level)
            if new_bal is not None:
                return new_bal, grid, level
            break
    return balance, latest_grid, bought_level

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
        check_resp = session.post(tick_url, headers=headers, json={}, timeout=8)
        if check_resp.status_code in [400, 401]:
            send_alert_msg(chat_id, "❌ التوكن منتهي الصلاحية أو غير صالح!\nيرجى فتح اللعبة ونسخ init-data جديد وإرساله هنا.")
            return
    except Exception:
        pass

    session = reset_and_reenter(headers)
    grid = auto_merge_all(session, headers)

    highest_lvl = get_highest_squirrel_level(grid)
    nuts, percent, _ = get_basket_info(session, headers)

    total_profit = 0.0
    last_balance = None
    start_time = time.time()

    update_or_send_msg(chat_id, build_dashboard_text(0.0, total_profit, highest_lvl, nuts, percent, 0, "تم بدء التجميع ودمج السناجب! 🚀"))

    while True:
        fresh_token = load_user_token(chat_id)
        if fresh_token and fresh_token != current_token:
            current_token = fresh_token
            headers["x-telegram-init-data"] = current_token
            session.close()
            session = reset_and_reenter(headers)
            grid = auto_merge_all(session, headers)

        try:
            uptime_sec = time.time() - start_time
            response = session.post(tick_url, headers=headers, json={}, timeout=12)

            if response.status_code == 200:
                data = response.json()
                seconds = data.get("sessionSeconds", 0)
                current_balance = float(data.get("balanceB", 0))
                interval = data.get("tickIntervalSeconds", 10)

                if last_balance is not None and current_balance > last_balance:
                    total_profit += (current_balance - last_balance)
                last_balance = current_balance

                nuts, percent, is_full = get_basket_info(session, headers)
                status_text = "تجميع النقاط جاري... ⚡"

                if nuts >= 5000 or is_full:
                    sold_bal, earned_from_b, was_sold = execute_sell(session, headers)
                    if was_sold and sold_bal is not None:
                        total_profit += earned_from_b
                        current_balance = sold_bal
                        last_balance = current_balance
                        nuts, percent = 0.0, 0.0
                        status_text = f"تم تفريغ وبيع السلة (+{earned_from_b:.2f} B)! 🧺✨"

                merged_grid = auto_merge_all(session, headers)
                if merged_grid:
                    grid = merged_grid

                new_balance, buy_grid, bought_lvl = try_buy_best_squirrel(session, headers, current_balance)
                if buy_grid:
                    grid = buy_grid
                if bought_lvl:
                    status_text = f"تم شراء سنجاب لفل {bought_lvl} ودمجه! 🐿️"
                    current_balance = new_balance
                    last_balance = current_balance

                highest_lvl = get_highest_squirrel_level(grid)
                update_or_send_msg(chat_id, build_dashboard_text(current_balance, total_profit, highest_lvl, nuts, percent, uptime_sec, status_text))

                if seconds >= 268:
                    session.close()
                    time.sleep(60)
                    session = reset_and_reenter(headers)
                    grid = auto_merge_all(session, headers)
                    continue

                time.sleep(interval)

            elif response.status_code in [400, 401]:
                session.close()
                token_expired_msg = (
                    "╔══════════════════════╗\n"
                    "   🚨  انتهت صلاحية الجلسة  🚨\n"
                    "╚══════════════════════╝\n\n"
                    "⌛ انتهت صلاحية التوكن الحالي أو تم فتح اللعبة من جهاز آخر.\n"
                    "🔑 يرجى نسخ التوكن الجديد وإرساله هنا فوراً لاستئناف التجميع دون توقف!"
                )
                send_alert_msg(chat_id, token_expired_msg)

                old_token = current_token
                while True:
                    time.sleep(4)
                    new_token = load_user_token(chat_id)
                    if new_token and new_token != old_token:
                        current_token = new_token
                        headers["x-telegram-init-data"] = current_token
                        session = reset_and_reenter(headers)
                        break
            else:
                time.sleep(8)

        except Exception:
            time.sleep(4)

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

    welcome_msg = (
        "╔══════════════════════╗\n"
        "       🐿️ مرحباً بك في بوت NUTSCA 🐿️       \n"
        "╚══════════════════════╝\n\n"
        "✨ نظام التجميع والدمج الذكي يعمل على مدار الساعة:\n\n"
        "⚡ تجميع التكات التلقائي والمستمر\n"
        "🧺 بيع وتفريغ السلة عند الوصول لـ 5000 جوزة\n"
        "🐿️ شراء السناجب ودمجها تلقائياً لأعلى مستوى\n"
        "📊 لوحة تحكم حية ومباشرة تتحدث في نفس الرسالة\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔑 أرسل كود الـ init-data الخاص بحسابك هنا للبدء مباشرة:"
    )
    bot.reply_to(message, welcome_msg)
    if load_user_token(chat_id):
        start_user_thread(chat_id)

@bot.message_handler(func=lambda msg: True)
def handle_incoming_token(message):
    chat_id = message.chat.id
    text = message.text.strip()

    if "user=" in text or "hash=" in text:
        if "&tgWebApp" in text:
            text = text.split("&tgWebApp")[0]

        with open(get_token_filename(chat_id), "w", encoding="utf-8") as f:
            f.write(text)

        user_status_messages[chat_id] = None

        success_msg = (
            "╔══════════════════════╗\n"
            "      ✅ تم التحقق والربط بنجاح ✅      \n"
            "╚══════════════════════╝\n\n"
            "🚀 تم استلام التوكن وحفظه لحسابك!\n"
            "🎮 جاري الاتصال بخوادم اللعبة وتشغيل اللوحة الحية..."
        )
        bot.reply_to(message, success_msg)
        start_user_thread(chat_id)
    else:
        invalid_msg = (
            "╔══════════════════════╗\n"
            "       ❌ تنسيق غير صالح ❌       \n"
            "╚══════════════════════╝\n\n"
            "⚠️ النص المرسل لا يحتوي على بيانات init-data صالحة.\n"
            "تأكد من نسخ النص الذي يحتوي على user= أو hash= بالكامل."
        )
        bot.reply_to(message, invalid_msg)

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()

    for fname in os.listdir("."):
        if fname.startswith("token_") and fname.endswith(".txt"):
            try:
                saved_id = int(fname.replace("token_", "").replace(".txt", ""))
                start_user_thread(saved_id)
            except Exception:
                pass

    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception:
            time.sleep(3)
