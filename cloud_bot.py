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
import html
import threading
import requests
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor
from http.server import HTTPServer, BaseHTTPRequestHandler
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, MessageEntity
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, ChatMemberHandler, MessageHandler, filters

# ========== CẤU HÌNH ==========
BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not set")
ADMIN_ID = 7267437767
GROUP_ID = -1004318229096
GROUP_LINK = "https://t.me/cloudfreeaot"

JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY")
if not JSONBIN_API_KEY:
    raise ValueError("JSONBIN_API_KEY is not set")
USERS_BIN_ID = os.environ.get("USERS_BIN_ID", "6a9a2b51da38895dfe368386")
GROUPS_BIN_ID = os.environ.get("GROUPS_BIN_ID", "6a9a2babf5f4af5e2968148c")
PENDING_BIN_ID = os.environ.get("PENDING_BIN_ID", "6a9a2be2da38895dfe36851d")
JSONBIN_BASE = "https://api.jsonbin.io/v3/b"
MAX_LEN = 3500

HEADERS = {"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"}

def load_json_from_bin(bin_id):
    url = f"{JSONBIN_BASE}/{bin_id}/latest"
    for attempt in range(3):
        try:
            r = requests.get(url, headers=HEADERS, timeout=30)
            if r.status_code == 200:
                return r.json().get("record", {})
        except Exception:
            if attempt == 2:
                return None
            time.sleep(2)
    return None

def save_json_to_bin(bin_id, data):
    url = f"{JSONBIN_BASE}/{bin_id}"
    for attempt in range(3):
        try:
            r = requests.put(url, headers=HEADERS, json=data, timeout=30)
            if r.status_code == 200:
                return True
        except Exception:
            if attempt == 2:
                return False
            time.sleep(2)
    return False

# ========== DỮ LIỆU ==========
DATA = {"users": {}, "daily_counts": {}, "private_started": {}, "banned": {}, "tag_users": [], "last_cloud_status": None}
GROUPS = []
PENDING = {}
LAST_CLOUD_STATUS = None

tmp = load_json_from_bin(USERS_BIN_ID)
if isinstance(tmp, dict):
    DATA = tmp
    LAST_CLOUD_STATUS = tmp.get("last_cloud_status")

tmp_g = load_json_from_bin(GROUPS_BIN_ID)
if isinstance(tmp_g, list):
    GROUPS = tmp_g

tmp_p = load_json_from_bin(PENDING_BIN_ID)
if isinstance(tmp_p, dict):
    PENDING = tmp_p

if GROUP_ID not in GROUPS:
    GROUPS.append(GROUP_ID)
    save_json_to_bin(GROUPS_BIN_ID, GROUPS)

# Cache thành viên nhóm — tránh gọi getChatMember quá nhiều
GROUP_MEMBERS_CACHE = set()

# ========== UMO CLOUD ==========
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

def save_data():
    save_json_to_bin(USERS_BIN_ID, DATA)

def save_groups():
    save_json_to_bin(GROUPS_BIN_ID, GROUPS)

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
            "user_id": user_id, "username": username or "",
            "first_name": first_name or "", "last_name": last_name or "",
            "first_seen": now, "last_seen": now,
            "total_accounts": 0, "accounts_today": 0, "last_account_date": None
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
    if DATA["users"][uid].get("last_account_date") != today:
        DATA["users"][uid]["accounts_today"] = 0
        DATA["users"][uid]["last_account_date"] = today
    DATA["users"][uid]["total_accounts"] += 1
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

def ensure_account_today_reset(user_id):
    uid = str(user_id)
    today = get_vn_today()
    if uid in DATA["users"] and DATA["users"][uid].get("last_account_date") != today:
        DATA["users"][uid]["accounts_today"] = 0
        DATA["users"][uid]["last_account_date"] = today
        save_data()

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
    threading.Thread(target=server.serve_forever, daemon=True).start()

# ========== KIỂM TRA THÀNH VIÊN ==========
async def is_member(context, user_id):
    """Kiểm tra thành viên với cache và retry.
    - Nếu user trong cache → OK.
    - Nếu không, gọi getChatMember, retry 3 lần với delay 1.5s.
    - Nếu vẫn left nhưng user đã tương tác với bot → chấp nhận tạm.
    """
    uid = str(user_id)
    # Nếu user đã có trong cache thì OK luôn
    if uid in GROUP_MEMBERS_CACHE:
        return True

    # Thử gọi getChatMember 3 lần
    for attempt in range(3):
        try:
            member = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
            if member.status in ["member", "administrator", "creator", "restricted"]:
                GROUP_MEMBERS_CACHE.add(uid)
                return True
            # Nếu status là left/kicked, chờ 1.5s rồi thử lại (Telegram có độ trễ)
            if attempt < 2:
                await asyncio.sleep(1.5)
                continue
            # Lần cuối vẫn left — kiểm tra fallback
            # Nếu user đã từng nhắn private với bot (đã start bot), chấp nhận tạm
            if has_private_started(user_id):
                logger.warning(f"getChatMember returned {member.status} for {uid} but user has started bot. Accepting temporarily.")
                return True
            return False
        except Exception as e:
            logger.error(f"is_member error for {uid} (attempt {attempt+1}): {e}")
            if attempt < 2:
                await asyncio.sleep(1.5)
                continue
            # Nếu lỗi và user đã start bot → chấp nhận
            if has_private_started(user_id):
                return True
            return False
    return False

async def is_bot_admin(context, chat_id):
    try:
        b = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        return b.status == "administrator" and b.can_delete_messages
    except Exception:
        return False

async def is_bot_mention(context, chat_id, entity, message_text):
    if entity.type == MessageEntity.TEXT_MENTION:
        u = entity.user
        return u and u.is_bot and u.id != context.bot.id
    elif entity.type == MessageEntity.MENTION:
        username = message_text[entity.offset:entity.offset+entity.length].lstrip('@')
        try:
            chat = await context.bot.get_chat(f"@{username}")
            member = await context.bot.get_chat_member(chat_id=chat_id, user_id=chat.id)
            return member.user.is_bot and chat.id != context.bot.id
        except Exception:
            return False
    return False

TAG_WARNED = {}

async def handle_regular_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return
    user = update.effective_user
    if not user or user.id == ADMIN_ID:
        return
    if not message.entities:
        return
    has = False
    for entity in message.entities:
        if entity.type in [MessageEntity.MENTION, MessageEntity.TEXT_MENTION]:
            if await is_bot_mention(context, message.chat_id, entity, message.text):
                has = True
                break
    if not has:
        return
    if await is_bot_admin(context, message.chat_id):
        try:
            await message.delete()
        except Exception:
            pass
    now = time.time()
    if now - TAG_WARNED.get(user.id, 0) >= 3600:
        try:
            await context.bot.send_message(chat_id=message.chat_id, text="Tuất tag bot khác ăn cứt à 🚫")
            TAG_WARNED[user.id] = now
        except Exception:
            pass

# ========== WILLCLOUDS ==========
def java_url_encode(s):
    bs = str(s).encode('utf-8')
    out = []
    for b in bs:
        if b == 32: out.append('+')
        elif (48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122) or b in (45, 46, 95, 42): out.append(chr(b))
        else: out.append('%' + format(b, '02X'))
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
        "Accept": "*/*", "Accept-Language": "en-US",
        "Origin": "https://h5.willclouds.com", "Referer": "https://h5.willclouds.com/",
        "tenant-id": TENANT_ID, "client-brand-id": BRAND_ID, "timezone": "Asia/Saigon",
    }
    if token: h["Authorization"] = f"Bearer {token}"
    if content_type: h["Content-Type"] = "application/x-www-form-urlencoded"
    return h

def rsa_encrypt(data):
    key = RSA.import_key(PUBLIC_KEY)
    cipher = PKCS1_v1_5.new(key)
    return base64.b64encode(cipher.encrypt(data.encode('utf-8'))).decode('utf-8')

def create_temp_mail():
    headers = {"User-Agent": "Mozilla/5.0"}
    last_err = None
    for _ in range(3):
        try:
            r = requests.get("https://api.mail.tm/domains", timeout=15, headers=headers)
            domains = r.json().get("hydra:member", [])
            if not domains: raise Exception("No domain")
            domain = random.choice(domains)["domain"]
            email = f"{EMAIL_PREFIX}{''.join(random.choices(string.digits, k=4))}@{domain}"
            pw = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
            payload = {"address": email, "password": pw}
            requests.post("https://api.mail.tm/accounts", json=payload, timeout=15, headers={**headers, "Content-Type": "application/json"})
            r = requests.post("https://api.mail.tm/token", json=payload, timeout=15, headers={**headers, "Content-Type": "application/json"})
            token = r.json().get("token")
            if not token: raise Exception("No token")
            return email, pw, token
        except Exception as e:
            last_err = e
            time.sleep(2)
    raise Exception(f"Mail failed: {last_err}")

def read_code_from_mail(token, timeout=240):
    start = time.time()
    while time.time() - start < timeout:
        try:
            headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
            r = requests.get("https://api.mail.tm/messages", timeout=15, headers=headers)
            if r.status_code != 200:
                time.sleep(3); continue
            msgs = r.json().get("hydra:member", [])
            if msgs:
                msg = msgs[0]
                r2 = requests.get(f"https://api.mail.tm/messages/{msg['id']}", timeout=15, headers=headers)
                text = r2.json().get("text", "") or r2.json().get("html", "") if r2.status_code == 200 else msg.get("subject", "")
                codes = re.findall(r'\b\d{4,6}\b', text)
                if codes: return codes[0]
        except Exception:
            pass
        time.sleep(3)
    raise Exception("No OTP")

def req(method, url, **kwargs):
    for attempt in range(3):
        try:
            r = requests.request(method, url, **kwargs)
            if r.status_code == 200: return r
            if r.status_code in [500, 502, 503, 504]:
                time.sleep(2); continue
            return r
        except Exception:
            if attempt == 2: raise
            time.sleep(2)

def jres(r):
    try: return r.json()
    except: return {"code": -1}

def send_verification_code(email, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": "", "cid": CID, "chnl": CHANNEL,
            "cver": CVER, "locale": LOCALE, "clientType": CLIENT_TYPE, "scene": "1", "captcha": "",
            "account": email, "accountType": "mail"}
    sig, b = sign(data)
    h = make_headers(content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-api.willclouds.com/saas-api/cloud-client/auth/send-verification-code", data=b, headers=h, timeout=20)
    if jres(r).get("code") != 0: raise Exception("send verification failed")

def login_email_code(email, code, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": "", "cid": CID, "chnl": CHANNEL,
            "cver": CVER, "locale": LOCALE, "clientType": CLIENT_TYPE, "account": email,
            "loginType": "MAIL_CODE", "authContent": code}
    sig, b = sign(data)
    h = make_headers(content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-core.willclouds.com/saas-api/cloud-client/auth/login", data=b, headers=h, timeout=20)
    res = jres(r)
    if res.get("code") != 0: raise Exception("login failed")
    return res["data"]["userId"], res["data"]["token"]

def set_password_cloud(user_id, token, password, cuid):
    enc = rsa_encrypt(password)
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": str(user_id), "cid": CID,
            "chnl": CHANNEL, "cver": CVER, "locale": LOCALE, "clientType": CLIENT_TYPE, "password": enc}
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-core.willclouds.com/saas-api/cloud-client/user/set-member-password", data=b, headers=h, timeout=20)
    if jres(r).get("code") != 0: raise Exception("set password failed")

def receive_trial_cloud(user_id, token, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": str(user_id), "cid": CID,
            "chnl": CHANNEL, "cver": CVER, "locale": LOCALE, "clientType": CLIENT_TYPE}
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-api.willclouds.com/saas-api/cloud-client/user/receive-instance", data=b, headers=h, timeout=20)
    res = jres(r)
    return res.get("code") == 0, res

def login_password_cloud(email, password, cuid):
    enc = rsa_encrypt(password)
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": "", "cid": CID, "chnl": CHANNEL,
            "cver": CVER, "locale": LOCALE, "clientType": CLIENT_TYPE, "account": email,
            "loginType": "ACCOUNT_PASSWORD", "authContent": enc, "captcha": "", "p": password}
    sig, b = sign(data)
    h = make_headers(content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-core.willclouds.com/saas-api/cloud-client/auth/login", data=b, headers=h, timeout=20)
    res = jres(r)
    if res.get("code") == 0: return res["data"]["userId"], res["data"]["token"]
    raise Exception("relogin failed")

def check_login_cloud(user_id, token, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": str(user_id), "cid": CID,
            "chnl": CHANNEL, "cver": CVER, "locale": LOCALE, "clientType": CLIENT_TYPE}
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-api.willclouds.com/saas-api/cloud-client/user/get-experience-qual", data=b, headers=h, timeout=20)
    return jres(r)

# ========== LOCKS ==========
USER_LOCKS = {}
USER_LOCKS_GUARD = asyncio.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=50)
LAST_ACCOUNT_CREATED = {}

async def get_user_lock(user_id):
    uid = str(user_id)
    async with USER_LOCKS_GUARD:
        if uid not in USER_LOCKS:
            USER_LOCKS[uid] = asyncio.Lock()
        return USER_LOCKS[uid]

async def safe_edit(query, text, reply_markup=None, parse_mode=None):
    try:
        await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "Message is not modified" not in str(e):
            logger.error(f"Edit err: {e}")

async def safe_ans(query, text=None, show_alert=False):
    try:
        await query.answer(text=text, show_alert=show_alert)
    except Exception as e:
        if "Query is too old" not in str(e) and "query id is invalid" not in str(e):
            logger.warning(f"Ans err: {e}")

async def send_long(context, chat_id, text):
    if len(text) <= MAX_LEN:
        try:
            await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            logger.error(f"Send err: {e}")
        return
    lines = text.split("\n")
    chunk = ""
    for line in lines:
        if len(chunk) + len(line) + 1 > MAX_LEN:
            try:
                await context.bot.send_message(chat_id=chat_id, text=chunk)
            except Exception as e:
                logger.error(f"Send chunk err: {e}")
            chunk = line + "\n"
        else:
            chunk += line + "\n"
    if chunk.strip():
        try:
            await context.bot.send_message(chat_id=chat_id, text=chunk)
        except Exception as e:
            logger.error(f"Send last err: {e}")

# ========== SPAM ==========
SPAM_DATA = {}

async def check_user_blocked(update, context):
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id: return False
    if user_id == ADMIN_ID: return False
    uid = str(user_id)
    if uid in DATA.get("banned", {}):
        try:
            await context.bot.send_message(chat_id=user_id, text="🚫 Tuất đã bị cấm 😡 Vui lòng ib @jdaydichs để mở cam.")
        except Exception: pass
        return True
    now = time.time()
    info = SPAM_DATA.get(uid)
    if info is None:
        SPAM_DATA[uid] = {"count": 0, "window_start": now, "blocked_until": None,
                          "notified_spam": False, "notified_unblock": True}
        info = SPAM_DATA[uid]
    if info["blocked_until"] and now < info["blocked_until"]:
        return True
    if info["blocked_until"] and now >= info["blocked_until"]:
        if not info["notified_unblock"]:
            try:
                await context.bot.send_message(chat_id=user_id, text="😤 Mở rồi đó tuất spam nữa tao cấm 🔨")
            except Exception: pass
            info["notified_unblock"] = True
        info["count"] = 0
        info["window_start"] = now
        info["blocked_until"] = None
        info["notified_spam"] = False
    if now - info["window_start"] > 60:
        info["window_start"] = now
        info["count"] = 1
    else:
        info["count"] += 1
    if info["count"] > 5:
        info["blocked_until"] = now + 60
        if not info["notified_spam"]:
            try:
                await context.bot.send_message(chat_id=user_id, text="😡 Mày tuất à spam lắm cấm 1p 🤬")
            except Exception: pass
            info["notified_spam"] = True
        return True
    return False

# ========== KEYBOARDS ==========
def join_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Tham gia nhóm", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ Đã tham gia - Verify", callback_data="verify_membership")]
    ])

def main_kb(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🖥️ Nhận máy cloud 6h", callback_data=f"get_cloud_machine:{uid}")]
    ])

def trial_kb(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có", callback_data=f"receive_trial_yes:{uid}")],
        [InlineKeyboardButton("❌ Không", callback_data=f"receive_trial_no:{uid}")]
    ])

def confirm_new_kb(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có, tạo mới", callback_data=f"confirm_create_new:{uid}")],
        [InlineKeyboardButton("❌ Từ chối", callback_data=f"cancel_create_new:{uid}")]
    ])

async def send_acc_info(context, user_id, email, password, is_received=False):
    status = "Bạn đã lấy máy trial thành công!" if is_received else "Bạn có muốn lấy máy sẵn không?"
    text = f"🎉 Tài khoản UMO Cloud của bạn:\n\n📧 Email: {email}\n🔑 Mật khẩu: {password}\n\n{status}"
    markup = None if is_received else trial_kb(user_id)
    try:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=markup)
        return True
    except Exception as e:
        logger.error(f"Send acc err: {e}")
        return False

# ========== HANDLERS ==========
async def my_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Xử lý khi bot được thêm/xóa khỏi nhóm."""
    m = update.my_chat_member
    if m.new_chat_member.user.id == context.bot.id:
        chat = m.chat
        if chat.type in ["group", "supergroup"]:
            cid = chat.id
            if m.new_chat_member.status in ["member", "administrator"]:
                if cid not in GROUPS:
                    GROUPS.append(cid); save_groups()
            elif m.new_chat_member.status in ["left", "kicked"]:
                if cid in GROUPS:
                    GROUPS.remove(cid); save_groups()

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cache thành viên: khi user join thì thêm vào cache, khi rời thì xóa."""
    cm = update.chat_member
    if cm.chat.id != GROUP_ID:
        return
    uid = str(cm.new_chat_member.user.id)
    old_status = cm.old_chat_member.status
    new_status = cm.new_chat_member.status

    # User vừa join / được thêm vào nhóm
    if new_status in ["member", "administrator", "creator", "restricted"] and old_status in ["left", "kicked"]:
        GROUP_MEMBERS_CACHE.add(uid)
        logger.info(f"User {uid} joined group, added to cache")

    # User rời / bị kick
    if new_status in ["left", "kicked"] and old_status not in ["left", "kicked"]:
        GROUP_MEMBERS_CACHE.discard(uid)
        logger.info(f"User {uid} left group, removed from cache")
        # Xóa khỏi tag_users nếu có
        if uid in DATA["tag_users"]:
            DATA["tag_users"].remove(uid)
            save_data()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if await check_user_blocked(update, context): return
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id, user.username, user.first_name, user.last_name)

    # Thêm user vào cache nếu họ đang ở trong nhóm
    uid = str(user_id)

    is_mem = await is_member(context, user_id)

    pd = PENDING.get(uid)
    if pd and isinstance(pd, dict) and pd.get("status") != "creating":
        if update.effective_chat.type == "private":
            await update.message.reply_text(
                f"🎉 Tài khoản UMO Cloud của bạn:\n\n📧 Email: {pd['email']}\n🔑 Mật khẩu: {pd['password']}\n\nBạn có muốn lấy máy sẵn không?",
                reply_markup=trial_kb(user_id))
        else:
            try:
                await send_acc_info(context, user_id, pd['email'], pd['password'])
            except Exception: pass
            await update.message.reply_text("⚠️ Bạn đang có tài khoản chưa nhận máy. Vui lòng kiểm tra tin nhắn riêng với bot.")
        return

    if update.effective_chat.type == "private":
        set_private_started(user_id)
        if not is_mem:
            await update.message.reply_text(
                f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.",
                reply_markup=join_kb()); return
        await update.message.reply_text(
            "🤖 BOT TẠO MÁY CLOUD UMO\n\n🔔 Dùng /tag để nhận thông báo khi có máy.\n🔕 Dùng /huytag để hủy thông báo khi có máy.\nCó lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_kb(user_id))
    else:
        if not has_private_started(user_id):
            await update.message.reply_text(
                f"👋 [{user.first_name}](tg://user?id={user_id}) vui lòng nhắn tin riêng với bot trước khi sử dụng.\n👉 [Bấm vào đây để mở chat riêng với bot](https://t.me/{(await context.bot.get_me()).username})",
                parse_mode="Markdown"); return
        if not is_mem:
            await update.message.reply_text(
                f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.",
                reply_markup=join_kb()); return
        await update.message.reply_text(
            "✅ Bạn đã là thành viên nhóm. Sử dụng bot bình thường.\n🔔 Dùng /tag để nhận thông báo khi có máy.\n🔕 Dùng /huytag để hủy thông báo khi có máy.\nCó lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_kb(user_id))

async def verify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    if await check_user_blocked(update, context): return
    user = q.from_user
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    # Kiểm tra lại thành viên (có retry)
    if await is_member(context, user.id):
        await safe_edit(q, "✅ Xác minh thành công! Bạn có thể sử dụng bot.\nCó lỗi gì cần fix ib @jdaydichs", reply_markup=main_kb(user.id))
    else:
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify lại.", reply_markup=join_kb())

async def create_acc_progress(context, query, user_id, user_mention):
    uid = str(user_id)
    loop = asyncio.get_running_loop()
    lock = await get_user_lock(user_id)
    if lock.locked():
        await safe_edit(query, "⚠️ Bạn đang có yêu cầu đang xử lý, vui lòng chờ.")
        return
    async with lock:
        if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") == "creating":
            await safe_edit(query, "⚠️ Bạn đang có yêu cầu đang xử lý, vui lòng chờ.")
            return
        if uid in PENDING:
            del PENDING[uid]
        PENDING[uid] = {"chat_id": user_id, "status": "creating"}
        save_pending()
        email = None
        try:
            await safe_edit(query, "⏳ Đang tạo email tạm...")
            email, mpw, mtoken = await loop.run_in_executor(EXECUTOR, create_temp_mail)
            await safe_edit(query, "📧 Đang gửi mã xác minh...")
            cuid = str(uuid.uuid4()).replace("-", "")
            await loop.run_in_executor(EXECUTOR, send_verification_code, email, cuid)
            await safe_edit(query, "🔍 Đang chờ mã xác minh...")
            code = await loop.run_in_executor(EXECUTOR, read_code_from_mail, mtoken)
            await safe_edit(query, "🔐 Đang đăng nhập...")
            cid, ctok = await loop.run_in_executor(EXECUTOR, login_email_code, email, code, cuid)
            await safe_edit(query, "🔑 Đang đặt mật khẩu...")
            npw = "aot" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
            await loop.run_in_executor(EXECUTOR, set_password_cloud, cid, ctok, npw, cuid)
            PENDING[uid] = {"email": email, "password": npw, "cloud_user_id": cid, "cloud_token": ctok, "cuid": cuid,
                            "trial_received": False, "account_sent": False, "trial_fail_sent": False}
            save_pending()
            sent = await send_acc_info(context, user_id, email, npw)
            if sent:
                PENDING[uid]["account_sent"] = True
                save_pending()
            try:
                increment_user_account(user_id)
                LAST_ACCOUNT_CREATED[uid] = time.time()
                if user_id != ADMIN_ID:
                    at = DATA["users"].get(uid, {}).get("accounts_today", 0)
                    rem = max(0, 4 - at)
                    await context.bot.send_message(chat_id=user_id, text=f"📊 Hôm nay bạn còn {rem}/4 lượt tạo tài khoản.")
            except Exception as e:
                logger.error(f"Quota err: {e}")
            if query.message.chat.type == "private":
                await safe_edit(query, "✅ Tài khoản đã được tạo thành công.")
            else:
                await safe_edit(query, "✅ Tài khoản mật khẩu đã được tạo. Vui lòng kiểm tra tin nhắn riêng của bot.")
        except Exception as e:
            logger.exception(f"Create acc err for {user_id}: {e}")
            em = str(e)
            if "send verification failed" in em: um = "❌ Gửi mã xác minh thất bại. Vui lòng thử lại."
            elif "login failed" in em: um = "❌ Đăng nhập UMO Cloud thất bại. Vui lòng thử lại."
            elif "No OTP" in em or "Không nhận" in em: um = "❌ Chưa nhận được mã xác minh. Vui lòng thử lại."
            elif "set password failed" in em: um = "❌ Đặt mật khẩu thất bại. Vui lòng thử lại."
            elif "Mail failed" in em: um = "❌ Không tạo được email tạm. Vui lòng thử lại."
            else: um = "❌ Lỗi không xác định. Vui lòng ib @jdaydichs."
            await safe_edit(query, um)
        finally:
            if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") == "creating":
                del PENDING[uid]
                save_pending()

async def get_cloud_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "get_cloud_machine":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    try:
        target = int(data[1])
    except ValueError:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if target != user_id:
        await safe_ans(q, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True); return
    if await check_user_blocked(update, context): return
    if not await is_member(context, user_id):
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.", reply_markup=join_kb()); return
    uid = str(user_id)
    update_user_activity(user_id, user.username, user.first_name, user.last_name)
    ensure_account_today_reset(user_id)
    if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") != "creating":
        pd = PENDING[uid]
        if pd.get("trial_received", False):
            del PENDING[uid]; save_pending()
        else:
            try:
                await send_acc_info(context, user_id, pd['email'], pd['password'])
            except Exception: pass
            await safe_edit(q, "⚠️ Bạn đang có tài khoản chưa nhận máy. Vui lòng kiểm tra tin nhắn riêng với bot.")
            return
    if user_id != ADMIN_ID:
        ui = DATA["users"].get(uid, {})
        if ui.get("accounts_today", 0) >= 4:
            await safe_edit(q, "⛔ Bạn đã tạo đủ 4 tài khoản hôm nay. Vui lòng quay lại vào ngày mai.")
            return
    if not has_private_started(user_id):
        await safe_edit(q, f"⚠️ {user.mention_markdown()} vui lòng nhắn tin riêng với bot trước khi sử dụng.\n👉 [Bấm vào đây](https://t.me/{(await context.bot.get_me()).username})", parse_mode="Markdown")
        return
    await create_acc_progress(context, q, user_id, user.mention_markdown())

async def confirm_create_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "confirm_create_new":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    try:
        target = int(data[1])
    except ValueError:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if target != user_id:
        await safe_ans(q, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True); return
    if await check_user_blocked(update, context): return
    if not await is_member(context, user_id):
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.", reply_markup=join_kb()); return
    uid = str(user_id)
    if uid in PENDING:
        del PENDING[uid]; save_pending()
    await safe_edit(q, "⏳ Đang bắt đầu tạo tài khoản mới...")
    await create_acc_progress(context, q, user_id, user.mention_markdown())

async def cancel_create_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "cancel_create_new":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    try:
        target = int(data[1])
    except ValueError:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if target != user_id:
        await safe_ans(q, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True); return
    if await check_user_blocked(update, context): return
    uid = str(user_id)
    pd = PENDING.get(uid)
    if not pd or isinstance(pd, bool) or pd.get("status") == "creating":
        await safe_edit(q, "Phiên làm việc hết hạn, vui lòng /start lại."); return
    try:
        await send_acc_info(context, user_id, pd['email'], pd['password'])
    except Exception as e:
        logger.error(f"Send acc err: {e}")
    await safe_edit(q, "✅ Đã gửi lại thông tin tài khoản cũ. Bạn có thể chọn Có hoặc Không trong tin nhắn riêng.")

def build_tags():
    tags = []
    for uid in DATA.get("tag_users", []):
        ui = DATA["users"].get(str(uid), {})
        un = ui.get("username")
        fn = ui.get("first_name") or "User"
        if un:
            tags.append(f"@{html.escape(un)}")
        else:
            tags.append(f'<a href="tg://user?id={uid}">{html.escape(fn)}</a>')
    return " ".join(tags)

async def notify_all_groups(context, text):
    groups = list(set(GROUPS))
    if GROUP_ID not in groups:
        groups.append(GROUP_ID)
    for gid in groups:
        try:
            await context.bot.send_message(chat_id=gid, text=text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Notify group err {gid}: {e}")
            try:
                plain = re.sub(r'<[^>]+>', '', text)
                await context.bot.send_message(chat_id=gid, text=plain)
            except Exception as e2:
                logger.error(f"Fallback notify err: {e2}")

async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if await check_user_blocked(update, context): return
    if not await is_member(context, update.effective_user.id):
        await update.message.reply_text(f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.", reply_markup=join_kb()); return
    user = update.effective_user
    uid = str(user.id)
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    if uid not in DATA["tag_users"]:
        DATA["tag_users"].append(uid); save_data()
        await update.message.reply_text("✅ Đã thêm bạn vào thông báo khi có máy.")
    else:
        await update.message.reply_text("⛔ Bạn đã đăng ký tag rồi.")

async def untag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if await check_user_blocked(update, context): return
    if not await is_member(context, update.effective_user.id):
        await update.message.reply_text(f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.", reply_markup=join_kb()); return
    uid = str(update.effective_user.id)
    if uid in DATA["tag_users"]:
        DATA["tag_users"].remove(uid); save_data()
        await update.message.reply_text("✅ Đã bỏ bạn khỏi thông báo khi có máy.")
    else:
        await update.message.reply_text("⛔ Bạn chưa đăng ký tag.")

async def receive_trial_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_CLOUD_STATUS
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "receive_trial_yes":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    try:
        target = int(data[1])
    except ValueError:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if target != user_id:
        await safe_ans(q, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True); return
    if await check_user_blocked(update, context): return
    if not await is_member(context, user_id):
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.", reply_markup=join_kb()); return
    uid = str(user_id)
    lock = await get_user_lock(user_id)
    async with lock:
        pd = PENDING.get(uid)
        if not pd or isinstance(pd, bool) or pd.get("status") == "creating":
            await safe_edit(q, "Phiên làm việc hết hạn, vui lòng /start lại."); return
        if pd.get("trial_received", False):
            await safe_edit(q, "⛔ Nick này đã lấy máy trial rồi, vui lòng tạo tài khoản mới."); return
        await safe_edit(q, "⏳ Đang nhận máy trial, vui lòng chờ...")
        loop = asyncio.get_running_loop()
        try:
            cid = pd["cloud_user_id"]
            ctok = pd["cloud_token"]
            cuid = pd["cuid"]
            chk = await loop.run_in_executor(EXECUTOR, lambda: check_login_cloud(cid, ctok, cuid))
            if chk.get("code") == 1000000008:
                await safe_edit(q, "🔐 Token hết hạn, đang đăng nhập lại...")
                nu, nt = await loop.run_in_executor(EXECUTOR, login_password_cloud, pd["email"], pd["password"], cuid)
                pd["cloud_user_id"] = nu; pd["cloud_token"] = nt
                save_pending()
                cid, ctok = nu, nt
            ok, res = await loop.run_in_executor(EXECUTOR, lambda: receive_trial_cloud(cid, ctok, cuid))
            if ok:
                await safe_edit(q, "✅ Đã lấy máy trial thành công!\nBạn có thể đăng nhập vào UMO Cloud bằng tài khoản trên.\nNếu cần hỗ trợ, ib @jdaydichs")
                try:
                    await send_acc_info(context, user_id, pd['email'], pd['password'], is_received=True)
                except Exception: pass
                pd["trial_received"] = True
                save_pending()
                if LAST_CLOUD_STATUS != "available":
                    tags = build_tags()
                    txt = "✅ <b>Máy cloud đã có lại, mọi người nhận đi!</b>"
                    if tags: txt += "\n" + tags
                    await notify_all_groups(context, txt)
                    LAST_CLOUD_STATUS = "available"
                    DATA["last_cloud_status"] = LAST_CLOUD_STATUS
                    save_data()
                if uid in PENDING:
                    del PENDING[uid]; save_pending()
            else:
                if isinstance(res, dict) and ("not eligible" in str(res.get("msg", "")) or res.get("code") == 1003000071):
                    try:
                        await send_acc_info(context, user_id, pd['email'], pd['password'])
                    except Exception: pass
                    await safe_edit(q, "⛔ Nick này không đủ điều kiện nhận máy.\nVui lòng tạo tài khoản mới.")
                    if uid in PENDING:
                        del PENDING[uid]; save_pending()
                elif isinstance(res, dict) and "all been claimed" in str(res.get("msg", "")):
                    if LAST_CLOUD_STATUS != "unavailable":
                        await notify_all_groups(context, "⛔ <b>Máy cloud đã hết, vui lòng chờ.</b>")
                        LAST_CLOUD_STATUS = "unavailable"
                        DATA["last_cloud_status"] = LAST_CLOUD_STATUS
                        save_data()
                    if not pd.get("trial_fail_sent", False):
                        try:
                            await send_acc_info(context, user_id, pd['email'], pd['password'])
                            pd["trial_fail_sent"] = True
                            save_pending()
                        except Exception: pass
                    await safe_edit(q, "⛔ Máy cloud đã hết, bấm nút dưới để thử lại khi nào có máy.\nTài khoản của bạn đã được gửi trong tin nhắn riêng.",
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Thử lại", callback_data=f"receive_trial_yes:{user_id}")]]))
                else:
                    await safe_edit(q, f"❌ Lấy máy trial thất bại: {res}\nVui lòng thử lại hoặc ib @jdaydichs")
        except Exception as e:
            logger.exception(f"Trial err for {user_id}")
            await safe_edit(q, "❌ Lỗi khi nhận máy, vui lòng thử lại sau.")

async def receive_trial_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "receive_trial_no":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    try:
        target = int(data[1])
    except ValueError:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if target != user_id:
        await safe_ans(q, "⛔ Bạn không thể bấm nút của người khác!", show_alert=True); return
    if await check_user_blocked(update, context): return
    uid = str(user_id)
    lock = await get_user_lock(user_id)
    async with lock:
        pd = PENDING.get(uid)
        if pd and not isinstance(pd, bool) and pd.get("status") != "creating":
            try:
                await send_acc_info(context, user_id, pd['email'], pd['password'])
            except Exception: pass
        if uid in PENDING:
            del PENDING[uid]; save_pending()
    await safe_edit(q, "Đã hủy lấy máy sẵn. Bạn vẫn có thể dùng tài khoản để đăng nhập.\nNếu cần hỗ trợ, ib @jdaydichs")

# ========== ADMIN ==========
async def cam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    if not context.args:
        await update.message.reply_text("Sử dụng: /cam <id hoặc @username>"); return
    target = context.args[0]
    user_id = None
    if target.startswith("@"):
        un = target[1:]
        for uid, info in DATA["users"].items():
            if info.get("username") == un:
                user_id = int(uid); break
        if not user_id:
            await update.message.reply_text("Không tìm thấy người dùng với username đó."); return
    else:
        try:
            user_id = int(target)
        except:
            await update.message.reply_text("ID không hợp lệ."); return
    DATA.setdefault("banned", {})[str(user_id)] = True
    save_data()
    await update.message.reply_text(f"✅ Đã cấm người dùng {user_id} sử dụng bot.")
    try:
        await context.bot.send_message(chat_id=user_id, text="🚫 Tuất đã bị cấm 😡 Vui lòng ib @jdaydichs để mở cam.")
    except Exception: pass

async def mocam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    if not context.args:
        await update.message.reply_text("Sử dụng: /mocam <id>"); return
    try:
        user_id = int(context.args[0])
    except:
        await update.message.reply_text("ID không hợp lệ."); return
    if str(user_id) in DATA.get("banned", {}):
        del DATA["banned"][str(user_id)]; save_data()
        await update.message.reply_text(f"✅ Đã mở cam cho người dùng {user_id}.")
    else:
        await update.message.reply_text("Người dùng này không bị cấm.")

async def reset_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    today = get_vn_today()
    for uid, info in DATA["users"].items():
        info["accounts_today"] = 0
        info["last_account_date"] = None
    DATA["daily_counts"].pop(today, None)
    save_data()
    await update.message.reply_text("✅ Đã reset toàn bộ số tài khoản hôm nay về 0.")

async def thongtin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    users = DATA.get("users", {})
    if not users:
        await update.message.reply_text("Chưa có người dùng nào."); return
    sorted_users = sorted(users.items(), key=lambda x: x[1].get("total_accounts", 0), reverse=True)
    total = len(sorted_users)
    header = "📋 THÔNG TIN NGƯỜI DÙNG\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    footer = f"\n━━━━━━━━━━━━━━━━━━━━━\n📊 Tổng: {total} người dùng"
    chunks = []
    current = header
    for uid, info in sorted_users:
        un = info.get("username")
        fn = info.get("first_name") or "Không tên"
        ta = info.get("total_accounts", 0)
        display = f"@{un}" if un else fn
        entry = f"👤 {display}\n   🆔 ID: {uid}\n   📦 Tổng acc: {ta}\n\n"
        if len(current) + len(entry) > MAX_LEN:
            chunks.append(current); current = entry
        else:
            current += entry
    if len(current) + len(footer) > MAX_LEN:
        chunks.append(current); current = footer
    else:
        current += footer
    if current.strip(): chunks.append(current)
    for c in chunks:
        try:
            await update.message.reply_text(c)
        except Exception as e:
            logger.error(f"Send info err: {e}")

async def kiemtra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    today = get_vn_today()
    daily = DATA.get("daily_counts", {}).get(today, {})
    total_today = daily.get("total", 0)
    by_user = daily.get("by_user", {})
    header = f"📊 THỐNG KÊ NGÀY {today}\n━━━━━━━━━━━━━━━━━━━━━\n🎯 Tổng acc đã tạo: {total_today}\n\n"
    footer = "\n━━━━━━━━━━━━━━━━━━━━━"
    chunks = []
    current = header
    if by_user:
        sorted_bu = sorted(by_user.items(), key=lambda x: x[1], reverse=True)
        for uid, cnt in sorted_bu:
            ui = DATA["users"].get(uid, {})
            un = ui.get("username")
            fn = ui.get("first_name") or "Không tên"
            display = f"@{un}" if un else fn
            entry = f"• {display} → {cnt} acc\n"
            if len(current) + len(entry) > MAX_LEN:
                chunks.append(current); current = entry
            else:
                current += entry
    else:
        current += "Chưa có ai tạo acc hôm nay."
    if len(current) + len(footer) > MAX_LEN:
        chunks.append(current); current = footer
    else:
        current += footer
    if current.strip(): chunks.append(current)
    for c in chunks:
        try:
            await update.message.reply_text(c)
        except Exception as e:
            logger.error(f"Send stats err: {e}")

async def thongbao(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    if not context.args:
        await update.message.reply_text("Sử dụng: /thongbao <nội dung>"); return
    msg = ' '.join(context.args)
    users = DATA.get("users", {})
    if not users:
        await update.message.reply_text("Không có người dùng nào để gửi thông báo."); return
    s = f = 0
    for uid in users.keys():
        try:
            await context.bot.send_message(chat_id=int(uid), text=f"📢 Thông báo từ Admin:\n{msg}")
            s += 1
        except Exception as e:
            logger.error(f"Send to {uid} err: {e}")
            f += 1
    await update.message.reply_text(f"Đã gửi tới {s} người dùng, thất bại {f}.")

async def nhom(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    count = len(GROUPS)
    await update.message.reply_text(f"Bot hiện đang có mặt trong {count} nhóm.")
    if count > 0:
        ids = "\n".join([str(g) for g in GROUPS])
        await send_long(context, update.effective_chat.id, f"Danh sách ID nhóm:\n{ids}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)
    try:
        if update and isinstance(update, Update) and update.effective_user:
            await context.bot.send_message(chat_id=ADMIN_ID, text=f"⚠️ Lỗi bot:\n{context.error}")
    except Exception: pass

async def handle_pending_on_startup(app):
    if not PENDING: return
    for uid, data in list(PENDING.items()):
        if uid == "_dirty": continue
        if isinstance(data, dict) and data.get("status") != "creating":
            try:
                await app.bot.send_message(chat_id=int(uid),
                    text=f"🎉 Tài khoản UMO Cloud của bạn:\n\n📧 Email: {data['email']}\n🔑 Mật khẩu: {data['password']}\n\nBạn có muốn lấy máy sẵn không?",
                    reply_markup=trial_kb(int(uid)))
            except Exception: pass
        elif data is True or (isinstance(data, dict) and data.get("status") == "creating"):
            if uid in PENDING:
                del PENDING[uid]
            save_pending()
            try:
                await app.bot.send_message(chat_id=int(uid), text="⏳ Bot đang tạo bù tài khoản cho bạn...")
            except Exception:
                continue
            try:
                loop = asyncio.get_event_loop()
                email, mpw, mtoken = await loop.run_in_executor(EXECUTOR, create_temp_mail)
                cuid = str(uuid.uuid4()).replace("-", "")
                await loop.run_in_executor(EXECUTOR, send_verification_code, email, cuid)
                code = await loop.run_in_executor(EXECUTOR, read_code_from_mail, mtoken)
                cid, ctok = await loop.run_in_executor(EXECUTOR, login_email_code, email, code, cuid)
                npw = "aot" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
                await loop.run_in_executor(EXECUTOR, set_password_cloud, cid, ctok, npw, cuid)
                PENDING[uid] = {"email": email, "password": npw, "cloud_user_id": cid, "cloud_token": ctok,
                                "cuid": cuid, "trial_received": False, "account_sent": False, "trial_fail_sent": False}
                save_pending()
                sent = await send_acc_info(app, int(uid), email, npw)
                if sent:
                    PENDING[uid]["account_sent"] = True
                    save_pending()
                try:
                    increment_user_account(int(uid))
                    LAST_ACCOUNT_CREATED[uid] = time.time()
                except Exception: pass
            except Exception:
                try:
                    await app.bot.send_message(chat_id=int(uid), text="❌ Không thể tạo bù tài khoản. Vui lòng thử lại sau.")
                except Exception: pass

async def backup_task():
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(60)
        try:
            await loop.run_in_executor(EXECUTOR, save_data)
        except Exception as e:
            logger.error(f"Backup err: {e}")

async def cleanup_spam_task():
    while True:
        await asyncio.sleep(600)
        now = time.time()
        expired = [uid for uid, info in SPAM_DATA.items()
                   if (info.get("blocked_until") and now >= info["blocked_until"]) or
                      (not info.get("blocked_until") and now - info.get("window_start", 0) > 120)]
        for uid in expired:
            del SPAM_DATA[uid]

def main():
    start_health_server()
    app = Application.builder().token(BOT_TOKEN).connect_timeout(30).read_timeout(30).write_timeout(30).concurrent_updates(True).build()
    app.add_error_handler(error_handler)
    app.add_handler(ChatMemberHandler(my_chat_member_update, ChatMemberHandler.MY_CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(chat_member_update, ChatMemberHandler.CHAT_MEMBER))
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
    app.add_handler(CallbackQueryHandler(verify_cb, pattern="^verify_membership$"))
    app.add_handler(CallbackQueryHandler(get_cloud_machine, pattern="^get_cloud_machine:"))
    app.add_handler(CallbackQueryHandler(confirm_create_new, pattern="^confirm_create_new:"))
    app.add_handler(CallbackQueryHandler(cancel_create_new, pattern="^cancel_create_new:"))
    app.add_handler(CallbackQueryHandler(receive_trial_yes, pattern="^receive_trial_yes:"))
    app.add_handler(CallbackQueryHandler(receive_trial_no, pattern="^receive_trial_no:"))
    app.add_handler(MessageHandler(filters.TEXT, handle_regular_message))
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.create_task(handle_pending_on_startup(app))
        loop.create_task(backup_task())
        loop.create_task(cleanup_spam_task())
        print("Bot đang chạy...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=0.5)
    finally:
        pass

if __name__ == "__main__":
    main()
