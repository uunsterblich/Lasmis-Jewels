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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def main():
    try:
        file_dir = "data/" + trade_api_utils.current_league
        if not os.path.exists(file_dir):
            logger.info("Didn't find data for current league. Updating...")
            poe_db_utils.updateClusterData()

        app = QApplication([])
        dialog = gui_utils.Dialog(file_dir)
        dialog.show()
        if not dialog.exec_():
            sys.exit(0)

        resultList = dialog.result

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
