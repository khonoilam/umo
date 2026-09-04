import asyncio
import logging
import re
import time
import random
import string
import uuid
import base64
import hashlib
import json
import os
import sys
import threading
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ChatMemberHandler, MessageHandler, filters

# ========== CẤU HÌNH BOT ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8988947106:AAEQxdenSha6W_5De4NMEnDoc5-RSvMkenk")
ADMIN_ID = 7267437767
GROUP_ID = -1004318229096
GROUP_LINK = "https://t.me/cloudfreeaot"

# ========== CẤU HÌNH JSONBIN ==========
JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "$2a$10$ZKItx9kCcaQktuLuBDKY1ewYhT2gy3OWH.w7nkeTLWUy9sCxtjVWO")
USERS_BIN_ID = os.environ.get("USERS_BIN_ID", "6a9a2b51da38895dfe368386")
GROUPS_BIN_ID = os.environ.get("GROUPS_BIN_ID", "6a9a2babf5f4af5e2968148c")
PENDING_BIN_ID = os.environ.get("PENDING_BIN_ID", "6a9a2be2da38895dfe36851d")
JSONBIN_BASE = "https://api.jsonbin.io/v3/b"

HEADERS = {
    "X-Master-Key": JSONBIN_API_KEY,
    "Content-Type": "application/json"
}

def load_json_from_bin(bin_id):
    url = f"{JSONBIN_BASE}/{bin_id}/latest"
    r = requests.get(url, headers=HEADERS, timeout=15)
    if r.status_code == 200:
        return r.json().get("record", {})
    return None

def save_json_to_bin(bin_id, data):
    url = f"{JSONBIN_BASE}/{bin_id}"
    r = requests.put(url, headers=HEADERS, json=data, timeout=15)
    return r.status_code == 200

# ========== DỮ LIỆU ==========
DATA = {"users": {}, "daily_counts": {}, "private_started": {}, "banned": {}, "tag_users": []}
GROUPS = []
PENDING = {}

try:
    tmp = load_json_from_bin(USERS_BIN_ID)
    if tmp:
        DATA = tmp
except Exception:
    pass

try:
    tmp = load_json_from_bin(GROUPS_BIN_ID)
    if tmp is not None:
        GROUPS = tmp
except Exception:
    pass

try:
    tmp = load_json_from_bin(PENDING_BIN_ID)
    if tmp:
        PENDING = tmp
except Exception:
    pass

if GROUP_ID not in GROUPS:
    GROUPS.append(GROUP_ID)
    save_json_to_bin(GROUPS_BIN_ID, GROUPS)

# ========== CẤU HÌNH UMO CLOUD ==========
CLIENT_CODE = "ae02b"
CID = "50000"
CVER = "10010016"
LOCALE = "en-US"
CLIENT_TYPE = "h5"
SALT = "4d9cbb6b585448419578a95954a2b886"
TENANT_ID = "242"
BRAND_ID = "108"
CHANNEL = "h5_cphone"
PUBLIC_KEY = """-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQCbHF73B6NPGm5lwS4hVGg+W8VO
ezCt+Af4Cvx7UZjXakyk7U6QgPABK4JNnlRTV0wgySMM5zv9H9qXL6ltbqskKeZd
DXhWaqu9oytBCaBg4nEA5O/y44qnm+NI+Tu35ulGDzSfQxP2js9LV3bcqjv/hP0S
9aj2jBKINUKE2swiGQIDAQAB
-----END PUBLIC KEY-----"""
EMAIL_PREFIX = "aotvippro"

# ========== LƯU TRỮ ==========
def load_data():
    global DATA
    tmp = load_json_from_bin(USERS_BIN_ID)
    if tmp:
        DATA = tmp

def save_data():
    save_json_to_bin(USERS_BIN_ID, DATA)

def load_groups():
    global GROUPS
    tmp = load_json_from_bin(GROUPS_BIN_ID)
    if tmp is not None:
        GROUPS = tmp

def save_groups():
    save_json_to_bin(GROUPS_BIN_ID, GROUPS)

def load_pending():
    global PENDING
    tmp = load_json_from_bin(PENDING_BIN_ID)
    if tmp:
        PENDING = tmp

def save_pending():
    save_json_to_bin(PENDING_BIN_ID, PENDING)

# ========== LOGGING ==========
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram._bot").setLevel(logging.WARNING)

def get_vn_now():
    return datetime.now(timezone(timedelta(hours=7)))

def get_vn_today():
    return get_vn_now().strftime("%Y-%m-%d")

def update_user_activity(user_id, username=None, first_name=None, last_name=None):
    now = get_vn_now().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)
    if uid not in DATA["users"]:
        DATA["users"][uid] = {
            "user_id": user_id,
            "username": username or "",
            "first_name": first_name or "",
            "last_name": last_name or "",
            "first_seen": now,
            "last_seen": now,
            "total_accounts": 0,
            "accounts_today": 0,
            "last_account_date": None
        }
    else:
        DATA["users"][uid]["last_seen"] = now
        if username:
            DATA["users"][uid]["username"] = username
        if first_name:
            DATA["users"][uid]["first_name"] = first_name
        if last_name:
            DATA["users"][uid]["last_name"] = last_name
    save_data()

def increment_user_account(user_id):
    today = get_vn_today()
    uid = str(user_id)
    if uid not in DATA["users"]:
        update_user_activity(user_id)
    DATA["users"][uid]["total_accounts"] += 1
    if DATA["users"][uid]["last_account_date"] != today:
        DATA["users"][uid]["accounts_today"] = 1
        DATA["users"][uid]["last_account_date"] = today
    else:
        DATA["users"][uid]["accounts_today"] += 1
    if today not in DATA["daily_counts"]:
        DATA["daily_counts"][today] = {"total": 0, "by_user": {}}
    DATA["daily_counts"][today]["total"] += 1
    if uid not in DATA["daily_counts"][today]["by_user"]:
        DATA["daily_counts"][today]["by_user"][uid] = 0
    DATA["daily_counts"][today]["by_user"][uid] += 1
    save_data()

def set_private_started(user_id):
    DATA["private_started"][str(user_id)] = True
    save_data()

def has_private_started(user_id):
    return str(user_id) in DATA.get("private_started", {})

# ========== HEALTH SERVER ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")
    def log_message(self, format, *args):
        pass

def start_health_server():
    port = int(os.environ.get("PORT", 8000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

# ========== KIỂM TRA MEMBER / BOT TAG ==========
async def is_member(context, user_id):
    try:
        member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False

async def is_bot_admin(context, chat_id):
    try:
        bot_member = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        return bot_member.status == "administrator" and bot_member.can_delete_messages
    except Exception:
        return False

async def is_bot_mention(context, chat_id, entity, message_text):
    """Xác định chính xác entity có phải là bot khác không."""
    if entity.type == MessageEntity.TEXT_MENTION:
        user = entity.user
        # TEXT_MENTION luôn có thông tin user đầy đủ
        if user and user.is_bot and user.id != context.bot.id:
            return True
        return False
    elif entity.type == MessageEntity.MENTION:
        # Trích xuất username từ text
        offset = entity.offset
        length = entity.length
        username = message_text[offset:offset+length].lstrip('@')
        try:
            # Lấy thông tin chat từ username
            chat = await context.bot.get_chat(f"@{username}")
            user_id = chat.id
            # Lấy member để kiểm tra is_bot
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
            if member.user.is_bot and user_id != context.bot.id:
                return True
        except Exception:
            # Nếu không lấy được thông tin, coi như không phải bot
            return False
    return False

# Lưu thời gian cảnh báo cho mỗi user
TAG_WARNED_TIMESTAMPS = {}

async def handle_regular_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return
    user = update.effective_user
    if not user:
        return
    if user.id == ADMIN_ID:
        return

    if message.entities:
        has_bot_mention = False
        for entity in message.entities:
            if entity.type in [MessageEntity.MENTION, MessageEntity.TEXT_MENTION]:
                if await is_bot_mention(context, message.chat_id, entity, message.text):
                    has_bot_mention = True
                    break

        if has_bot_mention:
            # Xóa tin nhắn nếu bot có quyền
            can_delete = await is_bot_admin(context, message.chat_id)
            if can_delete:
                try:
                    await message.delete()
                except Exception:
                    pass

            # Gửi cảnh báo nếu chưa gửi trong 1 giờ qua
            current_time = time.time()
            last_warned = TAG_WARNED_TIMESTAMPS.get(user.id, 0)
            if current_time - last_warned >= 3600:
                try:
                    await context.bot.send_message(
                        chat_id=message.chat_id,
                        text="Tuất tag bot khác ăn cứt à 🚫"
                    )
                    TAG_WARNED_TIMESTAMPS[user.id] = current_time
                except Exception:
                    pass

# ========== WILLCLOUDS FUNCTIONS ==========
def java_url_encode(s):
    bs = str(s).encode('utf-8')
    out = []
    for b in bs:
        if b == 32:
            out.append('+')
        elif (48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122) or b in (45, 46, 95, 42):
            out.append(chr(b))
        else:
            out.append('%' + format(b, '02X'))
    return ''.join(out)

def build_query(obj):
    return '&'.join([java_url_encode(k) + '=' + java_url_encode(str(obj[k])) for k in sorted(obj.keys())])

def sign(obj):
    b = build_query(obj)
    w = hashlib.md5((b + SALT).encode()).hexdigest()
    return w[4:20], b

def make_headers(token="", content_type=False):
    h = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/139.0.0.0 Mobile Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US",
        "Origin": "https://h5.willclouds.com",
        "Referer": "https://h5.willclouds.com/",
        "tenant-id": TENANT_ID,
        "client-brand-id": BRAND_ID,
        "timezone": "Asia/Saigon",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    if content_type:
        h["Content-Type"] = "application/x-www-form-urlencoded"
    return h

def rsa_encrypt(data):
    key = RSA.import_key(PUBLIC_KEY)
    cipher = PKCS1_v1_5.new(key)
    enc = cipher.encrypt(data.encode('utf-8'))
    return base64.b64encode(enc).decode('utf-8')

def create_temp_mail():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get("https://api.mail.tm/domains", timeout=15, headers=headers)
    domain = r.json()["hydra:member"][0]["domain"]
    random_digits = ''.join(random.choices(string.digits, k=4))
    email = f"{EMAIL_PREFIX}{random_digits}@{domain}"
    mail_password = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    payload = {"address": email, "password": mail_password}
    requests.post("https://api.mail.tm/accounts", json=payload, timeout=15, headers={**headers, "Content-Type": "application/json"})
    r2 = requests.post("https://api.mail.tm/token", json=payload, timeout=15, headers={**headers, "Content-Type": "application/json"})
    token = r2.json().get("token")
    if not token:
        raise Exception("No token from mail.tm")
    return email, mail_password, token

def read_code_from_mail(token, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        r = requests.get("https://api.mail.tm/messages", timeout=15, headers=headers)
        if r.status_code != 200:
            continue
        messages = r.json().get("hydra:member", [])
        if messages:
            msg = messages[0]
            r2 = requests.get(f"https://api.mail.tm/messages/{msg['id']}", timeout=15, headers=headers)
            if r2.status_code == 200:
                data = r2.json()
                text = data.get("text", "") or data.get("html", "")
            else:
                text = msg.get("subject", "")
            codes = re.findall(r'\b\d{4,6}\b', text)
            if codes:
                return codes[0]
    raise Exception("No code received")

def send_verification_code(email, cuid):
    data = {
        "cuid": cuid,
        "ts": str(int(time.time() * 1000)),
        "userId": "",
        "cid": CID,
        "chnl": CHANNEL,
        "cver": CVER,
        "locale": LOCALE,
        "clientType": CLIENT_TYPE,
        "scene": "1",
        "captcha": "",
        "account": email,
        "accountType": "mail",
    }
    sig, b = sign(data)
    h = make_headers(content_type=True)
    h["x-signature"] = sig
    r = requests.post("https://oem-api.willclouds.com/saas-api/cloud-client/auth/send-verification-code", data=b, headers=h, timeout=20)
    res = r.json()
    if res.get("code") != 0:
        raise Exception("send verification failed: " + r.text)

def login_email_code(email, code, cuid):
    data = {
        "cuid": cuid,
        "ts": str(int(time.time() * 1000)),
        "userId": "",
        "cid": CID,
        "chnl": CHANNEL,
        "cver": CVER,
        "locale": LOCALE,
        "clientType": CLIENT_TYPE,
        "account": email,
        "loginType": "MAIL_CODE",
        "authContent": code,
    }
    sig, b = sign(data)
    h = make_headers(content_type=True)
    h["x-signature"] = sig
    r = requests.post("https://oem-core.willclouds.com/saas-api/cloud-client/auth/login", data=b, headers=h, timeout=20)
    res = r.json()
    if res.get("code") != 0:
        raise Exception("login failed: " + r.text)
    return res["data"]["userId"], res["data"]["token"]

def set_password_cloud(user_id, token, password, cuid):
    enc_pw = rsa_encrypt(password)
    data = {
        "cuid": cuid,
        "ts": str(int(time.time() * 1000)),
        "userId": str(user_id),
        "cid": CID,
        "chnl": CHANNEL,
        "cver": CVER,
        "locale": LOCALE,
        "clientType": CLIENT_TYPE,
        "password": enc_pw,
    }
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True)
    h["x-signature"] = sig
    r = requests.post("https://oem-core.willclouds.com/saas-api/cloud-client/user/set-member-password", data=b, headers=h, timeout=20)
    res = r.json()
    if res.get("code") != 0:
        raise Exception("set password failed: " + r.text)

def receive_trial_cloud(user_id, token, cuid):
    data = {
        "cuid": cuid,
        "ts": str(int(time.time() * 1000)),
        "userId": str(user_id),
        "cid": CID,
        "chnl": CHANNEL,
        "cver": CVER,
        "locale": LOCALE,
        "clientType": CLIENT_TYPE,
    }
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True)
    h["x-signature"] = sig
    r = requests.post("https://oem-api.willclouds.com/saas-api/cloud-client/user/receive-instance", data=b, headers=h, timeout=20)
    res = r.json()
    return res.get("code") == 0, res

# ========== LOCKS ==========
USER_LOCKS = {}
USER_LOCKS_GUARD = asyncio.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=20)
LAST_CLOUD_STATUS = None

async def get_user_lock(user_id):
    uid = str(user_id)
    async with USER_LOCKS_GUARD:
        if uid not in USER_LOCKS:
            USER_LOCKS[uid] = asyncio.Lock()
        return USER_LOCKS[uid]

async def safe_edit_message_text(query, text, reply_markup=None, parse_mode=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Edit message error: {e}")

async def safe_answer_callback(query, text=None, show_alert=False):
    try:
        await query.answer(text=text, show_alert=show_alert)
    except Exception as e:
        if "Query is too old" not in str(e) and "query id is invalid" not in str(e):
            logger.warning(f"Answer callback error (ignored): {e}")

# ========== CHỐNG SPAM ==========
SPAM_DATA = {}

async def check_user_blocked(update, context):
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return False
    if user_id == ADMIN_ID:
        return False
    uid = str(user_id)
    if uid in DATA.get("banned", {}):
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🚫 Tuất đã bị cấm 😡 Vui lòng ib @jdaydichs để mở cam."
            )
        except Exception:
            pass
        return True
    current_time = time.time()
    spam_info = SPAM_DATA.get(uid, None)
    if spam_info is None:
        SPAM_DATA[uid] = {
            "count": 0,
            "window_start": current_time,
            "blocked_until": None,
            "notified_spam": False,
            "notified_unblock": True
        }
        spam_info = SPAM_DATA[uid]
    if spam_info["blocked_until"] and current_time < spam_info["blocked_until"]:
        return True
    if spam_info["blocked_until"] and current_time >= spam_info["blocked_until"]:
        if not spam_info["notified_unblock"]:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="😤 Mở rồi đó tuất spam nữa tao cấm 🔨"
                )
            except Exception:
                pass
            spam_info["notified_unblock"] = True
        spam_info["count"] = 0
        spam_info["window_start"] = current_time
        spam_info["blocked_until"] = None
        spam_info["notified_spam"] = False
    if current_time - spam_info["window_start"] > 60:
        spam_info["window_start"] = current_time
        spam_info["count"] = 1
    else:
        spam_info["count"] += 1
    if spam_info["count"] > 5:
        spam_info["blocked_until"] = current_time + 60
        if not spam_info["notified_spam"]:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text="😡 Mày tuất à spam lắm cấm 1p 🤬"
                )
            except Exception:
                pass
            spam_info["notified_spam"] = True
        return True
    return False

# ========== KEYBOARDS ==========
def join_group_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Tham gia nhóm", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ Đã tham gia - Verify", callback_data="verify_membership")]
    ])

def main_menu_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ Nhận máy cloud 6h", callback_data=f"get_cloud_machine:{user_id}")]
    ])

def trial_question_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có", callback_data=f"receive_trial_yes:{user_id}")],
        [InlineKeyboardButton("❌ Không", callback_data=f"receive_trial_no:{user_id}")]
    ])

def confirm_new_account_keyboard(user_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có, tạo tài khoản mới", callback_data=f"confirm_create_new:{user_id}")],
        [InlineKeyboardButton("❌ Từ chối", callback_data=f"cancel_create_new:{user_id}")]
    ])

# ========== HANDLERS ==========
async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    my_chat_member = update.my_chat_member
    if my_chat_member.new_chat_member.user.id == context.bot.id:
        chat = my_chat_member.chat
        if chat.type in ["group", "supergroup"]:
            chat_id = chat.id
            if my_chat_member.new_chat_member.status in ["member", "administrator"]:
                if chat_id not in GROUPS:
                    GROUPS.append(chat_id)
                    save_groups()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if await check_user_blocked(update, context):
        return
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id, user.username, user.first_name, user.last_name)

    is_member_group = await is_member(context, user_id)

    if update.effective_chat.type == "private":
        set_private_started(user_id)
        if not is_member_group:
            await update.message.reply_text(
                "🔒 Bạn cần tham gia nhóm để sử dụng bot:\n"
                f"👉 {GROUP_LINK}\n\n"
                "Sau khi tham gia, bấm nút Verify bên dưới.",
                reply_markup=join_group_keyboard()
            )
            return
        await update.message.reply_text(
            "🤖 BOT TẠO MÁY CLOUD UMO\n\n"
            "🔔 Dùng /tag để nhận thông báo khi có máy.\n"
            "🔕 Dùng /huytag để hủy thông báo khi có máy.\n"
            "Có lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_menu_keyboard(user_id)
        )
    else:
        if not has_private_started(user_id):
            await update.message.reply_text(
                f"👋 [{user.first_name}](tg://user?id={user_id}) vui lòng nhắn tin riêng với bot trước khi sử dụng.\n"
                f"👉 [Bấm vào đây để mở chat riêng với bot](https://t.me/{(await context.bot.get_me()).username})",
                parse_mode="Markdown"
            )
            return
        if not is_member_group:
            await update.message.reply_text(
                "🔒 Bạn cần tham gia nhóm để sử dụng bot:\n"
                f"👉 {GROUP_LINK}\n\n"
                "Sau khi tham gia, bấm nút Verify bên dưới.",
                reply_markup=join_group_keyboard()
            )
            return
        await update.message.reply_text(
            "✅ Bạn đã là thành viên nhóm. Sử dụng bot bình thường.\n"
            "🔔 Dùng /tag để nhận thông báo khi có máy.\n"
            "🔕 Dùng /huytag để hủy thông báo khi có máy.\n"
            "Có lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_menu_keyboard(user_id)
        )

async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback(query)
    if await check_user_blocked(update, context):
        return
    user = query.from_user
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    if await is_member(context, user.id):
        await safe_edit_message_text(
            query,
            "✅ Xác minh thành công! Bạn có thể sử dụng bot.\n"
            "Có lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_menu_keyboard(user.id)
        )
    else:
        await safe_edit_message_text(
            query,
            "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify lại.",
            reply_markup=join_group_keyboard()
        )

async def create_account_with_progress(context, query, user_id, user_mention):
    uid = str(user_id)
    loop = asyncio.get_running_loop()
    user_lock = await get_user_lock(user_id)

    if user_lock.locked():
        await safe_edit_message_text(query, "⚠️ Bạn đang có yêu cầu đang xử lý, vui lòng chờ.")
        return

    async with user_lock:
        if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") == "creating":
            await safe_edit_message_text(query, "⚠️ Bạn đang có yêu cầu đang xử lý, vui lòng chờ.")
            return

        if uid in PENDING:
            del PENDING[uid]
            save_pending()

        PENDING[uid] = {"chat_id": user_id, "status": "creating"}
        save_pending()

        try:
            await safe_edit_message_text(query, "⏳ Đang tạo email tạm...")
            email, mail_password, mail_token = await loop.run_in_executor(EXECUTOR, create_temp_mail)

            await safe_edit_message_text(query, "📧 Đang gửi mã xác minh...")
            cuid = str(uuid.uuid4()).replace("-", "")
            await loop.run_in_executor(EXECUTOR, send_verification_code, email, cuid)

            await safe_edit_message_text(query, "🔍 Đang chờ mã xác minh từ email...")
            code = await loop.run_in_executor(EXECUTOR, read_code_from_mail, mail_token)

            await safe_edit_message_text(query, "🔐 Đang đăng nhập...")
            cloud_user_id, cloud_token = await loop.run_in_executor(EXECUTOR, login_email_code, email, code, cuid)

            await safe_edit_message_text(query, "🔑 Đang đặt mật khẩu...")
            new_password = "aot" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
            await loop.run_in_executor(EXECUTOR, set_password_cloud, cloud_user_id, cloud_token, new_password, cuid)

            PENDING[uid] = {
                "email": email,
                "password": new_password,
                "cloud_user_id": cloud_user_id,
                "cloud_token": cloud_token,
                "cuid": cuid,
                "trial_received": False,
                "account_sent": False
            }
            save_pending()

            # Gửi thông tin tài khoản vào tin nhắn riêng
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 Tài khoản UMO Cloud của bạn đã được tạo thành công!\n\n"
                         f"📧 Email: {email}\n"
                         f"🔑 Mật khẩu: {new_password}\n\n"
                         f"Bạn có muốn lấy máy sẵn không?",
                    reply_markup=trial_question_keyboard(user_id)
                )
                PENDING[uid]["account_sent"] = True
                save_pending()
            except Exception as e:
                logger.error(f"Failed to send DM: {e}")

            # Cập nhật số lượng và gửi thông báo remaining (nếu lỗi cũng không ảnh hưởng)
            try:
                increment_user_account(user_id)
                LAST_ACCOUNT_CREATED[uid] = time.time()
                if user_id != ADMIN_ID:
                    accounts_today = DATA["users"].get(uid, {}).get("accounts_today", 0)
                    remaining = max(0, 4 - accounts_today)
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"📊 Hôm nay bạn còn {remaining}/4 lượt tạo tài khoản."
                    )
            except Exception as e:
                logger.error(f"Failed to update quota: {e}")

            # Thông báo kết quả phù hợp với loại chat
            if query.message.chat.type == "private":
                await safe_edit_message_text(
                    query,
                    "✅ Tài khoản đã được tạo thành công."
                )
            else:
                await safe_edit_message_text(
                    query,
                    "✅ Tài khoản mật khẩu đã được tạo. Vui lòng kiểm tra tin nhắn riêng của bot."
                )

        except Exception as e:
            logger.exception(f"Error creating account for {user_id}")
            await safe_edit_message_text(
                query,
                "❌ Lỗi trong quá trình tạo tài khoản.\n"
                "Vui lòng thử lại hoặc ib @jdaydichs"
            )
        finally:
            if PENDING.get(uid) and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") == "creating":
                del PENDING[uid]
                save_pending()

async def get_cloud_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback(query)
    user = query.from_user
    user_id = user.id

    data = query.data.split(":")
    if len(data) != 2 or int(data[1]) != user_id:
        await safe_answer_callback(query, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True)
        return

    if await check_user_blocked(update, context):
        return

    if not await is_member(context, user_id):
        await safe_edit_message_text(
            query,
            "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.",
            reply_markup=join_group_keyboard()
        )
        return

    uid = str(user_id)
    update_user_activity(user_id, user.username, user.first_name, user.last_name)

    # Kiểm tra xem có pending tài khoản chưa xử lý không (không phải trạng thái creating)
    if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") != "creating":
        pending_data = PENDING[uid]
        # Nếu đã nhận trial rồi thì xóa pending và cho tạo mới
        if pending_data.get("trial_received", False):
            del PENDING[uid]
            save_pending()
        else:
            # Thông báo xác nhận tạo tài khoản mới
            email = pending_data.get("email", "N/A")
            password = pending_data.get("password", "N/A")
            await safe_edit_message_text(
                query,
                f"⚠️ Bạn chưa nhận máy ở nick:\n"
                f"📧 Email: {email}\n"
                f"🔑 Mật khẩu: {password}\n\n"
                f"Bạn có muốn tiếp tục tạo tài khoản mới không?",
                reply_markup=confirm_new_account_keyboard(user_id)
            )
            return

    if user_id != ADMIN_ID:
        user_info = DATA["users"].get(uid, {})
        accounts_today = user_info.get("accounts_today", 0)
        if accounts_today >= 4:
            await safe_edit_message_text(
                query,
                "⛔ Bạn đã tạo đủ 4 tài khoản hôm nay. Vui lòng quay lại vào ngày mai."
            )
            return

    if not has_private_started(user_id):
        await safe_edit_message_text(
            query,
            f"⚠️ {user.mention_markdown()} vui lòng nhắn tin riêng với bot trước khi sử dụng.\n"
            f"👉 [Bấm vào đây để mở chat riêng với bot](https://t.me/{(await context.bot.get_me()).username})",
            parse_mode="Markdown"
        )
        return

    await create_account_with_progress(context, query, user_id, user.mention_markdown())

async def confirm_create_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback(query)
    user = query.from_user
    user_id = user.id

    data = query.data.split(":")
    if len(data) != 2 or int(data[1]) != user_id:
        await safe_answer_callback(query, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True)
        return

    if await check_user_blocked(update, context):
        return

    # Xóa pending cũ
    uid = str(user_id)
    if uid in PENDING:
        del PENDING[uid]
        save_pending()

    # Tiếp tục tạo tài khoản mới
    await safe_edit_message_text(query, "⏳ Đang bắt đầu tạo tài khoản mới...")
    await create_account_with_progress(context, query, user_id, user.mention_markdown())

async def cancel_create_new_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback(query)
    user = query.from_user
    user_id = user.id

    data = query.data.split(":")
    if len(data) != 2 or int(data[1]) != user_id:
        await safe_answer_callback(query, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True)
        return

    if await check_user_blocked(update, context):
        return

    uid = str(user_id)
    pending_data = PENDING.get(uid)
    if not pending_data or isinstance(pending_data, bool) or pending_data.get("status") == "creating":
        await safe_edit_message_text(query, "Phiên làm việc hết hạn, vui lòng /start lại.")
        return

    # Gửi lại thông tin tài khoản cũ và nút Có/Không
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🎉 Tài khoản UMO Cloud của bạn:\n\n"
                 f"📧 Email: {pending_data['email']}\n"
                 f"🔑 Mật khẩu: {pending_data['password']}\n\n"
                 f"Bạn có muốn lấy máy sẵn không?",
            reply_markup=trial_question_keyboard(user_id)
        )
    except Exception as e:
        logger.error(f"Failed to send account info: {e}")

    await safe_edit_message_text(
        query,
        "✅ Đã gửi lại thông tin tài khoản cũ. Bạn có thể chọn Có hoặc Không trong tin nhắn riêng."
    )

# ========== TAG ==========
def build_tag_mentions():
    """Tạo chuỗi mention HTML để tag người dùng."""
    tags = []
    for uid in DATA.get("tag_users", []):
        user_info = DATA["users"].get(str(uid), {})
        username = user_info.get("username")
        first_name = user_info.get("first_name") or "User"
        if username:
            tags.append(f"@{username}")
        else:
            # Sử dụng HTML tag an toàn
            tags.append(f'<a href="tg://user?id={uid}">{first_name}</a>')
    return " ".join(tags)

async def notify_all_groups(context, text):
    groups_to_notify = list(set(GROUPS))
    if GROUP_ID not in groups_to_notify:
        groups_to_notify.append(GROUP_ID)
    for gid in groups_to_notify:
        try:
            # Dùng parse_mode='HTML' để các tag hoạt động
            await context.bot.send_message(chat_id=gid, text=text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Failed to notify group {gid}: {e}")

async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if await check_user_blocked(update, context):
        return
    if not await is_member(context, update.effective_user.id):
        await update.message.reply_text(
            "🔒 Bạn cần tham gia nhóm để sử dụng bot:\n"
            f"👉 {GROUP_LINK}\n\n"
            "Sau khi tham gia, bấm nút Verify bên dưới.",
            reply_markup=join_group_keyboard()
        )
        return
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id, user.username, user.first_name, user.last_name)
    uid = str(user_id)
    if uid not in DATA["tag_users"]:
        DATA["tag_users"].append(uid)
        save_data()
        await update.message.reply_text("✅ Đã thêm bạn vào thông báo khi có máy.")
    else:
        await update.message.reply_text("⛔ Bạn đã đăng ký tag rồi.")

async def untag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if await check_user_blocked(update, context):
        return
    if not await is_member(context, update.effective_user.id):
        await update.message.reply_text(
            "🔒 Bạn cần tham gia nhóm để sử dụng bot:\n"
            f"👉 {GROUP_LINK}\n\n"
            "Sau khi tham gia, bấm nút Verify bên dưới.",
            reply_markup=join_group_keyboard()
        )
        return
    user = update.effective_user
    uid = str(user.id)
    if uid in DATA["tag_users"]:
        DATA["tag_users"].remove(uid)
        save_data()
        await update.message.reply_text("✅ Đã bỏ bạn khỏi thông báo khi có máy.")
    else:
        await update.message.reply_text("⛔ Bạn chưa đăng ký tag.")

async def receive_trial_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_CLOUD_STATUS
    query = update.callback_query
    await safe_answer_callback(query)
    user = query.from_user
    user_id = user.id

    data = query.data.split(":")
    if len(data) != 2 or int(data[1]) != user_id:
        await safe_answer_callback(query, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True)
        return

    if await check_user_blocked(update, context):
        return

    if not await is_member(context, user_id):
        await safe_edit_message_text(
            query,
            "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.",
            reply_markup=join_group_keyboard()
        )
        return

    uid = str(user_id)
    user_lock = await get_user_lock(user_id)
    async with user_lock:
        pending_data = PENDING.get(uid)
        if not pending_data or isinstance(pending_data, bool) or pending_data.get("status") == "creating":
            await safe_edit_message_text(query, "Phiên làm việc hết hạn, vui lòng /start lại.")
            return

        # Kiểm tra xem tài khoản đã nhận trial chưa
        if pending_data.get("trial_received", False):
            await safe_edit_message_text(
                query,
                "⛔ Nick này đã lấy máy trial rồi, vui lòng tạo tài khoản mới."
            )
            return

        await safe_edit_message_text(query, "⏳ Đang nhận máy trial, vui lòng chờ...")
        loop = asyncio.get_running_loop()
        try:
            ok, res = await loop.run_in_executor(
                EXECUTOR,
                lambda: receive_trial_cloud(
                    pending_data["cloud_user_id"],
                    pending_data["cloud_token"],
                    pending_data["cuid"]
                )
            )
            if ok:
                await safe_edit_message_text(
                    query,
                    "✅ Đã lấy máy trial thành công!\n"
                    "Bạn có thể đăng nhập vào UMO Cloud bằng tài khoản trên.\n"
                    "Nếu cần hỗ trợ, ib @jdaydichs"
                )
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"🎉 Tài khoản UMO Cloud của bạn:\n\n"
                             f"📧 Email: {pending_data['email']}\n"
                             f"🔑 Mật khẩu: {pending_data['password']}\n\n"
                             f"Bạn đã lấy máy trial thành công!"
                    )
                except Exception:
                    pass
                # Đánh dấu đã nhận trial
                pending_data["trial_received"] = True
                save_pending()

                # Gửi thông báo lên nhóm nếu trạng thái trước đó không phải available
                if LAST_CLOUD_STATUS != "available":
                    mentions = build_tag_mentions()
                    notify_text = "✅ Máy cloud đã có lại, mọi người nhận đi!"
                    if mentions:
                        notify_text += "\n" + mentions
                    await notify_all_groups(context, notify_text)
                    LAST_CLOUD_STATUS = "available"

                # Xóa pending sau khi hoàn tất
                if uid in PENDING:
                    del PENDING[uid]
                    save_pending()
            else:
                if isinstance(res, dict) and "all been claimed" in str(res.get("msg", "")):
                    if LAST_CLOUD_STATUS != "unavailable":
                        await notify_all_groups(context, "⛔ Máy cloud đã hết, vui lòng chờ.")
                        LAST_CLOUD_STATUS = "unavailable"
                    # Chỉ gửi tài khoản nếu chưa gửi lần nào
                    if not pending_data.get("account_sent", False):
                        try:
                            await context.bot.send_message(
                                chat_id=user_id,
                                text=f"📧 Email: {pending_data['email']}\n"
                                     f"🔑 Mật khẩu: {pending_data['password']}\n\n"
                                     f"Bạn có thể dùng tài khoản này để đăng nhập UMO Cloud."
                            )
                            pending_data["account_sent"] = True
                            save_pending()
                        except Exception:
                            pass

                    await safe_edit_message_text(
                        query,
                        "⛔ Máy cloud đã hết, bấm nút dưới để thử lại khi nào có máy.\n"
                        "Tài khoản của bạn đã được gửi trong tin nhắn riêng.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Thử lại", callback_data=f"receive_trial_yes:{user_id}")]
                        ])
                    )
                else:
                    await safe_edit_message_text(
                        query,
                        f"❌ Lấy máy trial thất bại: {res}\n"
                        "Vui lòng thử lại hoặc ib @jdaydichs"
                    )
        except Exception as e:
            logger.exception(f"Error receiving trial for {user_id}")
            await safe_edit_message_text(query, "❌ Lỗi khi nhận máy, vui lòng thử lại sau.")

async def receive_trial_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await safe_answer_callback(query)
    user = query.from_user
    user_id = user.id

    data = query.data.split(":")
    if len(data) != 2 or int(data[1]) != user_id:
        await safe_answer_callback(query, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True)
        return

    if await check_user_blocked(update, context):
        return

    uid = str(user_id)
    user_lock = await get_user_lock(user_id)
    async with user_lock:
        pending_data = PENDING.get(uid)
        if pending_data and not isinstance(pending_data, bool) and pending_data.get("status") != "creating":
            if not pending_data.get("account_sent", False):
                try:
                    await context.bot.send_message(
                        chat_id=user_id,
                        text=f"📧 Email: {pending_data['email']}\n"
                             f"🔑 Mật khẩu: {pending_data['password']}\n\n"
                             f"Bạn có thể dùng tài khoản này để đăng nhập UMO Cloud."
                    )
                    pending_data["account_sent"] = True
                    save_pending()
                except Exception:
                    pass

        if uid in PENDING:
            del PENDING[uid]
            save_pending()

    await safe_edit_message_text(
        query,
        "Đã hủy lấy máy sẵn. Bạn vẫn có thể dùng tài khoản để đăng nhập.\n"
        "Nếu cần hỗ trợ, ib @jdaydichs"
    )

# ========== ADMIN COMMANDS ==========
async def cam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    if not context.args:
        await update.message.reply_text("Sử dụng: /cam <id hoặc @username>")
        return
    target = context.args[0]
    user_id = None
    if target.startswith("@"):
        username = target[1:]
        for uid, info in DATA["users"].items():
            if info.get("username") == username:
                user_id = int(uid)
                break
        if not user_id:
            await update.message.reply_text("Không tìm thấy người dùng với username đó.")
            return
    else:
        try:
            user_id = int(target)
        except:
            await update.message.reply_text("ID không hợp lệ.")
            return
    DATA.setdefault("banned", {})[str(user_id)] = True
    save_data()
    await update.message.reply_text(f"✅ Đã cấm người dùng {user_id} sử dụng bot.")
    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="🚫 Tuất đã bị cấm 😡 Vui lòng ib @jdaydichs để mở cam."
        )
    except Exception:
        pass

async def mocam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    if not context.args:
        await update.message.reply_text("Sử dụng: /mocam <id>")
        return
    try:
        user_id = int(context.args[0])
    except:
        await update.message.reply_text("ID không hợp lệ.")
        return
    if str(user_id) in DATA.get("banned", {}):
        del DATA["banned"][str(user_id)]
        save_data()
        await update.message.reply_text(f"✅ Đã mở cam cho người dùng {user_id}.")
    else:
        await update.message.reply_text("Người dùng này không bị cấm.")

async def reset_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    today = get_vn_today()
    for uid, info in DATA["users"].items():
        info["accounts_today"] = 0
        info["last_account_date"] = None
    DATA["daily_counts"].pop(today, None)
    save_data()
    await update.message.reply_text("✅ Đã reset toàn bộ số tài khoản hôm nay về 0.")

async def thongtin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    users = DATA.get("users", {})
    if not users:
        await update.message.reply_text("Chưa có người dùng nào.")
        return
    text = "📋 THÔNG TIN NGƯỜI DÙNG\n\n"
    for uid, info in users.items():
        username = info.get("username") or "N/A"
        first_name = info.get("first_name") or "N/A"
        total_acc = info.get("total_accounts", 0)
        today_acc = info.get("accounts_today", 0)
        text += (
            f"👤 ID: {uid}\n"
            f"   • Username: @{username}\n"
            f"   • Tên: {first_name}\n"
            f"   • Tổng acc đã tạo: {total_acc}\n"
            f"   • Acc hôm nay: {today_acc}\n\n"
        )
    await update.message.reply_text(text)

async def kiemtra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    today = get_vn_today()
    daily = DATA.get("daily_counts", {}).get(today, {})
    total_today = daily.get("total", 0)
    by_user = daily.get("by_user", {})
    text = f"📊 THỐNG KÊ HÔM NAY ({today})\n"
    text += f"Tổng số acc đã tạo: {total_today}\n\n"
    if by_user:
        text += "Chi tiết theo người dùng:\n"
        for uid, count in by_user.items():
            user_info = DATA["users"].get(uid, {})
            username = user_info.get("username") or uid
            text += f"   • @{username} (ID: {uid}): {count} acc\n"
    else:
        text += "Chưa có ai tạo acc hôm nay."
    await update.message.reply_text(text)

async def thongbao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    if not context.args:
        await update.message.reply_text("Sử dụng: /thongbao <nội dung>")
        return
    message_text = ' '.join(context.args)
    users = DATA.get("users", {})
    if not users:
        await update.message.reply_text("Không có người dùng nào để gửi thông báo.")
        return
    success = 0
    fail = 0
    for uid in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 Thông báo từ Admin:\n{message_text}")
            success += 1
        except Exception as e:
            logger.error(f"Failed to send to {uid}: {e}")
            fail += 1
    await update.message.reply_text(f"Đã gửi thông báo đến {success} người dùng, thất bại {fail}.")

async def nhom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message:
        return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này.")
        return
    count = len(GROUPS)
    await update.message.reply_text(f"Bot hiện đang có mặt trong {count} nhóm.")
    if count > 0:
        ids = "\n".join([str(gid) for gid in GROUPS])
        await update.message.reply_text(f"Danh sách ID nhóm:\n{ids}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)
    try:
        if update and isinstance(update, Update) and update.effective_user:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"⚠️ Lỗi bot:\n{context.error}"
            )
    except Exception:
        pass

async def handle_pending_on_startup(app):
    if not PENDING:
        return
    for uid, data in list(PENDING.items()):
        if isinstance(data, dict) and data.get("status") != "creating":
            try:
                await app.bot.send_message(
                    chat_id=int(uid),
                    text=f"🎉 Tài khoản UMO Cloud của bạn:\n\n"
                         f"📧 Email: {data['email']}\n"
                         f"🔑 Mật khẩu: {data['password']}\n\n"
                         f"Bạn có muốn lấy máy sẵn không?",
                    reply_markup=trial_question_keyboard(int(uid))
                )
            except Exception:
                pass
        elif data is True or (isinstance(data, dict) and data.get("status") == "creating"):
            if uid in PENDING:
                del PENDING[uid]
            save_pending()
            try:
                await app.bot.send_message(
                    chat_id=int(uid),
                    text="⏳ Bot đang tạo bù tài khoản cho bạn..."
                )
            except Exception:
                continue
            try:
                loop = asyncio.get_event_loop()
                email, mail_password, mail_token = await loop.run_in_executor(EXECUTOR, create_temp_mail)
                cuid = str(uuid.uuid4()).replace("-", "")
                await loop.run_in_executor(EXECUTOR, send_verification_code, email, cuid)
                code = await loop.run_in_executor(EXECUTOR, read_code_from_mail, mail_token)
                cloud_user_id, cloud_token = await loop.run_in_executor(EXECUTOR, login_email_code, email, code, cuid)
                new_password = "aot" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
                await loop.run_in_executor(EXECUTOR, set_password_cloud, cloud_user_id, cloud_token, new_password, cuid)
                PENDING[uid] = {
                    "email": email,
                    "password": new_password,
                    "cloud_user_id": cloud_user_id,
                    "cloud_token": cloud_token,
                    "cuid": cuid,
                    "trial_received": False,
                    "account_sent": False
                }
                save_pending()
                await app.bot.send_message(
                    chat_id=int(uid),
                    text=f"🎉 Tài khoản UMO Cloud của bạn đã được tạo bù thành công!\n\n"
                         f"📧 Email: {email}\n"
                         f"🔑 Mật khẩu: {new_password}\n\n"
                         f"Bạn có muốn lấy máy sẵn không?",
                    reply_markup=trial_question_keyboard(int(uid))
                )
                increment_user_account(int(uid))
                LAST_ACCOUNT_CREATED[uid] = time.time()
            except Exception:
                try:
                    await app.bot.send_message(chat_id=int(uid), text="❌ Không thể tạo bù tài khoản. Vui lòng thử lại sau.")
                except Exception:
                    pass

def main():
    start_health_server()
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .concurrent_updates(True)
        .build()
    )
    app.add_error_handler(error_handler)

    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("thongtin", thongtin))
    app.add_handler(CommandHandler("kiemtra", kiemtra))
    app.add_handler(CommandHandler("thongbao", thongbao))
    app.add_handler(CommandHandler("nhom", nhom))
    app.add_handler(CommandHandler("cam", cam))
    app.add_handler(CommandHandler("mocam", mocam))
    app.add_handler(CommandHandler("resetacc", reset_accounts))
    app.add_handler(CommandHandler("tag", tag_command))
    app.add_handler(CommandHandler("untag", untag_command))
    app.add_handler(CommandHandler("huytag", untag_command))
    app.add_handler(CallbackQueryHandler(verify_callback, pattern="^verify_membership$"))
    app.add_handler(CallbackQueryHandler(get_cloud_machine, pattern="^get_cloud_machine:"))
    app.add_handler(CallbackQueryHandler(confirm_create_new_callback, pattern="^confirm_create_new:"))
    app.add_handler(CallbackQueryHandler(cancel_create_new_callback, pattern="^cancel_create_new:"))
    app.add_handler(CallbackQueryHandler(receive_trial_yes, pattern="^receive_trial_yes:"))
    app.add_handler(CallbackQueryHandler(receive_trial_no, pattern="^receive_trial_no:"))
    app.add_handler(MessageHandler(filters.TEXT, handle_regular_message))

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.create_task(handle_pending_on_startup(app))
        print("Bot đang chạy...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=0.5)
    finally:
        pass

if __name__ == "__main__":
    main()