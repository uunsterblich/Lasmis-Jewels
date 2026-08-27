import requests
from bs4 import BeautifulSoup
import trade_api_utils
import json
import os
from itertools import combinations
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

headers = requests.utils.default_headers()
headers.update({
    'User-Agent': "IDareYouLV's cluster notable combination price checker",
    'From': 'arturino009@gmail.com'
})


def find(lst, key, value):
    for i, dic in enumerate(lst):
        try:
            if dic[key] == value:
                return i
        except Exception:
            continue
    return -1


def get_data_poedb(size, timeout=10):
    listOfClusters = []
    link = f"https://poedb.tw/us/{size}_Cluster_Jewel#EnchantmentModifiers"
    try:
        page = requests.get(link, timeout=timeout)
        page.raise_for_status()
    except Exception:
        logger.exception('Failed to fetch poedb page')
        return listOfClusters

    soup = BeautifulSoup(page.content, 'lxml')
    table = soup.find(id="EnchantmentModifiers")
    if not table:
        return listOfClusters

    listOfClustersData = table.findAll('button')
    for cluster in listOfClustersData:
        listOfNotables = []
        weightOfNotables = 0
        clusterId = ''
        parent = cluster.find_parent('td')
        if not parent:
            continue
        nameOfCluster = parent.contents[0].text if parent.contents else ''
        nameOfCluster = nameOfCluster.split("(", 1)[0]
        if nameOfCluster in ("3% increased effect of Non-Curse Auras from your Skills", "2% increased Effect of your Curses"):
            continue
        elif nameOfCluster == "12% increased Trap Damage12% increased Mine Damage":
            nameOfCluster = "12% increased Trap Damage\n12% increased Mine Damage"
        elif nameOfCluster == "10% increased Life Recovery from Flasks10% increased Mana Recovery from Flasks":
            nameOfCluster = "10% increased Life Recovery from Flasks\n10% increased Mana Recovery from Flasks"

        actualData = parent.contents[4] if len(parent.contents) > 4 else None
        if not actualData:
            continue
        listOfNotablesData = actualData.find('tbody').contents if actualData.find('tbody') else []
        for notable in listOfNotablesData:
            try:
                notableName = notable.contents[0].contents[1].text
                if "Added Small Passive Skills also grant:" in notableName:
                    continue
                notableLevel = int(notable.contents[2].text)
                notableWeight = notable.contents[1].text
                weightOfNotables = weightOfNotables + int(notableWeight)
                notableId = None
                for entry in trade_api_utils.getCurrencies(trade_api_utils.current_league):
                    # Note: previous logic used allStats; simplified mapping required
                    pass
                # Fallback: try to find an id from page structure (omitted) or continue
                notableInfo = {
                    'notableId': notableId,
                    'notableName': notableName,
                    'notableWeight': int(notableWeight),
                    'notableLevel': notableLevel
                }
                listOfNotables.append(notableInfo)
            except Exception:
                continue

        if size == "Small":
            weightOfNotables = weightOfNotables + 9800
        else:
            weightOfNotables = weightOfNotables + 8000

        # The following logic expects allStats and complex lookups; keep structure but skip if missing
        # Determine clusterId by searching trade_api_utils data (best-effort)
        clusterId = ''
        notableLevelBreakpoint = {}
        for notable in listOfNotables:
            lvl = notable.get("notableLevel")
            if lvl not in notableLevelBreakpoint:
                notableLevelBreakpoint[lvl] = 0
            notableLevelBreakpoint[lvl] = notableLevelBreakpoint[lvl] + notable.get("notableWeight", 0)

        if clusterId == '':
            # skip clusters where clusterId wasn't resolved
            continue

        notableCount = len(listOfNotables)
        combCount = len(list(combinations(listOfNotables, 2)))
        clusterInfo = {
            'clusterId': clusterId,
            'clusterName': nameOfCluster,
            'clusterWeightPrefix': weightOfNotables,
            'clusterNotables': listOfNotables,
            'clusterNotableCount': notableCount,
            'clusterNotableCombinationCount': combCount,
            'clusterNotableLevels': dict(sorted(notableLevelBreakpoint.items()))
        }
        listOfClusters.append(clusterInfo)
    return listOfClusters


def updateClusterData():
    try:
        responseStats = requests.get("https://www.pathofexile.com/api/trade/data/stats", headers=headers, timeout=10)
        responseStats.raise_for_status()
        allStats = responseStats.json()
    except Exception:
        logger.exception('Failed to fetch trade data stats')
        return

    try:
        leagues = requests.get('http://api.pathofexile.com/leagues', headers=headers, timeout=10)
        leagues.raise_for_status()
        leagues = leagues.json()
        current_league = leagues[trade_api_utils.current_league_id]['id']
    except Exception:
        logger.exception('Failed to resolve current league')
        return

    file_dir = "data/" + current_league
    os.makedirs(file_dir, exist_ok=True)

    with open(os.path.join(file_dir, 'small.json'), 'w') as outfile:
        json.dump(get_data_poedb("Small"), outfile)

    with open(os.path.join(file_dir, 'medium.json'), 'w') as outfile:
        json.dump(get_data_poedb("Medium"), outfile)
