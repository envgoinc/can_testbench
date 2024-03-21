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
    QHBoxLayout,
    QTableView,
    QLabel,
    QFrame,
    QComboBox,
    QCheckBox,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
)

class DbcMsgModel(QAbstractTableModel):
    Columns = [
        {'heading':'Signal Name', 'property':'name', 'signal_meta':True, 'editable':False},
        {'heading':'Description', 'property':'comment', 'signal_meta':False, 'editable': False},
        {'heading':'Unit', 'property':'unit', 'signal_meta':False, 'editable': False},
        {'heading':'Minimum', 'property':'minimum', 'signal_meta':False, 'editable': False},
        {'heading':'Maximum', 'property':'maximum', 'signal_meta':False, 'editable': False},
        {'heading':'Value', 'property':'initial', 'signal_meta':False, 'editable': True}
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
        return len(DbcMsgModel.Columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            signal = self.vcu_msg.signals[index.row()]
            if DbcMsgModel.Columns[index.column()]['editable']:
                return str(self.value[index.row()])
            else:
                return getattr(signal,DbcMsgModel.Columns[index.column()]['property'])
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return DbcMsgModel.Columns[section]['heading']
        return None

    def flags(self, index):
        # Set the flag to editable for the Name column
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 5:
            return super().flags(index) | Qt.ItemIsEditable
        return super().flags(index)

    def setData(self, index, value, role=Qt.EditRole):
        if not index.isValid() or role != Qt.EditRole:
            return False
        signal = self.vcu_msg.signals[index.row()]
        if index.column() == 5:
            requestedValue = int(value)
            if (requestedValue >= self.vcu_msg.signals[index.row()].minimum and
                requestedValue <= self.vcu_msg.signals[index.row()].maximum):
                self.value[index.row()] = int(value)
                self.dataChanged.emit(index, index, [role])
                return True
        return False

    @property
    def msgData(self):
        signalDict = {}
        for idx, signal in enumerate(self.vcu_msg.signals):
            signalDict[signal.name] = self.value[idx]
        logging.debug(f'{signalDict=}')
        data = self.vcu_msg.encode(signalDict, strict=True)
        return data

class MessageLayout(QWidget):
    FrequencyValues = [0, 1, 5, 10, 20, 40, 50, 100]

    def __init__(self, message):
        super().__init__()
        self.frequency = 0
        self.message = message
        self.initUI()

    def onDataChanged(self, topLeft, bottomRight, roles):
        logging.debug(f'data changed! {roles=}')
        if not roles or Qt.EditRole in roles:
            self.updateSendString()

    def resizeTableViewToContents(self, tableView: QTableView):
        height = tableView.horizontalHeader().height()
        for row in range(tableView.model().rowCount()):
            height += tableView.rowHeight(row)
        if tableView.horizontalScrollBar().isVisible():
            height += tableView.horizontalScrollBar().height()
        tableView.setFixedHeight(height + 5)

    def initBaseUI(self):
        self.mainLayout = QVBoxLayout()
        msgString = f'{self.message.name}: {hex(self.message.frame_id)}; Frequency = '
        cycleTime = self.message.cycle_time
        if cycleTime is None or cycleTime == 0:
            msgString += 'not specified'
        else:
            cycleTime /= 1000
            self.frequency = min(self.FrequencyValues, key=lambda x: abs(x - 1/cycleTime))
            msgString += f'{self.frequency} Hz'
        msgLabel = QLabel(msgString)
        self.mainLayout.addWidget(msgLabel)

        # Initialize and configure the table for signals
        signalTableView = QTableView()
        self.signalTableModel = DbcMsgModel(self.message)
        signalTableView.setModel(self.signalTableModel)
        self.signalTableModel.dataChanged.connect(self.onDataChanged)
        for column in range(self.signalTableModel.columnCount()):
            signalTableView.resizeColumnToContents(column)
            if signalTableView.columnWidth(column) > 500:
                signalTableView.setColumnWidth(column, 500)
        signalTableView.resizeRowsToContents()
        self.resizeTableViewToContents(signalTableView)
        self.mainLayout.addWidget(signalTableView)

        self.setLayout(self.mainLayout)

    def initUI(self):
        self.initBaseUI()
        logging.debug('super initUI')
        # This method will be overridden by derived classes
class TxMessageLayout(MessageLayout):
    def __init__(self, message):
        super().__init__(message)

    def sendChanged(self):
        if self.sendCheckBox.isChecked():
            logging.info(f'Send CAN frames at {self.frequency} Hz')
            self.send = True
        else:
            logging.info(f'Stop sending CAN frames')
            self.send = False

    def frequencyChanged(self):
        frequency = self.sendFrequencyCombo.currentData()
        logging.info(f'Frequency change: {frequency} Hz')
        self.frequency = frequency

    def updateSendString(self):
        sendData = self.signalTableModel.msgData
        logging.debug(f'{sendData=}')
        sendDataStr = ''.join(f'0x{byte:02x} ' for byte in sendData)
        logging.debug(f'{sendDataStr=}')
        sendString = hex(self.message.frame_id) + ': <' + sendDataStr + '>'
        self.sendLabel.setText(sendString)
        logging.info(f'Data changed: {sendString}')

    def initUI(self):
        super().initBaseUI()  # Initialize base UI components

        logging.debug('tx initUI')
        canSendLayout = QHBoxLayout()
        self.sendLabel = QLabel()
        self.updateSendString()
        canSendLayout.addWidget(self.sendLabel)

        freqComboLayout = QHBoxLayout()
        sendFrequencyLabel = QLabel('Select Send Frequency')
        freqComboLayout.addStretch(1)
        freqComboLayout.addWidget(sendFrequencyLabel)
        self.sendFrequencyCombo = QComboBox()
        for value in self.FrequencyValues:
            self.sendFrequencyCombo.addItem(str(value), value)
        index = self.sendFrequencyCombo.findData(self.frequency)
        if index != -1:
            self.sendFrequencyCombo.setCurrentIndex(index)
        self.sendFrequencyCombo.currentIndexChanged.connect(self.frequencyChanged)
        freqComboLayout.addWidget(self.sendFrequencyCombo)
        freqComboLayout.setSpacing(0)
        freqComboLayout.addStretch(1)
        canSendLayout.addLayout(freqComboLayout)
        self.sendCheckBox = QCheckBox('Send')
        self.sendCheckBox.stateChanged.connect(self.sendChanged)
        canSendLayout.addWidget(self.sendCheckBox)
        self.mainLayout.addLayout(canSendLayout)

class RxMessageLayout(MessageLayout):
    def __init__(self, message):
        super().__init__(message)

    def initUI(self):
        super().initBaseUI()

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

    def getMsgs(self, vcu):
        msg_list = []
        for msg in self.dbc_db.messages:
            if vcu and msg.senders is not None and 'VCU' in msg.senders:
                msg_list.append(msg)
            elif not vcu and 'VCU' not in msg.senders:
                msg_list.append(msg)
        return msg_list

    def setupTab(self, title, messages, layoutClass):
        tab = QWidget()

        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollContent = QWidget()
        tabLayout = QVBoxLayout(scrollContent)

        for msg in messages:
            msgLayout = layoutClass(msg)
            tabLayout.addWidget(msgLayout)

        scrollArea.setWidget(scrollContent)
        layout = QVBoxLayout(tab)  # This is the layout for the tab itself
        layout.addWidget(scrollArea)  # Add the scrollArea to the tab's layout

        self.tabWidget.addTab(tab, title)

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.setCentralWidget(self.tabWidget)

        # Setup tabs
        self.setupTab('VCU TX CAN Messages', self.getMsgs(True), TxMessageLayout)
        self.setupTab('VCU RX CAN Messages', self.getMsgs(False), RxMessageLayout)


if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logging.info(sys.version)
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
