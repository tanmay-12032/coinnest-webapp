import os, json, hmac, hashlib, time, uuid, re
from urllib.parse import parse_qsl
from functools import wraps
import requests
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024  # reject oversized JSON bodies

# Lightweight per-instance abuse throttle. Use a shared store/WAF for multi-instance production.
_RATE_BUCKETS = {}
_RATE_LIMITS = {"/api/lifafas": (8, 60), "/api/lifafa/": (30, 60)}
@app.before_request
def _basic_request_guards():
    if request.method in ("POST", "PUT", "PATCH") and request.path.startswith("/api/"):
        if request.content_length is not None and request.content_length > 64 * 1024:
            return jsonify({"error": "Request body too large."}), 413
        if request.mimetype != "application/json":
            return jsonify({"error": "Content-Type must be application/json."}), 415
    limit = next(((n, window) for prefix, (n, window) in _RATE_LIMITS.items() if request.path == prefix or request.path.startswith(prefix)), None)
    if limit:
        count, window = limit
        now = time.time()
        ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
        key = (ip, request.path.split("/")[:4].__str__())
        hits = [t for t in _RATE_BUCKETS.get(key, []) if now - t < window]
        if len(hits) >= count:
            return jsonify({"error": "Too many requests. Please wait and try again."}), 429
        hits.append(now); _RATE_BUCKETS[key] = hits
    return None

@app.after_request
def _security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; base-uri 'self'; object-src 'none'; "
        "frame-ancestors 'self' https://web.telegram.org https://*.telegram.org; "
        "form-action 'self'; upgrade-insecure-requests; "
        "script-src 'self' 'unsafe-inline' https://telegram.org https://*.telegram.org; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com data:; "
        "img-src 'self' data: https:; connect-src 'self' https://api.telegram.org")
    if request.is_secure:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "CoinNest_bot").strip().lstrip("@")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
DEMO_MODE = os.environ.get("DEMO_MODE", "0") == "1"
COINS_PER_RUPEE = 100
MIN_WITHDRAW_RUPEES = 10
OWNER_ADMIN_ID = os.environ.get("OWNER_ADMIN_ID", "1849699189").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://coinnest-webapp.vercel.app").strip().rstrip("/")
MINI_APP_SHORT_NAME = os.environ.get("MINI_APP_SHORT_NAME", "CoinNest").strip()
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()
class DBConnection:
    """Small compatibility wrapper for the existing SQL call style, backed by PostgreSQL."""
    def __init__(self):
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is missing. Connect Neon PostgreSQL in Vercel Environment Variables.")
        self.conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor, connect_timeout=10)
    def execute(self, sql, params=None):
        sql = sql.replace("BEGIN IMMEDIATE", "BEGIN")
        sql = sql.replace("INSERT OR IGNORE INTO", "INSERT INTO")
        if "INSERT INTO admins(telegram_id, added_by, created_at)" in sql or "INSERT INTO referrals(referred_id, referrer_id, created_at)" in sql or "INSERT INTO pending_referrals(referred_id, referrer_id, created_at)" in sql:
            if "ON CONFLICT" not in sql.upper(): sql += " ON CONFLICT DO NOTHING"
        if "INSERT OR REPLACE INTO required_channels" in sql:
            sql = sql.replace("INSERT OR REPLACE INTO", "INSERT INTO") + " ON CONFLICT (channel_id) DO UPDATE SET title=EXCLUDED.title, join_url=EXCLUDED.join_url, created_by=EXCLUDED.created_by, created_at=EXCLUDED.created_at"
        elif "INSERT OR REPLACE INTO banned_users" in sql:
            sql = sql.replace("INSERT OR REPLACE INTO", "INSERT INTO") + " ON CONFLICT (telegram_id) DO UPDATE SET reason=EXCLUDED.reason, banned_by=EXCLUDED.banned_by, created_at=EXCLUDED.created_at"
        sql = sql.replace("?", "%s")
        cur = self.conn.cursor()
        cur.execute(sql, params or ())
        return cur
    def commit(self): self.conn.commit()
    def rollback(self): self.conn.rollback()
    def close(self): self.conn.close()
    def __enter__(self): return self
    def __exit__(self, typ, value, tb):
        try:
            if typ is None: self.conn.commit()
            else: self.conn.rollback()
        finally: self.conn.close()

def db():
    return DBConnection()

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            balance INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
            id BIGSERIAL PRIMARY KEY, telegram_id TEXT NOT NULL,
            amount_rupees INTEGER NOT NULL, amount_coins INTEGER NOT NULL, upi_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL)""")
        existing_cols = {r["column_name"] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name='withdrawals'").fetchall()}
        for col, definition in (("method", "TEXT NOT NULL DEFAULT 'payz'"), ("payout_id", "TEXT NOT NULL DEFAULT ''"), ("amount_value", "DOUBLE PRECISION NOT NULL DEFAULT 0")):
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE withdrawals ADD COLUMN {col} {definition}")
        conn.execute("UPDATE withdrawals SET payout_id=upi_id WHERE payout_id='' AND upi_id IS NOT NULL")
        conn.execute("""CREATE TABLE IF NOT EXISTS ad_claims (
            id BIGSERIAL PRIMARY KEY, telegram_id TEXT NOT NULL, day TEXT NOT NULL,
            created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS monetag_ad_sessions (
            ymid TEXT PRIMARY KEY, telegram_id TEXT NOT NULL, created_at BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending')""")
        conn.execute("""CREATE TABLE IF NOT EXISTS monetag_reward_events (
            ymid TEXT PRIMARY KEY, telegram_id TEXT NOT NULL, event_type TEXT NOT NULL,
            reward_event_type TEXT NOT NULL, estimated_price TEXT NOT NULL DEFAULT '0',
            status TEXT NOT NULL, created_at BIGINT NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS game_rewards (
            telegram_id TEXT NOT NULL, game TEXT NOT NULL, day TEXT NOT NULL,
            coins INTEGER NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY (telegram_id, game, day))""")
        conn.execute("""CREATE TABLE IF NOT EXISTS game_reward_claims (
            id BIGSERIAL PRIMARY KEY, telegram_id TEXT NOT NULL,
            game TEXT NOT NULL, coins INTEGER NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_game_reward_claims_user_time ON game_reward_claims(telegram_id, created_at)")
        conn.execute("""CREATE TABLE IF NOT EXISTS admins (
            telegram_id TEXT PRIMARY KEY, added_by TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS banned_users (
            telegram_id TEXT PRIMARY KEY, reason TEXT NOT NULL DEFAULT '', banned_by TEXT NOT NULL,
            created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS required_channels (
            channel_id TEXT PRIMARY KEY, title TEXT NOT NULL, join_url TEXT NOT NULL,
            created_by TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS balance_logs (
            id BIGSERIAL PRIMARY KEY, target_id TEXT NOT NULL, admin_id TEXT NOT NULL,
            delta INTEGER NOT NULL, note TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS pending_referrals (
            referred_id TEXT PRIMARY KEY, referrer_id TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS referrals (
            referred_id TEXT PRIMARY KEY, referrer_id TEXT NOT NULL, created_at INTEGER NOT NULL,
            verified_ads INTEGER NOT NULL DEFAULT 0, completed INTEGER NOT NULL DEFAULT 0,
            bonus_paid INTEGER NOT NULL DEFAULT 0, commission_coins INTEGER NOT NULL DEFAULT 0)""")
        # The configured owner is always an admin.
        conn.execute("INSERT OR IGNORE INTO admins(telegram_id, added_by, created_at) VALUES(?,?,?)",
                     (OWNER_ADMIN_ID, OWNER_ADMIN_ID, int(time.time())))

def verify_telegram_init_data(init_data):
    """Validate Telegram Mini App initData using the bot token."""
    if not BOT_TOKEN or not init_data:
        return None
    try:
        values = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", None)
        if not received_hash:
            return None
        check_string = "\n".join(f"{k}={v}" for k, v in sorted(values.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated, received_hash):
            return None
        auth_date = int(values.get("auth_date", "0"))
        if abs(int(time.time()) - auth_date) > 86400:
            return None
        user = json.loads(values.get("user", "{}"))
        if not user.get("id"):
            return None
        return user
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def verified_telegram_user():
    """Return a user only when Telegram initData has passed server-side verification."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data)
    if not user:
        return None
    return {
        "telegram_id": str(user["id"]),
        "username": user.get("username", ""),
        "first_name": user.get("first_name", "User"),
        "last_name": user.get("last_name", "")
    }

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = verified_telegram_user()
        if not user:
            return jsonify({"error": "Telegram authentication failed. Open this panel inside Telegram."}), 401
        with db() as conn:
            banned = conn.execute("SELECT 1 FROM banned_users WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
            admin = conn.execute("SELECT 1 FROM admins WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
        if banned:
            return jsonify({"error": "Your account is banned."}), 403
        if not admin:
            return jsonify({"error": "Your not admin 🚫"}), 403
        request.admin_user = user
        return fn(*args, **kwargs)
    return wrapper

def join_status(telegram_id):
    """Check all required channels with Telegram getChatMember; bot must be admin in each channel."""
    with db() as conn:
        channels = conn.execute("SELECT channel_id, title, join_url FROM required_channels ORDER BY created_at").fetchall()
    missing = []
    for ch in channels:
        if not BOT_TOKEN:
            missing.append({**dict(ch), "reason": "bot_not_configured"})
            continue
        try:
            r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",
                             params={"chat_id": ch["channel_id"], "user_id": telegram_id}, timeout=10)
            data = r.json()
            member = data.get("result", {})
            status = member.get("status", "")
            joined = data.get("ok") and (status in ("creator", "administrator", "member") or
                                          (status == "restricted" and member.get("is_member", False)))
            if not joined:
                missing.append(dict(ch))
        except requests.RequestException:
            missing.append(dict(ch))
    return missing


def current_user():
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    user = verify_telegram_init_data(init_data)
    if user:
        return {
            "telegram_id": str(user["id"]),
            "username": user.get("username", ""),
            "first_name": user.get("first_name", "User"),
            "last_name": user.get("last_name", "")
        }
    if DEMO_MODE:
        return {"telegram_id": "demo-user", "username": "demo_user",
                "first_name": "Demo User", "last_name": ""}
    return None

def require_user(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user()
        if not user:
            return jsonify({"error": "Telegram authentication failed. Open this app from your Telegram bot."}), 401
        request.user_data = user
        with db() as conn:
            if conn.execute("SELECT 1 FROM banned_users WHERE telegram_id=?", (user["telegram_id"],)).fetchone():
                return jsonify({"error": "Your account is banned."}), 403
            existed = conn.execute("SELECT 1 FROM users WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
            conn.execute("""INSERT INTO users(telegram_id, username, first_name, last_name, created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name""",
                (user["telegram_id"], user["username"], user["first_name"], user["last_name"], int(time.time())))
            if not existed and user["telegram_id"] != "demo-user":
                pending = conn.execute("SELECT referrer_id FROM pending_referrals WHERE referred_id=?",
                                       (user["telegram_id"],)).fetchone()
                if pending and pending["referrer_id"] != user["telegram_id"]:
                    conn.execute("INSERT OR IGNORE INTO referrals(referred_id, referrer_id, created_at) VALUES(?,?,?)",
                                 (user["telegram_id"], pending["referrer_id"], int(time.time())))
                conn.execute("DELETE FROM pending_referrals WHERE referred_id=?", (user["telegram_id"],))
        if request.path not in ("/api/join-status",) and not request.path.startswith("/api/lifafa/") and request.path != "/api/lifafas":
            missing = join_status(user["telegram_id"])
            if missing:
                return jsonify({"error": "Join all required channels first.", "required_channels": missing}), 428
        return fn(*args, **kwargs)
    return wrapper

def telegram_send_message(text):
    if not BOT_TOKEN or not CHANNEL_ID:
        raise RuntimeError("BOT_TOKEN and CHANNEL_ID must be configured in Termux environment variables.")
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    response = requests.post(url, json={"chat_id": CHANNEL_ID, "text": text, "parse_mode": "HTML"}, timeout=15)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "Telegram API request failed"))
    return True

@app.get("/")
@app.get("/lifafa/<lifafa_id>")
def index(lifafa_id=None):
    return render_template("index.html", bot_username=BOT_USERNAME, demo_mode=DEMO_MODE, lifafa_id=lifafa_id or "")

@app.get("/api/config")
def config():
    return jsonify({"bot_username": BOT_USERNAME, "demo_mode": DEMO_MODE,
                    "coins_per_rupee": COINS_PER_RUPEE, "min_withdraw_rupees": MIN_WITHDRAW_RUPEES})

@app.get("/api/me")
@require_user
def me():
    user = current_user()
    with db() as conn:
        row = conn.execute("SELECT balance FROM users WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
        history = conn.execute("SELECT id, amount_rupees, amount_coins, upi_id, status, created_at, method, payout_id, amount_value FROM withdrawals WHERE telegram_id=? ORDER BY id DESC LIMIT 10",
                               (user["telegram_id"],)).fetchall()
        transactions = conn.execute("SELECT id, delta_coins, reason, reference_id, created_at FROM wallet_transactions WHERE telegram_id=? ORDER BY id DESC LIMIT 100", (user["telegram_id"],)).fetchall()
    return jsonify({"user": user, "balance": row["balance"],
                    "withdrawals": [dict(x) for x in history], "transactions": [dict(x) for x in transactions]})

@app.post("/api/withdraw")
@require_user
def withdraw():
    user = request.user_data
    payload = request.get_json(silent=True) or {}
    method = str(payload.get("method", "payz")).strip().lower()
    payout_id = str(payload.get("payout_id", "")).strip()
    if method not in ("payz", "upi", "cwallet"):
        return jsonify({"error": "Choose Payz, UPI, or Cwallet USDT."}), 400
    try:
        amount_value = float(payload.get("amount", 0))
    except (ValueError, TypeError):
        amount_value = 0
    if method == "payz":
        if not (len(payout_id) == 10 and payout_id.isdigit()):
            return jsonify({"error": "Enter your 10-digit Payz number."}), 400
        if not amount_value.is_integer() or amount_value < 1:
            return jsonify({"error": "Payz minimum withdrawal is ₹1."}), 400
        amount_rupees=int(amount_value); coins=amount_rupees*100; display_amount=f"₹{amount_rupees}"; method_label="Payz Gateway"
    elif method == "upi":
        if not (3 <= len(payout_id) <= 100 and "@" in payout_id and payout_id.count("@") == 1):
            return jsonify({"error": "Enter a valid UPI ID containing @."}), 400
        if not amount_value.is_integer() or amount_value < 50:
            return jsonify({"error": "UPI minimum withdrawal is ₹50."}), 400
        amount_rupees=int(amount_value); coins=amount_rupees*100; display_amount=f"₹{amount_rupees}"; method_label="UPI"
    else:
        if not (3 <= len(payout_id) <= 120):
            return jsonify({"error": "Enter a valid Cwallet ID."}), 400
        if amount_value < 0.01 or round(amount_value, 2) != amount_value:
            return jsonify({"error": "Cwallet minimum is 0.01 USDT; use up to 2 decimal places."}), 400
        amount_rupees=0; coins=int(round(amount_value*10000)); display_amount=f"{amount_value:.2f} USDT"; method_label="Cwallet USDT"
    now=int(time.time())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row=conn.execute("SELECT balance FROM users WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
        if not row or row["balance"] < coins:
            conn.rollback()
            return jsonify({"error": "Insufficient coin balance."}), 400
        cur=conn.execute("INSERT INTO withdrawals(telegram_id, amount_rupees, amount_coins, upi_id, created_at, method, payout_id, amount_value) VALUES(?,?,?,?,?,?,?,?) RETURNING id",
            (user["telegram_id"], amount_rupees, coins, payout_id, now, method, payout_id, amount_value))
        withdrawal_id=cur.fetchone()["id"]
        conn.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?", (coins, user["telegram_id"]))
        conn.execute("INSERT INTO wallet_transactions(telegram_id,delta_coins,reason,reference_id,created_at) VALUES(?,?,?,?,?)", (user["telegram_id"], -coins, "Withdrawal requested", str(withdrawal_id), now))
        conn.commit()
    safe_name=f"{user.get('first_name','')} {user.get('last_name','')}".strip() or "Unknown"
    safe_username=user.get("username") or "not_set"
    message=("🪙 <b>CoinNest Withdrawal Request</b>\n"
        f"Request: <b>#{withdrawal_id}</b>\nUser ID: <code>{user['telegram_id']}</code>\n"
        f"Name: {safe_name}\nUsername: @{safe_username}\nMethod: <b>{method_label}</b>\n"
        f"Amount: <b>{display_amount}</b> ({coins:,} coins)\nWallet / payout ID: <code>{payout_id}</code>\n"
        "Status: <b>Pending manual review</b>")
    try:
        telegram_send_message(message)
    except Exception:
        with db() as conn:
            conn.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?", (coins, user["telegram_id"]))
            conn.execute("UPDATE withdrawals SET status='notification_failed' WHERE id=?", (withdrawal_id,))
            conn.execute("INSERT INTO wallet_transactions(telegram_id,delta_coins,reason,reference_id,created_at) VALUES(?,?,?,?,?)", (user["telegram_id"], coins, "Withdrawal refund", str(withdrawal_id), int(time.time())))
        app.logger.exception("Withdrawal channel notification failed")
        return jsonify({"error": "Could not send request to the Telegram channel. Coins have been returned. Check bot permissions and server configuration."}), 502
    return jsonify({"ok": True, "message": f"Withdrawal request #{withdrawal_id} sent for manual review."})

@app.get("/api/join-status")
@require_user
def api_join_status():
    user = request.user_data
    return jsonify({"required_channels": join_status(user["telegram_id"])})

@app.get("/api/referrals")
@require_user
def referral_stats():
    user = request.user_data
    if user["telegram_id"] == "demo-user":
        return jsonify({"referral_link": "", "total": 0, "completed": 0, "bonus_coins": 0,
                        "commission_coins": 0, "note": "Open from Telegram to get your personal referral link."})
    with db() as conn:
        rows = conn.execute("SELECT completed, bonus_paid, commission_coins FROM referrals WHERE referrer_id=?",
                            (user["telegram_id"],)).fetchall()
    total = len(rows)
    completed = sum(int(r["completed"]) for r in rows)
    bonuses = sum(50 for r in rows if int(r["bonus_paid"]))
    commissions = sum(int(r["commission_coins"]) for r in rows)
    link = f"https://t.me/{BOT_USERNAME}?start=ref_{user['telegram_id']}"
    return jsonify({"referral_link": link, "total": total, "completed": completed,
                    "bonus_coins": bonuses, "commission_coins": commissions,
                    "commission_percent": 20, "bonus_per_completed_referral": 50,
                    "ads_required": 5,
                    "note": "Referral attribution is enabled. Bonus/commission payouts stay disabled until Monetag server-side reward verification is configured."})


@app.get("/api/admin/status")
@admin_required
def admin_status():
    return jsonify({"ok": True, "owner_admin_id": OWNER_ADMIN_ID})

@app.get("/api/admin/data")
@admin_required
def admin_data():
    with db() as conn:
        admins = [dict(r) for r in conn.execute("SELECT telegram_id, added_by, created_at FROM admins ORDER BY created_at").fetchall()]
        channels = [dict(r) for r in conn.execute("SELECT channel_id, title, join_url, created_by, created_at FROM required_channels ORDER BY created_at").fetchall()]
        banned = [dict(r) for r in conn.execute("SELECT telegram_id, reason, banned_by, created_at FROM banned_users ORDER BY created_at DESC LIMIT 100").fetchall()]
    return jsonify({"admins": admins, "channels": channels, "banned_users": banned, "owner_admin_id": OWNER_ADMIN_ID})

@app.post("/api/admin/admins")
@admin_required
def manage_admins():
    actor = request.admin_user["telegram_id"]
    data = request.get_json(silent=True) or {}
    target = str(data.get("telegram_id", "")).strip()
    action = str(data.get("action", "")).strip()
    if not target.isdigit():
        return jsonify({"error": "Enter a numeric Telegram user ID."}), 400
    if target == OWNER_ADMIN_ID and action == "remove":
        return jsonify({"error": "Owner admin cannot be removed."}), 400
    if action == "add":
        with db() as conn:
            conn.execute("INSERT OR IGNORE INTO admins(telegram_id, added_by, created_at) VALUES(?,?,?)",
                         (target, actor, int(time.time())))
    elif action == "remove":
        with db() as conn:
            conn.execute("DELETE FROM admins WHERE telegram_id=?", (target,))
    else:
        return jsonify({"error": "Action must be add or remove."}), 400
    return jsonify({"ok": True})

@app.post("/api/admin/balance")
@admin_required
def admin_balance():
    actor = request.admin_user["telegram_id"]
    data = request.get_json(silent=True) or {}
    target = str(data.get("telegram_id", "")).strip()
    action = str(data.get("action", "")).strip()
    try:
        amount = int(data.get("amount", 0))
    except (ValueError, TypeError):
        amount = 0
    if not target.isdigit() or amount <= 0 or amount > 100000000:
        return jsonify({"error": "Enter numeric user ID and a positive coin amount."}), 400
    if action not in ("add", "remove"):
        return jsonify({"error": "Action must be add or remove."}), 400
    delta = amount if action == "add" else -amount
    now = int(time.time())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT balance FROM users WHERE telegram_id=?", (target,)).fetchone()
        if not row:
            conn.rollback()
            return jsonify({"error": "User not found. They must open the Mini App at least once first."}), 404
        if row["balance"] + delta < 0:
            conn.rollback()
            return jsonify({"error": "Insufficient balance to remove that many coins."}), 400
        conn.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?", (delta, target))
        conn.execute("INSERT INTO balance_logs(target_id, admin_id, delta, note, created_at) VALUES(?,?,?,?,?)",
                     (target, actor, delta, str(data.get("note", "admin adjustment"))[:200], now))
        conn.execute("INSERT INTO wallet_transactions(telegram_id,delta_coins,reason,reference_id,created_at) VALUES(?,?,?,?,?)",
                     (target, delta, "Admin balance adjustment", "admin:"+actor, now))
        conn.commit()
    return jsonify({"ok": True, "new_balance": row["balance"] + delta})

@app.post("/api/admin/channels")
@admin_required
def manage_channels():
    actor = request.admin_user["telegram_id"]
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).strip()
    raw = str(data.get("channel", "")).strip()
    if action == "remove":
        with db() as conn:
            cur = conn.execute("DELETE FROM required_channels WHERE channel_id=?", (raw,))
        if not cur.rowcount and raw.startswith("@"):
            with db() as conn:
                cur = conn.execute("DELETE FROM required_channels WHERE join_url LIKE ?", ("%"+raw.lstrip("@")+"%",))
        if not cur.rowcount:
            return jsonify({"error": "Channel not found. Remove it using its stored numeric ID."}), 404
        return jsonify({"ok": True})
    if action != "add" or not raw:
        return jsonify({"error": "Provide channel and action add/remove."}), 400
    channel_id = raw
    join_url = ""
    title = raw
    if raw.startswith("@"):
        username = raw[1:]
        join_url = f"https://t.me/{username}"
        channel_id = raw
    elif raw.lstrip("-").isdigit():
        channel_id = raw
        join_url = str(data.get("join_url", "")).strip()
    else:
        return jsonify({"error": "Use @channelusername or numeric channel ID."}), 400
    # Validate access via Telegram API and infer title; public username is easiest for join links.
    try:
        resp = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getChat",
                            params={"chat_id": channel_id}, timeout=10)
        result = resp.json()
        if not result.get("ok"):
            return jsonify({"error": "Bot cannot access this channel. Add bot as admin and verify the channel ID/username."}), 400
        title = result["result"].get("title", title)
        if not join_url:
            invite = str(data.get("join_url", "")).strip()
            if not invite.startswith("https://t.me/"):
                return jsonify({"error": "For a private channel ID, provide its invite URL in join_url."}), 400
            join_url = invite
    except requests.RequestException:
        return jsonify({"error": "Could not reach Telegram API."}), 502
    with db() as conn:
        conn.execute("INSERT OR REPLACE INTO required_channels(channel_id, title, join_url, created_by, created_at) VALUES(?,?,?,?,?)",
                     (channel_id, title, join_url, actor, int(time.time())))
    return jsonify({"ok": True, "title": title, "channel_id": channel_id})

@app.post("/api/admin/ban")
@admin_required
def admin_ban():
    actor = request.admin_user["telegram_id"]
    data = request.get_json(silent=True) or {}
    target = str(data.get("telegram_id", "")).strip()
    action = str(data.get("action", "")).strip()
    reason = str(data.get("reason", ""))[:200]
    if not target.isdigit():
        return jsonify({"error": "Enter a numeric Telegram user ID."}), 400
    if target == OWNER_ADMIN_ID:
        return jsonify({"error": "Owner admin cannot be banned."}), 400
    with db() as conn:
        if action == "ban":
            conn.execute("INSERT OR REPLACE INTO banned_users(telegram_id, reason, banned_by, created_at) VALUES(?,?,?,?)",
                         (target, reason, actor, int(time.time())))
        elif action == "unban":
            conn.execute("DELETE FROM banned_users WHERE telegram_id=?", (target,))
        else:
            return jsonify({"error": "Action must be ban or unban."}), 400
    return jsonify({"ok": True})


def send_bot_reply(chat_id, text, keyboard=None):
    """Send a bot reply using the server-side token; never expose the token to the browser."""
    if not BOT_TOKEN:
        app.logger.error("BOT_TOKEN is not configured; cannot reply to Telegram commands")
        return False
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = {"inline_keyboard": keyboard}
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json=payload, timeout=15
    )
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        app.logger.error("Telegram sendMessage failed: %s", data.get("description", "unknown error"))
        return False
    return True


@app.post("/telegram-webhook")
def telegram_webhook():
    # Configure the same secret with Telegram setWebhook's secret_token parameter.
    if not WEBHOOK_SECRET:
        app.logger.error("WEBHOOK_SECRET is not configured")
        return jsonify({"error": "Webhook is not configured"}), 503
    supplied_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if not hmac.compare_digest(supplied_secret, WEBHOOK_SECRET):
        return jsonify({"error": "Forbidden"}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or update.get("edited_message") or {}
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    text = (message.get("text") or "").strip()
    chat_id = chat.get("id")
    sender_id = str(sender.get("id", ""))
    if not chat_id or not text.startswith("/"):
        return jsonify({"ok": True})

    command = text.split()[0].split("@", 1)[0].lower()
    if command == "/start":
        parts = text.split(maxsplit=1)
        if len(parts) > 1 and parts[1].startswith("ref_"):
            referrer_id = parts[1][4:].strip()
            if referrer_id.isdigit() and referrer_id != sender_id and sender_id.isdigit():
                with db() as conn:
                    existing_user = conn.execute("SELECT 1 FROM users WHERE telegram_id=?", (sender_id,)).fetchone()
                    existing_ref = conn.execute("SELECT 1 FROM referrals WHERE referred_id=?", (sender_id,)).fetchone()
                    if not existing_user and not existing_ref:
                        conn.execute("INSERT OR IGNORE INTO pending_referrals(referred_id, referrer_id, created_at) VALUES(?,?,?)",
                                     (sender_id, referrer_id, int(time.time())))
        keyboard = [[{"text": "🪙 Open CoinNest", "web_app": {"url": PUBLIC_URL + "/"}}]]
        send_bot_reply(chat_id,
                       "Welcome to CoinNest! 🪙\nOpen the Mini App below to view your rewards and wallet.",
                       keyboard)
    elif command == "/adminpanel":
        if sender_id != OWNER_ADMIN_ID:
            send_bot_reply(chat_id, "Your not admin 🚫")
        else:
            keyboard = [[{"text": "🔐 Open Admin Panel", "web_app": {"url": PUBLIC_URL + "/adminpanel"}}]]
            send_bot_reply(chat_id, "Admin access verified. Open your admin panel below.", keyboard)
    return jsonify({"ok": True})


@app.get("/adminpanel")
def adminpanel():
    return render_template("admin.html", bot_username=BOT_USERNAME)

def _telegram_member(channel_id, telegram_id):
    if not BOT_TOKEN:
        return False
    try:
        r = requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember", params={"chat_id": channel_id, "user_id": telegram_id}, timeout=10)
        data = r.json(); member = data.get("result", {}); status = member.get("status", "")
        return bool(data.get("ok") and (status in ("creator", "administrator", "member") or (status == "restricted" and member.get("is_member", False))))
    except requests.RequestException:
        return False

@app.post("/api/lifafas")
@require_user
def create_lifafa():
    user=request.user_data; data=request.get_json(silent=True) or {}
    title=str(data.get("title", "")).strip()[:100]
    try: amount_rupees=int(data.get("amount_per_user", 0)); slots=int(data.get("total_users", 0))
    except (TypeError, ValueError): return jsonify({"error":"Enter a valid amount and user count."}),400
    channels=data.get("channels", [])
    password=str(data.get("password", ""))[:128]
    if not title: return jsonify({"error":"Lifafa title is required."}),400
    if amount_rupees < 1 or amount_rupees > 100000 or slots < 1 or slots > 100000: return jsonify({"error":"Amount and total users must be positive and within limits."}),400
    if not isinstance(channels,list) or not 1 <= len(channels) <= 6: return jsonify({"error":"Add between 1 and 6 required channels."}),400
    clean=[]; seen=set()
    for ch in channels:
        cid=str((ch or {}).get("channel_id", "")).strip(); url=str((ch or {}).get("join_url", "")).strip()
        if not cid or not url.startswith("https://t.me/"): return jsonify({"error":"Each channel needs a valid channel ID and Telegram invite link."}),400
        if cid in seen: continue
        seen.add(cid)
        try:
            check=requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getChatMember",params={"chat_id":cid,"user_id":(requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getMe",timeout=10).json().get("result") or {}).get("id")},timeout=10).json()
        except requests.RequestException: check={}
        if not check.get("ok") or check.get("result",{}).get("status") not in ("administrator","creator"):
            return jsonify({"error":f"First make bot admin in {cid} and try again."}),400
        clean.append({"channel_id":cid,"join_url":url,"title":str(ch.get("title") or cid)[:120]})
    if not 1 <= len(clean) <= 6: return jsonify({"error":"Add between 1 and 6 unique channels."}),400
    total_coins=amount_rupees*COINS_PER_RUPEE*slots; now=int(time.time()); lid=uuid.uuid4().hex[:16]
    password_hash=hashlib.sha256(password.encode()).hexdigest() if password else ""
    with db() as conn:
        conn.execute("BEGIN")
        wallet=conn.execute("SELECT balance FROM users WHERE telegram_id=? FOR UPDATE",(user["telegram_id"],)).fetchone()
        if not wallet or int(wallet["balance"]) < total_coins:
            conn.rollback(); return jsonify({"error":f"Insufficient balance. This lifafa needs {total_coins:,} coins."}),400
        conn.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?",(total_coins,user["telegram_id"]))
        conn.execute("INSERT INTO lifafas(id,creator_id,title,amount_per_user_coins,total_slots,remaining_slots,reserved_coins,channels_json,password_hash,refer_enabled,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (lid,user["telegram_id"],title,amount_rupees*COINS_PER_RUPEE,slots,slots,total_coins,json.dumps(clean),password_hash,bool(data.get("refer_enabled")),"active",now))
        conn.execute("INSERT INTO wallet_transactions(telegram_id,delta_coins,reason,reference_id,created_at) VALUES(?,?,?,?,?)",(user["telegram_id"],-total_coins,"Lifafa created: "+title,lid,now))
        conn.commit()
    return jsonify({"ok":True,"lifafa_id":lid,"share_url":f"https://t.me/{BOT_USERNAME}/{MINI_APP_SHORT_NAME}?startapp=lifafa_{lid}","reserved_coins":total_coins,"balance_after":int(wallet["balance"])-total_coins})

@app.get("/api/lifafa/<lifafa_id>")
@require_user
def lifafa_details(lifafa_id):
    if not re.fullmatch(r"[a-f0-9]{16}", lifafa_id): return jsonify({"error":"Invalid Lifafa link."}), 400
    with db() as conn:
        row=conn.execute("SELECT id,title,amount_per_user_coins,total_slots,remaining_slots,channels_json,password_hash,status,creator_id FROM lifafas WHERE id=?",(lifafa_id,)).fetchone()
        if not row: return jsonify({"error":"Lifafa not found."}),404
        channels=json.loads(row["channels_json"])
        joined=[dict(ch,joined=_telegram_member(ch["channel_id"],request.user_data["telegram_id"])) for ch in channels]
    return jsonify({"id":row["id"],"title":row["title"],"amount_coins":row["amount_per_user_coins"],"remaining_slots":row["remaining_slots"],"total_slots":row["total_slots"],"requires_password":bool(row["password_hash"]),"channels":joined,"status":row["status"]})

@app.post("/api/lifafa/<lifafa_id>/claim")
@require_user
def claim_lifafa(lifafa_id):
    if not re.fullmatch(r"[a-f0-9]{16}", lifafa_id): return jsonify({"error":"Invalid Lifafa link."}), 400
    user=request.user_data; data=request.get_json(silent=True) or {}; password=str(data.get("password", ""))[:128]; now=int(time.time())
    with db() as conn:
        conn.execute("BEGIN")
        lf=conn.execute("SELECT * FROM lifafas WHERE id=? FOR UPDATE",(lifafa_id,)).fetchone()
        if not lf: conn.rollback(); return jsonify({"error":"Lifafa not found."}),404
        if lf["status"]!="active" or int(lf["remaining_slots"])<=0 or int(lf["reserved_coins"])<int(lf["amount_per_user_coins"]):
            conn.rollback(); return jsonify({"error":"This lifafa is full or no longer active."}),409
        if conn.execute("SELECT 1 FROM lifafa_claims WHERE lifafa_id=? AND telegram_id=?",(lifafa_id,user["telegram_id"])).fetchone():
            conn.rollback(); return jsonify({"error":"You have already claimed this lifafa."}),409
        if lf["password_hash"] and not hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(),lf["password_hash"]):
            conn.rollback(); return jsonify({"error":"Incorrect lifafa password."}),403
        channels=json.loads(lf["channels_json"])
        missing=[ch for ch in channels if not _telegram_member(ch["channel_id"],user["telegram_id"])]
        if missing:
            conn.rollback(); return jsonify({"error":"Join all required channels first.","required_channels":missing}),428
        reward=int(lf["amount_per_user_coins"])
        conn.execute("INSERT INTO lifafa_claims(lifafa_id,telegram_id,amount_coins,created_at) VALUES(?,?,?,?)",(lifafa_id,user["telegram_id"],reward,now))
        conn.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?",(reward,user["telegram_id"]))
        remaining=int(lf["remaining_slots"])-1; reserved=int(lf["reserved_coins"])-reward
        conn.execute("UPDATE lifafas SET remaining_slots=?,reserved_coins=?,status=? WHERE id=?",(remaining,reserved,"completed" if remaining==0 else "active",lifafa_id))
        conn.execute("INSERT INTO wallet_transactions(telegram_id,delta_coins,reason,reference_id,created_at) VALUES(?,?,?,?,?)",(user["telegram_id"],reward,"Lifafa claimed: "+lf["title"],lifafa_id,now))
        conn.commit()
    return jsonify({"ok":True,"coins_added":reward,"remaining_slots":remaining,"message":f"Claim successful! {reward:,} coins added to your wallet."})

@app.get("/api/wallet/history")
@require_user
def wallet_history():
    with db() as conn:
        rows=conn.execute("SELECT id,delta_coins,reason,reference_id,created_at FROM wallet_transactions WHERE telegram_id=? ORDER BY id DESC LIMIT 100",(request.user_data["telegram_id"],)).fetchall()
    return jsonify({"transactions":[dict(x) for x in rows]})

@app.get("/health")
def health():
    return jsonify({"ok": True})

init_db()
if __name__ == "__main__":
    # For local development only. Use HTTPS/reverse proxy before public launch.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
