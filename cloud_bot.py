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
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, ContextTypes,
    ChatMemberHandler, MessageHandler, filters
)

# ==================================================================
# CẤU HÌNH
# ==================================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8988947106:AAENyrSzL0dWbeJD9GjiLaZN10VF6Fzgvms")
ADMIN_ID = 7267437767
GROUP_ID = -1004318229096
GROUP_LINK = "https://t.me/cloudfreeaot"
GROUP_USERNAME = "@cloudfreeaot"

JSONBIN_API_KEY = os.environ.get("JSONBIN_API_KEY", "$2a$10$ZKItx9kCcaQktuLuBDKY1ewYhT2gy3OWH.w7nkeTLWUy9sCxtjVWO")
USERS_BIN_ID = os.environ.get("USERS_BIN_ID", "6a9a2b51da38895dfe368386")
GROUPS_BIN_ID = os.environ.get("GROUPS_BIN_ID", "6a9a2babf5f4af5e2968148c")
PENDING_BIN_ID = os.environ.get("PENDING_BIN_ID", "6a9a2be2da38895dfe36851d")
JSONBIN_BASE = "https://api.jsonbin.io/v3/b"
MAX_LEN = 3500
LOCAL_CACHE_FILE = os.environ.get("LOCAL_CACHE_FILE", "bot_cache.json")

# ==================================================================
# CLOUDFLARE WORKER PROXY
# ==================================================================
CF_WORKER_URL = os.environ.get("CF_WORKER_URL", "https://um-proxy.hahuytien19.workers.dev").strip()
UMO_HOSTS = ["oem-api.willclouds.com", "oem-core.willclouds.com"]

def _route_through_worker(url):
    if not CF_WORKER_URL:
        return url
    for host in UMO_HOSTS:
        prefix = f"https://{host}/"
        if prefix in url:
            path = url.replace(prefix, "", 1)
            return f"{CF_WORKER_URL}/proxy/{host}/{path}"
    return url

# ==================================================================
# GITHUB BACKUP CONFIG (token chỉ lấy từ env)
# ==================================================================
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.environ.get("GITHUB_REPO", "khonoilam/umo-data").strip()
GITHUB_API = "https://api.github.com"

# ==================================================================
# LOGGING
# ==================================================================
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram._bot").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)

# ==================================================================
# JSONBIN + LOCAL + GITHUB
# ==================================================================
BIN_HEADERS = {"X-Master-Key": JSONBIN_API_KEY, "Content-Type": "application/json"}

def bin_load(bin_id):
    url = f"{JSONBIN_BASE}/{bin_id}/latest"
    for attempt in range(2):
        try:
            r = requests.get(url, headers=BIN_HEADERS, timeout=15)
            if r.status_code == 200:
                return r.json().get("record")
        except Exception as e:
            logger.warning(f"bin_load {bin_id} err: {e}")
        if attempt < 1: time.sleep(1)
    return None

def bin_save(bin_id, data):
    url = f"{JSONBIN_BASE}/{bin_id}"
    try:
        r = requests.put(url, headers=BIN_HEADERS, json=data, timeout=15)
        if r.status_code == 200:
            return True
    except Exception as e:
        logger.warning(f"bin_save {bin_id} err: {e}")
    return False

def _load_local_cache():
    try:
        if os.path.exists(LOCAL_CACHE_FILE):
            with open(LOCAL_CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Local cache load err: {e}")
    return {}

def _save_local_cache():
    try:
        with open(LOCAL_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump({"users": DATA, "groups": GROUPS, "pending": PENDING, "ts": time.time()},
                      f, ensure_ascii=False)
        return True
    except Exception as e:
        logger.warning(f"Local cache save err: {e}")
        return False

def github_load():
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return None
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/data.json"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}", "Accept": "application/vnd.github+json"}
    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code != 200:
            logger.warning(f"github_load status={r.status_code}")
            return None
        content_b64 = r.json().get("content", "").replace("\n", "")
        parsed = json.loads(base64.b64decode(content_b64).decode("utf-8"))
        logger.info("✓ GitHub load OK")
        return parsed
    except Exception as e:
        logger.warning(f"github_load err: {e}")
        return None

_GH_SHA = {"current": None}

def github_save(payload):
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return False
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/data.json"
    headers = {"Authorization": f"Bearer {GITHUB_TOKEN}",
               "Accept": "application/vnd.github+json",
               "Content-Type": "application/json"}
    if not _GH_SHA["current"]:
        try:
            r = requests.get(url, headers=headers, timeout=15)
            if r.status_code == 200:
                _GH_SHA["current"] = r.json().get("sha")
        except Exception: pass
    content_b64 = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode("utf-8")).decode("utf-8")
    body = {"message": f"backup {int(time.time())}", "content": content_b64}
    if _GH_SHA["current"]:
        body["sha"] = _GH_SHA["current"]
    try:
        r = requests.put(url, headers=headers, json=body, timeout=20)
        if r.status_code in [200, 201]:
            _GH_SHA["current"] = r.json().get("content", {}).get("sha") or _GH_SHA["current"]
            logger.info("✓ GitHub save OK")
            return True
        elif r.status_code == 409:
            _GH_SHA["current"] = None
        else:
            logger.warning(f"github_save status={r.status_code} body={r.text[:200]}")
    except Exception as e:
        logger.warning(f"github_save err: {e}")
    return False

# ==================================================================
# DỮ LIỆU TOÀN CỤC
# ==================================================================
DATA = {"users": {}, "daily_counts": {}, "private_started": {}, "banned": {}, "tag_users": [], "last_cloud_status": None}
GROUPS = []
PENDING = {}
LAST_CLOUD_STATUS = None
GROUP_MEMBERS_CACHE = set()

def _restore_keys(d):
    if not isinstance(d, dict): return d
    d.setdefault("users", {})
    d.setdefault("daily_counts", {})
    d.setdefault("private_started", {})
    d.setdefault("banned", {})
    d.setdefault("tag_users", [])
    d.setdefault("last_cloud_status", None)
    return d

# Tầng 1: local cache
_cached = _load_local_cache()
if isinstance(_cached.get("users"), dict) and _cached["users"]:
    DATA = _restore_keys(_cached["users"])
    if isinstance(_cached.get("groups"), list): GROUPS = _cached["groups"]
    if isinstance(_cached.get("pending"), dict): PENDING = _cached["pending"]
    logger.info(f"✓ Local load OK ({len(DATA.get('users', {}))} users)")

# Tầng 2: GitHub
if not DATA.get("users"):
    _gh = github_load()
    if isinstance(_gh, dict) and _gh.get("users"):
        DATA = _restore_keys(_gh["users"])
        if isinstance(_gh.get("groups"), list): GROUPS = _gh["groups"]
        if isinstance(_gh.get("pending"), dict): PENDING = _gh["pending"]
        _save_local_cache()
        logger.info(f"✓ GitHub load OK ({len(DATA.get('users', {}))} users)")

# Tầng 3: JSONBin
if not DATA.get("users"):
    _tmp = bin_load(USERS_BIN_ID)
    if isinstance(_tmp, dict) and _tmp.get("users"):
        DATA = _restore_keys(_tmp)
        logger.info(f"✓ JSONBin load OK ({len(DATA.get('users', {}))} users)")

LAST_CLOUD_STATUS = DATA.get("last_cloud_status")

if not GROUPS:
    _tmp_g = bin_load(GROUPS_BIN_ID)
    if isinstance(_tmp_g, list) and _tmp_g: GROUPS = _tmp_g

if not PENDING:
    _tmp_p = bin_load(PENDING_BIN_ID)
    if isinstance(_tmp_p, dict): PENDING = _tmp_p

if GROUP_ID not in GROUPS:
    GROUPS.append(GROUP_ID)

if not CF_WORKER_URL:
    logger.warning("⚠️ CF_WORKER_URL chưa set")
else:
    logger.info(f"✓ CF_WORKER_URL = {CF_WORKER_URL}")

if GITHUB_TOKEN and GITHUB_REPO:
    logger.info(f"✓ GitHub backup: {GITHUB_REPO}")
else:
    logger.warning("⚠️ GITHUB_TOKEN/GITHUB_REPO chưa set — backup GitHub tắt")

# ==================================================================
# SAVE SYSTEM
# ==================================================================
_SAVE_LOCK = threading.Lock()
_IO_LOCK = threading.Lock()
_SAVE_DIRTY = {"users": False, "groups": False, "pending": False}
_LAST_GH_PUSH = 0
GH_PUSH_INTERVAL = 300

def _flush_users_now():
    with _IO_LOCK:
        if not DATA.get("users"):
            logger.warning("Skip flush users — rỗng")
            return
        local_ok = _save_local_cache()
        if not local_ok:
            bin_save(USERS_BIN_ID, DATA)

def _flush_groups_now():
    with _IO_LOCK:
        try: bin_save(GROUPS_BIN_ID, GROUPS)
        except Exception as e: logger.error(f"flush groups err: {e}")

def _flush_pending_now():
    with _IO_LOCK:
        _save_local_cache()

def save_data(force=False):
    with _SAVE_LOCK: _SAVE_DIRTY["users"] = True
    if force: _flush_users_now()

def save_groups(force=False):
    with _SAVE_LOCK: _SAVE_DIRTY["groups"] = True
    if force: _flush_groups_now()

def save_pending(force=False):
    with _SAVE_LOCK: _SAVE_DIRTY["pending"] = True
    if force: _flush_pending_now()

def _flush_all_if_dirty():
    global _LAST_GH_PUSH
    with _SAVE_LOCK:
        u, g, p = _SAVE_DIRTY["users"], _SAVE_DIRTY["groups"], _SAVE_DIRTY["pending"]
        _SAVE_DIRTY["users"] = False
        _SAVE_DIRTY["groups"] = False
        _SAVE_DIRTY["pending"] = False
    _save_local_cache()
    if u: _flush_users_now()
    if g: _flush_groups_now()
    if p: _flush_pending_now()
    now = time.time()
    if (u or g or p) and (now - _LAST_GH_PUSH >= GH_PUSH_INTERVAL):
        payload = {"users": DATA, "groups": GROUPS, "pending": PENDING, "ts": now}
        if github_save(payload):
            _LAST_GH_PUSH = now

def _flush_github_force():
    payload = {"users": DATA, "groups": GROUPS, "pending": PENDING, "ts": time.time()}
    return github_save(payload)

# ==================================================================
# UMO CLOUD CONFIG
# ==================================================================
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

# ==================================================================
# HELPERS
# ==================================================================
def vn_now(): return datetime.now(timezone(timedelta(hours=7)))
def vn_today(): return vn_now().strftime("%Y-%m-%d")

def safe_int(v, default=None):
    try: return int(v)
    except Exception: return default

def update_user_activity(user_id, username=None, first_name=None, last_name=None):
    now = vn_now().strftime("%Y-%m-%d %H:%M:%S")
    uid = str(user_id)
    if uid not in DATA["users"]:
        DATA["users"][uid] = {
            "user_id": user_id, "username": username or "", "first_name": first_name or "",
            "last_name": last_name or "", "first_seen": now, "last_seen": now,
            "total_accounts": 0, "accounts_today": 0, "last_account_date": None
        }
    else:
        u = DATA["users"][uid]
        u["last_seen"] = now
        if username: u["username"] = username
        if first_name: u["first_name"] = first_name
        if last_name: u["last_name"] = last_name
    save_data()

def increment_user_account(user_id):
    today = vn_today()
    uid = str(user_id)
    if uid not in DATA["users"]: update_user_activity(user_id)
    u = DATA["users"][uid]
    if u.get("last_account_date") != today:
        u["accounts_today"] = 0
        u["last_account_date"] = today
    u["total_accounts"] = u.get("total_accounts", 0) + 1
    u["accounts_today"] = u.get("accounts_today", 0) + 1
    dc = DATA["daily_counts"].setdefault(today, {"total": 0, "by_user": {}})
    dc["total"] += 1
    dc["by_user"][uid] = dc["by_user"].get(uid, 0) + 1
    save_data()

def ensure_account_reset(user_id):
    uid = str(user_id)
    today = vn_today()
    if uid in DATA["users"]:
        if DATA["users"][uid].get("last_account_date") != today:
            DATA["users"][uid]["accounts_today"] = 0
            DATA["users"][uid]["last_account_date"] = today
            save_data()

def set_private_started(user_id):
    uid = str(user_id)
    if "private_started" not in DATA: DATA["private_started"] = {}
    if DATA["private_started"].get(uid): return
    DATA["private_started"][uid] = True
    save_data(force=True)

def has_private_started(user_id):
    return str(user_id) in DATA.get("private_started", {})

# ==================================================================
# HEALTH SERVER
# ==================================================================
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header("Content-Type", "text/plain"); self.end_headers()
        self.wfile.write(b"OK")
    def do_HEAD(self):
        self.send_response(200); self.end_headers()
    def log_message(self, format, *args): pass

def start_health_server():
    port = safe_int(os.environ.get("PORT", 8000), 8000)
    srv = HTTPServer(("0.0.0.0", port), HealthHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

# ==================================================================
# KIỂM TRA THÀNH VIÊN
# ==================================================================
async def is_member(context, user_id):
    uid = str(user_id)
    if uid in GROUP_MEMBERS_CACHE: return True
    for attempt in range(2):
        try:
            m = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=user_id)
            if m.status in ["member", "administrator", "creator", "restricted"]:
                GROUP_MEMBERS_CACHE.add(uid); return True
            if attempt < 1:
                await asyncio.sleep(0.6); continue
            return has_private_started(user_id)
        except Exception as e:
            logger.warning(f"is_member err {uid}: {e}")
            if attempt < 1:
                await asyncio.sleep(0.6); continue
            return has_private_started(user_id)
    return False

async def is_bot_admin(context, chat_id):
    try:
        b = await context.bot.get_chat_member(chat_id=chat_id, user_id=context.bot.id)
        return b.status == "administrator" and b.can_delete_messages
    except Exception: return False

# ==================================================================
# BOT TAG DETECTION
# ==================================================================
async def is_bot_mention(context, chat_id, entity, text):
    if entity.type == MessageEntity.TEXT_MENTION:
        u = entity.user
        return u and u.is_bot and u.id != context.bot.id
    if entity.type == MessageEntity.MENTION:
        username = text[entity.offset:entity.offset + entity.length].lstrip('@')
        try:
            chat = await context.bot.get_chat(f"@{username}")
            mem = await context.bot.get_chat_member(chat_id=chat_id, user_id=chat.id)
            return mem.user.is_bot and chat.id != context.bot.id
        except Exception: return False
    return False

TAG_WARNED = {}

async def handle_regular_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message: return
    user = update.effective_user
    if not user or user.id == ADMIN_ID: return
    if message.chat.type == "private":
        set_private_started(user.id); return
    if not message.text or not message.entities: return
    has = False
    for ent in message.entities:
        if ent.type in [MessageEntity.MENTION, MessageEntity.TEXT_MENTION]:
            if await is_bot_mention(context, message.chat_id, ent, message.text):
                has = True; break
    if not has: return
    if await is_bot_admin(context, message.chat_id):
        try: await message.delete()
        except Exception: pass
    now = time.time()
    if now - TAG_WARNED.get(user.id, 0) >= 3600:
        try:
            await context.bot.send_message(chat_id=message.chat_id, text="Tuất tag bot khác ăn cứt à 🚫")
            TAG_WARNED[user.id] = now
        except Exception: pass

# ==================================================================
# WILLCLOUDS
# ==================================================================
def java_url_encode(s):
    bs = str(s).encode('utf-8'); out = []
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
        "User-Agent": "Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Mobile Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
        "Origin": "https://h5.willclouds.com",
        "Referer": "https://h5.willclouds.com/",
        "tenant-id": TENANT_ID,
        "client-brand-id": BRAND_ID,
        "timezone": "Asia/Saigon",
        "Connection": "keep-alive",
    }
    if token: h["Authorization"] = f"Bearer {token}"
    if content_type: h["Content-Type"] = "application/x-www-form-urlencoded"
    return h

def rsa_encrypt(data):
    key = RSA.import_key(PUBLIC_KEY)
    cipher = PKCS1_v1_5.new(key)
    return base64.b64encode(cipher.encrypt(data.encode('utf-8'))).decode('utf-8')

# ---- Mail providers ----
def _mail_provider_mailtm():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get("https://api.mail.tm/domains", timeout=15, headers=headers)
    domains = r.json().get("hydra:member", [])
    if not domains: raise Exception("No domain")
    domain = random.choice(domains)["domain"]
    email = f"{EMAIL_PREFIX}{''.join(random.choices(string.digits, k=6))}@{domain}"
    pw = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    payload = {"address": email, "password": pw}
    requests.post("https://api.mail.tm/accounts", json=payload, timeout=15,
                  headers={**headers, "Content-Type": "application/json"})
    r = requests.post("https://api.mail.tm/token", json=payload, timeout=15,
                      headers={**headers, "Content-Type": "application/json"})
    token = r.json().get("token")
    if not token: raise Exception("No token")
    return email, pw, token, "https://api.mail.tm"

def _mail_provider_mailgw():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get("https://api.mail.gw/domains", timeout=15, headers=headers)
    domains = r.json().get("hydra:member", [])
    if not domains: raise Exception("No domain")
    domain = random.choice(domains)["domain"]
    email = f"{EMAIL_PREFIX}{''.join(random.choices(string.digits, k=6))}@{domain}"
    pw = ''.join(random.choices(string.ascii_letters + string.digits, k=12))
    payload = {"address": email, "password": pw}
    requests.post("https://api.mail.gw/accounts", json=payload, timeout=15,
                  headers={**headers, "Content-Type": "application/json"})
    r = requests.post("https://api.mail.gw/token", json=payload, timeout=15,
                      headers={**headers, "Content-Type": "application/json"})
    token = r.json().get("token")
    if not token: raise Exception("No token")
    return email, pw, token, "https://api.mail.gw"

def _mail_provider_1secmail():
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get("https://www.1secmail.com/api/v1/?action=getDomainList", timeout=15, headers=headers)
    domains = r.json()
    if not domains: raise Exception("No domain")
    domain = random.choice(domains)
    login = f"{EMAIL_PREFIX}{''.join(random.choices(string.digits, k=6))}"
    email = f"{login}@{domain}"
    return email, "", f"{login}|{domain}", "https://www.1secmail.com/api/v1"

def _mail_provider_tempmail_lol():
    headers = {"User-Agent": "Mozilla/5.0", "Content-Type": "application/json"}
    r = requests.post("https://api.tempmail.lol/v2/inbox/create", json={}, timeout=15, headers=headers)
    data = r.json()
    email = data.get("address")
    token = data.get("token")
    if not email or not token: raise Exception("tempmail.lol bad response")
    return email, "", token, "https://api.tempmail.lol"

def create_temp_mail():
    providers = [_mail_provider_mailtm, _mail_provider_mailgw,
                 _mail_provider_1secmail, _mail_provider_tempmail_lol]
    random.shuffle(providers)
    last_err = None
    for fn in providers:
        try: return fn()
        except Exception as e:
            last_err = e
            logger.warning(f"mail provider {fn.__name__} err: {e}")
            time.sleep(0.5)
    raise Exception(f"Mail failed: {last_err}")

def _read_code_once(token, base_url):
    try:
        if "1secmail" in base_url:
            login, domain = token.split("|", 1)
            r = requests.get(
                f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}",
                timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            msgs = r.json()
            if msgs:
                mid = msgs[0]["id"]
                r2 = requests.get(
                    f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={mid}",
                    timeout=15, headers={"User-Agent": "Mozilla/5.0"})
                txt = r2.json().get("textBody", "") or r2.json().get("htmlBody", "")
                codes = re.findall(r'\b\d{4,6}\b', txt)
                if codes: return codes[0]
            return None

        if "tempmail.lol" in base_url:
            r = requests.get(f"https://api.tempmail.lol/v2/inbox?token={token}",
                             timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            data = r.json()
            emails = data.get("emails", [])
            if emails:
                txt = emails[0].get("body", "") or emails[0].get("html", "")
                codes = re.findall(r'\b\d{4,6}\b', txt)
                if codes: return codes[0]
            return None

        headers = {"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0"}
        r = requests.get(f"{base_url}/messages", timeout=15, headers=headers)
        if r.status_code != 200:
            return None
        msgs = r.json().get("hydra:member", [])
        if msgs:
            msg = msgs[0]
            r2 = requests.get(f"{base_url}/messages/{msg['id']}", timeout=15, headers=headers)
            if r2.status_code == 200:
                txt = r2.json().get("text", "") or r2.json().get("html", "")
            else:
                txt = msg.get("subject", "")
            codes = re.findall(r'\b\d{4,6}\b', txt)
            if codes: return codes[0]
        return None
    except Exception:
        return None

async def read_code_from_mail_async(loop, token, timeout=90, base_url="https://api.mail.tm", status_cb=None):
    start = time.time()
    last_update = 0
    while time.time() - start < timeout:
        elapsed = int(time.time() - start)
        if status_cb and elapsed - last_update >= 15:
            last_update = elapsed
            try:
                await status_cb(elapsed, timeout)
            except Exception:
                pass
        try:
            code = await loop.run_in_executor(EXECUTOR, _read_code_once, token, base_url)
            if code:
                return code
        except Exception as e:
            logger.warning(f"read_code err: {e}")
        await asyncio.sleep(3)
    raise Exception("No OTP")

def req(method, url, **kwargs):
    final_url = _route_through_worker(url)
    if final_url != url:
        logger.info(f"[REQ] routed via worker: {final_url[:120]}")
    kwargs.setdefault("timeout", 20)
    last_exc = None
    for attempt in range(3):
        try:
            r = requests.request(method, final_url, **kwargs)
            logger.info(f"[REQ] {method} {url} → {r.status_code} (attempt {attempt+1})")
            if r.status_code == 200: return r
            if r.status_code in [403, 429]:
                if attempt < 2: time.sleep(3); continue
                return r
            if r.status_code in [500, 502, 503, 504]:
                time.sleep(2); continue
            return r
        except Exception as e:
            last_exc = e
            logger.warning(f"[REQ] {method} {url} err (attempt {attempt+1}): {e}")
            if attempt == 2:
                raise Exception(f"Network failed: {type(last_exc).__name__}: {last_exc}")
            time.sleep(2)

def jres(r):
    if r is None:
        return {"code": -1, "_err": "response is None"}
    try: return r.json()
    except Exception:
        body = (r.text or "")[:300]
        logger.error(f"jres fail — status={r.status_code} body={body!r}")
        return {"code": -1, "_status": r.status_code, "_body": body}

def send_verification_code(email, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": "",
            "cid": CID, "chnl": CHANNEL, "cver": CVER, "locale": LOCALE,
            "clientType": CLIENT_TYPE, "scene": "1", "captcha": "",
            "account": email, "accountType": "mail"}
    sig, b = sign(data)
    h = make_headers(content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-api.willclouds.com/saas-api/cloud-client/auth/send-verification-code",
            data=b, headers=h)
    _res = jres(r)
    if _res.get("code") != 0:
        raise Exception(f"send verification failed: code={_res.get('code')} msg={_res.get('msg')} status={_res.get('_status', r.status_code if r else 'None')}")

def login_email_code(email, code, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": "",
            "cid": CID, "chnl": CHANNEL, "cver": CVER, "locale": LOCALE,
            "clientType": CLIENT_TYPE, "account": email,
            "loginType": "MAIL_CODE", "authContent": code}
    sig, b = sign(data)
    h = make_headers(content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-core.willclouds.com/saas-api/cloud-client/auth/login", data=b, headers=h)
    res = jres(r)
    if res.get("code") != 0: raise Exception(f"login failed: code={res.get('code')} msg={res.get('msg')}")
    return res["data"]["userId"], res["data"]["token"]

def set_password_cloud(user_id, token, password, cuid):
    enc = rsa_encrypt(password)
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": str(user_id),
            "cid": CID, "chnl": CHANNEL, "cver": CVER, "locale": LOCALE,
            "clientType": CLIENT_TYPE, "password": enc}
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-core.willclouds.com/saas-api/cloud-client/user/set-member-password", data=b, headers=h)
    res = jres(r)
    if res.get("code") != 0: raise Exception(f"set password failed: code={res.get('code')} msg={res.get('msg')}")

def receive_trial_cloud(user_id, token, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": str(user_id),
            "cid": CID, "chnl": CHANNEL, "cver": CVER, "locale": LOCALE,
            "clientType": CLIENT_TYPE}
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-api.willclouds.com/saas-api/cloud-client/user/receive-instance", data=b, headers=h)
    res = jres(r)
    return res.get("code") == 0, res

def login_password_cloud(email, password, cuid):
    enc = rsa_encrypt(password)
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": "",
            "cid": CID, "chnl": CHANNEL, "cver": CVER, "locale": LOCALE,
            "clientType": CLIENT_TYPE, "account": email,
            "loginType": "ACCOUNT_PASSWORD", "authContent": enc, "captcha": "", "p": password}
    sig, b = sign(data)
    h = make_headers(content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-core.willclouds.com/saas-api/cloud-client/auth/login", data=b, headers=h)
    res = jres(r)
    if res.get("code") == 0:
        return res["data"]["userId"], res["data"]["token"]
    raise Exception(f"relogin failed: code={res.get('code')}")

def check_login_cloud(user_id, token, cuid):
    data = {"cuid": cuid, "ts": str(int(time.time()*1000)), "userId": str(user_id),
            "cid": CID, "chnl": CHANNEL, "cver": CVER, "locale": LOCALE,
            "clientType": CLIENT_TYPE}
    sig, b = sign(data)
    h = make_headers(token=token, content_type=True); h["x-signature"] = sig
    r = req("POST", "https://oem-api.willclouds.com/saas-api/cloud-client/user/get-experience-qual", data=b, headers=h)
    return jres(r)

# ==================================================================
# LOCKS + COOLDOWN
# ==================================================================
USER_LOCKS = {}
USER_LOCKS_GUARD = asyncio.Lock()
EXECUTOR = ThreadPoolExecutor(max_workers=80)
LAST_ACCOUNT_CREATED = {}
GLOBAL_RATE_LIMIT_UNTIL = 0
USER_COOLDOWN = {}
COOLDOWN_SECONDS = 90
GLOBAL_LIMIT_BACKOFF = 300

async def get_lock(user_id):
    uid = str(user_id)
    async with USER_LOCKS_GUARD:
        if uid not in USER_LOCKS: USER_LOCKS[uid] = asyncio.Lock()
        return USER_LOCKS[uid]

async def safe_edit(query, text, reply_markup=None, parse_mode=None):
    try: await query.edit_message_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception as e:
        if "Message is not modified" not in str(e): logger.warning(f"Edit err: {e}")

async def safe_ans(query, text=None, show_alert=False):
    try: await query.answer(text=text, show_alert=show_alert)
    except Exception as e:
        if "Query is too old" not in str(e) and "query id is invalid" not in str(e): logger.warning(f"Ans err: {e}")

async def send_long(context, chat_id, text):
    if len(text) <= MAX_LEN:
        try: await context.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e: logger.error(f"Send err: {e}")
        return
    buf = ""
    for line in text.split("\n"):
        if len(buf) + len(line) + 1 > MAX_LEN:
            try: await context.bot.send_message(chat_id=chat_id, text=buf)
            except Exception as e: logger.error(f"Send chunk err: {e}")
            buf = line + "\n"
        else: buf += line + "\n"
    if buf.strip():
        try: await context.bot.send_message(chat_id=chat_id, text=buf)
        except Exception as e: logger.error(f"Send last err: {e}")

# ==================================================================
# CHỐNG SPAM
# ==================================================================
SPAM_DATA = {}

async def check_user_blocked(update, context):
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id: return False
    if user_id == ADMIN_ID: return False
    uid = str(user_id)
    if uid in DATA.get("banned", {}):
        try: await context.bot.send_message(chat_id=user_id, text="🚫 Tuất đã bị cấm 😡 Vui lòng ib @jdaydichs để mở cam.")
        except Exception: pass
        return True
    now = time.time()
    info = SPAM_DATA.get(uid)
    if info is None:
        SPAM_DATA[uid] = {"count": 0, "window_start": now, "blocked_until": None,
                          "notified_spam": False, "notified_unblock": True}
        info = SPAM_DATA[uid]
    if info["blocked_until"] and now < info["blocked_until"]: return True
    if info["blocked_until"] and now >= info["blocked_until"]:
        if not info["notified_unblock"]:
            try: await context.bot.send_message(chat_id=user_id, text="😤 Mở rồi đó tuất spam nữa tao cấm 🔨")
            except Exception: pass
            info["notified_unblock"] = True
        info["count"] = 0; info["window_start"] = now
        info["blocked_until"] = None; info["notified_spam"] = False
    if now - info["window_start"] > 60:
        info["window_start"] = now; info["count"] = 1
    else: info["count"] += 1
    if info["count"] > 5:
        info["blocked_until"] = now + 60
        if not info["notified_spam"]:
            try: await context.bot.send_message(chat_id=user_id, text="😡 Mày tuất à spam lắm cấm 1p 🤬")
            except Exception: pass
            info["notified_spam"] = True
        return True
    return False

# ==================================================================
# KEYBOARDS
# ==================================================================
def join_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔗 Tham gia nhóm", url=GROUP_LINK)],
        [InlineKeyboardButton("✅ Đã tham gia - Verify", callback_data="verify_membership")]
    ])

def main_kb(uid):
    return InlineKeyboardMarkup([[InlineKeyboardButton("🖥️ Nhận máy cloud 6h", callback_data=f"get_cloud_machine:{uid}")]])

def trial_kb(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có", callback_data=f"receive_trial_yes:{uid}")],
        [InlineKeyboardButton("❌ Không", callback_data=f"receive_trial_no:{uid}")]
    ])

def confirm_kb(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Có, tạo mới", callback_data=f"confirm_create_new:{uid}")],
        [InlineKeyboardButton("❌ Từ chối", callback_data=f"cancel_create_new:{uid}")]
    ])

# ==================================================================
# SEND ACC
# ==================================================================
async def send_acc_info(context, user_id, email, password, is_received=False):
    status = "Bạn đã lấy máy trial thành công!" if is_received else "Bạn có muốn lấy máy sẵn không?"
    text = (f"🎉 Tài khoản UMO Cloud của bạn:\n\n"
            f"📧 Email: {email}\n"
            f"🔑 Mật khẩu: {password}\n\n"
            f"{status}")
    markup = None if is_received else trial_kb(user_id)
    try:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=markup)
        return True
    except Exception as e:
        logger.error(f"Send acc err: {e}"); return False

# ==================================================================
# CHAT MEMBER
# ==================================================================
async def my_chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    m = update.my_chat_member
    if m.new_chat_member.user.id == context.bot.id:
        chat = m.chat
        if chat.type in ["group", "supergroup"]:
            cid = chat.id
            if m.new_chat_member.status in ["member", "administrator"]:
                if cid not in GROUPS: GROUPS.append(cid); save_groups()
            elif m.new_chat_member.status in ["left", "kicked"]:
                if cid in GROUPS: GROUPS.remove(cid); save_groups()

async def chat_member_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cm = update.chat_member
    if cm.chat.id != GROUP_ID: return
    uid = str(cm.new_chat_member.user.id)
    old_s, new_s = cm.old_chat_member.status, cm.new_chat_member.status
    if new_s in ["member", "administrator", "creator", "restricted"] and old_s in ["left", "kicked"]:
        GROUP_MEMBERS_CACHE.add(uid)
    if new_s in ["left", "kicked"] and old_s not in ["left", "kicked"]:
        GROUP_MEMBERS_CACHE.discard(uid)
        if uid in DATA.get("tag_users", []):
            DATA["tag_users"].remove(uid); save_data()

# ==================================================================
# /start
# ==================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if await check_user_blocked(update, context): return
    user = update.effective_user
    user_id = user.id
    update_user_activity(user_id, user.username, user.first_name, user.last_name)
    uid = str(user_id)
    pd = PENDING.get(uid)
    if pd and isinstance(pd, dict) and pd.get("status") != "creating":
        if update.effective_chat.type == "private":
            await update.message.reply_text(
                f"🎉 Tài khoản UMO Cloud của bạn:\n\n📧 Email: {pd['email']}\n🔑 Mật khẩu: {pd['password']}\n\nBạn có muốn lấy máy sẵn không?",
                reply_markup=trial_kb(user_id))
        else:
            try: await send_acc_info(context, user_id, pd['email'], pd['password'])
            except Exception: pass
            await update.message.reply_text("⚠️ Bạn đang có tài khoản chưa nhận máy. Vui lòng kiểm tra tin nhắn riêng với bot.")
        return
    is_mem = await is_member(context, user_id)
    if update.effective_chat.type == "private":
        set_private_started(user_id)
        if not is_mem:
            await update.message.reply_text(
                f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.",
                reply_markup=join_kb()); return
        await update.message.reply_text(
            "🤖 *BOT TẠO MÁY CLOUD UMO*\n\n"
            "🔔 Dùng /tag để nhận thông báo khi có máy.\n"
            "🔕 Dùng /huytag để hủy thông báo khi có máy.\n"
            "Có lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_kb(user_id), parse_mode="Markdown")
    else:
        if not has_private_started(user_id):
            await update.message.reply_text(
                f"👋 [{user.first_name}](tg://user?id={user_id}) vui lòng nhắn tin riêng với bot trước khi sử dụng.\n"
                f"👉 [Bấm vào đây để mở chat riêng với bot](https://t.me/{(await context.bot.get_me()).username})",
                parse_mode="Markdown"); return
        if not is_mem:
            await update.message.reply_text(
                f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.",
                reply_markup=join_kb()); return
        await update.message.reply_text(
            "✅ Bạn đã là thành viên nhóm. Sử dụng bot bình thường.\n"
            "🔔 Dùng /tag để nhận thông báo khi có máy.\n"
            "🔕 Dùng /huytag để hủy thông báo khi có máy.\n"
            "Có lỗi gì cần fix ib @jdaydichs",
            reply_markup=main_kb(user_id))

async def verify_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    if await check_user_blocked(update, context): return
    user = q.from_user
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    set_private_started(user.id)
    if await is_member(context, user.id):
        await safe_edit(q, "✅ Xác minh thành công! Bạn có thể sử dụng bot.\nCó lỗi gì cần fix ib @jdaydichs",
                        reply_markup=main_kb(user.id))
    else:
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify lại.", reply_markup=join_kb())

# ==================================================================
# CREATE ACC
# ==================================================================
async def create_acc_progress(context, query, user_id, user_mention):
    global GLOBAL_RATE_LIMIT_UNTIL
    uid = str(user_id)
    loop = asyncio.get_running_loop()
    lock = await get_lock(user_id)
    if lock.locked():
        await safe_edit(query, "⚠️ Bạn đang có yêu cầu đang xử lý, vui lòng chờ."); return
    async with lock:
        now = time.time()
        if now < GLOBAL_RATE_LIMIT_UNTIL:
            wait = int(GLOBAL_RATE_LIMIT_UNTIL - now)
            await safe_edit(query, f"⏳ Server đang bận, vui lòng chờ {wait}s rồi thử lại."); return
        # Admin bypass cooldown
        if user_id != ADMIN_ID:
            last = USER_COOLDOWN.get(uid, 0)
            if now - last < COOLDOWN_SECONDS:
                wait = int(COOLDOWN_SECONDS - (now - last))
                await safe_edit(query, f"⏳ Bạn vừa tạo acc, chờ {wait}s nữa rồi thử lại."); return
        if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") == "creating":
            await safe_edit(query, "⚠️ Bạn đang có yêu cầu đang xử lý, vui lòng chờ."); return
        if uid in PENDING: del PENDING[uid]
        PENDING[uid] = {"chat_id": user_id, "status": "creating"}
        save_pending()
        try:
            max_attempts = 2
            last_err = None
            code = None
            email = None
            cuid = None
            mbase = None
            for attempt in range(max_attempts):
                try:
                    await safe_edit(query, f"⏳ Đang tạo email tạm... (lần {attempt+1}/{max_attempts})")
                    email, mpw, mtoken, mbase = await loop.run_in_executor(EXECUTOR, create_temp_mail)
                    logger.info(f"[{uid}] email={email} provider={mbase}")

                    await safe_edit(query, "📧 Đang gửi mã xác minh...")
                    cuid = str(uuid.uuid4()).replace("-", "")
                    await loop.run_in_executor(EXECUTOR, send_verification_code, email, cuid)
                    if user_id != ADMIN_ID:
                        USER_COOLDOWN[uid] = time.time()

                    await safe_edit(query, "🔍 Đang chờ mã xác minh...")

                    async def _status_cb(elapsed, total, _att=attempt+1):
                        remaining = total - elapsed
                        try:
                            await safe_edit(query, f"🔍 Chờ OTP lần {_att}... ({elapsed}s/{total}s, còn {remaining}s)")
                        except Exception:
                            pass

                    code = await read_code_from_mail_async(loop, mtoken, 90, mbase, _status_cb)
                    logger.info(f"[{uid}] OTP received: {code}")
                    break
                except Exception as e:
                    last_err = e
                    logger.warning(f"[{uid}] OTP attempt {attempt+1} failed: {e}")
                    if attempt < max_attempts - 1:
                        await safe_edit(query, f"⚠️ Không nhận được mail, thử provider khác...")
                        continue
            if not code:
                raise Exception(f"No OTP after {max_attempts} attempts: {last_err}")

            await safe_edit(query, "🔐 Đang đăng nhập...")
            cid, ctok = await loop.run_in_executor(EXECUTOR, login_email_code, email, code, cuid)

            await safe_edit(query, "🔑 Đang đặt mật khẩu...")
            npw = "aot" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
            await loop.run_in_executor(EXECUTOR, set_password_cloud, cid, ctok, npw, cuid)

            PENDING[uid] = {"email": email, "password": npw, "cloud_user_id": cid,
                            "cloud_token": ctok, "cuid": cuid, "trial_received": False,
                            "account_sent": False, "trial_fail_sent": False}
            save_pending()
            sent = await send_acc_info(context, user_id, email, npw)
            if sent:
                PENDING[uid]["account_sent"] = True; save_pending()
            try:
                increment_user_account(user_id)
                LAST_ACCOUNT_CREATED[uid] = time.time()
                if user_id != ADMIN_ID:
                    at = DATA["users"].get(uid, {}).get("accounts_today", 0)
                    rem = max(0, 4 - at)
                    await context.bot.send_message(chat_id=user_id, text=f"📊 Hôm nay bạn còn {rem}/4 lượt tạo tài khoản.")
            except Exception as e: logger.error(f"Quota err: {e}")
            if query.message.chat.type == "private":
                await safe_edit(query, "✅ Tài khoản đã được tạo thành công.")
            else:
                await safe_edit(query, "✅ Tài khoản mật khẩu đã được tạo. Vui lòng kiểm tra tin nhắn riêng của bot.")
        except Exception as e:
            logger.exception(f"Create acc err for {user_id}: {e}")
            em = str(e)
            if "1002025003" in em or "邮件发送过于频繁" in em or "too frequent" in em.lower():
                GLOBAL_RATE_LIMIT_UNTIL = time.time() + GLOBAL_LIMIT_BACKOFF
                um = f"⏳ Server đang bận do quá nhiều người tạo. Vui lòng chờ {GLOBAL_LIMIT_BACKOFF // 60} phút."
            elif "send verification failed" in em:
                um = f"❌ Gửi mã xác minh thất bại. Vui lòng thử lại.\n({em[:150]})"
            elif "login failed" in em:
                um = f"❌ Đăng nhập UMO Cloud thất bại. Vui lòng thử lại.\n({em[:150]})"
            elif "No OTP" in em:
                um = "❌ Chưa nhận được mã xác minh sau 2 lần thử. Vui lòng thử lại sau ít phút."
            elif "set password failed" in em:
                um = f"❌ Đặt mật khẩu thất bại. Vui lòng thử lại.\n({em[:150]})"
            elif "Mail failed" in em:
                um = "❌ Không tạo được email tạm. Vui lòng thử lại."
            elif "Network failed" in em:
                um = f"❌ Lỗi kết nối server. Vui lòng thử lại.\n({em[:150]})"
            else:
                um = f"❌ Lỗi không xác định. Vui lòng ib @jdaydichs.\n({em[:150]})"
            await safe_edit(query, um)
        finally:
            if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") == "creating":
                del PENDING[uid]; save_pending()

async def get_cloud_machine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "get_cloud_machine":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    target = safe_int(data[1])
    if target is None or target != user_id:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if await check_user_blocked(update, context): return
    if not await is_member(context, user_id):
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.", reply_markup=join_kb()); return
    uid = str(user_id)
    update_user_activity(user_id, user.username, user.first_name, user.last_name)
    ensure_account_reset(user_id)
    if uid in PENDING and isinstance(PENDING[uid], dict) and PENDING[uid].get("status") != "creating":
        pd = PENDING[uid]
        if pd.get("trial_received", False):
            del PENDING[uid]; save_pending()
        else:
            try: await send_acc_info(context, user_id, pd['email'], pd['password'])
            except Exception: pass
            await safe_edit(q, "⚠️ Bạn đang có tài khoản chưa nhận máy. Vui lòng kiểm tra tin nhắn riêng với bot."); return
    if user_id != ADMIN_ID:
        ui = DATA["users"].get(uid, {})
        if ui.get("accounts_today", 0) >= 4:
            await safe_edit(q, "⛔ Bạn đã tạo đủ 4 tài khoản hôm nay. Vui lòng quay lại vào ngày mai."); return
    if not has_private_started(user_id):
        await safe_edit(q,
            f"⚠️ {user.mention_markdown()} vui lòng nhắn tin riêng với bot trước khi sử dụng.\n"
            f"👉 [Bấm vào đây](https://t.me/{(await context.bot.get_me()).username})",
            parse_mode="Markdown"); return
    await create_acc_progress(context, q, user_id, user.mention_markdown())

async def confirm_create_new(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "confirm_create_new":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    target = safe_int(data[1])
    if target is None or target != user_id:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if await check_user_blocked(update, context): return
    if not await is_member(context, user_id):
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.", reply_markup=join_kb()); return
    uid = str(user_id)
    if uid in PENDING: del PENDING[uid]; save_pending()
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
    target = safe_int(data[1])
    if target is None or target != user_id:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if await check_user_blocked(update, context): return
    uid = str(user_id)
    pd = PENDING.get(uid)
    if not pd or isinstance(pd, bool) or pd.get("status") == "creating":
        await safe_edit(q, "Phiên làm việc hết hạn, vui lòng /start lại."); return
    try: await send_acc_info(context, user_id, pd['email'], pd['password'])
    except Exception as e: logger.error(f"Send acc err: {e}")
    await safe_edit(q, "✅ Đã gửi lại thông tin tài khoản cũ. Bạn có thể chọn Có hoặc Không trong tin nhắn riêng.")

# ==================================================================
# TAG COMMANDS
# ==================================================================
def build_tags():
    tags = []
    for uid in DATA.get("tag_users", []):
        ui = DATA["users"].get(str(uid), {})
        un = ui.get("username"); fn = ui.get("first_name") or "User"
        if un: tags.append(f"@{html.escape(un)}")
        else: tags.append(f'<a href="tg://user?id={uid}">{html.escape(fn)}</a>')
    return " ".join(tags)

async def notify_groups(context, text):
    groups = list(set(GROUPS))
    if GROUP_ID not in groups: groups.append(GROUP_ID)
    for gid in groups:
        try: await context.bot.send_message(chat_id=gid, text=text, parse_mode='HTML')
        except Exception as e:
            logger.error(f"Notify group err {gid}: {e}")
            try:
                plain = re.sub(r'<[^>]+>', '', text)
                await context.bot.send_message(chat_id=gid, text=plain)
            except Exception as e2: logger.error(f"Fallback notify err: {e2}")

async def tag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if await check_user_blocked(update, context): return
    if not await is_member(context, update.effective_user.id):
        await update.message.reply_text(
            f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.",
            reply_markup=join_kb()); return
    user = update.effective_user
    uid = str(user.id)
    update_user_activity(user.id, user.username, user.first_name, user.last_name)
    if uid not in DATA["tag_users"]:
        DATA["tag_users"].append(uid); save_data()
        await update.message.reply_text("✅ Đã thêm bạn vào thông báo khi có máy.")
    else: await update.message.reply_text("⛔ Bạn đã đăng ký tag rồi.")

async def untag_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if await check_user_blocked(update, context): return
    if not await is_member(context, update.effective_user.id):
        await update.message.reply_text(
            f"🔒 Bạn cần tham gia nhóm để sử dụng bot:\n👉 {GROUP_LINK}\n\nSau khi tham gia, bấm nút Verify bên dưới.",
            reply_markup=join_kb()); return
    uid = str(update.effective_user.id)
    if uid in DATA["tag_users"]:
        DATA["tag_users"].remove(uid); save_data()
        await update.message.reply_text("✅ Đã bỏ bạn khỏi thông báo khi có máy.")
    else: await update.message.reply_text("⛔ Bạn chưa đăng ký tag.")

# ==================================================================
# TRIAL CALLBACKS
# ==================================================================
async def receive_trial_yes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global LAST_CLOUD_STATUS
    q = update.callback_query
    await safe_ans(q)
    user = q.from_user
    user_id = user.id
    data = q.data.split(":")
    if len(data) != 2 or data[0] != "receive_trial_yes":
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    target = safe_int(data[1])
    if target is None or target != user_id:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if await check_user_blocked(update, context): return
    if not await is_member(context, user_id):
        await safe_edit(q, "❌ Bạn chưa tham gia nhóm! Vui lòng tham gia rồi bấm Verify.", reply_markup=join_kb()); return
    uid = str(user_id)
    lock = await get_lock(user_id)
    async with lock:
        pd = PENDING.get(uid)
        if not pd or isinstance(pd, bool) or pd.get("status") == "creating":
            await safe_edit(q, "Phiên làm việc hết hạn, vui lòng /start lại."); return
        if pd.get("trial_received", False):
            await safe_edit(q, "⛔ Nick này đã lấy máy trial rồi, vui lòng tạo tài khoản mới."); return
        await safe_edit(q, "⏳ Đang nhận máy trial, vui lòng chờ...")
        loop = asyncio.get_running_loop()
        try:
            cid = pd["cloud_user_id"]; ctok = pd["cloud_token"]; cuid = pd["cuid"]
            chk = await loop.run_in_executor(EXECUTOR, lambda: check_login_cloud(cid, ctok, cuid))
            if chk.get("code") == 1000000008:
                await safe_edit(q, "🔐 Token hết hạn, đang đăng nhập lại...")
                nu, nt = await loop.run_in_executor(EXECUTOR, login_password_cloud, pd["email"], pd["password"], cuid)
                pd["cloud_user_id"] = nu; pd["cloud_token"] = nt
                save_pending(); cid, ctok = nu, nt
            ok, res = await loop.run_in_executor(EXECUTOR, lambda: receive_trial_cloud(cid, ctok, cuid))
            if ok:
                await safe_edit(q, "✅ Đã lấy máy trial thành công!\nBạn có thể đăng nhập vào UMO Cloud bằng tài khoản trên.\nNếu cần hỗ trợ, ib @jdaydichs")
                try: await send_acc_info(context, user_id, pd['email'], pd['password'], is_received=True)
                except Exception: pass
                pd["trial_received"] = True; save_pending()
                if LAST_CLOUD_STATUS != "available":
                    tags = build_tags()
                    txt = "✅ <b>Máy cloud đã có lại, mọi người nhận đi!</b>"
                    if tags: txt += "\n" + tags
                    await notify_groups(context, txt)
                    LAST_CLOUD_STATUS = "available"
                    DATA["last_cloud_status"] = LAST_CLOUD_STATUS; save_data()
                if uid in PENDING: del PENDING[uid]; save_pending()
            else:
                msg = str(res.get("msg", "")).lower()
                code = res.get("code")
                if "not eligible" in msg or code == 1003000071:
                    try: await send_acc_info(context, user_id, pd['email'], pd['password'])
                    except Exception: pass
                    await safe_edit(q, "⛔ Nick này không đủ điều kiện nhận máy.\nVui lòng tạo tài khoản mới.")
                    if uid in PENDING: del PENDING[uid]; save_pending()
                elif "all been claimed" in msg:
                    if LAST_CLOUD_STATUS != "unavailable":
                        await notify_groups(context, "⛔ <b>Máy cloud đã hết, vui lòng chờ.</b>")
                        LAST_CLOUD_STATUS = "unavailable"
                        DATA["last_cloud_status"] = LAST_CLOUD_STATUS; save_data()
                    if not pd.get("trial_fail_sent", False):
                        try:
                            await send_acc_info(context, user_id, pd['email'], pd['password'])
                            pd["trial_fail_sent"] = True; save_pending()
                        except Exception: pass
                    await safe_edit(q,
                        "⛔ Máy cloud đã hết, bấm nút dưới để thử lại khi nào có máy.\nTài khoản của bạn đã được gửi trong tin nhắn riêng.",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("🔄 Thử lại", callback_data=f"receive_trial_yes:{user_id}")]]))
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
    target = safe_int(data[1])
    if target is None or target != user_id:
        await safe_ans(q, "⛔ Dữ liệu nút không hợp lệ!", show_alert=True); return
    if await check_user_blocked(update, context): return
    uid = str(user_id)
    lock = await get_lock(user_id)
    async with lock:
        pd = PENDING.get(uid)
        if pd and not isinstance(pd, bool) and pd.get("status") != "creating":
            try: await send_acc_info(context, user_id, pd['email'], pd['password'])
            except Exception: pass
        if uid in PENDING: del PENDING[uid]; save_pending()
    await safe_edit(q, "Đã hủy lấy máy sẵn. Bạn vẫn có thể dùng tài khoản để đăng nhập.\nNếu cần hỗ trợ, ib @jdaydichs")

# ==================================================================
# ADMIN COMMANDS
# ==================================================================
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
            if info.get("username") == un: user_id = int(uid); break
        if not user_id:
            await update.message.reply_text("Không tìm thấy người dùng với username đó."); return
    else:
        user_id = safe_int(target)
        if user_id is None: await update.message.reply_text("ID không hợp lệ."); return
    DATA.setdefault("banned", {})[str(user_id)] = True
    save_data(force=True)
    await update.message.reply_text(f"✅ Đã cấm người dùng {user_id} sử dụng bot.")
    try: await context.bot.send_message(chat_id=user_id, text="🚫 Tuất đã bị cấm 😡 Vui lòng ib @jdaydichs để mở cam.")
    except Exception: pass

async def mocam(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    if not context.args:
        await update.message.reply_text("Sử dụng: /mocam <id>"); return
    user_id = safe_int(context.args[0])
    if user_id is None: await update.message.reply_text("ID không hợp lệ."); return
    if str(user_id) in DATA.get("banned", {}):
        del DATA["banned"][str(user_id)]; save_data(force=True)
        await update.message.reply_text(f"✅ Đã mở cam cho người dùng {user_id}.")
    else: await update.message.reply_text("Người dùng này không bị cấm.")

async def reset_accounts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    today = vn_today()
    for uid, info in DATA["users"].items():
        info["accounts_today"] = 0; info["last_account_date"] = None
    DATA["daily_counts"].pop(today, None)
    save_data(force=True)
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
    chunks = []; buf = header
    for uid, info in sorted_users:
        un = info.get("username"); fn = info.get("first_name") or "Không tên"
        ta = info.get("total_accounts", 0)
        display = f"@{un}" if un else fn
        entry = f"👤 {display}\n   🆔 ID: {uid}\n   📦 Tổng acc: {ta}\n\n"
        if len(buf) + len(entry) > MAX_LEN: chunks.append(buf); buf = entry
        else: buf += entry
    if len(buf) + len(footer) > MAX_LEN: chunks.append(buf); buf = footer
    else: buf += footer
    if buf.strip(): chunks.append(buf)
    for c in chunks:
        try: await update.message.reply_text(c)
        except Exception as e: logger.error(f"Send info err: {e}")

async def kiemtra(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_message: return
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    today = vn_today()
    daily = DATA.get("daily_counts", {}).get(today, {})
    total_today = daily.get("total", 0); by_user = daily.get("by_user", {})
    header = f"📊 THỐNG KÊ NGÀY {today}\n━━━━━━━━━━━━━━━━━━━━━\n🎯 Tổng acc đã tạo: {total_today}\n\n"
    footer = "\n━━━━━━━━━━━━━━━━━━━━━"
    chunks = []; buf = header
    if by_user:
        for uid, cnt in sorted(by_user.items(), key=lambda x: x[1], reverse=True):
            ui = DATA["users"].get(uid, {})
            un = ui.get("username"); fn = ui.get("first_name") or "Không tên"
            display = f"@{un}" if un else fn
            entry = f"• {display} → {cnt} acc\n"
            if len(buf) + len(entry) > MAX_LEN: chunks.append(buf); buf = entry
            else: buf += entry
    else: buf += "Chưa có ai tạo acc hôm nay."
    if len(buf) + len(footer) > MAX_LEN: chunks.append(buf); buf = footer
    else: buf += footer
    if buf.strip(): chunks.append(buf)
    for c in chunks:
        try: await update.message.reply_text(c)
        except Exception as e: logger.error(f"Send stats err: {e}")

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
            await context.bot.send_message(chat_id=int(uid), text=f"📢 Thông báo từ Admin:\n{msg}"); s += 1
        except Exception as e:
            logger.error(f"Send to {uid} err: {e}"); f += 1
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

async def debug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Bạn không có quyền sử dụng lệnh này."); return
    if not context.args:
        await update.message.reply_text("Dùng: /debug <user_id>"); return
    uid = safe_int(context.args[0])
    if uid is None: await update.message.reply_text("ID không hợp lệ."); return
    try:
        m = await context.bot.get_chat_member(chat_id=GROUP_ID, user_id=uid)
        info = (f"📊 DEBUG user {uid}\nStatus: {m.status}\nIs bot: {m.user.is_bot}\n"
                f"User: @{m.user.username} - {m.user.first_name}\n"
                f"Private started: {has_private_started(uid)}\n")
        await update.message.reply_text(info)
    except Exception as e:
        await update.message.reply_text(f"❌ Lỗi get_chat_member: {e}")

# ==================================================================
# ERROR HANDLER
# ==================================================================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Exception:", exc_info=context.error)

# ==================================================================
# PENDING RECOVERY
# ==================================================================
async def handle_pending_on_startup(app):
    if not PENDING: return
    loop = asyncio.get_running_loop()
    for uid, data in list(PENDING.items()):
        if uid == "_dirty": continue
        uid_int = safe_int(uid)
        if uid_int is None: continue
        if isinstance(data, dict) and data.get("status") != "creating":
            try:
                await app.bot.send_message(chat_id=uid_int,
                    text=f"🎉 Tài khoản UMO Cloud của bạn:\n\n📧 Email: {data['email']}\n🔑 Mật khẩu: {data['password']}\n\nBạn có muốn lấy máy sẵn không?",
                    reply_markup=trial_kb(uid_int))
            except Exception: pass
        elif data is True or (isinstance(data, dict) and data.get("status") == "creating"):
            if uid in PENDING: del PENDING[uid]
            save_pending()
            try: await app.bot.send_message(chat_id=uid_int, text="⏳ Bot đang tạo bù tài khoản cho bạn...")
            except Exception: continue
            try:
                email, mpw, mtoken, mbase = await loop.run_in_executor(EXECUTOR, create_temp_mail)
                cuid = str(uuid.uuid4()).replace("-", "")
                await loop.run_in_executor(EXECUTOR, send_verification_code, email, cuid)
                code = await read_code_from_mail_async(loop, mtoken, 90, mbase, None)
                cid, ctok = await loop.run_in_executor(EXECUTOR, login_email_code, email, code, cuid)
                npw = "aot" + ''.join(random.choices(string.ascii_letters + string.digits, k=5))
                await loop.run_in_executor(EXECUTOR, set_password_cloud, cid, ctok, npw, cuid)
                PENDING[uid] = {"email": email, "password": npw, "cloud_user_id": cid,
                                "cloud_token": ctok, "cuid": cuid, "trial_received": False,
                                "account_sent": False, "trial_fail_sent": False}
                save_pending()
                await send_acc_info(app, uid_int, email, npw)
            except Exception as e:
                logger.error(f"Pending recovery err {uid}: {e}")

# ==================================================================
# BACKGROUND TASKS
# ==================================================================
async def backup_task():
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(3)
        try:
            await loop.run_in_executor(EXECUTOR, _flush_all_if_dirty)
        except Exception as e:
            logger.error(f"Backup err: {e}")

async def github_backup_task():
    loop = asyncio.get_running_loop()
    while True:
        await asyncio.sleep(300)
        try:
            await loop.run_in_executor(EXECUTOR, _flush_github_force)
        except Exception as e:
            logger.error(f"GitHub backup err: {e}")

async def cleanup_spam_task():
    while True:
        await asyncio.sleep(600)
        now = time.time(); expired = []
        for uid, info in list(SPAM_DATA.items()):
            bu = info.get("blocked_until"); ws = info.get("window_start", 0)
            if bu is None and now - ws > 120: expired.append(uid)
            elif bu is not None and now >= bu: expired.append(uid)
        for uid in expired: SPAM_DATA.pop(uid, None)

async def cleanup_cooldown_task():
    while True:
        await asyncio.sleep(300)
        now = time.time()
        for uid in list(USER_COOLDOWN.keys()):
            if now - USER_COOLDOWN[uid] > 3600: USER_COOLDOWN.pop(uid, None)

# ==================================================================
# MAIN
# ==================================================================
def main():
    start_health_server()

    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    if loop.is_closed():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    app = (Application.builder().token(BOT_TOKEN)
           .connect_timeout(30).read_timeout(30).write_timeout(30)
           .concurrent_updates(True).build())
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
    app.add_handler(CommandHandler("debug", debug))

    app.add_handler(CallbackQueryHandler(verify_cb, pattern="^verify_membership$"))
    app.add_handler(CallbackQueryHandler(get_cloud_machine, pattern="^get_cloud_machine:"))
    app.add_handler(CallbackQueryHandler(confirm_create_new, pattern="^confirm_create_new:"))
    app.add_handler(CallbackQueryHandler(cancel_create_new, pattern="^cancel_create_new:"))
    app.add_handler(CallbackQueryHandler(receive_trial_yes, pattern="^receive_trial_yes:"))
    app.add_handler(CallbackQueryHandler(receive_trial_no, pattern="^receive_trial_no:"))

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_regular_message))

    try:
        loop.create_task(handle_pending_on_startup(app))
        loop.create_task(backup_task())
        loop.create_task(github_backup_task())
        loop.create_task(cleanup_spam_task())
        loop.create_task(cleanup_cooldown_task())
        logger.info("Bot đang chạy...")
        app.run_polling(allowed_updates=Update.ALL_TYPES, poll_interval=0.3)
    finally:
        logger.info("Shutdown — push GitHub lần cuối...")
        try: _flush_github_force()
        except Exception as e: logger.error(f"Final push err: {e}")
        _flush_all_if_dirty()

if __name__ == "__main__":
    main()
