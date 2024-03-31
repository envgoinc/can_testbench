import sys
from dataclasses import dataclass, field
from collections import deque
import cantools
import can
import os
import logging
import pyqtgraph as pg
import numpy as np
from PySide6.QtCore import (
    Qt,
    QAbstractTableModel,
    QModelIndex,
    Signal,
    QObject,
    QTimer
)
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

class CanListener(can.Listener):
    def __init__(self, messageSignal):
        super().__init__()
        self.messageSignal = messageSignal

    def on_message_received(self, msg):
        # Emit signal with the received CAN message
        self.messageSignal.emit(msg)

    def stop(self):
        pass

class CanBusHandler(QObject):
    messageReceived = Signal(can.Message)

    def __init__(self, bus, parent=None):
        super(CanBusHandler, self).__init__(parent)
        self.bus = bus
        self.periodicMsgs = {}
        self.listener = CanListener(self.messageReceived)
        self.notifier = can.Notifier(self.bus, [self.listener])

    def sendCanMessage(self, msg, frequency=0):
        if frequency == 0:
            self.bus.send(msg)
        else:
            period = 1/frequency
            sendDetails = self.periodicMsgs.get(msg.arbitration_id)
            if sendDetails is None:
                sendDetails = {}
                sendDetails['data'] = msg.data
                sendDetails['period'] = period
                task = self.bus.send_periodic(msg, period)
                sendDetails['task'] = task
                self.periodicMsgs[msg.arbitration_id] = sendDetails
            elif sendDetails['period'] != period or sendDetails['data'] != msg.data:
                sendDetails['task'].stop()
                sendDetails['data'] = msg.data
                if sendDetails['period'] != [period]:
                    task = self.bus.send_periodic(msg, period)
                    sendDetails['task'] = task
                    sendDetails['period'] = period
                else:
                    sendDetails['task'].start()

    def stop(self, msg):
        sendDetails = self.periodicMsgs.get(msg.arbitration_id)
        if sendDetails is not None:
            sendDetails['task'].stop()


class DbcMsgModel(QAbstractTableModel):
    signalValueChanged = Signal(object, int, bool, object)

    Columns = [
        {'heading':'Signal Name', 'property':'name', 'editable':False},
        {'heading':'Description', 'property':'comment', 'editable': False},
        {'heading':'Unit', 'property':'unit', 'editable': False},
        {'heading':'Minimum', 'property':'minimum', 'editable': False},
        {'heading':'Maximum', 'property':'maximum', 'editable': False},
        {'heading':'Value', 'property':'initial', 'editable': True}
    ]
    def __init__(self, dbcMsg, parent=None):
        super().__init__(parent)
        self.dbcMsg = dbcMsg
        self.rxTable = 'VCU' not in dbcMsg.senders
        self.value = []

        for signal in dbcMsg.signals:
            signalName = signal.name
            signalValue = int(signal.initial) if signal.initial is not None else 0
            signalDict = {'name':signalName, 'value':signalValue, 'graph':False}
            self.value.append(signalDict)

    def rowCount(self, parent=None):
        # number of signals in message
        return len(self.dbcMsg.signals)

    def columnCount(self, parent=None):
        return len(DbcMsgModel.Columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            signal = self.dbcMsg.signals[index.row()]
            if DbcMsgModel.Columns[index.column()]['editable']:
                return str(self.value[index.row()]['value'])
            else:
                return getattr(signal,DbcMsgModel.Columns[index.column()]['property'])
        elif self.rxTable and role == Qt.CheckStateRole and index.column() == 5:
            return Qt.Checked if self.value[index.row()]['graph'] else Qt.Unchecked
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return DbcMsgModel.Columns[section]['heading']
        return None

    def flags(self, index):
        # Set the flag to editable for the Name column
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 5:
            if self.rxTable:
                return super().flags(index) | Qt.ItemIsUserCheckable
            else:
                return super().flags(index) | Qt.ItemIsEditable

        return super().flags(index)

    def setData(self, index, value, role=Qt.EditRole):
        if index.isValid() and index.column() == 5:
            if role == Qt.EditRole:
                requestedValue = int(value)
                if (requestedValue >= self.dbcMsg.signals[index.row()].minimum and
                    requestedValue <= self.dbcMsg.signals[index.row()].maximum):
                    self.value[index.row()]['value'] = int(value)
                    self.dataChanged.emit(index, index, [role])
                    if self.rxTable:
                        self.signalValueChanged.emit(self.dbcMsg,
                                                     index.row(),
                                                     self.value[index.row()]['value'],
                                                     None)
                    return True
            if self.rxTable and role == Qt.CheckStateRole:
                self.value[index.row()]['graph'] = value == 2
                self.dataChanged.emit(index, index)
                self.signalValueChanged.emit(self.dbcMsg,
                                             index.row(),
                                             None,
                                             self.value[index.row()]['graph'])
                return True
        return False

    def updateSignalValues(self, canMsg):
        signalValues = self.dbcMsg.decode(canMsg.data)
        for signalName in signalValues.keys():
            for i, valueDict in enumerate(self.value):
                if valueDict.get('name') == signalName:
                    row = i
                    break
            index = self.index(row, 5)
            self.setData(index, signalValues[signalName])

    @property
    def msgData(self):
        signalDict = {}
        for idx, signal in enumerate(self.dbcMsg.signals):
            signalDict[signal.name] = self.value[idx]['value']
        logging.debug(f'{signalDict=}')
        data = self.dbcMsg.encode(signalDict, strict=True)
        return data

@dataclass
class SignalGraphItem:
    sigName: str
    unit: str
    values: deque = field(default_factory=lambda: deque(maxlen=100))
    graph: bool = False

@dataclass
class MsgGraphItem:
    msgName: str
    signals: list[SignalGraphItem]

class MsgGraphWindow(QWidget):
    def __init__(self, data):
        super().__init__()
        self.data = data
        windowTitle = data.msgName + ' Graph'
        self.setWindowTitle(windowTitle)

        # PyQtGraph setup
        self.plotWidget = pg.PlotWidget()
        self.plot = self.plotWidget.plot(pen='y')

        layout = QVBoxLayout()
        layout.addWidget(self.plotWidget)
        self.setLayout(layout)

        # Update interval
        self.timer = QTimer(self)
        self.timer.setInterval(500)  # in milliseconds
        self.timer.timeout.connect(self.updatePlot)
        self.timer.start()

    def updatePlot(self):
        x = list(range(len(self.data.signals[0].values)))
        self.plot.setData(x, self.data.signals[0].values)  # Update the plot

    def closeEvent(self, event):
        # Perform any cleanup or save data here
        logging.debug('Closing graph window.')
        # Call the superclass's closeEvent method to proceed with the closing
        super().closeEvent(event)

class MessageLayout(QWidget):
    FrequencyValues = [0, 1, 5, 10, 20, 40, 50, 100]

    def __init__(self, bus, msgTable, message):
        super().__init__()
        MessageLayout.bus = bus
        self.frequency = 0
        self.msgTableModel = msgTable
        self.message = message
        self.canBusMsg = can.Message(arbitration_id=self.message.frame_id,
                                is_extended_id=self.message.is_extended_frame,
                                data=self.msgTableModel.msgData)
        self.initUI()

    def onDataChanged(self, topLeft, bottomRight, roles):
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
        signalTableView.setModel(self.msgTableModel)
        self.msgTableModel.dataChanged.connect(self.onDataChanged)
        for column in range(self.msgTableModel.columnCount()):
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
    def __init__(self, bus, msgTable, message):
        self.sendMsg = False
        super().__init__(bus, msgTable, message)

    def sendChanged(self):
        if self.sendCheckBox.isChecked():
            logging.info(f'Send CAN frames at {self.frequency} Hz')
            self.sendMsg = True
        else:
            logging.info(f'Stop sending CAN frames')
            self.sendMsg = False
        if self.sendMsg:
            self.bus.sendCanMessage(self.canBusMsg, self.frequency)
            if self.frequency == 0:
                self.sendCheckBox.click()
        else:
            self.bus.stop(self.canBusMsg)

    def frequencyChanged(self):
        frequency = self.sendFrequencyCombo.currentData()
        logging.info(f'Frequency change: {frequency} Hz')
        self.frequency = frequency
        if self.sendMsg:
            self.bus.sendCanMessage(self.canBusMsg, self.frequency)
            if self.frequency == 0:
                self.sendCheckBox.click()

    def updateSendString(self):
        sendData = self.msgTableModel.msgData
        logging.debug(f'{sendData=}')
        sendDataStr = ''.join(f'0x{byte:02x} ' for byte in sendData)
        logging.debug(f'{sendDataStr=}')
        sendString = hex(self.message.frame_id) + ': <' + sendDataStr + '>'
        self.sendLabel.setText(sendString)
        logging.info(f'Data changed: {sendString}')
        self.canBusMsg.data = sendData
        if self.sendMsg:
            self.bus.sendCanMessage(self.canBusMsg, self.frequency)

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
    def __init__(self, bus, msgTable, message):
        super().__init__(bus, msgTable, message)

    def initUI(self):
        super().initBaseUI()

    def updateSendString(self):
        pass

class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CAN Testbench')
        self.msgTableDict = {}
        self.msgGraphDataDict = {}
        self.msgGraphWindowDict = {}
        self.dbc_db = cantools.database.load_file('../envgo/dbc/xerotech_battery_j1939.dbc')
        canBus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=10000, receive_own_messages=False)
        self.canBus = CanBusHandler(canBus)
        self.canBus.messageReceived.connect(self.handleRxCanMsg)
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

    def handleRxCanMsg(self, msg):
        logging.debug(f'Received CAN message ID: {msg.arbitration_id:x}')
        msgTable = self.msgTableDict.get(msg.arbitration_id)
        if msgTable is not None:
            msgTable.updateSignalValues(msg)

    def getMsgs(self, vcu):
        msg_list = []
        for msg in self.dbc_db.messages:
            if vcu and msg.senders is not None and 'VCU' in msg.senders:
                msg_list.append(msg)
            elif not vcu and 'VCU' not in msg.senders:
                msg_list.append(msg)
        return msg_list

    def onSignalValueChanged(self, msg, row, value, graph):
        msgGraphData = self.msgGraphDataDict[msg]
        if graph is not None:
            msgGraphData.signals[row].graph = graph
            if graph:
                if self.msgGraphWindowDict.get(msg) is None:
                    self.msgGraphWindowDict[msg] = MsgGraphWindow(msgGraphData)
                    self.msgGraphWindowDict[msg].show()
            else:
                # stop plotting signal
                msgGraphData.signals[row].values = []

                closeGraphWindow = True

                # close window if no signals are plotted
                for signal in msgGraphData.signals:
                    if signal.graph:
                        closeGraphWindow = False

                if closeGraphWindow:
                    self.msgGraphWindowDict[msg].close()
                    self.msgGraphWindowDict[msg] = None

        if value is not None:
            if msgGraphData.signals[row].graph:
                msgGraphData.signals[row].values.append(value)

    def setupTab(self, title, messages, layoutClass):
        tab = QWidget()

        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollContent = QWidget()
        tabLayout = QVBoxLayout(scrollContent)

        for msg in messages:
            msgTable = DbcMsgModel(msg)
            msgLayout = layoutClass(self.canBus, msgTable, msg)

            if(layoutClass == RxMessageLayout):
                msgGraph = MsgGraphItem(msgName=msg.name,
                                        signals=[])
                for signal in msg.signals:
                    signalGraph = SignalGraphItem(sigName=signal.name,
                                                  unit=signal.unit)
                    msgGraph.signals.append(signalGraph)
                msgTable.signalValueChanged.connect(self.onSignalValueChanged)
                self.msgGraphDataDict[msg] = msgGraph
                self.msgTableDict[msg.frame_id] = msgTable
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
