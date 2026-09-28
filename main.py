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
from telebot import types
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.messages import RequestWebViewRequest

# --- إعدادات البوت والتحقق ---
TELEGRAM_BOT_TOKEN = "8681823633:AAGPEFeib4YEEW6fiim48O9WlPXiNVo-ozo"
GITHUB_LICENSES_URL = "https://raw.githubusercontent.com/MALHAMHACK2008/Nutsca_bot/refs/heads/main/licenses.json"

API_ID = int(os.environ.get("TELEGRAM_API_ID", 36791169))
API_HASH = os.environ.get("TELEGRAM_API_HASH", "d3965b64eb7e251a915ccd8ce3ee8104")

TARGET_GAME_BOT = "GoldNuts_Bot"
GAME_APP_URL = "https://game.nutsca.com/"

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

user_workers = {}
user_status_messages = {}
waiting_wallet = set()
waiting_manual_token = set()
waiting_session = set()

telethon_loop = asyncio.new_event_loop()
def run_tele_loop(loop):
    asyncio.set_event_loop(loop)
    loop.run_forever()
threading.Thread(target=run_tele_loop, args=(telethon_loop,), daemon=True).start()

# --- إدارة الملفات لكل مستخدم ---
def get_license_filename(chat_id): return f"license_{chat_id}.txt"
def get_session_filename(chat_id): return f"session_{chat_id}.txt"
def get_token_filename(chat_id): return f"token_{chat_id}.txt"
def get_wallet_filename(chat_id): return f"wallet_{chat_id}.txt"

def load_user_key(chat_id):
    f = get_license_filename(chat_id)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as file: return file.read().strip()
        except Exception: pass
    return None

def load_user_session(chat_id):
    f = get_session_filename(chat_id)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as file: return file.read().strip()
        except Exception: pass
    return None

def load_user_token(chat_id):
    f = get_token_filename(chat_id)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as file: return file.read().strip()
        except Exception: pass
    return None

def load_user_wallet(chat_id):
    f = get_wallet_filename(chat_id)
    if os.path.exists(f):
        try:
            with open(f, "r", encoding="utf-8") as file: return file.read().strip()
        except Exception: pass
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
    k = load_user_key(chat_id)
    return verify_license_remote(k) if k else False

server = Flask(__name__)
@server.route('/')
def home(): return "Nutsca Persistent Auto-Withdraw Running 24/7!"
threading.Thread(target=lambda: server.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080))), daemon=True).start()

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
            
            # تم إضافة فك التشفير للسحب التلقائي ليتطابق مع التوكن الصافي
            if "#tgWebAppData=" in raw_url:
                raw = raw_url.split("#tgWebAppData=")[1]
                if "&tgWebApp" in raw:
                    raw = raw.split("&tgWebApp")[0]
                return urllib.parse.unquote(raw)
        except Exception as e:
            try: await client.disconnect()
            except Exception: pass
        return None

    try:
        future = asyncio.run_coroutine_threadsafe(_fetch(), telethon_loop)
        return future.result(timeout=35.0)
    except Exception:
        return None

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

LEVEL_PRICES = [(7, 6400), (6, 3200), (5, 1600), (4, 800), (3, 400), (2, 200), (1, 100)]

def make_progress_bar(percent, total_blocks=10):
    filled = max(0, min(total_blocks, int(round(total_blocks * (percent / 100.0)))))
    return "▰" * filled + "▱" * (total_blocks - filled)

def format_uptime(seconds):
    mins, sec = divmod(int(seconds), 60)
    hours, mins = divmod(mins, 60)
    return f"{hours} س و {mins} د" if hours > 0 else f"{mins} د و {sec} ث"

class NutscaWorker:
    def __init__(self, chat_id):
        self.chat_id = chat_id
        self.session_str = load_user_session(chat_id)
        self.token = load_user_token(chat_id)
        self.wallet = load_user_wallet(chat_id)
        
        self.is_running = False
        self.stop_event = threading.Event()
        self.mining_thread = None
        
        self.is_withdrawing = False
        self.stop_withdraw_event = threading.Event()
        self.withdraw_thread = None
        self.total_withdraw_count = 0
        self.total_withdrawn_amount = 0
        self.notified_10k = False

        self.total_nuts_balance = 0.0
        self.balance = 0.0
        self.total_profit = 0.0
        self.highest_level = 0
        self.basket_nuts = 0.0
        self.basket_percent = 0.0
        self.start_time = time.time()
        self.last_token_refresh = time.time()
        self.status_text = "جاري البدء والاتصال... ⚡"

        self.http_session = requests.Session()
        adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504], raise_on_status=False))
        self.http_session.mount("https://", adapter)
        self.http_session.mount("http://", adapter)

    def get_headers(self):
        h = DEFAULT_HEADERS.copy()
        if self.token:
            h["x-telegram-init-data"] = self.token
        return h

    def refresh_token(self):
        if not self.session_str:
            return False
        fresh = fetch_token_from_session(self.session_str)
        if fresh:
            self.token = fresh
            with open(get_token_filename(self.chat_id), "w", encoding="utf-8") as f:
                f.write(fresh)
            self.last_token_refresh = time.time()
            return True
        return False

    def reset_and_reenter(self):
        try:
            h = self.get_headers()
            self.http_session.get(status_url, headers=h, timeout=8)
            r = self.http_session.get(state_url, headers=h, timeout=8)
            if r.status_code == 200:
                self.extract_total_nuts(r.json())
        except Exception:
            pass

    def extract_total_nuts(self, data):
        if not isinstance(data, dict): return
        for key in ["nuts", "totalNuts", "balanceNuts", "userNuts", "nutsBalance"]:
            if key in data and data[key] is not None:
                try:
                    self.total_nuts_balance = float(data[key])
                    return
                except Exception: pass
        user_info = data.get("user", {})
        if isinstance(user_info, dict):
            for key in ["nuts", "totalNuts", "balanceNuts", "nutsBalance"]:
                if key in user_info and user_info[key] is not None:
                    try:
                        self.total_nuts_balance = float(user_info[key])
                        return
                    except Exception: pass

    def get_highest_squirrel_level(self, grid):
        max_lvl = 0
        if isinstance(grid, list):
            for row in grid:
                if isinstance(row, list):
                    for val in row:
                        if isinstance(val, int) and val > max_lvl:
                            max_lvl = val
        return max_lvl

    def get_basket_info(self):
        try:
            r = self.http_session.get(apiary_url, headers=self.get_headers(), timeout=8)
            if r.status_code == 200:
                data = r.json()
                self.extract_total_nuts(data)
                nuts = 0.0
                for key in ["fullness", "amount", "current", "nuts"]:
                    val = data.get(key)
                    if val is not None:
                        try:
                            nuts = float(val)
                            break
                        except Exception: pass
                if nuts == 0 and isinstance(data.get("sellPreview"), dict):
                    nuts = float(data["sellPreview"].get("amount", 0))
                return nuts, min(100.0, (nuts / 5000.0) * 100.0), data.get("isFull", False)
        except Exception:
            pass
        return 0.0, 0.0, False

    def execute_sell(self):
        try:
            r = self.http_session.post(sell_url, headers=self.get_headers(), json={}, timeout=10)
            if r.status_code == 200:
                d = r.json()
                self.extract_total_nuts(d)
                return float(d.get("balanceB", 0)), float(d.get("receiveBalanceB", 0)), True
        except Exception:
            pass
        return None, 0.0, False

    def auto_merge_all(self):
        grid_out = []
        for _ in range(25):
            if self.stop_event.is_set(): break
            try:
                r = self.http_session.get(state_url, headers=self.get_headers(), timeout=8)
                if r.status_code != 200: break
                d = r.json()
                self.extract_total_nuts(d)
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
                if not pair: break

                p_from, p_to = pair
                m = self.http_session.post(action_url, headers=self.get_headers(), json={"action": "MOVE", "version": version, "from": p_from, "to": p_to}, timeout=8)
                if m.status_code == 200 and "grid" in m.json():
                    grid_out = m.json()["grid"]
                time.sleep(0.35)
            except Exception:
                break
        return grid_out

    def buy_squirrel(self, level):
        try:
            r = self.http_session.get(state_url, headers=self.get_headers(), timeout=8)
            if r.status_code != 200: return None, None
            d = r.json()
            grid = d.get("grid", [])
            version = d.get("version", 0)

            empty_slots = []
            counts_by_level = {}

            for y_idx, row in enumerate(grid):
                for x_idx, val in enumerate(row):
                    if val == 0:
                        empty_slots.append({"x": x_idx, "y": y_idx})
                    elif isinstance(val, int) and val > 0:
                        counts_by_level[val] = counts_by_level.get(val, 0) + 1

            free_slots_count = len(empty_slots)
            if free_slots_count == 0:
                return None, grid

            has_matching = counts_by_level.get(level, 0) > 0
            if free_slots_count <= 2 and not has_matching:
                return None, grid

            target_slot = empty_slots[0]
            payload = {
                "action": "PLACE",
                "version": version,
                "slotMode": "BUY",
                "slotLevel": level,
                "to": target_slot
            }

            b = self.http_session.post(action_url, headers=self.get_headers(), json=payload, timeout=10)
            if b.status_code == 200:
                new_balance = b.json().get("balanceB", 0)
                latest_grid = self.auto_merge_all()
                return float(new_balance), latest_grid
        except Exception:
            pass
        return None, None

    def try_buy_best_squirrel(self, balance):
        for level, price in LEVEL_PRICES:
            if balance >= price:
                new_bal, grid = self.buy_squirrel(level)
                if new_bal is not None:
                    return new_bal, grid, level
                break
        return balance, None, None

    def loop_withdrawal_worker(self):
        self.is_withdrawing = True
        self.stop_withdraw_event.clear()

        withdraw_headers = {
            "authority": "base.nutsca.com",
            "accept": "*/*",
            "accept-language": "ar-EG,ar;q=0.9,en-US;q=0.8,en;q=0.7",
            "content-type": "application/json",
            "origin": "https://game.nutsca.com",
            "referer": "https://game.nutsca.com/",
            "sec-ch-ua": '"Chromium";v="137", "Not/A)Brand";v="24"',
            "sec-ch-ua-mobile": "?1",
            "sec-ch-ua-platform": '"Android"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-site",
            "user-agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Mobile Safari/537.36",
            "x-telegram-init-data": self.token
        }

        while not self.stop_withdraw_event.is_set():
            if not self.wallet or not self.token:
                self.is_withdrawing = False
                break

            if 0 < self.total_nuts_balance < 10000:
                self.status_text = f"اكتمل السحب! رصيد الجوز أصبح أقل من 10k ({self.total_nuts_balance:.1f}) ✅"
                bot.send_message(self.chat_id, f"✅ <b>تم الانتهاء من دورة السحب:</b>\nأصبح رصيد الجوز الحالي: <code>{self.total_nuts_balance:.1f}</code> (أقل من 10,000).", parse_mode="HTML")
                break

            current_ts_ms = int(time.time() * 1000)
            payload = {
                "pid": "TON_CONNECT",
                "amount": 50,
                "wallet": self.wallet,
                "requestKey": f"TON_CONNECT:50:{current_ts_ms}"
            }

            try:
                resp = self.http_session.post(withdraw_url, headers=withdraw_headers, json=payload, timeout=12)
                try: res_data = resp.json()
                except Exception: res_data = {}

                current_status = str(res_data.get("status", "")).upper()
                self.extract_total_nuts(res_data)

                if current_status in ["CANCELLED", "CANCELED", "FAILED", "REJECTED"] or resp.status_code in [429, 403, 500, 502]:
                    self.status_text = f"⏳ حظر مؤقت من السيرفر ({current_status or resp.status_code}). انتظار دقيقة ثم المتابعة..."
                    self.update_ui()
                    for _ in range(60):
                        if self.stop_withdraw_event.is_set(): break
                        time.sleep(1)
                    continue

                if resp.status_code == 200:
                    self.total_withdraw_count += 1
                    self.total_withdrawn_amount += 50
                    if self.total_nuts_balance >= 50:
                        self.total_nuts_balance -= 50
                    self.status_text = f"🚀 جاري سحب الجوز المستمر... تم سحب: {self.total_withdrawn_amount} (+50)"
                    self.update_ui()
                else:
                    time.sleep(2)

            except Exception:
                time.sleep(3)

            time.sleep(0.5)

        self.is_withdrawing = False
        self.update_ui()

    def start_loop_withdrawal(self):
        if not self.wallet:
            bot.send_message(self.chat_id, "⚠️ لم تقم بتعيين محفظتك بعد! اضغط على <b>💳 تعيين المحفظة</b> أولاً.", parse_mode="HTML")
            return
        if not self.token:
            bot.send_message(self.chat_id, "⚠️ التوكن غير متوفر للاتصال باللعبة!", parse_mode="HTML")
            return
        if not self.is_withdrawing:
            self.withdraw_thread = threading.Thread(target=self.loop_withdrawal_worker, daemon=True)
            self.withdraw_thread.start()

    def stop_loop_withdrawal(self):
        if self.is_withdrawing:
            self.stop_withdraw_event.set()
            self.is_withdrawing = False
            self.status_text = "تم إيقاف السحب يدوياً ⏹️"
            self.update_ui()

    def get_dashboard_text(self):
        hours_run = max((time.time() - self.start_time) / 3600.0, 0.001)
        rate_per_hour = self.total_profit / hours_run
        bar = make_progress_bar(self.basket_percent)
        w_text = f"<code>{self.wallet[:8]}...{self.wallet[-6:]}</code>" if self.wallet else "⚠️ غير معينة"
        withdraw_state = "🔥 سحب الجوز مستمر وشغال" if self.is_withdrawing else "متوقف ⏹️"

        nuts_disp = f"{self.total_nuts_balance:.1f}" if self.total_nuts_balance > 0 else f"{self.basket_nuts:.1f} (سلة)"

        return (
            "╔══════════════════════╗\n"
            "       🐿️ لوحة تحكم NUTSCA PRO 🐿️       \n"
            "╚══════════════════════╝\n\n"
            f"• <b>البوت المستهدف:</b> <code>@{TARGET_GAME_BOT}</code>\n"
            f"🥜 <b>رصيد الجوز الإجمالي:</b> <code>{nuts_disp} جوزة</code>\n"
            f"💰 <b>رصيد العملات (B):</b> <code>{self.balance:.2f} B</code>\n"
            f"📈 <b>إجمالي الأرباح المكتسبة:</b> <code>+{self.total_profit:.2f} B</code>\n"
            f"⚡ <b>سرعة التجميع:</b> <code>~{rate_per_hour:.2f} B / س</code>\n"
            f"👑 <b>أعلى سنجاب لديك:</b> <code>لفل {self.highest_level}</code>\n\n"
            f"🧺 <b>حمولة السلة:</b> <code>[{bar}] {self.basket_percent:.1f}%</code> ({self.basket_nuts:.1f} / 5000)\n\n"
            f"💳 <b>المحفظة:</b> {w_text}\n"
            f"💸 <b>إجمالي المسحوب:</b> <code>{self.total_withdrawn_amount}</code> (عدد: {self.total_withdraw_count})\n"
            f"⚡ <b>حالة السحب:</b> <code>{withdraw_state}</code>\n"
            f"⏱️ <b>مدة التشغيل:</b> {format_uptime(time.time() - self.start_time)}\n"
            f"📊 <b>الحالة:</b> {self.status_text}\n"
        )

    def get_dashboard_markup(self):
        markup = types.InlineKeyboardMarkup(row_width=2)
        if self.is_withdrawing:
            btn_withdraw_toggle = types.InlineKeyboardButton("⏹️ إيقاف سحب الجوز", callback_data="stop_withdraw")
        else:
            btn_withdraw_toggle = types.InlineKeyboardButton("🚀 بدء سحب الجوز (حتى < 10k)", callback_data="start_withdraw")

        btn_session = types.InlineKeyboardButton("📱 ربط / تغيير الجلسة", callback_data="ask_session")
        btn_wallet = types.InlineKeyboardButton("💳 تعيين المحفظة", callback_data="set_wallet")
        btn_retry = types.InlineKeyboardButton("🔄 تحديث التوكن", callback_data="retry_pull")
        btn_manual = types.InlineKeyboardButton("🔑 إدخال توكن يدوي", callback_data="enter_token")
        
        markup.add(btn_withdraw_toggle)
        markup.add(btn_session, btn_wallet)
        markup.add(btn_retry, btn_manual)
        return markup

    def update_ui(self):
        msg_id = user_status_messages.get(self.chat_id)
        if not msg_id: return
        try:
            bot.edit_message_text(self.get_dashboard_text(), self.chat_id, msg_id, parse_mode="HTML", reply_markup=self.get_dashboard_markup())
        except Exception:
            pass

    def run_loop(self):
        if not self.token and self.session_str:
            self.refresh_token()

        if not self.token:
            self.status_text = "بانتظار ربط الجلسة أو إدخال التوكن..."
            self.update_ui()
            return

        self.reset_and_reenter()
        grid = self.auto_merge_all()
        self.highest_level = self.get_highest_squirrel_level(grid)
        self.basket_nuts, self.basket_percent, _ = self.get_basket_info()
        self.update_ui()

        last_balance = None

        while not self.stop_event.is_set():
            try:
                if self.session_str and (time.time() - self.last_token_refresh > 10800):
                    if self.refresh_token():
                        self.http_session.close()
                        self.reset_and_reenter()

                resp = self.http_session.post(tick_url, headers=self.get_headers(), json={}, timeout=12)

                if resp.status_code == 200:
                    data = resp.json()
                    self.extract_total_nuts(data)
                    current_bal = float(data.get("balanceB", 0))
                    interval = data.get("tickIntervalSeconds", 10)

                    if last_balance is not None and current_bal > last_balance:
                        self.total_profit += (current_bal - last_balance)
                    last_balance = current_bal
                    self.balance = current_bal

                    self.basket_nuts, self.basket_percent, is_full = self.get_basket_info()

                    if self.basket_nuts >= 5000 or is_full:
                        sold_bal, earned, ok = self.execute_sell()
                        if ok and sold_bal is not None:
                            self.total_profit += earned
                            self.balance = sold_bal
                            last_balance = self.balance
                            self.basket_nuts, self.basket_percent = 0.0, 0.0
                            if not self.is_withdrawing:
                                self.status_text = f"تم تفريغ وبيع السلة (+{earned:.2f} B)! 🧺"

                    if self.total_nuts_balance >= 10000:
                        if not self.notified_10k:
                            bot.send_message(self.chat_id, f"🔔 <b>تنبيه هام!</b>\nوصل رصيد الجوز لديك إلى: <code>{self.total_nuts_balance:.1f}</code> جوزة!\nتم تشغيل السحب المستمر تلقائياً إلى محفظتك.", parse_mode="HTML")
                            self.notified_10k = True
                        if self.wallet and not self.is_withdrawing:
                            self.start_loop_withdrawal()
                    elif self.total_nuts_balance < 9000:
                        self.notified_10k = False

                    if not self.is_withdrawing:
                        self.status_text = "تجميع التكات وشراء السناجب جاري... ⚡"

                    merged = self.auto_merge_all()
                    if merged: grid = merged

                    new_bal, buy_grid, bought_lvl = self.try_buy_best_squirrel(self.balance)
                    if buy_grid: grid = buy_grid
                    if bought_lvl:
                        self.balance = new_bal
                        last_balance = self.balance
                        if not self.is_withdrawing:
                            self.status_text = f"تم شراء سنجاب لفل {bought_lvl} ودمجه! 🐿️"

                    self.highest_level = self.get_highest_squirrel_level(grid)
                    self.update_ui()

                    if data.get("sessionSeconds", 0) >= 268:
                        self.http_session.close()
                        time.sleep(60)
                        self.reset_and_reenter()
                        continue

                    time.sleep(interval)

                elif resp.status_code in [400, 401]:
                    self.status_text = "⚠️ التوكن غير صالح أو منتهي. جاري التحديث..."
                    self.update_ui()
                    if self.session_str and self.refresh_token():
                        self.reset_and_reenter()
                        continue
                    else:
                        self.token = None
                        self.is_running = False
                        self.status_text = "بانتظار ربط الجلسة أو إدخال التوكن..."
                        self.update_ui()
                        break
                else:
                    time.sleep(8)
            except Exception:
                time.sleep(4)

    def start(self):
        if not self.is_running:
            self.is_running = True
            self.stop_event.clear()
            self.mining_thread = threading.Thread(target=self.run_loop, daemon=True)
            self.mining_thread.start()

def get_or_create_worker(chat_id):
    if chat_id not in user_workers:
        user_workers[chat_id] = NutscaWorker(chat_id)
    return user_workers[chat_id]

# --- معالجة الأزرار التفاعلية ---
@bot.callback_query_handler(func=lambda call: True)
def on_btn_click(call):
    cid = call.message.chat.id
    if not is_user_authorized(cid):
        bot.answer_callback_query(call.id, "الحساب غير مفعل 🔒")
        return

    w = get_or_create_worker(cid)

    if call.data == "start_withdraw":
        bot.answer_callback_query(call.id, "تم بدء سحب الجوز المستمر 🚀")
        w.start_loop_withdrawal()
        w.update_ui()

    elif call.data == "stop_withdraw":
        bot.answer_callback_query(call.id, "تم إيقاف السحب 🛑")
        w.stop_loop_withdrawal()

    elif call.data == "ask_session":
        waiting_session.add(cid)
        bot.send_message(cid, "📱 <b>أرسل الآن كود الجلسة النصية (StringSession) الخاص بحسابك:</b>\n(المستخرج من Pydroid 3)", parse_mode="HTML")
        bot.answer_callback_query(call.id, "بانتظار كود الجلسة...")

    elif call.data == "set_wallet":
        waiting_wallet.add(cid)
        bot.send_message(cid, "💳 <b>أرسل الآن عنوان محفظة TON الخاصة بك:</b>", parse_mode="HTML")
        bot.answer_callback_query(call.id, "بانتظار المحفظة...")

    elif call.data == "retry_pull":
        if not w.session_str:
            bot.answer_callback_query(call.id, "أرسل كود الجلسة أولاً!", show_alert=True)
            return
        bot.answer_callback_query(call.id, "جاري إعادة السحب...")
        bot.send_message(cid, f"⏳ جاري محاولة سحب التوكن من <b>@{TARGET_GAME_BOT}</b>...", parse_mode="HTML")
        if w.refresh_token():
            bot.send_message(cid, "✅ تم سحب التوكن بنجاح وبدء التعدين!")
            w.start()
        else:
            bot.send_message(cid, f"❌ تعذر السحب تلقائياً من @{TARGET_GAME_BOT}. استخدم زر '🔑 إدخال توكن يدوي'.")

    elif call.data == "enter_token":
        waiting_manual_token.add(cid)
        bot.send_message(cid, "🔑 <b>أرسل سطر initData أو رابط الويب كاملاً هنا:</b>", parse_mode="HTML")
        bot.answer_callback_query(call.id, "بانتظار التوكن...")

# --- الأوامر والرسائل النصية ---
@bot.message_handler(commands=['wallet'])
def handle_wallet_cmd(message):
    cid = message.chat.id
    parts = message.text.strip().split()
    w = get_or_create_worker(cid)
    if len(parts) < 2:
        saved = w.wallet
        bot.reply_to(message, f"💳 المحفظة الحالية: <code>{saved if saved else 'غير معينة'}</code>\nللتعيين أرسل:\n`/wallet عنوان_محفظتك`", parse_mode="HTML")
        return
    addr = parts[1].strip()
    w.wallet = addr
    with open(get_wallet_filename(cid), "w", encoding="utf-8") as f: f.write(addr)
    bot.reply_to(message, f"✅ تم حفظ محفظتك بنجاح:\n<code>{addr}</code>", parse_mode="HTML")
    w.update_ui()

@bot.message_handler(commands=['activate'])
def handle_activate_cmd(message):
    cid = message.chat.id
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "⚠️ أرسل الكود هكذا:\n`/activate YOUR-KEY`", parse_mode="Markdown")
        return
    k = parts[1].strip()
    if verify_license_remote(k):
        with open(get_license_filename(cid), "w", encoding="utf-8") as f: f.write(k)
        bot.reply_to(message, "✅ <b>تم التفعيل بنجاح!</b>\nأرسل الآن كود جلستك النصية أو استخدم الأزرار للبدء.", parse_mode="HTML")
    else:
        bot.reply_to(message, "❌ كود التفعيل غير صالح.")

@bot.message_handler(commands=['start'])
def handle_start_cmd(message):
    cid = message.chat.id
    if not is_user_authorized(cid):
        bot.reply_to(message, "🔒 البوت متاح للمشتركين فقط.\nفعّل حسابك بكتابة:\n`/activate YOUR-KEY`", parse_mode="Markdown")
        return

    w = get_or_create_worker(cid)
    sent = bot.send_message(cid, w.get_dashboard_text(), parse_mode="HTML", reply_markup=w.get_dashboard_markup())
    user_status_messages[cid] = sent.message_id
    w.start()

@bot.message_handler(func=lambda msg: True)
def handle_all_text(message):
    cid = message.chat.id
    text = message.text.strip()

    if not is_user_authorized(cid):
        bot.reply_to(message, "🔒 يجب تفعيل البوت أولاً عبر الأمر:\n`/activate YOUR-KEY`", parse_mode="Markdown")
        return

    w = get_or_create_worker(cid)

    if cid in waiting_wallet:
        waiting_wallet.remove(cid)
        w.wallet = text
        with open(get_wallet_filename(cid), "w", encoding="utf-8") as f:
            f.write(text)
        bot.reply_to(message, f"✅ <b>تم حفظ المحفظة بنجاح:</b>\n<code>{text}</code>", parse_mode="HTML")
        w.update_ui()
        return

    # التعديل الجديد: فحص التوكن اليدوي للتأكد من احتوائه على التوقيع الكامل
    if cid in waiting_manual_token or "user=" in text or "hash=" in text:
        if cid in waiting_manual_token: waiting_manual_token.remove(cid)
        
        raw_text = text
        if "#tgWebAppData=" in raw_text:
            raw_text = raw_text.split("#tgWebAppData=")[1]
            if "&tgWebApp" in raw_text:
                raw_text = raw_text.split("&tgWebApp")[0]
            raw_text = urllib.parse.unquote(raw_text)
            
        # فحص صارم للتوكن: هل يحتوي على hash؟
        if "hash=" not in raw_text:
            bot.reply_to(message, "❌ **التوكن ناقص ومرفوض!**\nلقد قمت بنسخ قسم `user=` فقط. سيرفر اللعبة يتطلب الرابط كاملاً للتحقق من هويتك.\n\nالرجاء العودة إلى HttpCanary ونسخ **الرابط (URL)** كاملاً الذي يحتوي على `hash=` وإرساله هنا.", parse_mode="Markdown")
            return
            
        w.token = raw_text
        with open(get_token_filename(cid), "w", encoding="utf-8") as f:
            f.write(raw_text)
            
        bot.reply_to(message, "✅ <b>تم تعيين التوكن بنجاح وبدأ العمل!</b>", parse_mode="HTML")
        w.start()
        w.update_ui()
        return

    clean_session = "".join(text.split())
    if cid in waiting_session or (clean_session.startswith("1BJ") and len(clean_session) > 100):
        if cid in waiting_session: waiting_session.remove(cid)
        w.session_str = clean_session
        with open(get_session_filename(cid), "w", encoding="utf-8") as f:
            f.write(clean_session)
        bot.reply_to(message, f"✅ <b>تم حفظ جلستك بنجاح!</b>\n⏳ جاري محاولة سحب التوكن تلقائياً من @{TARGET_GAME_BOT}...", parse_mode="HTML")
        if w.refresh_token():
            w.start()
            w.update_ui()
        return

    bot.reply_to(message, "⚠️ استخدم لوحة التحكم المرفقة أو الأزرار التفاعلية.", reply_markup=w.get_dashboard_markup())

if __name__ == "__main__":
    for f in os.listdir("."):
        if (f.startswith("session_") or f.startswith("token_")) and f.endswith(".txt"):
            try:
                uid = int(f.split("_")[1].replace(".txt", ""))
                if is_user_authorized(uid):
                    w = get_or_create_worker(uid)
                    w.start()
            except Exception: pass

    while True:
        try:
            bot.remove_webhook()
            time.sleep(1)
            bot.infinity_polling(skip_pending=True, timeout=20)
        except Exception:
            time.sleep(3)
