# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --disable-console
# nuitka-project: --standalone
from __future__ import annotations
import sys
from os import path
import configparser
import dataclasses
import collections
import enum
from cantools import database
from cantools.database.can import signal
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
    QFileDialog,
    QMessageBox,
    QGridLayout,
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
    graphed (bool): Whether or not the signal should be graphed.
    """
    signal: signal.Signal
    value: int | float | str
    graphValues: collections.deque = dataclasses.field(default_factory=lambda: collections.deque(maxlen=100))
    graphed: bool = False

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
    graphWindow: MsgGraphWindow | None = None


class CanListener(pycan.Listener):
    """
    A class representing a pycan.Listener from Python CAN.

    Attributes:
    messageSignal (Signal): A signal that can be emitted when a message is received
    channel (str): The channel this listener is associated with
    """
    def __init__(self, messageSignal, channel: str = ''):
        super().__init__()
        self.messageSignal = messageSignal
        self.channel = channel

    def on_message_received(self, msg):
        """
        Called from a different thread (other than the UI thread). when a message
        is received.  That is why it sends a signal.

        Parameters:
        msg (can.Message): The message received.
        """
        # Emit signal with the received CAN message and associated channel
        self.messageSignal.emit(msg, self.channel)

    def stop(self):
        pass

class CanBusHandler(QtCore.QObject):
    """
    A class representing the CAN bus.  It inherits from QObject so it can send a signal.

    Attributes:
    messageReceived (Signal): A class object that can notify on messages received
    bus (pycan.Bus): Represents the physical CAN bus
    channel (str): Name of the channel the bus is attached to
    periodicMsg (dictionary): Keeps track of the data, and period of the message sent.
    Also the task sending the periodic message.
    listener (CanListener): The class that is listening for CAN messages
    notifier (can.Notifier): The class that will notify on a message received from Python CAN.
    """
    messageReceived = QtCore.Signal(pycan.Message, str)

    def __init__(self, bus: pycan.bus, channel: str = '', parent=None):
        super(CanBusHandler, self).__init__(parent)
        self.bus = bus
        self.channel = channel
        self.periodicMsgs = {}
        self.listener = CanListener(self.messageReceived, channel)
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
            
    def shutdown(self):
        self.notifier.stop()
        self.bus.shutdown()


class MsgModel(QtCore.QAbstractTableModel):
    """
    A class that handles the data in a message table.  Can either be a message that
    is transmitted from the app or received by the app.

    Attributes:
    signalValueChanged (Qt.Signal): A class attribute that represents the signal
    to be sent if the value of a can Signal in the table changes.
    signalGraphedChanged (Qt.Signal): A signal to be sent if the graphed status
    of a can Signal in the table changes.
    Columns (dict): A class attribute describing the columns in the table
    msg (DbcMessage): The message the table is displaying
    rxTable (bool): True if this is a table that describes messages the app receives
    """
    signalValueChanged = QtCore.Signal(DbcMessage, int, float)
    signalGraphedChanged = QtCore.Signal(DbcMessage, int, bool, object)

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
            return Qt.CheckState.Checked if self.msg.signals[index.row()].graphed else Qt.CheckState.Unchecked
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

    def stopGraph(self):
        for x in range(0, self.rowCount()):
            self.setData(self.index(x, 5), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

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
                        graphValue = value
                    self.msg.signals[index.row()].value = requestedValue
                    self.dataChanged.emit(index, index, [role])
                    self.signalValueChanged.emit(self.msg,
                                                 index.row(),
                                                 graphValue)
                else:
                    # TX table
                    assert(isinstance(value, str))
                    isFloat = self.msg.signals[index.row()].signal.is_float
                    if isFloat:
                        requestedValue = float(value)
                    else:
                        requestedValue = int(value)

                    if ((self.msg.signals[index.row()].signal.minimum is None or
                        requestedValue >= self.msg.signals[index.row()].signal.minimum) and
                        (self.msg.signals[index.row()].signal.maximum is None or
                        requestedValue <= self.msg.signals[index.row()].signal.maximum)):
                        self.msg.signals[index.row()].value = requestedValue
                        self.dataChanged.emit(index, index, [role])
                        return True
            if self.rxTable and role == Qt.ItemDataRole.CheckStateRole:
                self.msg.signals[index.row()].graphed = (value == Qt.CheckState.Checked.value)
                self.dataChanged.emit(index, index)
                self.signalGraphedChanged.emit(self.msg,
                                             index.row(),
                                             self.msg.signals[index.row()].graphed,
                                             self.stopGraph)
                return True
        return False

    def updateSignalValues(self, canMsg: pycan.Message):
        signalValues = self.msg.message.decode(canMsg.data)
        assert(isinstance(signalValues, dict))
        row = -1
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
    graphWindowClosed (Qt.Signal): Signal sent on graph window close
    msg (DbcMessage): The message to be graphed (depending on the graph boolean)
    plotWidget (PlotWidget): pyqtgraph object representing the graph
    plotSeries (dict): Represent the data to be graphed
    timer (QTimer): How often to update the graph
    """
    
    graphWindowClosed = QtCore.Signal()
    
    def __init__(self, msg: DbcMessage, stopGraph = None):
        super().__init__()
        self.msg = msg
        windowTitle = msg.message.name + ' Graph'
        self.setWindowTitle(windowTitle)
        self.graphWindowClosed.connect(stopGraph)
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
        maxLength = max(len(signal.graphValues) for signal in self.msg.signals if signal.graphed)

        for index, sig in enumerate(self.msg.signals):
            if sig.graphed:  # Only plot signals marked for graphing
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
        
        if permitClose:
            self.graphWindowClosed.emit()
            logging.debug('Closing graph window')
            # Call the superclass's closeEvent method to proceed with the closing
            super().closeEvent(event)
        else:
            logging.debug('Ignoring graph window close event')
            event.ignore()

class Interface(enum.Enum):
    slcan = 0
    udp_multicast = 1


SLCAN_BITRATES = (10000, 20000, 50000, 100000, 125000, 250000, 500000, 750000, 1000000, 83300)

class CanConfig():
    """
    Source of truth for current and allowed configs

    Attributes:
    config (ConfigParser): Handler for read/write of config file
    scriptDir (str): Location of script or application
    configFile (str): Location of config file
    selected (enum): Type of selected interface
    dbcFile (str): Location of dbc file
    options (list[dict[str, str]]): Option sets for each interface type 
    """ 
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.scriptDir = path.dirname(path.abspath(__file__))
        self.configFile = path.join(self.scriptDir, 'can_config.ini')
        self.selected = Interface.udp_multicast
        self.dbcFile = path.join(self.scriptDir, '../envgo/dbc/testbench.dbc')
        self.options : list[dict[str, str]] = [
            {'interface': Interface.slcan.name,
            'channel': '/dev/tty.usbmodem3946375033311',
            'bitrate': '500000',
            'receive_own_messages': 'False'},
            {'interface': Interface.udp_multicast.name,
            'channel': '239.0.0.1',
            'port': '10000',
            'receive_own_messages': 'False'}
        ]
        self.initConfig()
        
    def initConfig(self):
        if not path.isfile(self.configFile):
            self.writeConfig()
        else:
            self.readConfig()
            
    def writeConfig(self):
        self.config['General'] = {
            'default_interface': self.selected.name,
            'dbc_file': self.dbcFile
        }
        for interface in Interface:
            self.config[interface.name] = self.options[interface.value]
            with open(self.configFile, 'w') as configfile:
                self.config.write(configfile)
            
    def readConfig(self):
        self.config.read(self.configFile)
        general = self.config['General']
        if general.get('default_interface', None) is not None:
            self.selected = Interface[general['default_interface']]
        if general.get('dbc_file', None) is not None:
            self.dbcFile = general['dbc_file']
        for interface in Interface:
            for key in self.options[interface.value]:
                if self.config[interface.name][key]:
                    self.options[interface.value][key] = self.config[interface.name][key]
        
    def index(self) -> int:
        return self.selected.value
    
    def setInterface(self, interface: int | Interface):
        if type(interface) == int:
            self.selected = Interface(interface)
        elif type(interface) == Interface:
            self.selected = interface
        
    def setChannel(self, channel: str):
        if 'channel' in self.options[self.index()]:
            self.options[self.index()]['channel'] = channel
        
    def setBitrate(self, bitrate: int):
        if ('bitrate' in self.options[self.index()] and
            bitrate in SLCAN_BITRATES):
            self.options[self.index()]['bitrate'] = str(bitrate)
        
    def setPort(self, port: str | int):
        if 'port' in self.options[self.index()]:
            self.options[self.index()]['port'] = str(port)
            
    def setDbc(self, file: str):
        self.dbcFile = file
    
    
class ConfigLayout(QWidget):
    """
    UI Tab for changing config settings

    Attributes:
    config (CanConfig): Source of truth for current config
    """
    dbcOpened = QtCore.Signal()
    connectPressed = QtCore.Signal()
    
    def __init__(self, config: CanConfig):
        super().__init__()
        self.config = config
        self.initUI()
    
    def openDbc(self):
        file = QFileDialog.getOpenFileName(caption = "Open CAN Database file", dir = self.config.dbcFile, filter = "DBC file (*.dbc)")
        print(file)
        if(file[1] != 'DBC file (*.dbc)'):
            return
        self.config.setDbc(file[0])
        self.updateBoxes()
        self.dbcOpened.emit()
        
    def connectEnabled(self, bool):
        self.connectButton.setEnabled(bool)
    
    def changeInterface(self, index: int):
        self.config.setInterface(index)
        self.updateBoxes()
        
    def changeBitrate(self, index: int):
        self.config.setBitrate(int(self.baudBox.itemText(index)))
        
    def applyChannel(self):
        self.config.setChannel(self.channelBox.text())
        
    def applyPort(self):
        self.config.setPort(self.portBox.text())    

    def updateBoxes(self):
        self.dbcBox.setText(path.abspath(self.config.dbcFile))
        
        channel = self.config.options[self.config.index()].get('channel')
        if(channel is not None):
            self.channelBox.setText(channel)
            self.channelBox.setEnabled(True)
        else:
            self.channelBox.setEnabled(False)
        
        bitrate = self.config.options[self.config.index()].get('bitrate')
        if(bitrate is not None):
            self.baudBox.setCurrentText(bitrate)
            self.baudBox.setEnabled(True)
        else:
            self.baudBox.setEnabled(False)
            
        port = self.config.options[self.config.index()].get('port')
        if(port is not None):
            self.portBox.setText(port)
            self.portBox.setEnabled(True)
        else:
            self.portBox.setEnabled(False)

    def initBaseUI(self):
        screenSize = QApplication.primaryScreen().size()
        
        self.mainLayout = QHBoxLayout()
        self.configLayout = QGridLayout()
        self.mainLayout.addSpacing(int(screenSize.width()*0.15))
        self.mainLayout.addLayout(self.configLayout, stretch=0)
        self.mainLayout.addSpacing(int(screenSize.width()*0.15))
        
        infoLabel = QLabel()
        infoLabel.setText('DBC File:')
        self.configLayout.addWidget(infoLabel, 1, 1)
                
        self.dbcBox = QLineEdit()
        self.dbcButton = QPushButton()
        self.dbcButton.setText('...')
        self.dbcButton.clicked.connect(self.openDbc)
        self.configLayout.addWidget(self.dbcBox, 1, 2)
        self.configLayout.addWidget(self.dbcButton, 1, 3)
        
        interfaceLabel = QLabel()
        interfaceLabel.setText('Interface Type:')
        self.configLayout.addWidget(interfaceLabel, 2, 1)     
          
        self.interfaceBox = QComboBox()
        for i in Interface:
            self.interfaceBox.addItem(i.name)
        self.interfaceBox.setCurrentIndex(self.config.index())
        self.interfaceBox.activated.connect(self.changeInterface)
        self.configLayout.addWidget(self.interfaceBox, 2, 2)
        
        channelLabel = QLabel()
        channelLabel.setText('Channel:')
        self.configLayout.addWidget(channelLabel, 3, 1)
        
        self.channelBox = QLineEdit()
        self.channelBox.editingFinished.connect(self.applyChannel)
        self.configLayout.addWidget(self.channelBox, 3, 2)
        
        baudLabel = QLabel()
        baudLabel.setText('Baud Rate:')
        self.configLayout.addWidget(baudLabel, 4, 1)
        
        self.baudBox = QComboBox()
        for num in SLCAN_BITRATES:
            self.baudBox.addItem(str(num))
        self.baudBox.activated.connect(self.changeBitrate)
        self.configLayout.addWidget(self.baudBox, 4, 2)
        
        portLabel = QLabel()
        portLabel.setText('Port:')
        self.configLayout.addWidget(portLabel, 5, 1)

        self.portBox = QLineEdit()
        self.portBox.editingFinished.connect(self.applyPort)
        self.configLayout.addWidget(self.portBox, 5, 2)
        
        self.connectButton = QPushButton('Connect')
        self.connectButton.clicked.connect(self.connectPressed)
        self.connectButton.setEnabled(False)
        self.configLayout.addWidget(self.connectButton, 6, 2)
        
        self.updateBoxes()
        
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
        self.initUI()

    def onDataChanged(self, topLeft, bottomRight, roles):
        pass
    
    def resizeTableViewToContents(self, tableView: QTableView):
        height = tableView.horizontalHeader().height()
        for row in range(tableView.model().rowCount()):
            height += tableView.rowHeight(row)
        if tableView.horizontalScrollBar().isVisible():
            height += tableView.horizontalScrollBar().height()
        tableView.setFixedHeight(height + 5)
        
    def setInfoLabel(self, label: str):
        self.infoLabel.setText(label)

    def initBaseUI(self):
        self.mainLayout = QVBoxLayout()
        topHorizontal = QHBoxLayout()
        msgString = f'{self.msg.message.name}: {hex(self.msg.message.frame_id)}; Frequency = '
        cycleTime = self.msg.message.cycle_time
        if cycleTime is None or cycleTime == 0:
            msgString += 'not specified'
        else:
            cycleTime /= 1000
            self.frequency = min(self.FrequencyValues, key=lambda x: abs(x - 1/cycleTime))
            msgString += f'{self.frequency} Hz'
        msgLabel = QLabel(msgString)
        topHorizontal.addWidget(msgLabel)
        self.infoLabel = QLabel('')
        topHorizontal.addWidget(self.infoLabel, alignment=Qt.AlignmentFlag.AlignRight)
        self.mainLayout.addLayout(topHorizontal)

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
        self.canBusMsg = pycan.Message(arbitration_id=msg.message.frame_id,
                        is_extended_id=msg.message.is_extended_frame,
                        data=msgTable.msgData)
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

class CanTabManager():
    """
    A class to manage tabs and logic for a connected CAN
    
    Attributes:
    config (CanConfig): Source of truth for current config
    channel (str): Channel that the associated bus is connected to
    canBus (pycan.bus): Associated bus
    txMsgs (list): DbcMessages for our Tx tab
    rxMsgs (list): Dbcmessages for our Rx tab
    msgTableDict (msgTableDict): All the tables of message signals and their associated message id
    """
    def __init__(self, config: CanConfig, channel: str, bus: pycan.bus):
        self.config = config
        self.channel = channel
        self.canBus = CanBusHandler(bus, self.channel)
        self.canBus.messageReceived.connect(self.handleRxCanMsg)
        self.txMsgs = []
        self.rxMsgs = []
        self.tabs = set()
        self.graphWindows = set()
        self.msgTableDict = {}
        
    def handleRxCanMsg(self, canMsg: pycan.Message, channel: str):
        if self.canBus.channel != channel:
            return
        logging.debug(f'{channel}: Received CAN message ID: {canMsg.arbitration_id:x}')
        msgTable = self.msgTableDict.get(canMsg.arbitration_id)
        if msgTable is not None:
            msgTable.updateSignalValues(canMsg)
            
    def onSignalValueChanged(self, msg: DbcMessage, row: int, value: float):
        if msg.signals[row].graphed:
            msg.signals[row].graphValues.append(value)       

    def onSignalGraphedChanged(self, msg: DbcMessage, row: int, graphed: bool, stopGraph):
        if graphed:
            if msg.graphWindow is None:
                msg.graphWindow = MsgGraphWindow(msg, stopGraph)
                self.graphWindows.add(msg.graphWindow)
                msg.graphWindow.show()
        else:
            if msg.graphWindow is not None:
                # stop plotting signal
                msg.signals[row].graphValues.clear()

                closeGraphWindow = True

                # close window if no signals are plotted
                for signal in msg.signals:
                    if signal.graphed:
                        closeGraphWindow = False

                if closeGraphWindow:
                    msg.graphWindow.close()
                    msg.graphWindow = None
                
    def setupMessages(self, dbcDb):
        for msg in dbcDb.messages:
            message = DbcMessage(message=msg, signals=[])
            for sig in msg.signals:
                if isinstance(sig.initial, NamedSignalValue):
                    value = sig.initial.name
                elif(sig.is_float):
                    value = float(sig.initial) if sig.initial is not None else 0.0
                else:
                    value = int(sig.initial) if sig.initial is not None else 0

                signal = DbcSignal(signal=sig, value=value)
                message.signals.append(signal)
            if msg.senders is not None and 'VCU' in msg.senders:
                self.txMsgs.append(message)
            else:
                self.rxMsgs.append(message)     
    
    def initTabs(self, tabWidget: QTabWidget):
        self.setupTab('VCU TX ' + self.channel, self.txMsgs, TxMessageLayout, tabWidget)
        self.setupTab('VCU RX ' + self.channel, self.rxMsgs, RxMessageLayout, tabWidget)
    
    def setupTab(self, title: str, messages: list[DbcMessage], layoutClass: type[MessageLayout], tabWidget: QTabWidget):
        tab = QWidget()

        scrollContent = QWidget()
        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollArea.setWidget(scrollContent)
        tabLayout = QVBoxLayout(scrollContent)

        # Add info label to the first element
        label = ''  
        options = self.config.options[self.config.index()]
        for k in options:
            if not k == 'receive_own_messages':
                label += options[k] + ':'
        label += path.basename(self.config.dbcFile)

        for msg in messages:
            msgTable = MsgModel(msg)
            msgLayout = layoutClass(self.canBus, msgTable, msg)

            if(layoutClass == RxMessageLayout):
                msgTable.signalValueChanged.connect(self.onSignalValueChanged)
                msgTable.signalGraphedChanged.connect(self.onSignalGraphedChanged)
                self.msgTableDict[msg.message.frame_id] = msgTable
            tabLayout.addWidget(msgLayout)
            
            if label:
                msgLayout.setInfoLabel(label)
                label = None
        
        layout = QVBoxLayout(tab)  # This is the layout for the tab itself
        layout.addWidget(scrollArea)  # Add the scrollArea to the tab's layout

        self.tabs.add(tab)
        tabWidget.addTab(tab, title)
        tabWidget.setTabWhatsThis(tabWidget.count() - 1 ,self.channel)
        
    def shutdown(self):
        self.canBus.shutdown()
        for tab in self.tabs:
            tab.deleteLater()
        for graph in self.graphWindows:
            graph.deleteLater()
        

class MainApp(QMainWindow):
    """
    A class that represents the main application

    Attributes:
    config (CanConfig): Source of truth for config settings
    configLayout (ConfigLayout): Initial tab for user to set config
    dbcDb (Database): Message data for loaded DBC file
    openCans (Dict): All connected CANs and their associated channel
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CAN Testbench')
        
        self.config = CanConfig()
        self.configLayout = ConfigLayout(self.config)
        self.configLayout.dbcOpened.connect(self.openDbc)
        self.configLayout.connectPressed.connect(self.connectCan)
        
        self.dbcDb = None
        self.openCans = {}
        self.initUI()
        self.resizeToScreenFraction()

    def resizeToScreenFraction(self, fractionWidth=1.0, fractionHeight=0.8):
        # Get the screen size
        screen = QApplication.primaryScreen()
        screenSize = screen.size()

        # Calculate the window size as a fraction of the screen size
        newWidth = int(screenSize.width() * fractionWidth)
        newHeight = int(screenSize.height() * fractionHeight)
        newWidth = min(newWidth,1350)
        logging.debug(f'Window size: {newWidth}x{newHeight}')

        # Resize the window
        self.resize(newWidth, newHeight)
    
    def setupLaunchTab(self):
        tab = QWidget()

        scrollContent = QWidget()
        scrollArea = QScrollArea(tab)
        scrollArea.setWidgetResizable(True)
        scrollArea.setWidget(scrollContent)
    
        tabLayout = QVBoxLayout(scrollContent)
        tabLayout.addWidget(self.configLayout)
        
        layout = QVBoxLayout(tab)  # This is the layout for the tab itself
        layout.addWidget(scrollArea)  # Add the scrollArea to the tab's layout

        self.tabWidget.addTab(tab, 'CAN Config')
        tabBar = self.tabWidget.tabBar()
        tabBar.tabButton(0, QTabBar.ButtonPosition.RightSide).resize(0, 0)
        
        if path.isfile(self.config.dbcFile):
            self.openDbc()
    
    def errorDialog(self, error):
        print(error)
        messageBox = QMessageBox()
        messageBox.critical(self, "Error Opening File", repr(error))
        messageBox.setFixedSize(500,200)
    
    @QtCore.Slot()
    def openDbc(self):
        self.configLayout.connectEnabled(False)
        try:
            self.dbcDb = database.load_file(self.config.dbcFile)
        except Exception as error:
            self.errorDialog(error)
            return

        self.configLayout.connectEnabled(True)
        self.config.writeConfig()
        
    @QtCore.Slot()
    def connectCan(self):                                                                                   
        channel = self.config.options[self.config.index()].get('channel')
        if channel:
            self.closeCan(channel)
            try:
                bus = pycan.Bus(**self.config.options[self.config.index()])
            except Exception as error:
                self.errorDialog(error)
                return
            canManager = CanTabManager(self.config, channel, bus)
        else:
            self.errorDialog("Channel is none")
            return
            
        try:
            canManager.setupMessages(self.dbcDb)
        except Exception as error:
            canManager.shutdown()
            self.errorDialog(error)
            return
        self.openCans[channel] = canManager
        canManager.initTabs(self.tabWidget)
        self.config.writeConfig()
    
    def closeCan(self, channel: str):
        can = self.openCans.pop(channel, None)
        if can is not None:
            can.shutdown()
            
    def removeTab(self, index: int):
        channel = self.tabWidget.tabWhatsThis(index)
        self.closeCan(channel)
    
    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.tabWidget.setTabsClosable(True)
        self.tabWidget.tabCloseRequested.connect(self.removeTab)
        self.setCentralWidget(self.tabWidget)
        self.setupLaunchTab()
        
    def closeEvent(self, event):
        # Perform any cleanup or save data here
        for can in self.openCans:
            self.openCans[can].shutdown()
        # Call the superclass's closeEvent method to proceed with the closing
        super().closeEvent(event)


if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.info(sys.version)
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
