from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot
from itertools import combinations
import trade_api_utils

class NotableCombinationCalculator(QObject):
    finished = pyqtSignal()
    data_updated = pyqtSignal(object)

    def __init__(self, selected_cluster_jewels, query, inp):
        super().__init__()
        self.selected_cluster_jewels = selected_cluster_jewels
        self.query = query
        self.inp = inp

    @pyqtSlot()
    def process(self):
        # all the code that updates the data goes here
        all_averages = []
        for cluster_jewel in self.selected_cluster_jewels:
            if self.query == 1:
                notable_combinations = cluster_jewel.get('clusterNotables', [])
            else:
                # make a list of all possible combinations of items in each category
                notable_combinations = list(combinations(cluster_jewel.get('clusterNotables', []), 2))

            # build breakpoint prices
            lvlPrice = []
            levels = list(cluster_jewel.get("clusterNotableLevels", {}).keys())
            for i, lvl in enumerate(levels):
                if i == len(levels) - 1:
                    maxLVL = 83
                else:
                    try:
                        maxLVL = int(levels[i + 1]) - 1
                    except Exception:
                        maxLVL = 83
                try:
                    price = trade_api_utils.get_category_jewel_price(cluster_jewel, int(lvl), maxLVL)
                except Exception:
                    price = 0
                lvlPrice.append({'lvl': lvl, 'price': price})
            cluster_jewel['breakpointPrices'] = lvlPrice

            cluster_results = []
            for notable_combination in notable_combinations:
                try:
                    if self.query == 1:
                        min_lvl = int(notable_combination.get('notableLevel', 1))
                    else:
                        seq = [int(x.get('notableLevel', 1)) for x in notable_combination]
                        min_lvl = max(seq)

                    jewel_price = 0
                    for item in cluster_jewel.get('breakpointPrices', []):
                        if str(item.get('lvl')) == str(min_lvl):
                            jewel_price = item.get('price', 0)
                            break

                    notableData = trade_api_utils.getNotablePrice(cluster_jewel, notable_combination, self.query, self.inp, jewel_price)
                    if notableData:
                        cluster_results.append(notableData)
                except Exception:
                    # don't fail the whole processing for one notable
                    continue

            if cluster_results:
                all_averages.extend(cluster_results)
                # emit less frequently (per cluster)
                self.data_updated.emit(all_averages)

        self.finished.emit()
