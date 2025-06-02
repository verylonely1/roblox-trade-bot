import aiohttp
from collections import deque
import asyncio

from . import trades


async def post_ad(roli_verification, player_id, offer_item_ids, request_item_ids, request_tags):
    async with aiohttp.ClientSession() as session:
        async with session.post("https://api.rolimons.com/tradeads/v1/createad", json={"player_id": player_id, "offer_item_ids": offer_item_ids, "request_item_ids": request_item_ids, "request_tags": request_tags}, cookies={"_RoliVerification": roli_verification}) as response:
            return response.status == 201
            
async def limiteds():
    async with aiohttp.ClientSession() as session:
        async with session.post("https://rolimons.com/itemapi/itemdetails") as response:
            if response.status == 429:
                return []
            else:
                return (await response.json())["items"]

async def track_trade_ads(self):
    seen_ids = deque(maxlen=500)
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                while True:
                    try:
                        async with session.get("https://api.rolimons.com/tradeads/v1/getrecentads") as response:
                            json_response = await response.json()
                            for trade_ad in json_response["trade_ads"]:
                                user_id = trade_ad[2]
                                if user_id not in seen_ids:
                                    seen_ids.append(user_id)
                                    await trades.send_trade(self, user_id)
                                    await asyncio.sleep(self.sleep_time_trade_send)
                    except:
                        break
                    
        except Exception as outer_error:
            print(f"[tracker] Full session error: {outer_error}")
            await asyncio.sleep(10)
