import trader
import json
import asyncio
import logging
import os
from aiohttp import web

from trader.auth.authenticator import AuthenticatorAsync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%d-%b-%Y %H:%M:%S",
    handlers=[logging.StreamHandler()]
)

async def run_bots():
    try:
        with open("config.json", encoding="utf-8") as f:
            config = json.load(f)

        for index, account in enumerate(config.get("accounts", []), start=1):
            cookie_env = f"COOKIE_{index}"
            secret_env = f"OPT_SECRET_{index}"

            account["account"]["cookie"] = os.environ.get(cookie_env, "")
            account["account"]["opt_secret"] = os.environ.get(secret_env, "")

            if not account["account"]["cookie"]:
                logging.warning(f"⚠️ Missing {cookie_env} for account #{index}")
            else:
                logging.info(f"✅ Loaded {cookie_env} for account #{index}")

        logging.info("✅ Configuration loaded successfully!")
    except Exception as e:
        logging.error(f"❌ Failed to load config.json: {e}")
        return

    try:
        auth_client = AuthenticatorAsync()
        logging.info("🔐 Authenticator initialized ✅")
    except Exception as e:
        logging.error(f"❌ Authenticator initialization failed: {e}")
        return

    bots = []
    for index, account_config in enumerate(config.get("accounts", []), start=1):
        try:
            bot_instance = trader.bot(account_config, auth_client)
            bots.append(bot_instance)
            logging.info(f"🤖 Bot #{index:02d} created successfully ✅")
        except Exception as e:
            logging.error(f"❌ Failed to create Bot #{index:02d}: {e}")

    try:
        await asyncio.gather(*(bot.start() for bot in bots))
        logging.info("🚀 All bots are now running! ✅")
    except Exception as e:
        logging.error(f"🔥 Error during bot startup: {e}")


# --- Web server part for Render ---
async def handle(request):
    return web.Response(text="🤖 Roblox Trade Bot is running!")

async def start_web():
    app = web.Application()
    app.add_routes([web.get("/", handle)])
    port = int(os.environ.get("PORT", 5000))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info(f"🌐 Web server started on port {port}")

async def main():
    # Start bots in the background
    asyncio.create_task(run_bots())

    # Start the web server (keeps process alive for Render)
    await start_web()

    # Keep running
    while True:
        await asyncio.sleep(3600)

if __name__ == "__main__":
    asyncio.run(main())



