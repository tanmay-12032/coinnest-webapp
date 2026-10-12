CoinNest AdsGram integration update

Replace these files in your existing project:
- templates/index.html
- static/app.js
- static/style.css
- coinnest_app_updated.py

IMPORTANT: Before deploying, open static/app.js and replace YOUR_ADSGRAM_BLOCK_ID with your numeric AdsGram Reward block ID from partner.adsgram.ai. Use a Reward block, not an Interstitial block.

This uses AdsGram's standard client-side rewarded-ad callback and applies the existing 25-ads/day limit, awarding 10 coins per completed callback. A client-side callback is not the same as a signed server-to-server proof; do not treat it as fraud-proof. Test with a real rewarded block; AdsGram debug mode does not send the Reward URL postback.

Do not upload .env or bot tokens. Keep Render environment variables unchanged. Backup the current files before replacing them.
