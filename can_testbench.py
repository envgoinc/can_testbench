import sys
from dataclasses import dataclass, field
from collections import deque
from typing import List
import cantools
import can
import os
import logging
import pyqtgraph as pg
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

@dataclass
class DbcSignal:
    signal: object
    value: int | float
    graphValues: field(default_factory=lambda: deque(maxlen=100))
    graph: bool = False

@dataclass
class DbcMessage:
    message: object
    signals: list[DbcSignal]


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


class MsgModel(QAbstractTableModel):
    signalValueChanged = Signal(DbcMessage, int, object, object)

    Columns = [
        {'heading':'Signal Name', 'property':'name', 'editable':False},
        {'heading':'Description', 'property':'comment', 'editable': False},
        {'heading':'Unit', 'property':'unit', 'editable': False},
        {'heading':'Minimum', 'property':'minimum', 'editable': False},
        {'heading':'Maximum', 'property':'maximum', 'editable': False},
        {'heading':'Value', 'property':'initial', 'editable': True}
    ]
    def __init__(self, msg: DbcMessage, parent=None):
        super().__init__(parent)
        self.msg = msg
        self.rxTable = 'VCU' not in msg.message.senders

    def rowCount(self, parent=None):
        # number of signals in message
        return len(self.msg.signals)

    def columnCount(self, parent=None):
        return len(MsgModel.Columns)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.DisplayRole:
            sig = self.msg.signals[index.row()]
            if MsgModel.Columns[index.column()]['editable']:
                return str(self.msg.signals[index.row()].value)
            else:
                return getattr(sig.signal,MsgModel.Columns[index.column()]['property'])
        elif self.rxTable and role == Qt.CheckStateRole and index.column() == 5:
            return Qt.Checked if self.msg.signals[index.row()].graph else Qt.Unchecked
        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return MsgModel.Columns[section]['heading']
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
                isFloat = self.msg.signals[index.row()].signal.is_float
                if isFloat:
                    requestedValue = float(value)
                else:
                    requestedValue = int(value)
                if (requestedValue >= self.msg.signals[index.row()].signal.minimum and
                    requestedValue <= self.msg.signals[index.row()].signal.maximum):
                    if isFloat:
                        self.msg.signals[index.row()].value = float(value)
                    else:
                        self.msg.signals[index.row()].value = int(value)
                    self.dataChanged.emit(index, index, [role])
                    if self.rxTable:
                        self.signalValueChanged.emit(self.msg,
                                                     index.row(),
                                                     self.msg.signals[index.row()].value,
                                                     None)
                    return True
            if self.rxTable and role == Qt.CheckStateRole:
                self.msg.signals[index.row()].graph = value == 2
                self.dataChanged.emit(index, index)
                self.signalValueChanged.emit(self.msg,
                                             index.row(),
                                             None,
                                             self.msg.signals[index.row()].graph)
                return True
        return False

    def updateSignalValues(self, canMsg: can.Message):
        signalValues = self.msg.message.decode(canMsg.data)
        for signalName in signalValues.keys():
            for i, signal in enumerate(self.msg.signals):
                if signal.name == signalName:
                    row = i
                    break
            index = self.index(row, 5)
            self.setData(index, signalValues[signalName])

    @property
    def msgData(self):
        signalDict = {}
        for idx, sig in enumerate(self.msg.signals):
            signalDict[sig.signal.name] = self.msg.signals[idx].value
        logging.debug(f'{signalDict=}')
        data = self.msg.message.encode(signalDict, strict=True)
        return data


class MsgGraphWindow(QWidget):
    def __init__(self, msg: DbcMessage):
        super().__init__()
        self.msg = msg
        windowTitle = msg.message.name + ' Graph'
        self.setWindowTitle(windowTitle)

        # PyQtGraph setup
        self.plotWidget = pg.PlotWidget()
        self.legend = self.plotWidget.addLegend()
        self.plotSeries = {}

        layout = QVBoxLayout()
        layout.addWidget(self.plotWidget)
        self.setLayout(layout)

        # Update interval
        self.timer = QTimer(self)
        self.timer.setInterval(500)  # in milliseconds
        self.timer.timeout.connect(self.updatePlot)
        self.timer.start()

    def updatePlot(self):
        # Find the length of the longest series
        maxLength = max(len(signal.graphValues) for signal in self.msg.signals if signal.graph)

        for index, signal in enumerate(self.msg.signals):
            if signal.graph:  # Only plot signals marked for graphing
                # The values are already guaranteed to be within the last 100 entries
                values = signal.graphValues
                # Calculate the starting x-value based on the maxLength
                startX = max(0, maxLength - len(values))
                x = list(range(startX, startX + len(values)))
                # Generate a unique color for each signal based on its index
                color = pg.intColor(index, hues=len(self.data.signals))
                pen = pg.mkPen(color=color, width=2)

                if index not in self.plotSeries:
                    # Create a new series if it doesn't exist
                    self.plotSeries[index] = self.plotWidget.plot(x, values, pen=pen, name=signal.name)
                else:
                    # Update existing series
                    self.plotSeries[index].setData(x, values, pen=pen)
            else:
                # Remove the plot series if it exists but should no longer be graphed
                if index in self.plotSeries:
                    self.plotWidget.removeItem(self.plotSeries[index])
                    del self.plotSeries[index]

    def closeEvent(self, event):
        # Perform any cleanup or save data here
        logging.debug('Closing graph window.')
        # Call the superclass's closeEvent method to proceed with the closing
        super().closeEvent(event)

class MessageLayout(QWidget):
    FrequencyValues = [0, 1, 5, 10, 20, 40, 50, 100]
    ColumnWidths = [300, 500, 50, 100, 100, 150]

    def __init__(self, bus: can.Bus, msgTable: MsgModel, msg: DbcMessage):
        super().__init__()
        MessageLayout.bus = bus
        self.frequency = 0
        self.msgTableModel = msgTable
        self.msg = msg
        self.canBusMsg = can.Message(arbitration_id=msg.message.frame_id,
                                is_extended_id=msg.message.is_extended_frame,
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
        msgString = f'{self.msg.message.name}: {hex(self.msg.message.frame_id)}; Frequency = '
        cycleTime = self.msg.message.cycle_time
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
            signalTableView.setColumnWidth(column, MessageLayout.ColumnWidths[column])
        signalTableView.resizeRowsToContents()
        signalTableView.setAlternatingRowColors(True)
        self.resizeTableViewToContents(signalTableView)
        self.mainLayout.addWidget(signalTableView)

        self.setLayout(self.mainLayout)

    def initUI(self):
        self.initBaseUI()
        logging.debug('super initUI')
        # This method will be overridden by derived classes
class TxMessageLayout(MessageLayout):
    def __init__(self, bus: can.Bus, msgTable: MsgModel, msg: DbcMessage):
        self.sendMsg = False
        super().__init__(bus, msgTable, msg)

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
        sendString = hex(self.msg.message.frame_id) + ': <' + sendDataStr + '>'
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
    def __init__(self, bus: can.Bus, msgTable: MsgModel, msg: DbcMessage):
        super().__init__(bus, msgTable, msg)

    def initUI(self):
        super().initBaseUI()

    def updateSendString(self):
        pass

class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CAN Testbench')
        self.dbcDb = cantools.database.load_file('../envgo/dbc/xerotech_battery_j1939.dbc')
        self.rxMsgs = []
        self.txMsgs = []
        self.setupMessages()
        self.msgTableDict = {}
        self.msgGraphWindowDict = {}
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

    def handleRxCanMsg(self, canMsg: can.Message):
        logging.debug(f'Received CAN message ID: {canMsg.arbitration_id:x}')
        msgTable = self.msgTableDict.get(canMsg.arbitration_id)
        if msgTable is not None:
            msgTable.updateSignalValues(canMsg)

    def setupMessages(self):
        for msg in self.dbcDb.messages:
            message = DbcMessage(message=msg, signals=[])
            for sig in msg.signals:
                isFloat = sig.is_float
                if(isFloat):
                    value = float(sig.initial) if sig.initial is not None else 0.0
                else:
                    value = int(sig.initial) if sig.initial is not None else 0

                signal = DbcSignal(signal=sig, value=value, graphValues=[])
                message.signals.append(signal)
            if msg.senders is not None and 'VCU' in msg.senders:
                self.txMsgs.append(message)
            else:
                self.rxMsgs.append(message)


    def onSignalValueChanged(self, msg: DbcMessage, row: int, value: object, graph: object):
        if graph is not None:
            if graph:
                if self.msgGraphWindowDict.get(msg) is None:
                    self.msgGraphWindowDict[msg] = MsgGraphWindow(msg)
                    self.msgGraphWindowDict[msg].show()
            else:
                # stop plotting signal
                msg.signals[row].graphValues = []

                closeGraphWindow = True

                # close window if no signals are plotted
                for signal in msg.signals:
                    if signal.graph:
                        closeGraphWindow = False

                if closeGraphWindow:
                    self.msgGraphWindowDict[msg].close()
                    self.msgGraphWindowDict[msg] = None

        if value is not None:
            if msg.signals[row].graph:
                msg.signals[row].graphValues.append(value)

    def setupTab(self, title: str, messages: List[DbcMessage], layoutClass: MessageLayout):
        tab = QWidget()

        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollContent = QWidget()
        tabLayout = QVBoxLayout(scrollContent)

        for msg in messages:
            msgTable = MsgModel(msg)
            msgLayout = layoutClass(self.canBus, msgTable, msg)

            if(layoutClass == RxMessageLayout):
                msgTable.signalValueChanged.connect(self.onSignalValueChanged)
                self.msgTableDict[msg.message.frame_id] = msgTable
            tabLayout.addWidget(msgLayout)

        scrollArea.setWidget(scrollContent)
        layout = QVBoxLayout(tab)  # This is the layout for the tab itself
        layout.addWidget(scrollArea)  # Add the scrollArea to the tab's layout

        self.tabWidget.addTab(tab, title)

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.setCentralWidget(self.tabWidget)

        # Setup tabs
        self.setupTab('VCU TX CAN Messages', self.txMsgs, TxMessageLayout)
        self.setupTab('VCU RX CAN Messages', self.rxMsgs, RxMessageLayout)


if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    logging.info(sys.version)
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
