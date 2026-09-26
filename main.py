import os
import re
import time
import json
import uuid
import logging
import asyncio
import threading
import urllib.parse
from flask import Flask
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import telebot
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import RequestWebViewRequest

# --- إعدادات البوت والتحقق ---
TELEGRAM_BOT_TOKEN = "8681823633:AAHHMpS4mOIiRf0sNo2MK2ZG7CDoTxEvzp8"
GITHUB_LICENSES_URL = "https://raw.githubusercontent.com/MALHAMHACK2008/Nutsca_bot/refs/heads/main/licenses.json"

API_ID = int(os.environ.get("TELEGRAM_API_ID", 36791169))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "d3965b64eb7e251a915ccd8ce3ee8104")

# إعدادات اللعبة والبوت المستهدف
TARGET_GAME_BOT = "nutscabot"  # أو يوزر البوت الخاص بلعبة السنجاب
GAME_APP_URL = "https://game.nutsca.com/"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

user_status_messages = {}
active_threads = {}

# حلقة Telethon للسحب المتزامن
telethon_loop = asyncio.new_event_loop()
def run_tele_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=run_tele_loop, args=(telethon_loop,), daemon=True).start()

# --- إدارة الملفات المستقلة لكل مستخدم ---
def get_license_filename(chat_id):
    return f"license_{chat_id}.txt"

def get_session_filename(chat_id):
    return f"session_{chat_id}.txt"

def get_wallet_filename(chat_id):
    return f"wallet_{chat_id}.txt"

def load_user_key(chat_id):
    fpath = get_license_filename(chat_id)
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None

def load_user_session(chat_id):
    fpath = get_session_filename(chat_id)
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None

def load_user_wallet(chat_id):
    fpath = get_wallet_filename(chat_id)
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return None

def verify_license_remote(user_key):
    try:
        resp = requests.get(GITHUB_LICENSES_URL, timeout=8)
        if resp.status_code == 200:
            licenses = resp.json()
            if user_key in licenses:
                return licenses[user_key].get("status", "expired") == "active"
    except Exception:
        pass
    return False

def is_user_authorized(chat_id):
    key = load_user_key(chat_id)
    if not key:
        return False
    return verify_license_remote(key)

# سيرفر إبقاء البوت نشطاً
server = Flask(__name__)
@server.route('/')
def home():
    return "Nutsca Auto-Pull & Withdraw Bot Running 24/7!"
threading.Thread(target=lambda: server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))), daemon=True).start()

# --- سحب الـ initData تلقائياً عبر الجلسة ---
def fetch_token_from_session(session_str):
    async def _fetch():
        clean_target = TARGET_GAME_BOT.replace("@", "").strip()
        client = TelegramClient(StringSession(session_str), API_ID, API_HASH, loop=telethon_loop)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                await client.disconnect()
                return None
            bot_entity = await client.get_input_entity(clean_target)
            web_view = await client(RequestWebViewRequest(
                peer=bot_entity,
                bot=bot_entity,
                platform="android",
                url=GAME_APP_URL
            ))
            raw_url = web_view.url
            await client.disconnect()
            if "#tgWebAppData=" in raw_url:
                raw = raw_url.split("#tgWebAppData=")[1].split("&tgWebAppVersion=")[0].split("&")[0]
                return urllib.parse.unquote(raw)
        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
        return None

    try:
        future = asyncio.run_coroutine_threadsafe(_fetch(), telethon_loop)
        return future.result(timeout=35.0)
    except Exception:
        return None

# روابط اللعبة
tick_url = "https://base.nutsca.com/api/active-earn/tick"
status_url = "https://base.nutsca.com/api/active-earn/status"
state_url = "https://base.nutsca.com/api/game/state"
apiary_url = "https://base.nutsca.com/api/apiary/state"
action_url = "https://base.nutsca.com/api/game/actions"
sell_url = "https://base.nutsca.com/api/apiary/sell"
withdraw_url = "https://base.nutsca.com/api/payments/crypto-withdrawal"

DEFAULT_HEADERS = {
    "authority": "base.nutsca.com",
    "Host": "base.nutsca.com",
    "content-type": "application/json",
    "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
    "accept": "*/*",
    "origin": "https://game.nutsca.com",
    "referer": "https://game.nutsca.com/",
    "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7"
}

LEVEL_PRICES = [(7, 6400), (6, 3200), (5, 1600), (4, 800), (3, 400), (2, 200), (1, 100)]

def make_progress_bar(percent, total_blocks=10):
    filled = max(0, min(total_blocks, int(round(total_blocks * (percent / 100.0)))))
    return "▰" * filled + "▱" * (total_blocks - filled)

def format_uptime(seconds):
    mins, sec = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours} س و {mins} د" if hours > 0 else f"{mins} د و {sec} ث"

def build_dashboard_text(balance, total_profit, highest_level, basket_nuts, basket_percent, uptime_sec, wallet_addr, status_text):
    hours_run = max(uptime_sec / 3600.0, 0.001)
    rate_per_hour = total_profit / hours_run
    bar = make_progress_bar(basket_percent)
    w_text = f"<code>{wallet_addr[:8]}...{wallet_addr[-6:]}</code>" if wallet_addr else "⚠️ غير معينة (/wallet)"

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
        f"💳 المحفظة: {w_text}\n"
        f"⏱️ مدة التشغيل: {format_uptime(uptime_sec)}\n"
        f"📊 الحالة: {status_text}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🔄 السحب التلقائي: يتم السحب عند بلوغ 10,000 جوزة"
    )

def update_or_send_msg(chat_id, text):
    msg_id = user_status_messages.get(chat_id)
    if msg_id:
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=text, parse_mode="HTML")
            return
        except Exception:
            pass
    try:
        sent = bot.send_message(chat_id, text, parse_mode="HTML")
        user_status_messages[chat_id] = sent.message_id
    except Exception:
        pass

def reset_and_reenter(headers):
    sess = requests.Session()
    adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504], raise_on_status=False))
    sess.mount("https://", adapter)
    try:
        sess.get(status_url, headers=headers, timeout=8)
        sess.get(state_url, headers=headers, timeout=8)
    except Exception:
        pass
    return sess

def get_highest_squirrel_level(grid):
    max_lvl = 0
    if isinstance(grid, list):
        for row in grid:
            if isinstance(row, list):
                for val in row:
                    if isinstance(val, int) and val > max_lvl:
                        max_lvl = val
    return max_lvl

def get_basket_info(session, headers):
    try:
        r = session.get(apiary_url, headers=headers, timeout=8)
        if r.status_code == 200:
            data = r.json()
            nuts = 0.0
            for key in ["fullness", "amount", "current", "nuts"]:
                val = data.get(key)
                if val:
                    try:
                        nuts = float(val)
                        break
                    except Exception:
                        pass
            return nuts, min(100.0, (nuts / 5000.0) * 100.0), data.get("isFull", False)
    except Exception:
        pass
    return 0.0, 0.0, False

def execute_sell(session, headers):
    try:
        r = session.post(sell_url, headers=headers, json={}, timeout=10)
        if r.status_code == 200:
            d = r.json()
            return float(d.get("balanceB", 0)), float(d.get("receiveBalanceB", 0)), True
    except Exception:
        pass
    return None, 0.0, False

def execute_crypto_withdraw(session, headers, wallet_address, amount=50):
    if not wallet_address:
        return False, "المحفظة غير معينة"
    payload = {
        "pid": "TON_CONNECT",
        "amount": amount,
        "wallet": wallet_address,
        "requestKey": f"TON_CONNECT:{amount}:{int(time.time() * 1000)}"
    }
    try:
        r = session.post(withdraw_url, headers=headers, json=payload, timeout=12)
        if r.status_code == 200:
            status = str(r.json().get("status", "")).upper()
            if status in ["CANCELLED", "CANCELED", "FAILED", "REJECTED"]:
                return False, f"حالة الطلب: {status}"
            return True, "تم السحب"
        return False, f"كود: {r.status_code}"
    except Exception as e:
        return False, str(e)

def auto_merge_all(session, headers):
    grid_out = []
    for _ in range(25):
        try:
            r = session.get(state_url, headers=headers, timeout=8)
            if r.status_code != 200:
                break
            d = r.json()
            grid = d.get("grid", [])
            grid_out = grid
            version = d.get("version", 0)

            positions = {}
            for y, row in enumerate(grid):
                for x, lvl in enumerate(row):
                    if isinstance(lvl, int) and 0 < lvl < 13:
                        positions.setdefault(lvl, []).append({"x": x, "y": y})

            pair = None
            for lvl, pos_list in sorted(positions.items()):
                if len(pos_list) >= 2:
                    pair = (pos_list[0], pos_list[1])
                    break

            if not pair:
                break

            p_from, p_to = pair
            m = session.post(action_url, headers=headers, json={"action": "MOVE", "version": version, "from": p_from, "to": p_to}, timeout=8)
            if m.status_code == 200 and "grid" in m.json():
                grid_out = m.json()["grid"]
            time.sleep(0.35)
        except Exception:
            break
    return grid_out

def buy_squirrel(session, headers, level):
    try:
        r = session.get(state_url, headers=headers, timeout=8)
        if r.status_code != 200:
            return None, None
        d = r.json()
        grid = d.get("grid", [])
        version = d.get("version", 0)

        empty = [{"x": x, "y": y} for y, row in enumerate(grid) for x, val in enumerate(row) if val == 0]
        if not empty:
            return None, grid

        b = session.post(action_url, headers=headers, json={"action": "PLACE", "version": version, "slotMode": "BUY", "slotLevel": level, "to": empty[0]}, timeout=10)
        if b.status_code == 200:
            return float(b.json().get("balanceB", 0)), auto_merge_all(session, headers)
    except Exception:
        pass
    return None, None

def try_buy_best_squirrel(session, headers, balance):
    for level, price in LEVEL_PRICES:
        if balance >= price:
            new_bal, grid = buy_squirrel(session, headers, level)
            if new_bal is not None:
                return new_bal, grid, level
            break
    return balance, None, None

# --- محرك عمل الحساب المستقل ---
def bot_worker_for_user(chat_id):
    if not is_user_authorized(chat_id):
        return

    session_str = load_user_session(chat_id)
    if not session_str:
        return

    headers = DEFAULT_HEADERS.copy()
    update_or_send_msg(chat_id, "⏳ جاري الاتصال وسحب التوكن تلقائياً من جلستك...")
    current_token = fetch_token_from_session(session_str)
    
    if not current_token:
        bot.send_message(chat_id, "❌ تعذر سحب التوكن من جلستك. تأكد من فتح اللعبة لمرة واحدة بحسابك.")
        return

    headers["x-telegram-init-data"] = current_token
    session = reset_and_reenter(headers)
    grid = auto_merge_all(session, headers)

    highest_lvl = get_highest_squirrel_level(grid)
    nuts, percent, _ = get_basket_info(session, headers)

    total_profit = 0.0
    last_balance = None
    start_time = time.time()
    last_token_refresh = time.time()
    accumulated_nuts = 0.0

    while True:
        try:
            # تجديد التوكن تلقائياً كل 45 دقيقة عبر الجلسة
            if time.time() - last_token_refresh > 2700:
                fresh = fetch_token_from_session(session_str)
                if fresh:
                    current_token = fresh
                    headers["x-telegram-init-data"] = current_token
                    session.close()
                    session = reset_and_reenter(headers)
                last_token_refresh = time.time()

            uptime = time.time() - start_time
            user_wallet = load_user_wallet(chat_id)
            resp = session.post(tick_url, headers=headers, json={}, timeout=12)

            if resp.status_code == 200:
                data = resp.json()
                current_bal = float(data.get("balanceB", 0))
                interval = data.get("tickIntervalSeconds", 10)

                if last_balance is not None and current_bal > last_balance:
                    total_profit += (current_bal - last_balance)
                last_balance = current_bal

                nuts, percent, is_full = get_basket_info(session, headers)
                status_text = "تجميع التكات جاري... ⚡"

                if nuts >= 5000 or is_full:
                    sold_bal, earned, ok = execute_sell(session, headers)
                    if ok and sold_bal is not None:
                        total_profit += earned
                        accumulated_nuts += nuts
                        current_bal = sold_bal
                        last_balance = current_bal
                        nuts, percent = 0.0, 0.0
                        status_text = f"تم تفريغ وبيع السلة (+{earned:.2f} B)! 🧺"

                # السحب التلقائي كل 10 آلاف جوزة
                if accumulated_nuts >= 10000:
                    if user_wallet:
                        succ, msg = execute_crypto_withdraw(session, headers, user_wallet, 50)
                        if succ:
                            bot.send_message(chat_id, f"🎉 <b>تم سحب الأرباح تلقائياً إلى محفظتك!</b>\nالمحفظة: <code>{user_wallet}</code>", parse_mode="HTML")
                            accumulated_nuts = 0.0
                            status_text = "تم سحب الأرباح تلقائياً 💸"
                    else:
                        status_text = "وصلت لـ 10k جوزة! عيّن محفظتك: /wallet"

                merged_grid = auto_merge_all(session, headers)
                if merged_grid:
                    grid = merged_grid

                new_bal, buy_grid, bought_lvl = try_buy_best_squirrel(session, headers, current_bal)
                if buy_grid:
                    grid = buy_grid
                if bought_lvl:
                    current_bal = new_bal
                    last_balance = current_bal
                    status_text = f"تم شراء سنجاب لفل {bought_lvl} ودمجه! 🐿️"

                highest_lvl = get_highest_squirrel_level(grid)
                update_or_send_msg(chat_id, build_dashboard_text(current_bal, total_profit, highest_lvl, nuts, percent, uptime, user_wallet, status_text))

                if data.get("sessionSeconds", 0) >= 268:
                    session.close()
                    time.sleep(60)
                    session = reset_and_reenter(headers)
                    continue

                time.sleep(interval)
            elif resp.status_code in [400, 401]:
                # تجديد فوري عند انتهاء التوكن
                fresh = fetch_token_from_session(session_str)
                if fresh:
                    headers["x-telegram-init-data"] = fresh
                    session = reset_and_reenter(headers)
                else:
                    time.sleep(10)
            else:
                time.sleep(8)
        except Exception:
            time.sleep(4)

def start_user_thread(chat_id):
    if not is_user_authorized(chat_id):
        return
    if chat_id not in active_threads or not active_threads[chat_id].is_alive():
        t = threading.Thread(target=bot_worker_for_user, args=(chat_id,), daemon=True)
        active_threads[chat_id] = t
        t.start()

# --- معالجة رسائل وأوامر تيليجرام ---
@bot.message_handler(commands=['wallet'])
def handle_wallet(message):
    cid = message.chat.id
    parts = message.text.strip().split()
    if len(parts) < 2:
        saved = load_user_wallet(cid)
        bot.reply_to(message, f"💳 المحفظة الحالية: <code>{saved if saved else 'غير معينة'}</code>\nللتعيين أرسل:\n`/wallet عنوان_محفظتك`", parse_mode="HTML")
        return
    addr = parts[1].strip()
    with open(get_wallet_filename(cid), "w", encoding="utf-8") as f:
        f.write(addr)
    bot.reply_to(message, f"✅ تم حفظ محفظتك بنجاح:\n<code>{addr}</code>\nسيتم سحب الأرباح إليها تلقائياً عند بلوغ 10k جوزة.", parse_mode="HTML")

@bot.message_handler(commands=['activate'])
def handle_activate(message):
    cid = message.chat.id
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ أرسل الكود هكذا:\n`/activate YOUR-KEY`", parse_mode="Markdown")
        return
    k = parts[1].strip()
    if verify_license_remote(k):
        with open(get_license_filename(cid), "w", encoding="utf-8") as f:
            f.write(k)
        bot.reply_to(message, "✅ <b>تم التفعيل بنجاح!</b>\nأرسل الآن كود جلستك النصية (StringSession) للبدء فوراً.", parse_mode="HTML")
    else:
        bot.reply_to(message, "❌ كود التفعيل غير صالح.")

@bot.message_handler(commands=['start'])
def handle_start(message):
    cid = message.chat.id
    if not is_user_authorized(cid):
        bot.reply_to(message, "🔒 البوت متاح للمشتركين فقط.\nفعّل حسابك بكتابة:\n`/activate YOUR-KEY`", parse_mode="Markdown")
        return
    bot.reply_to(message, "🐿️ <b>مرحباً بك!</b>\nأرسل كود جلستك النصية (StringSession) لربط حسابك وبدء التعدين والسحب التلقائي.", parse_mode="HTML")
    if load_user_session(cid):
        start_user_thread(cid)

@bot.message_handler(func=lambda msg: True)
def handle_all_messages(message):
    cid = message.chat.id
    text = "".join(message.text.strip().split())

    if not is_user_authorized(cid):
        bot.reply_to(message, "🔒 يجب تفعيل البوت أولاً عبر الأمر:\n`/activate YOUR-KEY`", parse_mode="Markdown")
        return

    # استقبال وحفظ كود الجلسة النصية
    if text.startswith("1BJ") and len(text) > 100:
        with open(get_session_filename(cid), "w", encoding="utf-8") as f:
            f.write(text)
        bot.reply_to(message, "✅ <b>تم استلام وحفظ جلستك النصية بنجاح!</b>\n🚀 جاري سحب التوكن تلقائياً وتشغيل التجميع ودمج السناجب...\n💡 لا تنسَ ضبط محفظتك عبر: `/wallet عنوانك`", parse_mode="HTML")
        start_user_thread(cid)
    else:
        bot.reply_to(message, "⚠️ يرجى إرسال كود الجلسة النصية (StringSession) الخاص بك والمستخرج من Pydroid 3 كسطر واحد متصل.")

if __name__ == "__main__":
    for f in os.listdir("."):
        if f.startswith("session_") and f.endswith(".txt"):
            try:
                uid = int(f.replace("session_", "").replace(".txt", ""))
                if is_user_authorized(uid):
                    start_user_thread(uid)
            except Exception:
                pass

    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception:
            time.sleep(3)
