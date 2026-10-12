import os, json, hmac, hashlib, sqlite3, time
from urllib.parse import parse_qsl
from functools import wraps
import requests
from flask import Flask, request, jsonify, render_template

app = Flask(__name__)
DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "coinnest.db"))
BOT_TOKEN = os.environ.get("BOT_TOKEN", "").strip()
BOT_USERNAME = os.environ.get("BOT_USERNAME", "CoinNest_bot").strip().lstrip("@")
CHANNEL_ID = os.environ.get("CHANNEL_ID", "").strip()
DEMO_MODE = os.environ.get("DEMO_MODE", "1") == "1"
COINS_PER_RUPEE = 100
COINS_PER_AD = 10
DAILY_AD_LIMIT = 25
MIN_WITHDRAW_RUPEES = 10
OWNER_ADMIN_ID = os.environ.get("OWNER_ADMIN_ID", "1849699189").strip()
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://coinnest-webapp.onrender.com").strip().rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "").strip()

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            telegram_id TEXT PRIMARY KEY, username TEXT, first_name TEXT, last_name TEXT,
            balance INTEGER NOT NULL DEFAULT 0, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT NOT NULL,
            amount_rupees INTEGER NOT NULL, amount_coins INTEGER NOT NULL, upi_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending', created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS ad_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT, telegram_id TEXT NOT NULL, day TEXT NOT NULL,
            created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS admins (
            telegram_id TEXT PRIMARY KEY, added_by TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS banned_users (
            telegram_id TEXT PRIMARY KEY, reason TEXT NOT NULL DEFAULT '', banned_by TEXT NOT NULL,
            created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS required_channels (
            channel_id TEXT PRIMARY KEY, title TEXT NOT NULL, join_url TEXT NOT NULL,
            created_by TEXT NOT NULL, created_at INTEGER NOT NULL)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS balance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, target_id TEXT NOT NULL, admin_id TEXT NOT NULL,
            delta INTEGER NOT NULL, note TEXT NOT NULL, created_at INTEGER NOT NULL)""")
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
            conn.execute("""INSERT INTO users(telegram_id, username, first_name, last_name, created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name""",
                (user["telegram_id"], user["username"], user["first_name"], user["last_name"], int(time.time())))
        if request.path != "/api/join-status":
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
def index():
    return render_template("index.html", bot_username=BOT_USERNAME, demo_mode=DEMO_MODE)

@app.get("/api/config")
def config():
    return jsonify({"bot_username": BOT_USERNAME, "demo_mode": DEMO_MODE,
                    "coins_per_rupee": COINS_PER_RUPEE, "coins_per_ad": COINS_PER_AD,
                    "daily_ad_limit": DAILY_AD_LIMIT, "min_withdraw_rupees": MIN_WITHDRAW_RUPEES})

@app.get("/api/me")
@require_user
def me():
    user = current_user()
    today = time.strftime("%Y-%m-%d", time.localtime())
    with db() as conn:
        row = conn.execute("SELECT balance FROM users WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
        ads = conn.execute("SELECT COUNT(*) n FROM ad_claims WHERE telegram_id=? AND day=?",
                           (user["telegram_id"], today)).fetchone()["n"]
        history = conn.execute("SELECT id, amount_rupees, amount_coins, upi_id, status, created_at FROM withdrawals WHERE telegram_id=? ORDER BY id DESC LIMIT 10",
                               (user["telegram_id"],)).fetchall()
    return jsonify({"user": user, "balance": row["balance"], "ads_today": ads,
                    "withdrawals": [dict(x) for x in history]})

@app.post("/api/claim-ad")
@require_user
def claim_ad():
    """Credit one reward after the AdsGram rewarded SDK reports completion.

    Note: this uses the standard client-side AdsGram callback. It is not equivalent
    to a signed server-to-server proof, so use this for the standard SDK flow and
    keep strict limits. Never expose BOT_TOKEN in the frontend.
    """
    user = request.user_data
    today = time.strftime("%Y-%m-%d", time.localtime())
    now = int(time.time())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT COUNT(*) AS n FROM ad_claims WHERE telegram_id=? AND day=?",
                           (user["telegram_id"], today)).fetchone()
        count = int(row["n"] if row else 0)
        if count >= DAILY_AD_LIMIT:
            conn.rollback()
            return jsonify({"error": f"Daily ad limit reached ({DAILY_AD_LIMIT} ads). Come back tomorrow."}), 429
        conn.execute("INSERT INTO ad_claims(telegram_id, day, created_at) VALUES(?,?,?)",
                     (user["telegram_id"], today, now))
        conn.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?",
                     (COINS_PER_AD, user["telegram_id"]))
        conn.commit()
    return jsonify({"ok": True, "reward": COINS_PER_AD,
                    "message": f"Success! {COINS_PER_AD} coins added.",
                    "ads_today": count + 1, "daily_limit": DAILY_AD_LIMIT})

@app.post("/api/withdraw")
@require_user
def withdraw():
    user = request.user_data
    payload = request.get_json(silent=True) or {}
    upi_id = str(payload.get("upi_id", "")).strip()
    try:
        amount = int(payload.get("amount_rupees", 0))
    except (ValueError, TypeError):
        amount = 0
    if not (5 <= len(upi_id) <= 100) or "@" not in upi_id or any(ch.isspace() for ch in upi_id):
        return jsonify({"error": "Enter a valid UPI ID, for example name@bank."}), 400
    if amount < MIN_WITHDRAW_RUPEES:
        return jsonify({"error": f"Minimum withdrawal is ₹{MIN_WITHDRAW_RUPEES}."}), 400
    coins = amount * COINS_PER_RUPEE
    now = int(time.time())
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT balance FROM users WHERE telegram_id=?", (user["telegram_id"],)).fetchone()
        if not row or row["balance"] < coins:
            conn.rollback()
            return jsonify({"error": "Insufficient coin balance."}), 400
        cur = conn.execute("INSERT INTO withdrawals(telegram_id, amount_rupees, amount_coins, upi_id, created_at) VALUES(?,?,?,?,?)",
                           (user["telegram_id"], amount, coins, upi_id, now))
        withdrawal_id = cur.lastrowid
        conn.execute("UPDATE users SET balance=balance-? WHERE telegram_id=?", (coins, user["telegram_id"]))
        conn.commit()
    message = (
        "🪙 <b>CoinNest Withdrawal Request</b>\n"
        f"Request: <b>#{withdrawal_id}</b>\n"
        f"User ID: <code>{user['telegram_id']}</code>\n"
        f"Name: {user['first_name']} {user['last_name']}\n"
        f"Username: @{user['username'] or 'not_set'}\n"
        f"Amount: <b>₹{amount}</b> ({coins} coins)\n"
        f"UPI ID: <code>{upi_id}</code>\n"
        "Status: <b>Pending manual review</b>"
    )
    try:
        telegram_send_message(message)
    except Exception as exc:
        # Refund the reserved coins if channel notification failed.
        with db() as conn:
            conn.execute("UPDATE users SET balance=balance+? WHERE telegram_id=?", (coins, user["telegram_id"]))
            conn.execute("UPDATE withdrawals SET status='notification_failed' WHERE id=?", (withdrawal_id,))
        app.logger.exception("Withdrawal channel notification failed")
        return jsonify({"error": "Could not send request to the Telegram channel. Coins have been returned. Check bot permissions and server configuration."}), 502
    return jsonify({"ok": True, "message": f"Withdrawal request #{withdrawal_id} sent for manual review."})


@app.get("/api/join-status")
@require_user
def api_join_status():
    user = request.user_data
    return jsonify({"required_channels": join_status(user["telegram_id"])})

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

@app.get("/health")
def health():
    return jsonify({"ok": True})

init_db()
if __name__ == "__main__":
    # For local development only. Use HTTPS/reverse proxy before public launch.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
