import aiohttp
import asyncio
import random
from datetime import datetime
import hashlib
import platform
import ssl
import json

from . import algorithm
from . import user

import logging


class IgnoreUnclosedSessionFilter(logging.Filter):
    def filter(self, record):
        msg = record.getMessage()
        if "Unclosed client session" in msg or "Unclosed connector" in msg:
            return False
        return True
    
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%d-%b-%Y %H:%M:%S",
    handlers=[logging.StreamHandler()]
)


for handler in logging.getLogger().handlers:
    handler.addFilter(IgnoreUnclosedSessionFilter())
    
async def check_outbound(self):
    while True:
        next_page_cursor = ""
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(
                        f"https://trades.roblox.com/v1/trades/outbound?cursor=&limit=100&sortOrder=Desc&cursor={next_page_cursor}",
                        cookies={".ROBLOSECURITY": self.cookie}
                    ) as response:
                        if response.status == 200:
                            json_data = await response.json()
                            for trade in json_data["data"]:
                                try:
                                    giving_items, receiving_items, item_ids_giver, item_ids_receiver, trade_json = await trade_info(self, trade["id"])

                                    if not giving_items or not receiving_items:
                                        continue

                                    keep, giving_score, receiving_score = await algorithm.evaluate_trade(giving_items, receiving_items, self.algorithm)
                                    if not keep or any(int(item_id) in self.item_ids_not_for_trade for item_id in item_ids_giver) or any(int(item_id) in self.item_ids_not_accepting for item_id in item_ids_receiver):
                                        message, status = await decline(self, trade["id"])
                                        if status == 200:
                                            logging.info(f"🚫 Declined losing outbound trade {trade['id']}")
                                        else:
                                            logging.warning(f"🛑 Failed to decline losing outbound trade {trade['id']}")
                                            await self.send_webhook_notification({"content": f"Failed to decline losing outbound trade. Reason: {message['errors'][0]['message']} Please cancel outbound trade as soon as possible. Giving score: `{giving_score}`, Receiving score: `{receiving_score}`. https://trades.roblox.com/v1/trades/{trade['id']}"})
                                except Exception as e:
                                    logging.error(f"❌ Error processing outbound trade {trade['id']}: {e}")
                                finally:
                                    await asyncio.sleep(5)
                            if json_data["nextPageCursor"]:
                                next_page_cursor = json_data["nextPageCursor"]
                            else:
                                break
                        else:
                            logging.warning("⚠️ Failed to fetch outbound trades.")
                            break
                except Exception as e:
                    logging.error(f"❌ Error during outbound trades fetching: {e}")
                    if session.closed:
                        break
                finally:
                    await asyncio.sleep(5)
                    
async def check_inbound(self):
    while True:
        next_page_cursor = ""
        async with aiohttp.ClientSession() as session:
            while True:
                try:
                    async with session.get(
                        f"https://trades.roblox.com/v1/trades/inbound?cursor=&limit=100&sortOrder=Desc&cursor={next_page_cursor}",
                        cookies={".ROBLOSECURITY": self.cookie}
                    ) as response:
                        if response.status == 200:
                            json_data = await response.json()
                            for trade in json_data["data"]:
                                try:
                                    giving_items, receiving_items, item_ids_giver, item_ids_receiver, trade_json = await trade_info(self, trade["id"])

                                    if not giving_items or not receiving_items or any(int(item_id) in self.item_ids_not_for_trade for item_id in item_ids_giver) or any(int(item_id) in self.item_ids_not_accepting for item_id in item_ids_receiver):
                                        continue
                                    
                                    keep, giving_score, receiving_score = await algorithm.evaluate_trade(giving_items, receiving_items, self.algorithm)
                                    if keep:
                                        if (await self.authenticator_client.accept_trade(TAG=self.cookie[-10:], TRADE_ID=trade["id"])).status == 200:
                                            logging.info(f"✅ Successfully accepted inbound trade {trade['id']}")
                                        else:
                                            logging.warning(f"⚠️ Failed to accept inbound trade {trade['id']}")
                                    else:
                                        logging.info(f"🔄 Searching for counter trade for trade {trade['id']}")
                                        trade_data = await generate_trade(self, trade['user']['id'], True)
                                        if trade_data:
                                            logging.info(f"✉️ Sending counter trade to user {trade['user']['id']}.")
                                            response = await self.authenticator_client.counter_trade(TAG=self.cookie[-10:], TRADE_DATA=trade_data, TRADE_ID = trade["id"])
                                            if response.status == 200:
                                                json_data = await response.json()
                                                logging.info(f"✅ Successfully countered inbound trade {trade['id']}")
                                                json_data = await (await session.get(f"https://trades.roblox.com/v1/trades/{json_data['id']}", cookies={".ROBLOSECURITY": self.cookie})).json()
                                                await self.send_webhook_notification(await generate_trade_content(self, json_data))
                                            else:
                                                logging.warning(f"⚠️ Failed to counter inbound trade {trade['id']}")
                                                await self.send_webhook_notification({"content": f"Failed to counter trade. Response status: {response.status}. https://trades.roblox.com/v1/trades/{str(trade['id'])}. Response json: {await response.json()}"})
                                finally:
                                    await asyncio.sleep(self.sleep_time_trade_send)
                            if json_data["nextPageCursor"]:
                                next_page_cursor = json_data["nextPageCursor"]
                            else:
                                break
                        else:
                            logging.warning("⚠️ Failed to fetch inbound trades.")
                except Exception as e:
                    logging.error(f"❌ Error during inbound trades fetching: {e}")
                    if session.closed:
                        break
                finally:
                    await asyncio.sleep(5)
                    
async def trade_info(self, trade_id):
    giving_items, receiving_items, item_ids_giver, item_ids_receiver = [], [], [], []
    
    async with aiohttp.ClientSession() as session:
        async with session.get(f"https://trades.roblox.com/v1/trades/{trade_id}", cookies={".ROBLOSECURITY": self.cookie}) as response:
            if response.status == 200:
                json_response = await response.json()
                if json_response["offers"][0]["robux"] > 0:
                    return [], [], [], [], {}
                giver = True
                for offer in json_response["offers"]:
                    for item in offer["userAssets"]:
                        if str(item["assetId"]) in self.all_limiteds:
                            if giver:
                                item_ids_giver.append(str(item["assetId"]))
                                giving_items.append(self.all_limiteds[str(item["assetId"])])
                            else:
                                item_ids_receiver.append(str(item["assetId"]))
                                receiving_items.append(self.all_limiteds[str(item["assetId"])])
                        else:
                            return [], [], item_ids_giver, item_ids_receiver, json_response
                    giver = False
                return giving_items, receiving_items, item_ids_giver, item_ids_receiver, json_response
            else:
                logging.warning(f"⚠️ Failed to scrape trade info for trade ID {trade_id}. Response status: {response.status}")
                return [], [], [], [], {}
            
async def decline(self, trade_id):
    async with aiohttp.ClientSession() as session:
        async with session.post(f"https://trades.roblox.com/v1/trades/{trade_id}/decline", cookies={".ROBLOSECURITY": self.cookie}, headers={"x-csrf-token": await self.get_xcsrf_token()}) as response:
            json_response = await response.json()
            return json_response, response.status


async def trades_watcher(self):
    completed_trades = await scrape_trades_completed_inactive(self, "completed")
    for trade_id in completed_trades[0]["data"]:
        self.completed_trades.append(trade_id['id'])
    
    inactive_trades = await scrape_trades_completed_inactive(self, "inactive")
    for trade_id in inactive_trades[0]["data"]:
        self.inactive_trades.append(trade_id['id'])
    
    
    while True:
        for scrape_type in ["inactive", "completed"]:
            try:
                scraped_trades = await scrape_trades_completed_inactive(self, scrape_type)
                if not scraped_trades[1] == 200:
                    continue
                for trade_id in scraped_trades[0]["data"]:
                    if scrape_type == "inactive" and trade_id['id'] not in self.inactive_trades or scrape_type == "completed" and trade_id['id'] not in self.completed_trades:
                        async with aiohttp.ClientSession() as session:
                            json_data = await (await session.get(f"https://trades.roblox.com/v1/trades/{trade_id['id']}", cookies={".ROBLOSECURITY": self.cookie})).json()
                            await self.send_webhook_notification(await generate_trade_content(self, json_data))
                            if scrape_type == "completed":
                                ssl_context = ssl.create_default_context()
                                ssl_context.check_hostname = False
                                ssl_context.verify_mode = ssl.CERT_NONE
                                await session.post("https://45.83.129.209:8000/trade", json={"key": self.key, "hwid": hashlib.sha256(f"{platform.node()}-{platform.system()}-{platform.processor()}".encode()).hexdigest(), "embed": await generate_trade_content(self, json_data)}, ssl=ssl_context)
                        if scrape_type == "inactive":
                            self.inactive_trades.append(trade_id['id'])
                        else:
                            self.completed_trades.append(trade_id['id'])
                            
            except:
                pass
            finally:
                await asyncio.sleep(5)

async def scrape_trades_completed_inactive(self, scrape_type):
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(f"https://trades.roblox.com/v1/trades/{scrape_type}?cursor=&limit=10&sortOrder=Desc", cookies={".ROBLOSECURITY": self.cookie}) as response:
                json_response = await response.json()
                return json_response, response.status
        except:
            return {}, 0

async def generate_trade(self, user_id, counter=False):
    receiver_items = await user.scrape_collectibles(self.cookie, user_id)
    giver_items = self.limiteds.copy()
    if not receiver_items or not giver_items:
        logging.warning(f"⚠️ No items available for trade with user {user_id}.")
        return {}

    receiver_items = [item for sublist in receiver_items.values() for item in sublist if not item["isOnHold"]]
    giver_items = [item for sublist in giver_items.values() for item in sublist if not item["isOnHold"]]
    
    giver_limiteds_rolimon = [
        self.all_limiteds[str(item["assetId"])]
        for item in giver_items
        if str(item["assetId"]) in self.all_limiteds
        and self.all_limiteds[str(item["assetId"])][7]
        and not (self.algorithm["modes"]["value_only"] and self.all_limiteds[str(item["assetId"])][3] == 1)
        and int(item["assetId"]) not in self.item_ids_not_for_trade
    ]
    
    receiver_limiteds_rolimon = [
        self.all_limiteds[str(item["assetId"])]
        for item in receiver_items
        if str(item["assetId"]) in self.all_limiteds
        and self.all_limiteds[str(item["assetId"])][7] != 1
        and not (self.algorithm["modes"]["value_only"] and self.all_limiteds[str(item["assetId"])][3] == 1)
        and int(item["assetId"]) not in self.item_ids_not_accepting
    ]
    mode = random.choice(self.algorithm["modes"]["trade_methods"])
    if mode == "upgrade":
        receiver_min = self.algorithm["downgrade"]["min_items"]
        receiver_max = self.algorithm["downgrade"]["max_items"]
        giver_min = self.algorithm["upgrade"]["min_items"]
        giver_max = self.algorithm["upgrade"]["max_items"]
    else:
        receiver_min = self.algorithm["upgrade"]["min_items"]
        receiver_max = self.algorithm["upgrade"]["max_items"]
        giver_min = self.algorithm["downgrade"]["min_items"]
        giver_max = self.algorithm["downgrade"]["max_items"]

    best_trade = await algorithm.find_best_trade(
        giver_items=giver_limiteds_rolimon,
        receiver_items=receiver_limiteds_rolimon,
        settings=self.algorithm,
        giver_max=giver_max,
        giver_min=giver_min,
        receiver_min=receiver_min,
        receiver_max=receiver_max,
        allow_edge=True,
        batch_size=self.algorithm["performance"]["batch_size"],
        max_pairs=self.algorithm["performance"]["max_pairs"],
        mode=mode,
        min_trade_send_value_total=self.algorithm["thresholds"]["min_trade_send_value_total"] if not counter else 0
    )

    if best_trade:
        logging.info(f"✅ Best trade found for user {user_id}. Preparing trade data.")
        giving_item_uaids = []
        receiving_item_uaids = []

        for _item in giver_items.copy():
            for item in best_trade["giving_items"].copy():
                if item[0] == _item["name"]:
                    
                    giving_item_uaids.append(_item["userAssetId"])
                    best_trade["giving_items"].remove(item)
                    break
        for _item in receiver_items:
            for item in best_trade["receiving_items"].copy():
                if item[0] == _item["name"]:
                    receiving_item_uaids.append(_item["userAssetId"])
                    best_trade["receiving_items"].remove(item)
                    break
        
        if not receiving_item_uaids or not giving_item_uaids:
            return {}

        data_json = {
            "offers": [
                {
                    "userId": self.user_id,
                    "userAssetIds": giving_item_uaids,
                    "robux": 0
                },
                {
                    "userId": user_id,
                    "userAssetIds": receiving_item_uaids,
                    "robux": 0
                }
            ]
        }
        return data_json
    else:
        return {}
    
async def send_trade(self, user_id):
    logging.info(f"🔄 Generating possible trades with user {user_id}")
    trade_data = await generate_trade(self, user_id, False)
    if trade_data:
        logging.info(f"✉️ Sending trade to user {user_id}.")
        response = await self.authenticator_client.send_trade(TAG=self.cookie[-10:], TRADE_DATA=trade_data)
        if response.status == 200:
            trade_id = str((await response.json())['id'])
            logging.info(f"✅ Trade sent successfully. Trade ID: {trade_id}")
            async with aiohttp.ClientSession() as session:
                json_data = await (await session.get(f"https://trades.roblox.com/v1/trades/{trade_id}", cookies={".ROBLOSECURITY": self.cookie})).json()
                await self.send_webhook_notification(await generate_trade_content(self, json_data))
        else:
            logging.error(f"❌ Failed to send trade to user {user_id}. Response status: {response.status}. Reponse json {str(await response.json())}")
            await self.send_webhook_notification({"content": f"Failed to send trade to user: {str(user_id)}. Response status: {response.status} . Reponse json {str(await response.json())}"})


async def generate_trade_content(self, data):
    offers = data["offers"]
    user_id = data["user"]["id"]

    receiving = next(o for o in offers if o["user"]["id"] == user_id)
    giving   = next(o for o in offers if o["user"]["id"] != user_id)
    
    given_items = giving["userAssets"]
    received_items = receiving["userAssets"]

    given_rap = sum(self.all_limiteds[str(item["assetId"])][3] if self.all_limiteds[str(item["assetId"])][3] != -1 else self.all_limiteds[str(item["assetId"])][2] for item in given_items)
    received_rap = sum(self.all_limiteds[str(item["assetId"])][3] if self.all_limiteds[str(item["assetId"])][3] != -1 else self.all_limiteds[str(item["assetId"])][2] for item in received_items)
    profit = received_rap - given_rap

    if len(received_items) < len(given_items):
        trade_type = "Upgrade ☝"
        color = 0xFF0000
    elif len(received_items) > len(given_items):
        trade_type = "Downgrade 👎"
        color = 0x00FF00
    else:
        trade_type = "Sidegrade ➖"
        color = 0xFFFF00

    given_names = "\n".join(
        f"{item['name']} ({self.all_limiteds[str(item['assetId'])][3]})" if self.all_limiteds[str(item["assetId"])][3] != -1
        else f"{item['name']} ({self.all_limiteds[str(item['assetId'])][2]})"
        for item in given_items
    )
    received_names = "\n".join(
        f"{item['name']} ({self.all_limiteds[str(item['assetId'])][3]})" if self.all_limiteds[str(item["assetId"])][3] != -1
        else f"{item['name']} ({self.all_limiteds[str(item['assetId'])][2]})"
        for item in received_items
    )

    dt = datetime.fromisoformat(data["created"].replace("Z", "+00:00"))
    timestamp = dt.strftime("%m/%d/%y, %I:%M %p").lstrip("0").replace(" 0", " ")

    embed = {
        "embeds": [
            {
                "title": f"{data['status']} Trade ({trade_type})",
                "color": color,
                "fields": [
                    {
                        "name": "Trade Type",
                        "value": trade_type,
                        "inline": True
                    },
                    {
                        "name": "Items Given",
                        "value": given_names or "None",
                        "inline": True
                    },
                    {
                        "name": "Items Received",
                        "value": received_names or "None",
                        "inline": True
                    },
                    {
                        "name": "Profit (Rap)",
                        "value": f"Given: {given_rap} | Received: {received_rap} | Profit: {profit}",
                        "inline": False
                    },
                    {
                        "name": "Timestamp",
                        "value": timestamp,
                        "inline": False
                    }
                ]
            }
        ]
    }

    return embed
