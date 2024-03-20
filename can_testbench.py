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
        if index.column() == 4:
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

class VcuSignalLayout(QWidget):
    SendFrequencyValues = [0, 1, 5, 10, 20, 40, 50, 100]
    def __init__(self, message):
        super().__init__()
        self.message = message
        self.sendFrequency=0
        self.initUI()

    def sendChanged(self):
        if self.sendCheckBox.isChecked():
            logging.info(f'Send CAN frames at {self.sendFrequency} Hz')
            self.send = True
        else:
            logging.info(f'Stop sending CAN frames')
            self.send = False

    def frequencyChanged(self):
        self.sendFrequency = self.sendFrequencyCombo.currentData()
        logging.info(f'Frequency change: {self.sendFrequency} Hz')

    def updateSendString(self):
        sendData = self.signalTableModel.msgData
        logging.debug(f'{sendData=}')
        sendDataStr = ''.join(f'0x{byte:02x} ' for byte in sendData)
        logging.debug(f'{sendDataStr=}')
        sendString = hex(self.message.frame_id) + ': <' + sendDataStr + '>'
        self.sendLabel.setText(sendString)
        logging.info(f'Data changed: {sendString}')

    def onDataChanged(self, topLeft, bottomRight, roles):
        logging.debug(f'data changed! {roles=}')
        if not roles or Qt.EditRole in roles:
            self.updateSendString()

    def initUI(self):
        # Main layout for this widget
        mainLayout = QVBoxLayout()

        msgString = self.message.name + ': '
        msgString += hex(self.message.frame_id)
        msgString += '; Frequency = '
        cycleTime = self.message.cycle_time
        if cycleTime is None or cycleTime == 0:
            msgString += 'not specified'
            self.sendFrequency = 1
        else:
            cycleTime /= 1000
            self.sendFrequency = min(VcuSignalLayout.SendFrequencyValues, key=lambda x: abs(x - 1/cycleTime))
            msgString += str(self.sendFrequency)
            msgString += ' Hz'
        msgLabel = QLabel(msgString)
        mainLayout.addWidget(msgLabel)

        # Initialize the table for signals
        signalTableView = QTableView()
        self.signalTableModel = DbcVcuModel(self.message)
        signalTableView.setModel(self.signalTableModel)
        self.signalTableModel.dataChanged.connect(self.onDataChanged)

        for column in range(self.signalTableModel.columnCount()):
            signalTableView.resizeColumnToContents(column)
            if signalTableView.columnWidth(column) > 500:
                signalTableView.setColumnWidth(column, 500)

        # Ensure rows are tall enough to display wrapped text
        signalTableView.resizeRowsToContents()

        mainLayout.addWidget(signalTableView)

        canSendLayout = QHBoxLayout()
        self.sendLabel = QLabel()
        self.updateSendString()
        canSendLayout.addWidget(self.sendLabel)

        freqComboLayout = QHBoxLayout()
        sendFrequencyLabel = QLabel('Select Send Frequency')
        freqComboLayout.addStretch(1)
        freqComboLayout.addWidget(sendFrequencyLabel)
        self.sendFrequencyCombo = QComboBox()
        for value in VcuSignalLayout.SendFrequencyValues:
            self.sendFrequencyCombo.addItem(str(value), value)
        index = self.sendFrequencyCombo.findData(self.sendFrequency)
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

        mainLayout.addLayout(canSendLayout)

        # Create a horizontal line
        hline = QFrame()
        hline.setFrameShape(QFrame.HLine)
        hline.setFrameShadow(QFrame.Sunken)

        mainLayout.addWidget(hline)

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

    def getVcuMsgs(self):
        vcu_msg = []
        for msg in self.dbc_db.messages:
            if msg.senders is not None and 'VCU' in msg.senders:
                vcu_msg.append(msg)
        return vcu_msg

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.setCentralWidget(self.tabWidget)

        # Create the first tab
        self.firstTab = QWidget()
        self.firstTabLayout = QVBoxLayout()
        self.firstTab.setLayout(self.firstTabLayout)

        for msg in self.getVcuMsgs():
            signalLayout = VcuSignalLayout(msg)
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
