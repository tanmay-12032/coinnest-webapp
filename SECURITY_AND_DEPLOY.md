CoinNest secure release

Files: app.py, templates/index.html, static/app.js, static/style.css.

Required Vercel environment variables:
- DATABASE_URL: Neon PostgreSQL connection string
- BOT_TOKEN: Telegram bot token (secret; never commit it)
- BOT_USERNAME=CoinNest_bot
- MINI_APP_SHORT_NAME=CoinNest (must exactly match BotFather Mini App short name)
- PUBLIC_URL=https://coinnest-webapp.vercel.app
- OWNER_ADMIN_ID: your Telegram numeric user ID
- WEBHOOK_SECRET: a long random secret if webhook verification is configured
- DEMO_MODE=0 (important: disables unauthenticated demo fallback)

Deploy root directory with these files and folders. Configure BotFather Mini App URL to the deployed HTTPS site. Confirm database tables lifafas, lifafa_claims and wallet_transactions exist before enabling real rewards.

Security improvements included: safer production default (DEMO_MODE off), server-side Telegram initData auth retained, request-size and JSON content-type checks, basic endpoint throttling, security response headers/CSP, Lifafa ID format validation, safe DOM clearing, and Telegram startapp links. Rate limiting is per server process only; use a shared limiter/WAF for multi-instance deployment.

Important limitations: no software can guarantee that injection is impossible. Review every route and test against your live database before real-money/reward use. This archive is not deployed automatically.
