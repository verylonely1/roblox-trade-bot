import asyncio
import math
import itertools
from concurrent.futures import ThreadPoolExecutor

executor = ThreadPoolExecutor(max_workers=50)

async def adjust_value(value, rap):
    if rap <= value:
        return value
    p = rap / value
    scaling_factor = 0.1
    raw_multiplier = 1 + scaling_factor * math.tanh(10 * (p - 0.90))
    return value * raw_multiplier

async def item_score(item, settings):
    has_value = item[3] != -1
    if settings["modes"]["rap_only_base"]:
        base = item[2] * settings["modifiers"]["lower_rap_only_item"]
    else:
        base = item[3] if has_value else item[2] * settings["modifiers"]["lower_rap_only_item"]
        if has_value and item[3] != item[4]:
            base = await adjust_value(item[3], item[2])
    demand = max(item[5], 0)
    rare = max(item[9], 0)
    projected = item[7] == 1
    if projected and not has_value:
        base *= settings["modifiers"]["lower_projected_item"]
    bonus = (base / settings["modifiers"]["base_divisor"]) * (
        demand * settings["modifiers"]["demand_multiplier"] +
        rare * settings["modifiers"]["rare_multiplier"]
    )
    return base + bonus

async def total_score(items, settings):
    return sum([await item_score(item, settings) for item in items])

async def apply_bulk_penalty(score, item_count, settings):
    if item_count > 1:
        penalty = settings["penalties"]["bulk_penalty_rate"] * (item_count - 1)
        score *= (1 - penalty)
    return score

async def apply_upgrade_penalty(score, own_items, other_items, settings):
    if len(own_items) < len(other_items):
        score *= settings["penalties"]["upgrade_penalty_multiplier"]
    return score

async def is_valid_upgrade(given_items, max_item_ratio, min_item_ratio):
    total = sum(((item[3] + item[2]) / 2) if item[3] != -1 else item[2] for item in given_items)
    return all(
        ((item[3] + item[2]) / 2 if item[3] != -1 else item[2]) <= total * max_item_ratio and
        ((item[3] + item[2]) / 2 if item[3] != -1 else item[2]) >= total * min_item_ratio
        for item in given_items
    )

async def evaluate_trade(giving_items, receiving_items, settings, allow_edge=False):
    if settings["modes"]["value_only"] and any(item[3] <= 0 for item in receiving_items):
        return 0, 0, 0

    giving_score = await total_score(giving_items, settings)
    receiving_score = await total_score(receiving_items, settings)
    giving_score = await apply_bulk_penalty(giving_score, len(giving_items), settings)
    receiving_score = await apply_bulk_penalty(receiving_score, len(receiving_items), settings)
    giving_score = await apply_upgrade_penalty(giving_score, giving_items, receiving_items, settings)
    receiving_score = await apply_upgrade_penalty(receiving_score, receiving_items, giving_items, settings)
    giving_raw = sum(item[3] if item[3] != -1 else item[2] for item in giving_items)
    receiving_raw = sum(item[3] if item[3] != -1 else item[2] for item in receiving_items)
    downgrading = max(giving_items, key=lambda item: item[3] if item[3] != -1 else item[2]) > max(receiving_items, key=lambda item: item[3] if item[3] != -1 else item[2])
    upgrading = not downgrading


    decision = 0
    if upgrading:
        if giving_raw < receiving_raw * settings["thresholds"]["max_giving_value_when_upgrading"] and (receiving_raw < giving_raw and allow_edge or True and not allow_edge):
            decision = 1 if await is_valid_upgrade(
                giving_items,
                settings["item_ratio_constraints"]["max_item_ratio_upgrade"],
                settings["item_ratio_constraints"]["min_item_ratio_upgrade"]
            ) else 0

    elif downgrading:
        if receiving_raw > giving_raw * settings["thresholds"]["min_receiving_value_when_downgrading"] and receiving_raw > giving_raw:
            decision = 1 if await is_valid_upgrade(
                receiving_items,
                settings["item_ratio_constraints"]["max_item_ratio_upgrade"],
                settings["item_ratio_constraints"]["min_item_ratio_upgrade"]
            ) else 0

    else:
        decision = 0

    if giving_raw > receiving_raw * settings["thresholds"]["max_edge_value"]:
        decision = 0
    elif receiving_raw > giving_raw * settings["thresholds"]["max_edge_value"] and allow_edge:
        decision = 0

    if receiving_score <= giving_score:
        decision = 0

    return decision, round(giving_score, 2), round(receiving_score, 2)

async def generate_possible_trades(
    giver_items, receiver_items,
    giver_min=1, giver_max=4,
    receiver_min=1, receiver_max=4,
    mode=None, max_pairs=None,
    min_trade_send_value_total=0
):
    try:
        giver_items_sorted = sorted(giver_items, key=lambda x: x[3] if x[3] != -1 else x[2], reverse=True)
        receiver_items_sorted = sorted(receiver_items, key=lambda x: x[3] if x[3] != -1 else x[2], reverse=True)
        trades = []
        seen = set()

        giver_range = range(giver_min, min(giver_max, len(giver_items)) + 1)
        receiver_range = range(receiver_min, min(receiver_max, len(receiver_items)) + 1)

        if mode == "downgrade":
            giver_range = sorted(giver_range)
            receiver_range = sorted(receiver_range, reverse=True)
        elif mode == "upgrade":
            giver_range = sorted(giver_range, reverse=True)
            receiver_range = sorted(receiver_range)

        for i in giver_range:
            for giver_combo in itertools.combinations(giver_items_sorted, i):
                giver_ids = frozenset(item[0] for item in giver_combo)
                giver_values = set((item[3] if item[3] != -1 else item[2]) for item in giver_combo)
                for j in receiver_range:
                    if mode == "downgrade" and j <= i:
                        continue
                    if mode == "upgrade" and i <= j:
                        continue

                    for rc in itertools.combinations(receiver_items_sorted, j):
                        total_giving_value = sum(item[3] if item[3] != -1 else item[2] for item in giver_combo)
                        if total_giving_value < min_trade_send_value_total:
                            continue
                        receiver_ids = frozenset(item[0] for item in rc)
                        receiver_values = set((item[3] if item[3] != -1 else item[2]) for item in rc)

                        if giver_ids & receiver_ids:
                            continue

                        if giver_values & receiver_values:
                            continue

                        trade_key = (giver_ids, receiver_ids)
                        if trade_key in seen:
                            continue

                        seen.add(trade_key)
                        trades.append({
                            'giving_items': list(giver_combo),
                            'receiving_items': list(rc)
                        })

                        if max_pairs and len(trades) >= max_pairs:
                            return trades
        return trades
    except:
        return []

async def batch_evaluate_trade(trade, settings, allow_edge=False):
    giving_items = trade['giving_items']
    receiving_items = trade['receiving_items']
    decision, giving_score, receiving_score = await evaluate_trade(giving_items, receiving_items, settings, allow_edge)
    return {
        'trade': trade,
        'decision': decision,
        'giving_score': giving_score,
        'receiving_score': receiving_score
    }

def sync_batch_eval(trades, settings, allow_edge):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    async def run_batch():
        tasks = [batch_evaluate_trade(trade, settings, allow_edge) for trade in trades]
        return await asyncio.gather(*tasks)
    results = loop.run_until_complete(run_batch())
    loop.close()
    return results

async def find_best_trade(
    giver_items, receiver_items, settings,
    giver_min=1, giver_max=4,
    receiver_min=1, receiver_max=4,
    allow_edge=False, batch_size=10,
    mode=None, max_pairs=None, min_trade_send_value_total=0
):
    all_possible_trades = await generate_possible_trades(
        giver_items, receiver_items,
        giver_min, giver_max,
        receiver_min, receiver_max,
        mode, max_pairs, min_trade_send_value_total
    )
    all_possible_trades = sorted(
        all_possible_trades,
        key=lambda trade: sum([item[3] if item[3] != -1 else item[2] for item in trade['receiving_items']]) -
                          sum([item[3] if item[3] != -1 else item[2] for item in trade['giving_items']]),
        reverse=True
    )
    best_trade = None
    best_score = -float('inf')
    results = []

    loop = asyncio.get_event_loop()
    for i in range(0, len(all_possible_trades), batch_size):
        batch = all_possible_trades[i:i + batch_size]
        batch_results = await loop.run_in_executor(
            executor, sync_batch_eval, batch, settings, allow_edge
        )
        
        results.extend(batch_results)

    for result in results:
        trade = result['trade']
        decision = result['decision']
        giving_score = result['giving_score']
        receiving_score = result['receiving_score']
        if decision == 1 and giving_score - receiving_score > best_score:
            best_score = giving_score - receiving_score
            best_trade = trade

    return best_trade if best_score < 0 else None

# given_items = [
#     [362081769, "VC", 11842, 12000, 12000, 1, 0, 0, 0, 0],     # Virtual Commando
#     [16477149823, "GCWHP", 5111, 6000, 6000, 3, 0, 0, 0, 0]    # Gold Clockwork Headphones
# ]
# received_items = [
#     [19027209, "Legit", 3901, 4500, 4500, 3, 0, 0, 0, 0],     # Perfectly Legitimate Business Hat
#     [19027209, "Legit", 3901, 4500, 4500, 3, 0, 0, 0, 0],     # Perfectly Legitimate Business Hat
#     [1048037, -1, 5114, 4500, 4500, 2, 0, 0, 0, 0],           # Bighead
#     [1048037, -1, 5114, 4500, 4500, 2, 0, 0, 0, 0]            # Bighead
# ]

# algorithm = {
#     "modes": {
#         "value_only": False,
#         "trade_methods": ["upgrade", "downgrade"],
#         "rap_only_base": False
#     },
#     "thresholds": {
#         "min_receiving_value_when_downgrading": 1.13,
#         "max_giving_value_when_upgrading": 1.1,
#         "max_edge_value": 1.17,
#         "min_trade_send_value_total": 0
#     },
#     "modifiers": {
#         "base_divisor": 1000,
#         "demand_multiplier": 100,
#         "rare_multiplier": 50,
#         "lower_rap_only_item": 0.9,
#         "lower_projected_item": 0
#     },
#     "penalties": {
#         "bulk_penalty_rate": 0.01,
#         "upgrade_penalty_multiplier": 1
#     },
#     "performance": {
#         "batch_size": 5000,
#         "max_pairs": 500000
#     },
#     "upgrade": {
#         "min_items": 3,
#         "max_items": 4
#     },
#     "downgrade": {
#         "min_items": 1,
#         "max_items": 1
#     },
#     "item_ratio_constraints": {
#         "max_item_ratio_upgrade": 0.6,
#         "min_item_ratio_upgrade": 0.05
#     }
# }

# print(asyncio.run(evaluate_trade(given_items, received_items, algorithm, False)))