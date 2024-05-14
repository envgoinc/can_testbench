import sys
import dataclasses
import collections
import typing
import enum
import cantools
from cantools.database import can as toolcan
from cantools.database.namedsignalvalue import NamedSignalValue
import can as pycan
import logging
import pyqtgraph as pg
from PySide6 import QtCore
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QTabWidget,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QTableView,
    QLabel,
    QComboBox,
    QCheckBox,
    QScrollArea,
    QLineEdit,
    QPushButton,
    QTabBar,
    QFileDialog
)


@dataclasses.dataclass
class DbcSignal:
    """
    A class representing a signal in a CAN message.

    Attributes:
    signal (object): The cantools signal object.
    value (int | float | str): The value the signal should be (in case of TX) or
    is (in case of RX).
    graphValues (deque): A deque of max 100 values that will be graphed.
    Values are the latest values received
    graph (bool): Whether or not the signal should be graphed.
    """
    signal: toolcan.Signal
    value: int | float | str
    graphValues: collections.deque = dataclasses.field(default_factory=lambda: collections.deque(maxlen=100))
    graph: bool = False

@dataclasses.dataclass
class DbcMessage:
    """
    A class representing a CAN message.

    Attributes:
    message (object): The cantools message object.
    signals (list of DbcSignals): List of DbcSignals
    graphWindow (object): Represents the window that is showing the graph of signals
    """
    message: pycan.Message
    signals: list[DbcSignal]
    graphWindow: object = None


class CanListener(pycan.Listener):
    """
    A class representing a can.Listener from Python CAN.

    Attributes:
    messageSignal (Signal): A signal that can be emitted when a message is received
    """
    def __init__(self, messageSignal):
        super().__init__()
        self.messageSignal = messageSignal

    def on_message_received(self, msg):
        """
        Called from a different thread (other than the UI thread). when a message
        is received.  That is why it sends a signal.

        Parameters:
        msg (can.Message): The message received.
        """
        # Emit signal with the received CAN message
        self.messageSignal.emit(msg)

    def stop(self):
        pass

class CanBusHandler(QtCore.QObject):
    """
    A class representing the CAN bus.  It inherits from QObject so it can send a signal.

    Attributes:
    messageReceived (Signal): A class object that can notify on messages received
    bus (pycan.Bus): Represents the physical CAN bus
    periodicMsg (dictionary): Keeps track of the data, and period of the message sent.
    Also the task sending the periodic message.
    listener (CanListener): The class that is listening for CAN messages
    notifier (can.Notifier): The class that will notify on a message received from Python CAN.
    """
    messageReceived = QtCore.Signal(pycan.Message)

    def __init__(self, bus, parent=None):
        super(CanBusHandler, self).__init__(parent)
        self.bus = bus
        self.periodicMsgs = {}
        self.listener = CanListener(self.messageReceived)
        self.notifier = pycan.Notifier(self.bus, [self.listener])

    def sendCanMessage(self, msg, frequency=0):
        """
        Sends either a single CAN message in the case when frequency is 0
        Or sets up a task to send periodic messages if frequency is not 0

        Parameters:
        msg (can.Message): The message to be sent.
        frequency (int): The frequency of how often to send the message
        """
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


class MsgModel(QtCore.QAbstractTableModel):
    """
    A class that handles the data in a message table.  Can either be a message that
    is transmitted from the app or received by the app.

    Attributes:
    signalValueChanged (Signal): A class attribute that represents the signal
    to be sent if something in the table changes.
    Columns (dict): A class attribute describing the columns in the table
    msg (DbcMessage): The message the table is displaying
    rxTable (bool): True if this is a table that describes messages the app receives
    """
    SignalValueChanged = QtCore.Signal(DbcMessage, int, object, object)

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

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            sig = self.msg.signals[index.row()]
            if MsgModel.Columns[index.column()]['editable']:
                return str(self.msg.signals[index.row()].value)
            else:
                return getattr(sig.signal,MsgModel.Columns[index.column()]['property'])
        elif self.rxTable and role == Qt.ItemDataRole.CheckStateRole and index.column() == 5:
            return Qt.CheckState.Checked if self.msg.signals[index.row()].graph else Qt.CheckState.Unchecked
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return MsgModel.Columns[section]['heading']
        return None

    def flags(self, index):
        # Set the flag to editable for the Name column
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 5:
            if self.rxTable:
                return super().flags(index) | Qt.ItemFlag.ItemIsUserCheckable
            else:
                return super().flags(index) | Qt.ItemFlag.ItemIsEditable
        return super().flags(index)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 5:
            if role == Qt.ItemDataRole.EditRole:
                if self.rxTable:
                    if isinstance(value, NamedSignalValue):
                        requestedValue = value.name
                        graphValue = value.value
                    else:
                        # should already be int or float
                        assert(isinstance(value, int | float))
                        requestedValue = value
                        graphValue = requestedValue
                    self.msg.signals[index.row()].value = requestedValue
                    self.dataChanged.emit(index, index, [role])
                    self.SignalValueChanged.emit(self.msg,
                                                 index.row(),
                                                 graphValue,
                                                 None)
                else:
                    # TX table
                    assert(isinstance(value, str))
                    isFloat = self.msg.signals[index.row()].signal.is_float
                    if isFloat:
                        requestedValue = float(value)
                    else:
                        requestedValue = int(value)

                    if (requestedValue >= self.msg.signals[index.row()].signal.minimum and
                        requestedValue <= self.msg.signals[index.row()].signal.maximum):
                        self.msg.signals[index.row()].value = requestedValue
                        self.dataChanged.emit(index, index, [role])
                        return True
            if self.rxTable and role == Qt.ItemDataRole.CheckStateRole:
                self.msg.signals[index.row()].graph = value == 2
                self.dataChanged.emit(index, index)
                self.SignalValueChanged.emit(self.msg,
                                             index.row(),
                                             None,
                                             self.msg.signals[index.row()].graph)
                return True
        return False

    def updateSignalValues(self, canMsg: pycan.Message):
        signalValues = self.msg.message.decode(canMsg.data)
        assert(isinstance(signalValues, dict))
        for signalName in signalValues.keys():
            for i, sig in enumerate(self.msg.signals):
                if sig.signal.name == signalName:
                    row = i
                    break
            index = self.index(row, 5)
            self.setData(index, signalValues[signalName])

    @property
    def msgData(self) -> bytes:
        """
        Returns what the table represents as a can.Message

        Parameters:
        None
        """
        signalDict = {}
        for idx, sig in enumerate(self.msg.signals):
            signalDict[sig.signal.name] = self.msg.signals[idx].value
        logging.debug(f'{signalDict=}')
        data = self.msg.message.encode(signalDict, strict=True)
        return data


class MsgGraphWindow(QWidget):
    """
    A class that shows a realtime graph of the signals in a message in a separate window

    Attributes:
    msg (DbcMessage): The message to be graphed (depending on the graph boolean)
    plotWidget (PlotWidget): pyqtgraph object representing the graph
    plotSeries (dict): Represent the data to be graphed
    timer (QTimer): How often to update the graph
    """
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
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)  # in milliseconds
        self.timer.timeout.connect(self.updatePlot)
        self.timer.start()

    def updatePlot(self):
        # Find the length of the longest series
        maxLength = max(len(signal.graphValues) for signal in self.msg.signals if signal.graph)

        for index, sig in enumerate(self.msg.signals):
            if sig.graph:  # Only plot signals marked for graphing
                # The values are already guaranteed to be within the last 100 entries
                values = sig.graphValues
                # Calculate the starting x-value based on the maxLength
                startX = max(0, maxLength - len(values))
                x = list(range(startX, startX + len(values)))
                # Generate a unique color for each signal based on its index
                color = pg.intColor(index, hues=len(self.msg.signals))
                pen = pg.mkPen(color=color, width=2)

                if index not in self.plotSeries:
                    # Create a new series if it doesn't exist
                    self.plotSeries[index] = self.plotWidget.plot(x, values, pen=pen, name=sig.signal.name)
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
        permitClose = True
        for sig in self.msg.signals:
            if sig.graph:
                permitClose = False

        if permitClose:
            logging.debug('Closing graph window')
            # Call the superclass's closeEvent method to proceed with the closing
            super().closeEvent(event)
        else:
            logging.debug('Ignoring graph window close event')
            event.ignore()


class CanConfig():
    """
    Source of truth for current and allowed configs

    Attributes:

    """ 
    
    class Interface(enum.Enum):
        slcan = 0
        udp_multicast = 1
        
    selected = Interface.udp_multicast
    slcan_bitrates = [10000, 20000, 50000, 100000, 125000, 250000, 500000, 750000, 1000000, 83300]
    DbcFile = '../envgo/dbc/testbench.dbc'
    
    options = [
        {'interface': Interface.slcan.name,
         'channel': '/dev/tty.usbmodem3946375033311',
         'bitrate': 500000,
         'receive_own_messages': False},
        {'interface': Interface.udp_multicast.name,
         'channel': '239.0.0.1',
         'port': 10000,
         'receive_own_messages': False}
    ]
    
    def __init__(self):
        super().__init__()
        
    def index():
        return CanConfig.selected.value
    
    def setIndex(index: int):
        CanConfig.selected = CanConfig.Interface(index)
        
    def setChannel(channel: str):
        if 'channel' in CanConfig.options[CanConfig.index()]:
            CanConfig.options[CanConfig.index()]['channel'] = channel
        
    def changeBitrate(index: int):
        if 'bitrate' in CanConfig.options[CanConfig.index()]:
            CanConfig.options[CanConfig.index()]['bitrate'] = CanConfig.slcan_bitrates[index]
        
    def setPort(port: str | int):
        if 'port' in CanConfig.options[CanConfig.index()]:
            CanConfig.options[CanConfig.index()]['port'] = int(port)
            
    def setDbc(path: str):
        DbcFile = path
    
    
class ConfigLayout(QWidget):
    """
    UI Tab for changing config settings

    Attributes:

    """
    
    appliedCan = QtCore.Signal()

    def __init__(self):
        super().__init__()
        self.initUI()
    
    def applyCan(self):
        self.appliedCan.emit()

    def updateBoxes(self):
        channel = CanConfig.options[CanConfig.index()].get('channel')
        if(channel is not None):
            self.channelBox.setText(channel)
            self.channelBox.setEnabled(True)
        else:
            self.channelBox.setEnabled(False)
        
        bitrate = CanConfig.options[CanConfig.index()].get('bitrate')
        if(bitrate is not None):
            self.baudBox.setCurrentText(str(bitrate))
            self.baudBox.setEnabled(True)
        else:
            self.baudBox.setEnabled(False)
            
        port = CanConfig.options[CanConfig.index()].get('port')
        if(port is not None):
            self.portBox.setText(str(port))
            self.portBox.setEnabled(True)
        else:
            self.portBox.setEnabled(False)

    def changeInterface(self, index: int):
        CanConfig.setIndex(index)
        self.updateBoxes()

    def initBaseUI(self):
        self.mainLayout = QVBoxLayout()
        
        self.interfaceBox = QComboBox()
        for i in CanConfig.Interface:
            self.interfaceBox.addItem(i.name)
        self.interfaceBox.setCurrentIndex(CanConfig.index())
        self.interfaceBox.activated.connect(self.changeInterface)
        self.mainLayout.addWidget(self.interfaceBox)
        
        self.dbcDialog = QFileDialog()
        
        self.channelBox = QLineEdit()
        self.channelBox.textEdited.connect(CanConfig.setChannel)
        self.mainLayout.addWidget(self.channelBox)
        
        self.baudBox = QComboBox()
        for br in CanConfig.slcan_bitrates:
            self.baudBox.addItem(str(br))
        self.baudBox.activated.connect(CanConfig.changeBitrate)
        self.mainLayout.addWidget(self.baudBox)
        
        self.portBox = QLineEdit()
        self.channelBox.textEdited.connect(CanConfig.setPort)
        self.mainLayout.addWidget(self.portBox)
        
        self.updateBoxes()
        
        self.applyButton = QPushButton('Apply')
        self.applyButton.clicked.connect(self.applyCan)
        self.mainLayout.addWidget(self.applyButton)
        
        self.setLayout(self.mainLayout)

    def initUI(self):
        self.initBaseUI()
        
class MessageLayout(QWidget):
    """
    A class that represents the table that shows the Message

    Attributes:

    """
    FrequencyValues = [0, 1, 5, 10, 20, 40, 50, 100]
    ColumnWidths = [300, 500, 50, 100, 100, 150]

    def __init__(self, bus: pycan.Bus, msgTable: MsgModel, msg: DbcMessage):
        super().__init__()
        MessageLayout.bus = bus
        self.frequency = 0
        self.msgTableModel = msgTable
        self.msg = msg
        self.canBusMsg = pycan.Message(arbitration_id=msg.message.frame_id,
                                is_extended_id=msg.message.is_extended_frame,
                                data=self.msgTableModel.msgData)
        self.initUI()

    def onDataChanged(self, topLeft, bottomRight, roles):
        if not roles or Qt.ItemDataRole.EditRole in roles:
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
        # This method will be overridden by derived classes
        self.initBaseUI()
        logging.debug('super initUI')

class TxMessageLayout(MessageLayout):
    """
    A class that represents a table that shows a Message that can be transmitted
    on the can bus

    Attributes:

    """
    def __init__(self, bus: pycan.Bus, msgTable: MsgModel, msg: DbcMessage):
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
    """
    A class that represents a table that shows a Message that can be received
    on the can bus

    Attributes:

    """
    def __init__(self, bus: pycan.Bus, msgTable: MsgModel, msg: DbcMessage):
        super().__init__(bus, msgTable, msg)

    def initUI(self):
        super().initBaseUI()

    def updateSendString(self):
        pass

class MainApp(QMainWindow):
    """
    A class that represents the main application

    Attributes:

    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CAN Testbench')
        self.dbcDb = cantools.database.load_file(DbcFile)
        self.rxMsgs = []
        self.txMsgs = []
        self.setupMessages()
        self.msgTableDict = {}
        #canBus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=10000, receive_own_messages=False)
        # canBus = can.Bus(interface='slcan', channel='/dev/ttyACM0', bitrate=500000, receive_own_messages=False)
        # self.canBus = CanBusHandler(canBus)
        # self.canBus.messageReceived.connect(self.handleRxCanMsg)
        self.initUI()
        self.resizeToScreenFraction()

    def resizeToScreenFraction(self, fractionWidth=1, fractionHeight=0.8):
        # Get the screen size
        screen = QApplication.primaryScreen()
        screenSize = screen.size()

        # Calculate the window size as a fraction of the screen size
        newWidth = screenSize.width() * fractionWidth
        newHeight = screenSize.height() * fractionHeight
        newWidth = min(newWidth,1350)
        logging.debug(f'Window size: {newWidth}x{newHeight}')

        # Resize the window
        self.resize(newWidth, newHeight)

    def handleRxCanMsg(self, canMsg: pycan.Message):
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

                signal = DbcSignal(signal=sig, value=value)
                message.signals.append(signal)
            if msg.senders is not None and 'VCU' in msg.senders:
                self.txMsgs.append(message)
            else:
                self.rxMsgs.append(message)


    def onSignalValueChanged(self, msg: DbcMessage, row: int, value: object, graph: object):
        if graph is not None:
            if graph:
                if msg.graphWindow is None:
                    msg.graphWindow = MsgGraphWindow(msg)
                    msg.graphWindow.show()
            else:
                # stop plotting signal
                msg.signals[row].graphValues.clear()

                closeGraphWindow = True

                # close window if no signals are plotted
                for signal in msg.signals:
                    if signal.graph:
                        closeGraphWindow = False

                if closeGraphWindow:
                    msg.graphWindow.close()
                    msg.graphWindow = None

        if value is not None:
            if msg.signals[row].graph:
                msg.signals[row].graphValues.append(value)

    def setupTab(self, title: str, messages: typing.List[DbcMessage], layoutClass: MessageLayout):
        tab = QWidget()

        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollContent = QWidget()
        tabLayout = QVBoxLayout(scrollContent)

        for msg in messages:
            msgTable = MsgModel(msg)
            msgLayout = layoutClass(self.canBus, msgTable, msg)

            if(layoutClass == RxMessageLayout):
                msgTable.SignalValueChanged.connect(self.onSignalValueChanged)
                self.msgTableDict[msg.message.frame_id] = msgTable
            tabLayout.addWidget(msgLayout)

        scrollArea.setWidget(scrollContent)
        layout = QVBoxLayout(tab)  # This is the layout for the tab itself
        layout.addWidget(scrollArea)  # Add the scrollArea to the tab's layout

        self.tabWidget.addTab(tab, title)
        
    def setupLaunchTab(self):
        tab = QWidget()

        scrollContent = QWidget()
        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollArea.setWidget(scrollContent)
    
        configLayout = ConfigLayout()
        configLayout.appliedCan.connect(self.connectCan)
        tabLayout = QVBoxLayout(scrollContent)
        tabLayout.addWidget(configLayout)
        
        layout = QVBoxLayout(tab)  # This is the layout for the tab itself
        layout.addWidget(scrollArea)  # Add the scrollArea to the tab's layout

        self.tabWidget.addTab(tab, 'CAN Config')
        tabBar = self.tabWidget.tabBar()
        tabBar.tabButton(0, QTabBar.RightSide).deleteLater()
        tabBar.setTabButton(0, QTabBar.RightSide, None)
        
    @QtCore.Slot()
    def connectCan(self):                                                                                   
        channel = CanConfig.options[CanConfig.index()].get('channel')
        for x in range(self.tabWidget.count()):
            if self.tabWidget.tabText(x).endswith(channel):
                self.tabWidget.removeTab(x)
        # canBus = pycan.Bus(interface='slcan', channel=channel, bitrate=bitrate, receive_own_messages=False)
        canBus = pycan.Bus(**CanConfig.options[CanConfig.index()])
        self.canBus = CanBusHandler(canBus)
        self.canBus.messageReceived.connect(self.handleRxCanMsg)
        # Setup tabs
        self.setupTab('VCU TX ' + channel, self.txMsgs, TxMessageLayout)
        self.setupTab('VCU RX ' + channel, self.rxMsgs, RxMessageLayout)

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.tabWidget.setTabsClosable(True)
        self.setCentralWidget(self.tabWidget)
        self.setupLaunchTab()


if __name__ == '__main__':
#  DbcFile = '../envgo/dbc/cascadia_inverter_gen5_nomux.dbc'
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.info(sys.version)
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
