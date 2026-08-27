import uuid
from calculation_utils import NotableCombinationCalculator
import trade_api_utils
import gui_utils
import poe_db_utils
from PyQt5.QtWidgets import QApplication, QTableWidget
import time
from itertools import combinations
import os
import json
import sys
from PyQt5.QtCore import QThread
import logging
import re

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    try:
        file_dir = "data/" + trade_api_utils.current_league
        if not os.path.exists(file_dir):
            logger.info("Didn't find data for current league. Updating...")
            poe_db_utils.updateClusterData()

        # Always create QApplication early if we might show GUI later
        app = QApplication([])

        # Headless / env-driven dialog support:
        # Use CLUSTER_MODE to skip the modal dialog. Supported formats:
        # - CLUSTER_MODE=single or double (requires CLUSTER_SIZE to choose small/medium)
        # - CLUSTER_MODE=single-small or double-medium (hyphen/colon/underscore accepted)
        # Optional: CLUSTER_SIZE=small|medium
        # Optional: CLUSTER_CLUSTERS comma-separated list of cluster names to select
        cluster_mode_raw = os.environ.get('CLUSTER_MODE', '').strip()
        cluster_size_env = os.environ.get('CLUSTER_SIZE', '').strip().lower()
        headless_result = None
        if cluster_mode_raw:
            mode_parts = re.split('[-_:]', cluster_mode_raw.strip().lower())
            qpart = mode_parts[0] if len(mode_parts) > 0 else ''
            spart = mode_parts[1] if len(mode_parts) > 1 else cluster_size_env

            # map query (single/double)
            if qpart in ('single', '1'):
                query = 1
            elif qpart in ('double', '2'):
                query = 2
            else:
                logger.warning('Unknown CLUSTER_MODE query part "%s"; defaulting to single', qpart)
                query = 1

            # map size (small/medium)
            if spart in ('small', 's', '1'):
                inp = 1
            elif spart in ('medium', 'm', '2'):
                inp = 2
            else:
                # default to small
                inp = 1

            # determine clusters to select
            clusters_env = os.environ.get('CLUSTER_CLUSTERS', '').strip()
            cluster_names = []
            if clusters_env:
                cluster_names = [c.strip() for c in clusters_env.split(',') if c.strip()]
            else:
                # load cluster names from local data file (prefer medium.json, fallback to small.json)
                try:
                    pick_file = os.path.join(file_dir, 'medium.json' if inp == 2 else 'small.json')
                    if not os.path.exists(pick_file):
                        # try the other
                        pick_file = os.path.join(file_dir, 'small.json' if inp == 2 else 'medium.json')
                    with open(pick_file, 'r', encoding='utf-8') as jf:
                        all_cluster_jewels = json.load(jf)
                        cluster_names = [item.get('clusterName') for item in all_cluster_jewels if item.get('clusterName')]
                except Exception:
                    logger.exception('Failed to read cluster data for headless selection')
                    cluster_names = []

            # Build resultList with the same shape as dialog.result: [query, inp, <cluster names...>]
            headless_result = [query, inp] + cluster_names
            logger.info('Headless mode: CLUSTER_MODE=%s, selected clusters=%s', cluster_mode_raw, cluster_names)

        if headless_result is None:
            dialog = gui_utils.Dialog(file_dir)
            dialog.show()
            if not dialog.exec_():
                sys.exit(0)

            resultList = dialog.result
        else:
            resultList = headless_result

        try:
            query = resultList[0]
            inp = resultList[1]
        except Exception:
            sys.exit(0)

        dump_name = str(uuid.uuid4())

        if query == 1:
            location = file_dir + "/small.json" if inp == 1 else file_dir + "/medium.json"
        else:
            location = file_dir + "/medium.json"

        all_cluster_jewels = []
        try:
            with open(location) as json_file:
                all_cluster_jewels = json.load(json_file)
        except Exception:
            logger.exception('Failed to load cluster data')
            sys.exit(1)

        # resultList contains query and inp as first two elements; the remaining entries are cluster names
        selected_cluster_jewels = [item for item in all_cluster_jewels if item.get('clusterName') in resultList]

        if not selected_cluster_jewels:
            logger.info('No cluster jewels selected; exiting')
            sys.exit(0)

        start_time = time.time()
        levelBreakpoints = [1, 50, 68, 75]
        levelRequests = len(levelBreakpoints) * len(selected_cluster_jewels)
        notableRequests = 0

        if query == 2:
            for cluster_jewel in selected_cluster_jewels:
                notableRequests += cluster_jewel.get('clusterNotableCombinationCount', 0)
        else:
            for cluster_jewel in selected_cluster_jewels:
                notableRequests += cluster_jewel.get('clusterNotableCount', 0)

        print("Requests to make: " + str((levelRequests + notableRequests)))

        tableWidget = QTableWidget()
        tableWidget.show()

        calculator = NotableCombinationCalculator(selected_cluster_jewels, query, inp)
        workerThread = QThread()
        calculator.moveToThread(workerThread)

        # Connect the signals
        calculator.finished.connect(workerThread.quit)
        calculator.data_updated.connect(lambda data: gui_utils.display_table(tableWidget, data))

        workerThread.started.connect(calculator.process)

        workerThread.start()

        try:
            gui_utils.toggle_console(0)
        except Exception:
            pass

        app.exec_()

    except Exception:
        logger.exception('Unhandled exception in main')
        sys.exit(1)


if __name__ == '__main__':
    main()
