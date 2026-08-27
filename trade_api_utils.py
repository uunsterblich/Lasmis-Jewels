import math
import statistics
import requests
import time
from json import loads as load
import json
import os
import logging

# Basic logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

headers = requests.utils.default_headers()

# Current rate-limit header rules: 5:10:60,15:60:300,30:300:1800

headers.update({
    'User-Agent': "IDareYouLV's cluster notable combination price checker",
    'From': 'arturino009@gmail.com'
})

# Don't hardcode session IDs or secrets. Read from env if provided.
POESESSID = os.environ.get('POESESSID')
cookies = {"POESESSID": POESESSID} if POESESSID else {}


def getLeague(league_id, timeout=10):
    """Return league id string for a given league index. Raises on network errors."""
    resp = requests.get('http://api.pathofexile.com/leagues', headers=headers, timeout=timeout)
    resp.raise_for_status()
    leagues = resp.json()
    return leagues[league_id]['id']  # may raise IndexError if league_id invalid


def getCurrencies(league, timeout=10):
    """Get currency rates from poe.ninja for a given league string.
    Uses requests params to ensure proper URL encoding. On failure falls back
    to a local currency_rates_local.json file (if present) for offline testing.
    """
    url = 'https://poe.ninja/api/data/currencyoverview'
    params = {'league': league, 'type': 'Currency'}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=timeout)
        response.raise_for_status()
    except Exception:
        logger.exception("Failed to fetch currencies from poe.ninja; trying local fallback")
        # Try local fallback file
        try:
            with open('currency_rates_local.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Expect list of {currFull, curr, rate}
                return data if isinstance(data, list) else []
        except Exception:
            logger.exception("No local currency_rates_local.json fallback found or failed to parse")
            return []

    try:
        currencies = response.json().get('lines', [])
    except Exception:
        logger.exception("Failed to parse currencies response; trying local fallback")
        try:
            with open('currency_rates_local.json', 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            logger.exception("No local currency_rates_local.json fallback found or failed to parse")
            return []

    # Build result (map poe.ninja names to short codes from existing currency.json mapping)
    rates_map = {c['currencyTypeName']: c['chaosEquivalent'] for c in currencies}
    try:
        with open('currency.json') as json_file:
            currShort = json.load(json_file)
    except Exception:
        logger.exception('Failed to open currency.json (short name mapping); falling back to simple list')
        currShort = {}

    arr = []
    # If currShort present, build arr by matching names
    if isinstance(currShort, dict) and currShort:
        for name in currShort:
            rate = rates_map.get(name)
            if rate is not None:
                arr.append({'currFull': name, 'curr': currShort[name], 'rate': rate})
        return arr
    # Otherwise, produce a generic list from rates_map for common entries
    for fullname, rate in rates_map.items():
        # Try to derive short name from fullname (simple heuristic)
        short = fullname.lower().split()[0] if fullname else fullname
        arr.append({'currFull': fullname, 'curr': short, 'rate': rate})
    return arr


class RateLimitedRequester:
    def __init__(self):
        # Optional headers/cookies that can be passed in.
        self.headers = headers
        self.cookies = cookies
        # These dictionaries persist across requests.
        self.global_window_start_times = {}
        self.account_window_start_times = {}

    def get_rate_limit_headers(self, response):
        # If your API doesn't supply these headers, replace the default values as needed.
        return {
            "global_limit": response.headers.get("X-Rate-Limit-Ip", "8:10:60,15:60:120,60:300:1800"),
            "global_state": response.headers.get("X-Rate-Limit-Ip-State", "0:10:0,0:60:0,0:300:0"),
            "account_limit": response.headers.get("X-Rate-Limit-Account", "8:10:60,15:60:120,60:300:1800"),
            "account_state": response.headers.get("X-Rate-Limit-Account-State", "0:10:0,0:60:0,0:300:0")
        }

    def calculate_delay(self, rate_limit_rules, rate_limit_state, window_start_times):
        """
        For each rule:
          - If the burst limit is not yet reached, no delay is needed.
          - If the limit is reached, we wait until the current window resets.
          - If a penalty is active, we wait for that penalty.
        """
        try:
            rules = [tuple(map(int, rule.split(':'))) for rule in rate_limit_rules.split(',')]
            states = [tuple(map(int, state.split(':'))) for state in rate_limit_state.split(',')]
        except Exception:
            # Fallback: no delay
            return 0

        delays = []
        now = time.time()
        for idx, (rule, state) in enumerate(zip(rules, states)):
            try:
                max_requests, timeframe, penalty_time = rule
                requests_made, state_timeframe, remaining_penalty = state
            except Exception:
                continue

            window_start = window_start_times.get(idx, now)
            elapsed = now - window_start

            if remaining_penalty > 0:
                delays.append(remaining_penalty)
                continue

            if requests_made < max_requests:
                delay = 0
            else:
                delay = max(0, timeframe - elapsed)
            delays.append(delay)

        return max(delays) if delays else 0

    def update_window_times(self, rate_limit_rules, window_start_times, last_request_time):
        try:
            rules = [tuple(map(int, rule.split(':'))) for rule in rate_limit_rules.split(',')]
        except Exception:
            return
        for idx, (max_requests, timeframe, _) in enumerate(rules):
            if idx not in window_start_times:
                window_start_times[idx] = last_request_time
            else:
                if last_request_time - window_start_times[idx] >= timeframe:
                    window_start_times[idx] = last_request_time

    def send_request(self, url, data=None, timeout=15, max_attempts=3):
        last_request_time = None
        attempt = 0
        while True:
            attempt += 1
            try:
                if data:
                    response = requests.post(url, json=data, headers=self.headers, cookies=self.cookies, timeout=timeout)
                else:
                    response = requests.get(url, headers=self.headers, cookies=self.cookies, timeout=timeout)
            except requests.RequestException:
                logger.exception('Network error while requesting %s', url)
                if attempt >= max_attempts:
                    raise
                time.sleep(1 * attempt)
                continue

            rate_limits = self.get_rate_limit_headers(response)
            global_delay = self.calculate_delay(rate_limits.get("global_limit", ""),
                                                rate_limits.get("global_state", ""),
                                                self.global_window_start_times)
            account_delay = self.calculate_delay(rate_limits.get("account_limit", ""),
                                                 rate_limits.get("account_state", ""),
                                                 self.account_window_start_times)
            delay = max(global_delay, account_delay)

            try:
                response_json = response.json()
            except ValueError:
                logger.exception('Failed to parse JSON from %s', url)
                if attempt >= max_attempts:
                    raise
                time.sleep(delay or (1 * attempt))
                continue

            if isinstance(response_json, dict) and 'error' in response_json:
                logger.warning('API returned error: %s', response_json.get('error'))
                if attempt >= max_attempts:
                    return response_json
                time.sleep(delay or (1 * attempt))
                continue

            last_request_time = time.time()

            self.update_window_times(rate_limits.get("global_limit", ""),
                                     self.global_window_start_times,
                                     last_request_time)
            self.update_window_times(rate_limits.get("account_limit", ""),
                                     self.account_window_start_times,
                                     last_request_time)

            if delay and last_request_time and delay > 0:
                time.sleep(delay)

            return response_json


# Small breakpoints: 1-49; 50-67; 68-72; 75-77
# Medium breakpoints: 1-49; 50-67; 68-74; 75-83  //not all have 75 notables, so they have 68-83 breakpoint


def _prepare_result_str(result):
    # result can be a list of ids or a single id string
    if isinstance(result, list):
        if len(result) == 0:
            return ''
        return ','.join(result) if len(result) > 1 else str(result[0])
    return str(result)


def get_category_jewel_price(a, ilvl, maxlvl):
    data_set = {
        "query": {
            "status": {"option": "online"},
            "stats": [{
                "type": "and",
                "filters": [{"id": 'enchant.stat_3948993189', "value": {"option": a['clusterId']}},
                            {"id": "enchant.stat_3086156145", "value": {"max": 5}}]
            }],
            "filters": {
                "type_filters": {"filters": {"rarity": {"option": "nonunique"}}},
                "misc_filters": {"filters": {"corrupted": {"option": "false"}, "ilvl": {"min": ilvl, "max": maxlvl}}},
                "trade_filters": {"filters": {"sale_type": {"option": "priced"}}}
            }
        },
        "sort": {"price": "asc"}
    }

    response = requester.send_request('https://www.pathofexile.com/api/trade/search/' + current_league, data_set)
    if not isinstance(response, dict):
        return 0
    result = response.get('result', [])
    id_ = response.get('id')
    size = response.get('total', 0)
    if size == 0:
        return 0

    if size > 10 and isinstance(result, list):
        result = result[:10]

    str1 = _prepare_result_str(result)
    if not str1:
        return 0

    address = f'https://www.pathofexile.com/api/trade/fetch/{str1}?query={id_}'
    try:
        results_json = requester.send_request(address)
    except Exception:
        logger.exception('Failed to fetch listings')
        return 0

    medium = []
    logger.info('Base: %s', a.get('clusterName'))
    logger.info('ilvl: %s-%s', ilvl, maxlvl)
    logger.info('Listings: %s', size)

    for p in results_json.get('result', []) if isinstance(results_json, dict) else []:
        currency = p.get('listing', {}).get('price', {}).get('currency')
        if currency != 'chaos' or currency == 'p':
            try:
                curr = [dictionary for dictionary in rates if dictionary["curr"] == currency]
                p['listing']['price']['amount'] = p['listing']['price']['amount'] * curr[0]['rate']
                p['listing']['price']['currency'] = "chaos"
            except Exception:
                continue
        try:
            medium.append(p['listing']['price']['amount'])
        except Exception:
            continue

    if not medium:
        avg = 1
    else:
        try:
            avg = statistics.median_grouped(medium)
        except Exception:
            avg = statistics.median(medium) if medium else 1

    logger.info('Average median price: %s', round(avg, 2))
    return avg


def getNotablePrice(cluster_jewel, notable_combination, query, inp, jewel_price):
    try:
        if query == 1:
            ilvl = int(notable_combination.get('notableLevel', 1))
        else:
            ilvl = max(int(notable_combination[0].get('notableLevel', 1)), int(notable_combination[1].get('notableLevel', 1)))
    except Exception:
        ilvl = 1

    data_set = {
        "query": {
            "status": {"option": "online"},
            "type": "Small Cluster Jewel" if inp == 1 else "Medium Cluster Jewel",
            "stats": [{
                "type": "and",
                "filters": ([{"id": notable_combination.get('notableId')}]
                            if query == 1 else
                            [{"id": notable_combination[0].get('notableId')}, {"id": notable_combination[1].get('notableId')}, {"id": "enchant.stat_3086156145", "value": {"max": 5}}])
            }],
            "filters": {
                "type_filters": {"filters": {"rarity": {"option": "nonunique"}}},
                "trade_filters": {"filters": {"sale_type": {"option": "priced"}}}
            }
        },
        "sort": {"price": "asc"}
    }

    response = requester.send_request('https://www.pathofexile.com/api/trade/search/' + current_league, data_set)
    if not isinstance(response, dict):
        return 0
    result = response.get('result', [])
    id_ = response.get('id')
    size = response.get('total', 0)

    if size < 10:
        name = (notable_combination.get('notableName') if query == 1 else (notable_combination[0].get('notableName', '') + ' and ' + notable_combination[1].get('notableName', '')))
        logger.info('Not enough items!(%s) Skipping... %s', size, name)
        return 0

    if size > 10 and isinstance(result, list):
        result = result[:10]

    str1 = _prepare_result_str(result)
    if not str1:
        return 0

    address = f'https://www.pathofexile.com/api/trade/fetch/{str1}?query={id_}'
    try:
        results_json = requester.send_request(address)
    except Exception:
        logger.exception('Failed to fetch listings for notable')
        return 0

    # get currency rates for crafting math
    try:
        altPrice = [d for d in rates if d.get('currFull') == "Orb of Alteration"][0]['rate']
        augPrice = [d for d in rates if d.get('currFull') == "Orb of Augmentation"][0]['rate']
    except Exception:
        logger.exception('Failed to resolve craft currency rates')
        return 0

    clusterPrefixWeight = cluster_jewel.get('clusterWeightPrefix', 0)
    weight75 = 900 if inp == 1 else 2100
    weight68 = (cluster_jewel.get('clusterNotableLevels', {}).get(75, 0) if isinstance(cluster_jewel.get('clusterNotableLevels', {}), dict) else 0) + weight75 + (1200 if inp == 1 else 0)
    weight50 = (cluster_jewel.get('clusterNotableLevels', {}).get(68, 0) if isinstance(cluster_jewel.get('clusterNotableLevels', {}), dict) else 0) + weight68 + (4200 if inp == 1 else 2400)
    weight1 = (cluster_jewel.get('clusterNotableLevels', {}).get(50, 0) if isinstance(cluster_jewel.get('clusterNotableLevels', {}), dict) else 0) + weight50

    weights = {"1": weight1, "50": weight50, "68": weight68, "75": weight75, "84": weight75}
    clusterPrefixWeight = clusterPrefixWeight - weights.get(str(ilvl), 0)

    craft_price = 0
    tries = 1
    probability = 0

    if query == 1:
        probability = notable_combination.get('notableWeight', 0) / clusterPrefixWeight if clusterPrefixWeight else 0
        tries = math.ceil(1 / probability) if probability else 0
        alt_count = tries
        aug_count = math.ceil(alt_count / 4) if alt_count else 0
        craft_price = alt_count * altPrice + aug_count * augPrice
    else:
        try:
            regalPrice = [d for d in rates if d.get('currFull') == "Regal Orb"][0]['rate']
            scourPrice = [d for d in rates if d.get('currFull') == "Orb of Scouring"][0]['rate']
            transPrice = [d for d in rates if d.get('currFull') == "Orb of Transmutation"][0]['rate']
        except Exception:
            logger.exception('Failed to resolve craft currency rates for double-notable')
            return 0

        suffixWeight = 14150
        sweight75 = 1100 if inp == 1 else 3550
        sweight68 = sweight75 + (2200 if inp == 1 else 0)
        sweight50 = sweight68 + (7700 if inp == 1 else 4750)
        sweight1 = sweight50
        sweights = {"1": sweight1, "50": sweight50, "68": sweight68, "75": sweight75, "84": sweight75}
        suffixWeight = suffixWeight - sweights.get(str(ilvl), 0)

        a0 = notable_combination[0]
        a1 = notable_combination[1]
        pw0 = a0.get('notableWeight', 0)
        pw1 = a1.get('notableWeight', 0)
        probabilityFirst = pw0 / clusterPrefixWeight if clusterPrefixWeight else 0
        probabilityFirstSecond = pw1 / (clusterPrefixWeight + suffixWeight - pw0) if (clusterPrefixWeight + suffixWeight - pw0) else 0
        probabilityFirstSucess = probabilityFirst * probabilityFirstSecond

        probabilitySecond = pw1 / clusterPrefixWeight if clusterPrefixWeight else 0
        probabilitySecondFirst = pw0 / (clusterPrefixWeight + suffixWeight - pw1) if (clusterPrefixWeight + suffixWeight - pw1) else 0
        probabilitySecondSucess = probabilitySecond * probabilitySecondFirst

        probability = probabilityFirstSucess + probabilitySecondSucess

        probability_first = (pw0 + pw1) / clusterPrefixWeight if clusterPrefixWeight else 0
        probability_second = probability / probability_first if probability_first else 0

        tries = math.ceil(1 / probability) if probability else 0
        regal_count = math.ceil(1 / probability_second) if probability_second else 0
        scour_count = max(regal_count - 1, 0)
        trans_count = max(regal_count - 1, 0)
        alt_count = max(tries - trans_count, 0)
        aug_count = math.ceil((tries + alt_count) / 4) + 1 if (tries or alt_count) else 0
        craft_price = alt_count * altPrice + aug_count * augPrice + regal_count * regalPrice + scour_count * scourPrice + trans_count * transPrice

    craft_and_jewel_price = craft_price + jewel_price

    medium = []
    results_list = results_json.get('result', []) if isinstance(results_json, dict) else []

    for p in results_list:
        currency = p.get('listing', {}).get('price', {}).get('currency')
        if currency != 'chaos' or currency == 'p':
            try:
                curr = [dictionary for dictionary in rates if dictionary.get("curr") == currency]
                price = p['listing']['price']['amount'] * curr[0]['rate']
                p['listing']['price']['amount'] = price
                p['listing']['price']['currency'] = "chaos"
            except Exception:
                continue
        try:
            medium.append(p['listing']['price']['amount'])
        except Exception:
            continue

    if not medium:
        return 0

    try:
        avg = statistics.median_grouped(medium)
    except Exception:
        avg = statistics.median(medium) if medium else 0

    profit = avg - craft_and_jewel_price
    PPT = profit / tries if tries else 0
    if len(medium) > 1:
        first = (medium[0] + medium[1]) / 2
    else:
        first = medium[0]
    LPPT = (first - craft_and_jewel_price) / tries if tries else 0

    x = {
        'name': notable_combination.get('notableName') if query == 1 else (notable_combination[0].get('notableName', '') + " and " + notable_combination[1].get('notableName', '')),
        'listings': size,
        'tries': round(tries),
        'craft_price': round(craft_price, 2),
        'first': round(first, 2),
        'average_price': round(avg, 2),
        'profit': round(profit, 2),
        'PPT': round(PPT, 3),
        'LPPT': round(LPPT, 3),
        'category': cluster_jewel.get('clusterName'),
        'request': data_set,
        'category_full': cluster_jewel,
        'notable_full': notable_combination,
        'ilvl': ilvl,
        'id': id_
    }
    return x


# configuration defaults; override via env if desired
current_league_id = int(os.environ.get('CURRENT_LEAGUE_ID', 16))
# Hardcoded default league to get a quick success; can be overridden via CURRENT_LEAGUE env var.
current_league = os.environ.get('CURRENT_LEAGUE', 'Allflame')
# If CURRENT_LEAGUE is empty, fallback to resolving by id for compatibility
if not current_league:
    try:
        current_league = getLeague(current_league_id)
    except Exception:
        current_league = ''

logger.info("Current league : %s", current_league)

rates = getCurrencies(current_league) if current_league else []

requester = RateLimitedRequester()
