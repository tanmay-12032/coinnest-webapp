CoinNest Telegram Mini App + Flask backend
===========================================

IMPORTANT TOKEN SECURITY
- A bot token was shared in chat. Revoke it with @BotFather and generate a NEW token.
- Never paste the token into HTML, JavaScript, this ZIP, or a public repository.
- Set it only as the BOT_TOKEN environment variable in the Termux shell/server environment.

FILES
- app.py: Flask backend, SQLite, Telegram Mini App initData validation, withdrawal channel notification
- templates/index.html: website
- static/style.css: design
- static/app.js: frontend interactions

TERMUX SETUP
1) Extract the ZIP into ~/coinnest_bot_webapp
2) Run:
   pkg update
   pkg install python -y
   pip install flask requests
3) Set your NEW token privately (input is hidden):
   read -s -p "New bot token: " BOT_TOKEN
   export BOT_TOKEN
   echo
   export CHANNEL_ID="-1004352766896"
   export BOT_USERNAME="CoinNest_bot"
   export DEMO_MODE="1"
4) Run:
   cd ~/coinnest_bot_webapp
   python app.py
5) Open in Chrome:
   http://127.0.0.1:5000

DEMO MODE
DEMO_MODE=1 lets you preview the UI locally using a demo profile. Demo users start with zero balance.
Before real deployment, set DEMO_MODE=0 and use Telegram's Mini App button to open the website inside Telegram.
Telegram Mini App authentication requires HTTPS/public hosting and the bot's Mini App URL configured with BotFather.
The backend validates Telegram WebApp initData with the bot token. Do not trust user identity sent from browser JavaScript alone.

BOT CHANNEL SETUP
- Add the bot to channel -1004352766896.
- Grant permission to post messages.
- Channel requests contain Telegram ID, display name, username, requested amount, and UPI ID. Treat UPI IDs as personal data and restrict channel access.

WITHDRAWALS
- 100 coins = ₹1; minimum request ₹10.
- The backend reserves coins when a request is submitted and refunds them if sending the channel notification fails.
- Channel requests are pending manual review; this code does not transfer money.
- This is a starter project, not a production payout system. Add rate limiting, admin authorization, audit logs, privacy notice, HTTPS, backups, and review before public launch.

ADS
Ad rewards are intentionally disabled. Connect your actual ad provider's server-to-server verification callback before crediting coins. Never grant rewards based only on a client-side click.

LOCAL TESTING
With DEMO_MODE=1, profile and API preview work locally. Withdrawal attempts require a balance; demo starts at 0. Do not add a fake balance to a live system.
