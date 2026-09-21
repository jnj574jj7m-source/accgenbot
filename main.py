#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import json
import base64
import struct
import time
import asyncio
import aiohttp
import requests
import random
import string
import warnings
import re
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes
)

warnings.filterwarnings('ignore')

# ================================================================
#  CONFIGURATIONS & GLOBALS
# ================================================================
# Render Environment Variable aayi BOT_TOKEN edukkunnu
BOT_TOKEN = os.environ["BOT_TOKEN"]  
ADMIN_ID = 7212602902                      # Replace with your Telegram User I

API_KEY = 'AIzaSyCQDz9rgjgmvmFkvVfmvr2-7fT4tfrzRRQ'
CF_BASE = 'https://europe-west1-cpm-2-7cea1.cloudfunctions.net'
OG_BASE = 'https://cpm-2.ogames.kz/api'
OG_KEY = '320b93f3e7f4410aa52ce24da363ad04'
VERSION = '1.3.2.3'
CLIENT_HASH = 'F05A72840B40DC4FAADF539C5E38062527AE6422'
BUNDLE_ID = 'com.olzhas.carparking.multyplayer2'
USER_AGENT = 'UnityPlayer/2022.3.62f2 (UnityWebRequest/1.0, libcurl/8.10.1-DEV)'

FB_SIGNUP = f'https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={API_KEY}'
FB_LOGIN = f'https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={API_KEY}'

KEY_ADD = '12345678'
IV_ADD = '01234567'

MARKO_VERSION = "3.0.0-PHOENIX"
MARKO_SIGNATURE = "PH03N1X_C0R3"
MARKO_DEVICE_PREFIX = "PHOENIX-DEVICE-"
DEVELOPER = "MARKO"

# Global state controls for 24/7 loop and dynamic delay
AUTO_FARM_RUNNING = False
AUTO_TASK = None
DELAY_INTERVAL = 3600  # Default interval in seconds (1 hour = 3600s)

_session = requests.Session()

# ================================================================
# RENDER HEALTH SERVER (Must have for Render deployment)
# ================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            body = b"OK"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        return

def start_health_server():
    port = int(os.environ.get("PORT", "10000"))
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 Health server listening on port {port}")
    server.serve_forever()

# ================================================================
#  CRYPTO & MEMORYPACK ENGINE
# ================================================================
class Crypto:
    def __init__(self, uid):
        self.uid = uid
        self.key = (uid[:8] + KEY_ADD).encode()[:16]
        self.iv = (uid[:8] + IV_ADD).encode()[:16]

    def encrypt(self, s):
        return base64.b64encode(AES.new(self.key, AES.MODE_CBC, self.iv).encrypt(pad(s.encode(), 16))).decode()

    def decrypt(self, s):
        try:
            return unpad(AES.new(self.key, AES.MODE_CBC, self.iv).decrypt(base64.b64decode(s)), 16).decode()
        except Exception:
            return None

    def extract_value(self, data):
        if isinstance(data, (int, float)):
            return int(data)
        if isinstance(data, str):
            try:
                parsed = json.loads(data)
                return self.extract_value(parsed)
            except Exception:
                pass
            if data.isdigit():
                return int(data)
            numbers = re.findall(r'\d+', data)
            if numbers:
                return int(numbers[0])
        if isinstance(data, list):
            for item in data:
                val = self.extract_value(item)
                if val is not None:
                    return val
        if isinstance(data, dict):
            for key in ['coins', 'value', 'coin', 'amount', 'points', 'data']:
                if key in data:
                    val = self.extract_value(data[key])
                    if val is not None:
                        return val
        return None

def _xor_key(uid):
    c = list(uid)
    if len(c) >= 7: c[4], c[6] = c[6], c[4]
    if len(c) >= 9: del c[8]
    if len(c) >= 1: c.append(c[0])
    return ''.join(c).encode()

def _xor_data(d, k): return bytes(b ^ k[i % len(k)] for i, b in enumerate(d))

def mp_encode(data, uid):
    import brotli
    return base64.b64encode(_xor_data(brotli.compress(data, quality=5), _xor_key(uid))).decode()

def mp_i32(v): return struct.pack('<i', v)
def mp_u16(v): return struct.pack('<H', v)
def mp_i64(v): return struct.pack('<q', v)
def mp_str(s):
    if s is None: return b'\xff\xff\xff\xff'
    if s == "": return mp_i32(0)
    utf8 = s.encode('utf-8')
    return mp_i32(~len(utf8)) + mp_i32(len(s)) + utf8
def mp_int_array(arr):
    buf = mp_i32(len(arr))
    for v in arr: buf += mp_i32(v)
    return buf
def mp_i64_array(arr):
    buf = mp_i32(len(arr))
    for v in arr: buf += mp_i64(v)
    return buf
def mp_dict_ii(d):
    buf = mp_i32(len(d))
    for k in sorted(d.keys()):
        buf += mp_i32(k) + mp_i32(d[k])
    return buf
def mp_dict_is(d):
    buf = mp_i32(len(d))
    for k in sorted(d.keys()):
        buf += mp_i32(k) + mp_str(d[k])
    return buf

# ================================================================
#  ACCOUNT CREATION ENGINE (SYNCHRONOUS)
# ================================================================
def gen_device_id():
    return ''.join(random.choice('0123456789abcdef') for _ in range(32))

def gen_email():
    username = ''.join(random.choices(string.ascii_lowercase + string.digits, k=random.randint(8, 12)))
    return f"{username}@markocpm.com"

def gen_password():
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=random.randint(10, 14)))

def unity_headers(token):
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=utf-8",
        "X-Unity-Version": "2022.3.62f2",
        "Authorization": f"Bearer {token}",
        "X-Client-Hash": CLIENT_HASH,
        "X-Client-Platform": "ANDROID",
        "X-Client-Version": VERSION,
        "X-Client-DeviceId": gen_device_id(),
        "X-Api-Key": OG_KEY,
        "X-Client-Env": "prod",
        "X-Bundle-Id": BUNDLE_ID,
    }

def ogames_headers(token):
    return {
        "X-Firebase-Token": token,
        "X-Client-Platform": "ANDROID",
        "X-Client-Version": VERSION,
        "X-Client-DeviceId": gen_device_id(),
        "X-Api-Key": OG_KEY,
        "X-Client-Env": "prod",
        "X-Bundle-Id": BUNDLE_ID,
        "Content-Type": "application/json",
        "User-Agent": USER_AGENT,
        "X-Client-Hash": CLIENT_HASH,
    }

def cf(fn, payload, token, timeout=30):
    url = f"{CF_BASE}/{fn}"
    body = json.dumps({"data": payload})
    hdrs = unity_headers(token)
    for attempt in range(3):
        try:
            r = _session.post(url, headers=hdrs, data=body, timeout=timeout, verify=False)
            if r.status_code == 429 or r.status_code >= 500:
                time.sleep(2 + attempt * 2)
                continue
            return r.json().get("result")
        except Exception:
            if attempt < 2:
                time.sleep(2 + attempt * 2)
                continue
            return None
    return None

def cf_code(fn, payload, token, timeout=30):
    r = cf(fn, payload, token, timeout)
    if isinstance(r, dict): return r.get("code", -1)
    if isinstance(r, str):
        try:
            d = json.loads(r)
            if isinstance(d, dict): return d.get("code", -1)
        except Exception: pass
    return -1

def signup(email, password):
    try:
        r = _session.post(FB_SIGNUP, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20, verify=False)
        j = r.json()
        if "idToken" in j:
            return {"token": j["idToken"], "uid": j["localId"]}
    except Exception:
        pass
    return None

def login_sync(email, password):
    try:
        r = _session.post(FB_LOGIN, json={"email": email, "password": password, "returnSecureToken": True}, timeout=20, verify=False)
        j = r.json()
        if "idToken" in j: return {"token": j["idToken"], "uid": j["localId"]}
    except Exception:
        pass
    return None

def start_session_sync(token, uid):
    oh = ogames_headers(token)
    try: _session.get(f"{OG_BASE}/check-service/v1/hash/check", headers=oh, timeout=15, verify=False)
    except Exception: pass
    try: _session.post(f"{OG_BASE}/check-service/v1/session/start", headers=oh, json={}, timeout=15, verify=False)
    except Exception: pass
    time.sleep(0.5)
    r3 = cf("MasterMainStartup23_1", "0", token)
    return r3.get("code", -1) if isinstance(r3, dict) else -1

KING_RATING_RESULT_ALL = {
    "general": {
        "cars": 100000, "car_fix": 100000, "car_collided": 100000, "car_exchange": 100000,
        "car_trade": 100000, "car_wash": 100000, "slicer_cut": 100000, "drift_max": 100000,
        "drift": 100000, "cargo": 100000, "delivery": 100000, "taxi": 100000, "levels": 100000,
        "gifts": 100000, "fuel": 100000, "offroad": 100000, "speed_banner": 100000,
        "reactions": 100000, "police": 100000, "run": 100000, "real_estate": 100000,
        "t_distance": 100000, "treasure": 100000, "block_post": 100000, "push_ups": 100000,
        "burnt_tire": 100000, "passanger_distance": 100000, "time": 9999999999, "race_win": 5000,
    },
    "achievements": {
        "cars": 5, "car_fix": 5, "car_collided": 5, "car_exchange": 5,
        "car_trade": 5, "car_wash": 5, "slicer_cut": 5, "drift_max": 5,
        "drift": 5, "cargo": 5, "delivery": 5, "taxi": 5, "levels": 5,
        "gifts": 5, "fuel": 5, "offroad": 5, "speed_banner": 5,
        "reactions": 5, "police": 5, "run": 5, "real_estate": 5,
        "t_distance": 5, "treasure": 5, "block_post": 5, "push_ups": 5,
        "burnt_tire": 5, "passanger_distance": 5, "time": 5, "race_win": 5,
    },
    "race_win": 5000, "level": 120, "score": 999.0, "batches": [5, 15, 25, 45, 60, 120],
}

def apply_king_rank(email, pw):
    a = login_sync(email, pw)
    if not a: return False
    token, uid = a["token"], a["uid"]
    crypto = Crypto(uid)

    if start_session_sync(token, uid) == 297:
        return False
    time.sleep(0.5)

    cf("SetUserRating22_1", crypto.encrypt(json.dumps(KING_RATING_RESULT_ALL)), token)
    cf_code("ValidateRank23_1", "0", token)
    return True

def charge_wallet(token, uid, email, password):
    crypto = Crypto(uid)
    cf("SaveAppVersionOnAccountCreated22_1", crypto.encrypt(json.dumps({"version": VERSION})), token)
    time.sleep(0.3)
    cf("GetRewards22_1", crypto.encrypt(""), token)
    time.sleep(0.3)
    cf("SavePlayerRecords22_1", crypto.encrypt("{}"), token)
    time.sleep(0.3)

    wallet_data = mp_i32(1) + mp_u16(0) + mp_i32(8) + mp_i64(50_000_000)
    cf("SaveWalletData23_1", mp_encode(wallet_data, uid), token)
    time.sleep(0.3)

    entries = {
        0: mp_str(""), 1: mp_str("PREMIUM"), 2: mp_int_array(list(range(225))),
        3: mp_i32(255), 4: mp_i64(127), 5: mp_i64(127), 6: mp_i32(0),
    }
    for k in range(19, 30): entries[k] = mp_int_array(list(range(15)))
    entries[30] = mp_int_array(list(range(50)))
    for k in range(31, 42): entries[k] = mp_int_array(list(range(15)))
    entries[42] = mp_int_array(list(range(50)))
    entries[43] = mp_dict_ii({i: 1 for i in range(78)})
    entries[44] = mp_i64((1 << 50) - 1)
    entries[45] = mp_int_array([1, 2, 3, 4, 5, 6, 7, 8])
    entries[46] = mp_i64_array([-1, 16777215])
    entries[47] = mp_int_array([1]*110)
    entries[48] = mp_i64(15)
    entries[49] = mp_int_array([6, -1, 0, 0, 0, 999999999, 0, 1, 0, 0, 0])
    entries[50] = mp_int_array([1]*13)
    entries[51] = mp_int_array([0, 0, 0, 0, 0])
    entries[52] = mp_dict_is({i: "0#1#2#3#4#5#6" for i in range(5)})
    entries[53] = mp_int_array(list(range(10)))

    full_unlock = mp_i32(len(entries))
    for k in sorted(entries.keys()):
        v = entries[k]
        full_unlock += mp_u16(k) + mp_i32(len(v)) + v

    cf("SavePlayerRecords23_1", mp_encode(full_unlock, uid), token)
    time.sleep(0.3)

def create_single_account():
    email = gen_email()
    password = gen_password()
    a = signup(email, password)
    if not a: return None
    token, uid = a["token"], a["uid"]
    charge_wallet(token, uid, email, password)
    rank_ok = apply_king_rank(email, password)
    return {"email": email, "password": password, "uid": uid, "rank_success": rank_ok}

# ================================================================
#  COIN FARMING ENGINE (ASYNC)
# ================================================================
def phoenix_gen_device():
    return MARKO_DEVICE_PREFIX + ''.join(random.choice('0123456789abcdef') for _ in range(28))

def phoenix_headers(token):
    return {
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json; charset=utf-8",
        "X-Unity-Version": "2022.3.62f2",
        "Authorization": f"Bearer {token}",
        "X-Client-Hash": CLIENT_HASH,
        "X-Phoenix-Signature": MARKO_SIGNATURE,
        "X-Phoenix-Version": MARKO_VERSION,
        "X-Phoenix-Developer": DEVELOPER,
    }

async def phoenix_login(email, password, session):
    try:
        async with session.post(FB_LOGIN, json={"email": email, "password": password, "returnSecureToken": True}, timeout=aiohttp.ClientTimeout(total=20)) as response:
            data = await response.json()
            if "idToken" in data:
                return {"token": data["idToken"], "uid": data["localId"]}
    except Exception:
        pass
    return None

async def phoenix_get_coins(session, token, uid):
    headers = phoenix_headers(token)
    payload = {"data": None}
    url = f"{CF_BASE}/GetCoins23_1"
    try:
        async with session.post(url, headers=headers, json=payload) as response:
            if response.status == 200:
                result = await response.json()
                if "result" in result and isinstance(result["result"], dict) and "data" in result["result"]:
                    crypto = Crypto(uid)
                    decrypted_str = crypto.decrypt(result["result"]["data"])
                    return crypto.extract_value(decrypted_str) or 0
    except Exception:
        pass
    return 0

async def phoenix_farm_engine(token, uid, session):
    crypto = Crypto(uid)
    all_combos = [(a, b, c) for a in range(10) for b in range(1, 7) for c in range(10)]
    
    total_coins = 0

    async def phoenix_execute_drag(sequence):
        a, b, c = sequence
        encrypted = crypto.encrypt(f"{a},{b},{c}")
        url = f"{CF_BASE}/SetDragRacing23_1"
        try:
            async with session.post(url, headers=phoenix_headers(token), data=json.dumps({"data": encrypted}), timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    result = await response.json()
                    if "result" in result and isinstance(result["result"], dict) and "data" in result["result"]:
                        decrypted = crypto.decrypt(result["result"]["data"])
                        coins = crypto.extract_value(decrypted)
                        if coins: return coins
        except Exception:
            pass
        return 0

    batch_size = 100
    for i in range(0, len(all_combos), batch_size):
        batch = all_combos[i:i+batch_size]
        results = await asyncio.gather(*[phoenix_execute_drag(seq) for seq in batch])
        for coins in results:
            if coins > 0: total_coins += coins
        await asyncio.sleep(0.1)

    return total_coins

# ================================================================
#  DYNAMIC TIME HELPER & COUNTDOWN
# ================================================================
def format_seconds(seconds: int) -> str:
    """Format seconds into readable hours, minutes, and seconds."""
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)
    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    elif mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"

async def run_live_countdown(context: ContextTypes.DEFAULT_TYPE, chat_id: int, total_seconds: int, account_num: int):
    """Updates a countdown message respecting the dynamic delay."""
    time_str = format_seconds(total_seconds)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=f"⏱ **Cooldown Active** (Completed Account #{account_num})\nDelay configured to `{time_str}`...",
        parse_mode="Markdown"
    )
    step = 10
    for remaining in range(total_seconds, 0, -step):
        if not AUTO_FARM_RUNNING:
            await msg.edit_text("🛑 **Automated generation cancelled.**", parse_mode="Markdown")
            return

        elapsed = total_seconds - remaining
        percent = int((elapsed / total_seconds) * 100)
        filled_blocks = int((percent / 100) * 10)
        bar = "▓" * filled_blocks + "░" * (10 - filled_blocks)

        rem_str = format_seconds(remaining)

        try:
            await msg.edit_text(
                f"⏱ **24/7 Cooldown Active** (Next Account #{account_num + 1})\n"
                f"Progress: `[{bar}] {percent}%`\n"
                f"Next Generation In: `{rem_str}`\n"
                f"Current Gap Setting: `{format_seconds(DELAY_INTERVAL)}`",
                parse_mode="Markdown"
            )
        except Exception:
            pass
        await asyncio.sleep(step)

    try:
        await msg.edit_text("⚡ **Cooldown Complete!** Creating next account now...", parse_mode="Markdown")
    except Exception:
        pass

# ================================================================
#  24/7 AUTOMATION TASK
# ================================================================
async def auto_generator_loop(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    global AUTO_FARM_RUNNING, DELAY_INTERVAL
    account_count = 0

    await context.bot.send_message(
        chat_id=chat_id,
        text=f"🚀 **24/7 Generator Engine Started!**\nConfigured Gap: `{format_seconds(DELAY_INTERVAL)}` between accounts.",
        parse_mode="Markdown"
    )

    async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False)) as session:
        while AUTO_FARM_RUNNING:
            account_count += 1
            status_msg = await context.bot.send_message(
                chat_id=chat_id,
                text=f"⚙️ **[Account #{account_count}]** Generating account...",
                parse_mode="Markdown"
            )

            # Step 1: Create Account
            acc = await asyncio.to_thread(create_single_account)
            if not acc:
                await status_msg.edit_text(f"❌ **[Account #{account_count}]** Creation failed! Retrying after gap...")
                await run_live_countdown(context, chat_id, DELAY_INTERVAL, account_count)
                continue

            email, password, uid = acc["email"], acc["password"], acc["uid"]
            status_desc = "King Rank + 50M" if acc.get("rank_success") else "50M Only"

            await status_msg.edit_text(f"⚡ **[Account #{account_count}]** Created! Farming coins...", parse_mode="Markdown")

            # Step 2: Farm Coins
            auth = await phoenix_login(email, password, session)
            farmed_coins = 0
            final_coins = 0

            if auth:
                token = auth["token"]
                initial_coins = await phoenix_get_coins(session, token, uid)
                farmed_coins = await phoenix_farm_engine(token, uid, session)
                final_coins = await phoenix_get_coins(session, token, uid) or (initial_coins + farmed_coins)

            # Step 3: Send Output
            result_text = (
                f"🎉 **Account #{account_count} Generated & Farmed!**\n\n"
                f"📧 **Email:** `{email}`\n"
                f"🔑 **Password:** `{password}`\n"
                f"🆔 **UID:** `{uid}`\n"
                f"👑 **Status:** `{status_desc}`\n"
                f"🪙 **Coins Farmed:** `{farmed_coins:,}`\n"
                f"💰 **Total Balance:** `{final_coins:,}`"
            )
            await status_msg.edit_text(result_text, parse_mode="Markdown")

            # Step 4: Run Live Countdown with current DELAY_INTERVAL
            if AUTO_FARM_RUNNING:
                await run_live_countdown(context, chat_id, DELAY_INTERVAL, account_count)

# ================================================================
#  TELEGRAM BOT COMMANDS & HANDLERS
# ================================================================
def get_control_keyboard():
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("▶️ Start 24/7 Automation", callback_data="start_auto"),
            InlineKeyboardButton("⏹ Stop Automation", callback_data="stop_auto")
        ],
        [
            InlineKeyboardButton("⏱ Current Status & Delay", callback_data="view_status")
        ]
    ])

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Access Denied.")
        return

    status = "🟢 Running" if AUTO_FARM_RUNNING else "🔴 Stopped"
    await update.message.reply_text(
        f"🤖 **DARKROOT CPM2 Automated Farm Control Panel**\n\n"
        f"Status: **{status}**\n"
        f"Configured Gap: `{format_seconds(DELAY_INTERVAL)}`\n\n"
        f"• Use `/setdelay <seconds>` or `/setdelay <val>m` to change the interval gap.\n"
        f"• Example: `/setdelay 1800` or `/setdelay 30m` or `/setdelay 1h`",
        reply_markup=get_control_keyboard(),
        parse_mode="Markdown"
    )

async def set_delay_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Dynamically set time delay gap."""
    global DELAY_INTERVAL
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("Access Denied.")
        return

    if not context.args:
        await update.message.reply_text(
            "⚠️ **Usage:** `/setdelay <time>`\n\n"
            "**Examples:**\n"
            "• `/setdelay 3600` (Sets delay to 3600 seconds)\n"
            "• `/setdelay 45m` (Sets delay to 45 minutes)\n"
            "• `/setdelay 2h` (Sets delay to 2 hours)",
            parse_mode="Markdown"
        )
        return

    arg = context.args[0].lower().strip()
    seconds = 0

    try:
        if arg.endswith("h"):
            seconds = int(float(arg[:-1]) * 3600)
        elif arg.endswith("m"):
            seconds = int(float(arg[:-1]) * 60)
        elif arg.endswith("s"):
            seconds = int(arg[:-1])
        else:
            seconds = int(arg)

        if seconds < 10:
            await update.message.reply_text("❌ Minimum allowed delay gap is 10 seconds.")
            return

        DELAY_INTERVAL = seconds
        await update.message.reply_text(
            f"✅ **Time gap updated!**\n"
            f"The bot will now wait **{format_seconds(DELAY_INTERVAL)}** between account productions.",
            parse_mode="Markdown"
        )
    except ValueError:
        await update.message.reply_text("❌ **Invalid time format.** Use numbers like `300`, `30m`, or `1h`.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AUTO_FARM_RUNNING, AUTO_TASK, DELAY_INTERVAL
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    chat_id = query.message.chat_id

    if query.data == "start_auto":
        if AUTO_FARM_RUNNING:
            await query.edit_message_text("⚠️ **Automation is already running!**", reply_markup=get_control_keyboard(), parse_mode="Markdown")
            return

        AUTO_FARM_RUNNING = True
        AUTO_TASK = asyncio.create_task(auto_generator_loop(context, chat_id))
        await query.edit_message_text("✅ **24/7 Automation Triggered!**", reply_markup=get_control_keyboard(), parse_mode="Markdown")

    elif query.data == "stop_auto":
        if not AUTO_FARM_RUNNING:
            await query.edit_message_text("⚠️ **Automation is not running.**", reply_markup=get_control_keyboard(), parse_mode="Markdown")
            return

        AUTO_FARM_RUNNING = False
        if AUTO_TASK:
            AUTO_TASK.cancel()
        await query.edit_message_text("🛑 **24/7 Automation Stopped.**", reply_markup=get_control_keyboard(), parse_mode="Markdown")

    elif query.data == "view_status":
        status = "🟢 Running" if AUTO_FARM_RUNNING else "🔴 Stopped"
        await query.edit_message_text(
            f"📊 **Current Bot Status**\n\n"
            f"• **Automation Loop:** {status}\n"
            f"• **Current Gap Interval:** `{format_seconds(DELAY_INTERVAL)}` (`{DELAY_INTERVAL}` seconds)\n\n"
            f"Change interval using `/setdelay <time>`",
            reply_markup=get_control_keyboard(),
            parse_mode="Markdown"
        )

# ================================================================
#  MAIN RUNNER
# ================================================================
def main():
    # Start Render Health Server in background thread
    threading.Thread(target=start_health_server, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("setdelay", set_delay_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    print("🤖 24/7 Auto-Generator & Farming Bot Running...")
    app.run_polling()

if __name__ == "__main__":
    main()
