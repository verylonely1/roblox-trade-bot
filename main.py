import trader
import json
import asyncio
import logging

from trader.auth.authenticator import AuthenticatorAsync

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%d-%b-%Y %H:%M:%S",
    handlers=[logging.StreamHandler()]
)

async def main():
    try:
        with open("config.json", encoding="utf-8") as f:
            config = json.load(f)
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



# try:
#     response = requests.post("https://45.83.129.209:8000/validate", json={"key": hashlib.sha256(json.loads(open("config.json", "r").read())["key"].encode('utf-8')).hexdigest(), "hwid": hashlib.sha256(f"{platform.node()}-{platform.system()}-{platform.processor()}".encode()).hexdigest()}, verify=False)
#     if not response.status_code == 200:
#         input("WARNING: Invalid key or not linked HWID. If this continues steps will be taken")
#     else:
asyncio.run(main())
# except Exception as e:
#     input(f"ERROR {e}")