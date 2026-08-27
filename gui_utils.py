import ctypes
import json
import os
import webbrowser
import trade_api_utils
from PyQt5.QtWidgets import *
from PyQt5.QtCore import Qt
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def dump_data(dump_name, data):
    file_dir = "data/dump"
    os.makedirs(file_dir, exist_ok=True)

    with open(os.path.join(file_dir, f'{dump_name}.json'), 'w') as outfile:
        json.dump(data, outfile)


def toggle_console(a):
    # hiding the console on Windows
    try:
        kernel32 = ctypes.WinDLL('kernel32')
        user32 = ctypes.WinDLL('user32')
        SW_HIDE = a
        hWnd = kernel32.GetConsoleWindow()
        if hWnd:
            user32.ShowWindow(hWnd, SW_HIDE)
    except Exception:
        # Not a blocking error on non-windows or if DLLs not available
        logger.debug('toggle_console failed or not applicable on this platform')


def open_link(item):
    # item is QTableWidgetItem
    try:
        item_id = item.data(Qt.UserRole)
        if item_id:
            webbrowser.open('https://www.pathofexile.com/trade/search/' + trade_api_utils.current_league + '/' + str(item_id))
    except Exception:
        logger.exception('Failed to open link')


def display_table(tableWidget, data):
    if not data:
        return

    # remove heavy keys if present
    keys_to_remove = {"request", "category_full", "notable_full"}
    sanitized = []
    for item in data:
        row = {k: v for k, v in item.items() if k not in keys_to_remove}
        sanitized.append(row)

    headers = list(sanitized[0].keys())
    row_count = len(sanitized)
    column_count = len(headers)

    tableWidget.setColumnCount(column_count)
    tableWidget.setRowCount(row_count)
    tableWidget.setHorizontalHeaderLabels(headers)

    id_index = headers.index('id') if 'id' in headers else -1

    for row in range(row_count):
        values = list(sanitized[row].values())
        for column in range(column_count):
            item = QTableWidgetItem()
            # store id in UserRole instead of monkey-patching attribute
            if id_index != -1:
                item.setData(Qt.UserRole, values[id_index])
            # display the value
            try:
                item.setData(Qt.EditRole, values[column])
            except Exception:
                item.setData(Qt.EditRole, str(values[column]))
            tableWidget.setItem(row, column, item)

    if id_index != -1:
        tableWidget.setColumnHidden(id_index, True)

    tableWidget.setSortingEnabled(True)
    tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)
    # disconnect previous to avoid duplicate connections
    try:
        tableWidget.itemDoubleClicked.disconnect()
    except Exception:
        pass
    tableWidget.itemDoubleClicked.connect(open_link)


class Dialog(QDialog):
    file_dir = ""

    def __init__(self, file_dir, parent=None):
        super(Dialog, self).__init__(parent)

        self.file_dir = file_dir

        layout = QGridLayout()
        self.setLayout(layout)

        countbutton1 = QRadioButton("Single notable")
        countbutton1.setChecked(True)
        countbutton1.type = 1
        layout.addWidget(countbutton1, 0, 0)

        countbutton2 = QRadioButton("Double notable")
        countbutton2.type = 0
        layout.addWidget(countbutton2, 0, 1)

        clustersizebutton1 = QRadioButton("Small cluster jewels")
        clustersizebutton1.type = 1
        clustersizebutton1.toggled.connect(self.onClicked)
        layout.addWidget(clustersizebutton1, 1, 0)

        clustersizebutton2 = QRadioButton("Medium cluster jewels")
        clustersizebutton2.type = 0
        clustersizebutton2.toggled.connect(self.onClicked)
        layout.addWidget(clustersizebutton2, 1, 1)

        self.btngroup1 = QButtonGroup()
        self.btngroup2 = QButtonGroup()

        self.btngroup1.addButton(countbutton1)
        self.btngroup1.addButton(countbutton2)
        self.btngroup2.addButton(clustersizebutton1)
        self.btngroup2.addButton(clustersizebutton2)

    def deleteAllWidgetsUntil(self, a):
        layout = self.layout()
        for i in reversed(range(layout.count())):
            widget = layout.itemAt(i).widget()
            if widget:
                widget.setParent(None)
            if i == a:
                break

    def onClicked(self):
        clustersizebutton = self.sender()
        layout = self.layout()
        if clustersizebutton.type == 1:
            location = os.path.join(self.file_dir, "small.json")
        else:
            location = os.path.join(self.file_dir, "medium.json")
        try:
            with open(location) as json_file:
                all_lists = json.load(json_file)
        except Exception:
            logger.exception('Failed to open %s', location)
            all_lists = []

        if layout.count() > 4:
            self.deleteAllWidgetsUntil(4)

        count = 1
        for category in all_lists:
            count += 1
            clusterbox = QCheckBox(category.get('clusterName', 'unknown'))
            clusterbox.setChecked(False)
            clusterbox.type = category.get('clusterName')
            layout.addWidget(clusterbox, count, 0)

        executebutton = QPushButton("Execute")
        executebutton.clicked.connect(self.onExecute)
        layout.addWidget(executebutton, layout.count(), 0)

    def onExecute(self):
        layout = self.layout()
        result = []
        for i in range(layout.count()):
            widget = layout.itemAt(i).widget()
            if widget and hasattr(widget, 'isChecked') and widget.isChecked():
                result.append(getattr(widget, 'type', None))

        if len(result) == 0:
            print("No categories selected!")
            return
        self.result = result
        self.accept()
