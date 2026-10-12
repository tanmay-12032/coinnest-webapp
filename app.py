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
            conn.execute("""INSERT INTO users(telegram_id, username, first_name, last_name, created_at)
                VALUES(?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET
                username=excluded.username, first_name=excluded.first_name, last_name=excluded.last_name""",
                (user["telegram_id"], user["username"], user["first_name"], user["last_name"], int(time.time())))
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
    user = request.user_data
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
    # Deliberately disabled until a real ad provider callback/signature is integrated.
    return jsonify({"error": "Ad rewards are disabled until the ad provider's server-side verification is connected."}), 501

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

@app.get("/health")
def health():
    return jsonify({"ok": True})

init_db()
if __name__ == "__main__":
    # For local development only. Use HTTPS/reverse proxy before public launch.
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=False)
