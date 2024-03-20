import sys
import cantools
import os
import logging
from PySide6.QtCore import Qt, QAbstractTableModel
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QTableView,
    QLabel,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
)

CUSTOM_ROLE = Qt.UserRole + 1

class DbcVcuModel(QAbstractTableModel):
    Columns = [
        {'heading':'Signal Name', 'property':'name', 'signal_meta':True, 'editable':False},
        {'heading':'Description', 'property':'comment', 'signal_meta':False, 'editable': False},
        {'heading':'Unit', 'property':'unit', 'signal_meta':False, 'editable': False},
        {'heading':'Minimum', 'property':'minimum', 'signal_meta':False, 'editable': False},
        {'heading':'Value', 'property':'initial', 'signal_meta':False, 'editable': True},
        {'heading':'Maximum', 'property':'maximum', 'signal_meta':False, 'editable': False}
    ]
    def __init__(self, vcu_msg, parent=None):
        super().__init__(parent)
        self.vcu_msg = vcu_msg
        self.value = []

        for signal in vcu_msg.signals:
            self.value.append(int(signal.initial) if signal.initial is not None else 0)


    def rowCount(self, parent=None):
        # number of signals in message
        return len(self.vcu_msg.signals)

    def columnCount(self, parent=None):
        return len(DbcVcuModel.Columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            signal = self.vcu_msg.signals[index.row()]
            if DbcVcuModel.Columns[index.column()]['editable']:
                return str(self.value[index.row()])
            else:
                return getattr(signal,DbcVcuModel.Columns[index.column()]['property'])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return DbcVcuModel.Columns[section]['heading']
        return None

    def flags(self, index):
        # Set the flag to editable for the Name column
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 4:
            return super().flags(index) | Qt.ItemIsEditable
        return super().flags(index)

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole:
            return False
        signal = self.vcu_msg.signals[index.row()]
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 4:
            self.value[index.row()] = int(value)
            self.dataChanged.emit(index, index, [role])
            return True
        return False

class VcuSignalLayout(QWidget):
    def __init__(self, dbc_db):
        super().__init__()
        self.dbc_db = dbc_db
        self.initUI()

    def getVcuMsgs(self):
        vcu_msg = []
        for msg in self.dbc_db.messages:
            if msg.senders is not None and 'VCU' in msg.senders:
                vcu_msg.append(msg)
        return vcu_msg

    def initUI(self):
        # Main layout for this widget
        mainLayout = QVBoxLayout()

        # Initialize the table for signals
        signalTableView = QTableView()
        signalTableModel = DbcVcuModel(self.getVcuMsgs()[0])
        signalTableView.setModel(signalTableModel)

        for column in range(signalTableModel.columnCount()):
            signalTableView.resizeColumnToContents(column)
            if signalTableView.columnWidth(column) > 500:
                signalTableView.setColumnWidth(column, 500)

        # Ensure rows are tall enough to display wrapped text
        signalTableView.resizeRowsToContents()

        mainLayout.addWidget(signalTableView)

        self.setLayout(mainLayout)


class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CAN Testbench')
        self.dbc_db = cantools.database.load_file('../envgo/dbc/xerotech_battery_j1939.dbc')
        self.initUI()
        self.resizeToScreenFraction()

    def resizeToScreenFraction(self, fractionWidth=1, fractionHeight=0.8):
        # Get the screen size
        screen = QApplication.primaryScreen()
        screenSize = screen.size()

        # Calculate the window size as a fraction of the screen size
        newWidth = screenSize.width() * fractionWidth
        newHeight = screenSize.height() * fractionHeight

        # Resize the window
        self.resize(newWidth, newHeight)

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.setCentralWidget(self.tabWidget)

        # Create the first tab
        self.firstTab = QWidget()
        self.firstTabLayout = QVBoxLayout()
        self.firstTab.setLayout(self.firstTabLayout)

        signalLayout = VcuSignalLayout(self.dbc_db)

        self.firstTabLayout.addWidget(signalLayout)

        self.tabWidget.addTab(self.firstTab, 'TX CAN Messages')

        # Add a second blank tab
        self.secondTab = QWidget()
        self.tabWidget.addTab(self.secondTab, 'RX CAN Messages')


if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logging.info(sys.version)
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
