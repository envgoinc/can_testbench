# nuitka-project: --enable-plugin=pyside6
# nuitka-project: --disable-console
# nuitka-project: --standalone
# nuitka-project: --include-module=can.interfaces.slcan
# nuitka-project: --include-module=can.interfaces.udp_multicast
# nuitka-project-if: {OS} == "Darwin":
#    nuitka-project: --macos-create-app-bundle
from __future__ import annotations
import sys
import os
from os import path
import datetime
import time
import configparser
import dataclasses
import collections
import enum
from typing import Union
from cantools import database
from cantools.database import namedsignalvalue
from cantools.database import Message
from cantools.database.can import signal
import can as pycan
import logging
import pyqtgraph as pg
import plotly.express as px
import pandas as pd
from PySide6 import QtCore
from PySide6 import QtGui
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
    QHeaderView,
    QSizePolicy,
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
    graphValues: list = dataclasses.field(default_factory=lambda: [])
    graphed: bool = False

@dataclasses.dataclass
class DbcMessage:
    """
    A class representing a CAN message.

    Attributes:
    message (object): The cantools message object.
    signals (list of DbcSignals): List of DbcSignals
    graphWindow (object): Represents the window that is showing the graph of signals
    timestamps (list): List of timestamps for graphValues in DbcSignals
    """
    message: database.Message
    signals: list[DbcSignal]
    graph: plotly.graph_objs.Figure | None = None
    graphWindow: MsgGraphWindow | None = None
    timestamps: list = dataclasses.field(default_factory=lambda: [])

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
        msg (pycan.Message): The message received.
        """
        # Emit signal with the received CAN message and associated channel
        self.messageSignal.emit(msg, self.channel)

    def stop(self):
        pass

class CanBusHandler(QtCore.QObject):
    """
    A class representing the CAN bus.  It inherits from QObject so it can send a signal.

    Attributes:
    messageReceived (Signal): Signal sent on message received
    messageSent (Signal): Signal sent on message transmitted
    bus (pycan.Bus): Represents the physical CAN bus
    channel (str): Name of the channel the bus is attached to
    periodicMsg (dictionary): Keeps track of the data, and period of the message sent.
    Also the task sending the periodic message.
    listener (CanListener): The class that is listening for CAN messages
    notifier (pycan.Notifier): The class that will notify on a message received from Python CAN.
    """
    messageReceived = QtCore.Signal(pycan.Message, str)
    messageSent = QtCore.Signal(pycan.Message, str)

    def __init__(self, bus: pycan.bus, channel: str = '', logFile: str = '', parent=None):
        super().__init__(parent)
        self.bus = bus
        self.channel = channel
        self.periodicMsgs = {}
        self.listener = CanListener(self.messageReceived, channel)
        notifyList = [self.listener]
        if logFile != '':
            self.logger = pycan.CanutilsLogWriter(logFile, channel, True)
            self.messageSent.connect(self.logger.on_message_received)
            self.messageReceived.connect(self.logger.on_message_received)
        self.notifier = pycan.Notifier(self.bus, notifyList)

    def sendCanMessage(self, msg, frequency=0):
        """
        Sends either a single CAN message in the case when frequency is 0
        Or sets up a task to send periodic messages if frequency is not 0

        Parameters:
        msg (pycan.Message): The message to be sent.
        frequency (int): The frequency of how often to send the message
        """
        msg.timestamp = time.time()
        if frequency == 0:
            self.bus.send(msg)
            self.emitMessageSend(msg)
        else:
            period = 1/frequency
            sendDetails = self.periodicMsgs.get(msg.arbitration_id)
            if sendDetails is None:
                sendDetails = {}
                sendDetails['data'] = msg.data
                sendDetails['period'] = period
                task = self.bus.send_periodic(msg, period, modifier_callback = self.emitMessageSend)
                sendDetails['task'] = task
                self.periodicMsgs[msg.arbitration_id] = sendDetails
            elif sendDetails['period'] != period or sendDetails['data'] != msg.data:
                sendDetails['task'].stop()
                sendDetails['data'] = msg.data
                if sendDetails['period'] != [period]:
                    task = self.bus.send_periodic(msg, period, modifier_callback = self.emitMessageSend)
                    sendDetails['task'] = task
                    sendDetails['period'] = period
                else:
                    sendDetails['task'].start()
            else:
                sendDetails['task'].start()

    def emitMessageSend(self, message: pycan.Message):
        message.timestamp = time.time()
        self.messageSent.emit(message, self.listener.channel)

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
    setMsgLabel (Qt.Signal): Signal to be sent if the message label has been updated.
    setTimeLabel (Qt.Signal): Signal sent when timestamp is updated
    Columns (dict): A class attribute describing the columns in the table
    msg (DbcMessage): The message the table is displaying
    frequency (int): The expected frequency for rx/tx, used for the message label, not current frequency
    searchResults (list): Cache for results of signal search
    """
    setMsgLabel = QtCore.Signal(str)
    setTimeLabel = QtCore.Signal(str)
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
        self.frequency = 0
        self.searchResults = []
        self.msgLabel = ''
        self.timeLabel = ''

    def rowCount(self, parent=None):
        # number of signals in message
        return len(self.msg.signals)

    def columnCount(self, parent=None):
        return len(self.Columns)

    def data(self, index, role: int = Qt.ItemDataRole.DisplayRole):
        return super().data(index, role)

    def headerData(self, section, orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.Columns[section]['heading']
        return None

    def flags(self, index):
        return super().flags(index)

    def setData(self, index, value, role: int = Qt.ItemDataRole.EditRole):
        return super().setData(index, value, role)

    def search(self, text):
        self.searchResults.clear()
        if text != '':
            for row in range(self.rowCount()):
                index = self.index(row, 0)
                if str(text).casefold() in str(self.data(index)).casefold():
                    self.searchResults.append(index)
        self.dataChanged.emit(self.index(0, 0), self.index(self.rowCount(), 0))
        return self.searchResults

    def updateMsgLabel(self):
        pass

    def getMsgData(self) -> bytes:
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

class RxMsgModel(MsgModel):
    """
    A class that handles the data in a table for received messages.

    Attributes:
    signalGraphedChanged (Qt.Signal): Signal to be sent if the graphed status
    of a DbcSignal in the table changes.
    setDeltaLabel (Qt.Signal): Signal sent when rxDelta label is updated
    Columns (dict): A class attribute describing the columns in the table
    msg (DbcMessage): The message the table is displaying
    lastReceived (datetime.datetime): Timestamp of the most recent message
    rxDelta (datetime.timedelta): Time gap between the 2 most recent messages
    rowsUpdated: A set that keeps track of updated rows since last timer expiry
    timer: 100ms timer that sends dataChanged signal for rows changed
    """
    signalGraphedChanged = QtCore.Signal(DbcMessage, int, bool, object)
    setDeltaLabel = QtCore.Signal(str)

    def __init__(self, msg: DbcMessage, parent=None):
        super().__init__(msg, parent)
        self.lastReceived = None
        self.rxDelta = None
        self.deltaLabel = ''
        self.updateMsgLabel()
        self.rowsUpdated = set()
        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.updateTable)
        self.timer.start(100)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            sig = self.msg.signals[index.row()]
            if self.Columns[index.column()]['editable']:
                value = self.msg.signals[index.row()].value
                if isinstance(value, float):
                    return str(round(value, 2))
                else:
                    return str(value)
            else:
                return getattr(sig.signal, self.Columns[index.column()]['property'])
        elif role == Qt.ItemDataRole.CheckStateRole and index.column() == 5:
            return Qt.CheckState.Checked if self.msg.signals[index.row()].graphed else Qt.CheckState.Unchecked
        elif role == Qt.ItemDataRole.BackgroundRole:
            searchRows = [result.row() for result in self.searchResults]
            if index.row() in searchRows:
                color = QtGui.QColor("darkorange")
                color.setAlpha(50)
                return QtGui.QBrush(color)
        return None

    def flags(self, index):
        # Set the flag to editable for the Name column
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 5:
            return super().flags(index) | Qt.ItemFlag.ItemIsUserCheckable
        return super().flags(index)

    def stopGraph(self):
        for x in range(0, self.rowCount()):
            self.setData(self.index(x, 5), Qt.CheckState.Unchecked, Qt.ItemDataRole.CheckStateRole)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and index.column() == 5:
            if role == Qt.ItemDataRole.EditRole:
                if isinstance(value, namedsignalvalue.NamedSignalValue):
                    requestedValue = value.name
                    graphValue = value.value
                else:
                    # should already be int or float
                    assert(isinstance(value, int | float))
                    requestedValue = value
                    graphValue = value

                self.msg.signals[index.row()].graphValues.append(graphValue)
                if requestedValue != self.msg.signals[index.row()].value:
                    self.msg.signals[index.row()].value = requestedValue
                    self.rowsUpdated.add(index.row())
            elif role == Qt.ItemDataRole.CheckStateRole:
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
        self.msg.timestamps.append(canMsg.timestamp)
        for signalName in signalValues.keys():
            for i, sig in enumerate(self.msg.signals):
                if sig.signal.name == signalName:
                    row = i
                    break
            index = self.index(row, 5)
            self.setData(index, signalValues[signalName])
        prevReceive = self.lastReceived
        self.lastReceived = datetime.datetime.fromtimestamp(canMsg.timestamp)
        if prevReceive is not None:
            self.rxDelta = self.lastReceived - prevReceive

    def calcTimeLabel(self, time):
        if time is None:
            timeLabel = 'Default Values'
        else:
            timeLabel = f" Received at: {time.strftime('%H:%M:%S.%f')[:-3]}"
        return timeLabel

    def updateMsgLabel(self):
        rxData = self.getMsgData()
        logging.debug(f'{rxData=}')
        rxDataStr = ''.join(f'0x{byte:02x} ' for byte in rxData)[:-1]
        logging.debug(f'{rxDataStr=}')
        self.msgLabel = hex(self.msg.message.frame_id) + ': <' + rxDataStr + '>'
        self.timeLabel = self.calcTimeLabel(self.lastReceived)
        if self.rxDelta is not None:
            self.deltaLabel = f"Delta: {str(self.rxDelta)[:-3]}"
        self.setMsgLabel.emit(self.msgLabel)
        self.setTimeLabel.emit(self.timeLabel)
        self.setDeltaLabel.emit(self.deltaLabel)
        logging.debug(f'Data changed: {self.msgLabel}')

    def updateTable(self) -> None:
        # right now, update message label regardless of things changed
        # because I want to see if a new message has come in regardless
        # if it was different than the previous message.  An optimization
        # could be to only update if a new message did come in.
        self.updateMsgLabel()
        if(self.rowsUpdated):
            minRow = min(self.rowsUpdated)
            maxRow = max(self.rowsUpdated)
            self.dataChanged.emit(self.index(minRow, 5), self.index(maxRow, 5), Qt.ItemDataRole.EditRole)
            self.rowsUpdated.clear()

class TxMsgModel(MsgModel):
    """
    A class that handles the data in a table for transmitted messages.

    Attributes:
    changeQueued (Qt.Signal): Signal sent when changes to the tx message are queued
    setSend (Qt.Signal): Signal to control status of send checkbox
    Columns (dict): A class attribute describing the columns in the table
    bus (CanBusHandler): Handler for associated bus
    msg (DbcMessage): The message the table is displaying
    lastSent (datetime.datetime): Timestamp of most recently sent message
    sigValues (dict): Cache for currently queued changes
    """
    changeQueued = QtCore.Signal(bool)
    setSend = QtCore.Signal(bool)
    Columns = [
        {'heading':'Signal Name', 'property':'name', 'editable':False},
        {'heading':'Description', 'property':'comment', 'editable': False},
        {'heading':'Unit', 'property':'unit', 'editable': False},
        {'heading':'Minimum', 'property':'minimum', 'editable': False},
        {'heading':'Maximum', 'property':'maximum', 'editable': False},
        {'heading':'Value', 'property':'initial', 'editable': True},
        {'heading':'Sent', 'property':'initial', 'editable': False},
    ]
    def __init__(self, bus: CanBusHandler, msg: DbcMessage, parent=None):
        super().__init__(msg, parent)
        self.bus = bus
        self.isSend = False
        self.isQueue = False
        self.sigValues = {}
        self.lastSent = None
        self.bus.messageSent.connect(self.updateSentTime)
        for row in range(self.rowCount()):
            self.sigValues[row] = self.msg.signals[row].value
        self.canBusMsg = pycan.Message(arbitration_id=self.msg.message.frame_id,
                        is_extended_id=self.msg.message.is_extended_frame,
                        data=self.getMsgData(), is_rx = False)
        self.updateMsgLabel()

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        if role == Qt.ItemDataRole.DisplayRole:
            sig = self.msg.signals[index.row()]
            if self.Columns[index.column()]['heading'] == 'Sent':
                if isinstance(self.msg.signals[index.row()].value, float):
                    return str(round(self.msg.signals[index.row()].value, 2))
                else:
                    return str(self.msg.signals[index.row()].value)
            elif self.Columns[index.column()]['heading'] == 'Value':
                if isinstance(self.sigValues[index.row()], float):
                    return str(round(self.sigValues[index.row()], 2))
                else:
                    return str(self.sigValues[index.row()])
            else:
                return getattr(sig.signal,self.Columns[index.column()]['property'])
        elif role == Qt.ItemDataRole.BackgroundRole:
            searchRows = [result.row() for result in self.searchResults]
            if self.Columns[index.column()]['heading'] == 'Value':
                if(self.sigValues[index.row()] != self.msg.signals[index.row()].value):
                    color = QtGui.QColor("red")
                    color.setAlpha(50)
                    return QtGui.QBrush(color)
            if index.row() in searchRows:
                color = QtGui.QColor("darkorange")
                color.setAlpha(50)
                return QtGui.QBrush(color)
        return None

    def flags(self, index):
        # Set the flag to editable for the Name column
        # todo: use the dictionary to determine if it should be editable
        if index.column() == 5:
                return super().flags(index) | Qt.ItemFlag.ItemIsEditable
        return super().flags(index)

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if index.isValid() and self.Columns[index.column()]['heading'] == 'Value':
            if role == Qt.ItemDataRole.EditRole:
                # TX table
                assert(isinstance(value, str))

                if value[:2] == '0x':
                    requestedValue = int(value, 16)
                else:
                    scale = self.msg.signals[index.row()].signal.scale
                    requestedValue = round(float(value)/scale) * scale

                min = self.msg.signals[index.row()].signal.minimum
                max = self.msg.signals[index.row()].signal.maximum
                if min is None:
                    min = -float('inf')
                if max is None:
                    max = float('inf')

                if ((requestedValue >= min) and
                    (requestedValue <=  max)):
                    self.sigValues[index.row()] = requestedValue
                    if self.isQueue:
                        self.changeQueued.emit(True)
                    else:
                        self.applyChange()
                    self.dataChanged.emit(index, index, [role])
                    return True
        return False

    def applyChange(self):
        for row in range(self.rowCount()):
            self.msg.signals[row].value = self.sigValues[row]
        self.canBusMsg.data = self.getMsgData()
        if self.isSend:
            self.bus.sendCanMessage(self.canBusMsg, self.frequency)
        self.updateMsgLabel()
        self.dataChanged.emit(self.index(0, 5), self.index(self.rowCount()-1, 6), Qt.ItemDataRole.EditRole)
        self.changeQueued.emit(False)

    def discardChange(self):
        for row in range(self.rowCount()):
            self.sigValues[row] = self.msg.signals[row].value
        self.dataChanged.emit(self.index(0, 5), self.index(self.rowCount()-1, 6), Qt.ItemDataRole.EditRole)
        self.changeQueued.emit(False)

    def sendChanged(self, isSend):
        if isSend:
            logging.debug(f'Send CAN frames at {self.frequency} Hz')
            self.isSend = True
            self.bus.sendCanMessage(self.canBusMsg, self.frequency)
            if self.frequency == 0:
                self.setSend.emit(False)
        else:
            logging.debug(f'Stop sending CAN frames')
            self.isSend = False
            self.bus.stop(self.canBusMsg)

    def queueChanged(self, isQueue):
        if self.isQueue:
            self.applyChange()
        self.isQueue = isQueue

    def frequencyChanged(self, frequency):
        logging.debug(f'Frequency change: {frequency} Hz')
        self.frequency = frequency
        if self.isSend:
            self.bus.sendCanMessage(self.canBusMsg, self.frequency)
            if self.frequency == 0:
                self.setSend.emit(False)

    def updateMsgLabel(self):
        logging.debug(f'{self.canBusMsg.data=}')
        sendDataStr = ''.join(f'0x{byte:02x} ' for byte in self.canBusMsg.data)[:-1]
        logging.debug(f'{sendDataStr=}')
        self.msgLabel = hex(self.msg.message.frame_id) + ': <' + sendDataStr + '>'
        if self.lastSent is not None:
            self.timeLabel = f" Last sent at: {self.lastSent.strftime('%H:%M:%S.%f')[:-3]}"
        self.setMsgLabel.emit(self.msgLabel)
        self.setTimeLabel.emit(self.timeLabel)
        logging.debug(f'Data changed: {self.msgLabel}')

    def updateSentTime(self, message: pycan.Message, channel: str):
        if(message.arbitration_id == self.canBusMsg.arbitration_id):
            self.lastSent = datetime.datetime.now()
            self.updateMsgLabel()

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
        axis = pg.DateAxisItem()
        self.plotWidget.setAxisItems({'bottom':axis})

        layout = QVBoxLayout()
        layout.addWidget(self.plotWidget)
        self.setLayout(layout)

        # Update interval
        self.timer = QtCore.QTimer(self)
        self.timer.setInterval(500)  # in milliseconds
        self.timer.timeout.connect(self.updatePlot)
        self.timer.start()

    def updatePlot(self):
        for index, sig in enumerate(self.msg.signals):
            if sig.graphed:  # Only plot signals marked for graphing
                x = self.msg.timestamps[-250:]
                y = sig.graphValues[-250:]
                # Generate a unique color for each signal based on its index
                color = pg.intColor(index, hues=len(self.msg.signals))
                pen = pg.mkPen(color=color, width=2)

                if index not in self.plotSeries:
                    # Create a new series if it doesn't exist
                    self.plotSeries[index] = self.plotWidget.plot(x, y, pen=pen, name=sig.signal.name)
                else:
                    # Update existing series
                    self.plotSeries[index].setData(x, y, pen=pen)
            else:
                # Remove the plot series if it exists but should no longer be graphed
                if index in self.plotSeries:
                    self.plotWidget.removeItem(self.plotSeries[index])
                    del self.plotSeries[index]

    def closeEvent(self, event):
        self.graphWindowClosed.emit()
        logging.debug('Closing graph window')
        # Call the superclass's closeEvent method to proceed with the closing
        super().closeEvent(event)

class MessageLayout(QWidget):
    """
    A class to manage the layout and view for a Message table

    Attributes:
    FrequencyValues (list): Valid frequencies to send or recieve messages at
    ColumnWidths (list): Default width for each column in the table
    msgTable (MsgModel): The table model holding our message data
    msg (DbcMessage): The message associated with our table model
    """
    FrequencyValues = [0, 1, 5, 10, 20, 40, 50, 100]
    ColumnWidths = [300, 500, 50, 100, 100, 150]

    def __init__(self, msgTable: MsgModel, msg: DbcMessage):
        super().__init__()
        self.msgTableModel = msgTable
        self.msg = msg
        self.initBaseUI()

    def resizeTableViewToContents(self, tableView: QTableView):
        height = tableView.horizontalHeader().height()
        for row in range(tableView.model().rowCount()):
            height += tableView.rowHeight(row)
        if tableView.horizontalScrollBar().isVisible():
            height += tableView.horizontalScrollBar().height()
        tableView.setFixedHeight(height + 5)

    def rowPosition(self, row):
        return self.pos().y() + self.signalTableView.rowViewportPosition(row)

    def selectRow(self, row):
        self.signalTableView.clearSelection()
        self.signalTableView.selectRow(row)
        return self.rowPosition(row)

    def focusRow(self, row):
        self.selectRow(row)
        self.signalTableView.setFocus()

    def setMsgLabel(self, msgStr):
        self.msgLabel.setText(msgStr)

    def setTimeLabel(self, timeStr):
        self.timeLabel.setText(timeStr)

    def clearSelection(self):
        self.signalTableView.clearSelection()

    def initBaseUI(self):
        self.mainLayout = QVBoxLayout()
        msgString = f'{self.msg.message.name}: {hex(self.msg.message.frame_id)}; Frequency = '
        cycleTime = self.msg.message.cycle_time
        if cycleTime is None or cycleTime == 0:
            msgString += 'not specified'
        else:
            cycleTime /= 1000
            self.msgTableModel.frequency = min(self.FrequencyValues, key=lambda x: abs(x - 1/cycleTime))
            msgString += f'{self.msgTableModel.frequency} Hz'
        msgLabel = QLabel(msgString)
        self.mainLayout.addWidget(msgLabel)

        # Initialize and configure the table for signals
        self.signalTableView = QTableView()
        self.signalTableView.setModel(self.msgTableModel)
        for column in range(self.msgTableModel.columnCount()):
            #if self.ColumnWidths[column] == 0:
                #self.signalTableView.hideColumn(column)
            #else:
            self.signalTableView.setColumnWidth(column, self.ColumnWidths[column])
        self.signalTableView.resizeRowsToContents()
        self.signalTableView.setAlternatingRowColors(True)
        self.resizeTableViewToContents(self.signalTableView)
        self.signalTableView.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.signalTableView.horizontalHeader().setStretchLastSection(True)
        #self.signalTableView.setSelectionMode(QTableView.SelectionMode.ContiguousSelection)
        self.setFocusProxy(self.signalTableView)
        self.mainLayout.addWidget(self.signalTableView)
        self.setLayout(self.mainLayout)

        self.bottomHorizontal = QHBoxLayout()
        self.bottomLabel = QGridLayout()
        self.msgLabel = QLabel()
        self.msgLabel.setText(self.msgTableModel.msgLabel)
        msgSize = self.msgLabel.sizePolicy()
        msgSize.setHorizontalPolicy(QSizePolicy.Policy.Minimum)
        self.msgLabel.setSizePolicy(msgSize)
        self.bottomLabel.addWidget(self.msgLabel, 0, 0, Qt.AlignmentFlag.AlignLeft)
        self.bottomLabel.setColumnMinimumWidth(0, 400) # Couldn't figure this out, just hard code it. Monospace fonts are too big
        self.timeLabel = QLabel()
        self.timeLabel.setText(self.msgTableModel.timeLabel)
        timeSize = self.timeLabel.sizePolicy()
        timeSize.setHorizontalPolicy(QSizePolicy.Policy.Fixed)
        self.timeLabel.setSizePolicy(timeSize)
        self.bottomLabel.addWidget(self.timeLabel, 0, 1, Qt.AlignmentFlag.AlignLeft)
        self.bottomHorizontal.addLayout(self.bottomLabel, Qt.AlignmentFlag.AlignLeft)
        self.mainLayout.addLayout(self.bottomHorizontal)

class TxMessageLayout(MessageLayout):
    """
    A class to manage the layout and view for a Message table that
    can be transmitted

    Attributes:
    applyPressed (Qt.Signal): Signal sent when apply change button is pressed
    discardPressed (Qt.Signal): Signal sent when discard change button is pressed
    sendChanged (Qt.Signal): Signal sent when state of send checkbox is changed
    queueChanged (Qt.Signal): Signal sent when state of queue changes checkbox is changed
    frequencyChanged (Qt.Signal): Signal sent when selected frequency is changed
    ColumnWidths (list): Default width for each column in the table
    msgTable (MsgModel): The table model holding our message data
    msg (DbcMessage): The message associated with our table model
    """
    applyPressed = QtCore.Signal()
    discardPressed = QtCore.Signal()
    sendChanged = QtCore.Signal(bool)
    queueChanged = QtCore.Signal(bool)
    frequencyChanged = QtCore.Signal(int)
    ColumnWidths = [300, 500, 50, 100, 100, 100, 50]

    def __init__(self, msgTable: TxMsgModel, msg: DbcMessage):
        super().__init__(msgTable, msg) # Initialize base UI components
        self.msgTableModel = msgTable
        self.initTxUI()

    def onChangeQueued(self, bool):
        self.applyButton.setEnabled(bool)

    def setSend(self, bool = True):
        if bool:
            self.sendCheckBox.setCheckState(Qt.CheckState.Checked)
        else:
            self.sendCheckBox.setCheckState(Qt.CheckState.Unchecked)

    def emitSendChanged(self):
        self.sendChanged.emit(self.sendCheckBox.isChecked())

    def emitQueueChanged(self):
        self.queueChanged.emit(self.queueCheckBox.isChecked())

    def emitFrequencyChanged(self):
        self.frequencyChanged.emit(self.sendFrequencyCombo.currentData())

    def focusRow(self, row):
        self.signalTableView.clearSelection()
        self.signalTableView.setCurrentIndex(self.msgTableModel.index(row, 5))
        self.signalTableView.setFocus()

    def initTxUI(self):
        logging.debug('tx initUI')
        freqComboLayout = QHBoxLayout()
        sendFrequencyLabel = QLabel('Select Send Frequency')
        freqComboLayout.addStretch(1)
        freqComboLayout.addWidget(sendFrequencyLabel)
        self.sendFrequencyCombo = QComboBox()
        for value in self.FrequencyValues:
            self.sendFrequencyCombo.addItem(str(value), value)
        index = self.sendFrequencyCombo.findData(self.msgTableModel.frequency)
        if index != -1:
            self.sendFrequencyCombo.setCurrentIndex(index)
        self.sendFrequencyCombo.setFocusProxy(self.signalTableView)
        self.sendFrequencyCombo.currentIndexChanged.connect(self.emitFrequencyChanged)
        self.frequencyChanged.connect(self.msgTableModel.frequencyChanged)
        freqComboLayout.addWidget(self.sendFrequencyCombo)
        freqComboLayout.setSpacing(0)
        freqComboLayout.addSpacing(100)
        self.bottomHorizontal.addLayout(freqComboLayout)

        self.applyButton = QPushButton('Apply')
        self.applyButton.clicked.connect(self.applyPressed)
        self.applyButton.setFocusProxy(self.signalTableView)
        self.bottomHorizontal.addWidget(self.applyButton)
        self.queueCheckBox = QCheckBox('Queue Changes')
        self.queueCheckBox.setFocusProxy(self.signalTableView)
        self.queueCheckBox.stateChanged.connect(self.emitQueueChanged)
        self.queueChanged.connect(self.msgTableModel.queueChanged)
        self.bottomHorizontal.addWidget(self.queueCheckBox)
        self.onChangeQueued(False)
        self.sendCheckBox = QCheckBox('Send')
        self.sendCheckBox.setFocusProxy(self.signalTableView)
        self.sendCheckBox.stateChanged.connect(self.emitSendChanged)
        self.sendChanged.connect(self.msgTableModel.sendChanged)
        self.bottomHorizontal.addWidget(self.sendCheckBox)

class RxMessageLayout(MessageLayout):
    """
    A class to manage the layout and view for a Message table
    that can be received
    Attributes:
    msgTable (MsgModel): The table model holding our message data
    msg (DbcMessage): The message associated with our table model
    """
    def __init__(self, msgTable: RxMsgModel, msg: DbcMessage):
        super().__init__(msgTable, msg)
        self.msgTableModel = msgTable
        self.initRxUi()

    def initRxUi(self):
        self.deltaLabel = QLabel()
        self.deltaLabel.setText(self.msgTableModel.deltaLabel)
        deltaSize = self.deltaLabel.sizePolicy()
        deltaSize.setHorizontalPolicy(QSizePolicy.Policy.Fixed)
        self.deltaLabel.setSizePolicy(deltaSize)
        self.bottomLabel.addWidget(self.deltaLabel, 0, 3, Qt.AlignmentFlag.AlignLeft)
        self.bottomHorizontal.addStretch(1)

    def setDeltaLabel(self, deltaStr):
        self.deltaLabel.setText(deltaStr)

class CanConfig():
    """
    Source of truth for current and allowed configs

    Attributes:
    Interface (Enum): List of supported can interface tips
    SLCAN_BITRATES (Tuple): List of valid bitrates for the slcan interface
    config (ConfigParser): Handler for read/write of config file
    scriptDir (str): Location of script or application
    configFile (str): Location of config file
    selected (enum): Type of selected interface
    dbcFile (str): Location of dbc file
    options (list[dict[str, str]]): Option sets for each interface type
    """
    class Interface(enum.Enum):
        slcan = 0
        udp_multicast = 1
        socketcan = 2
        logging = 3

    SLCAN_BITRATES = (10000, 20000, 50000, 100000, 125000, 250000, 500000, 750000, 1000000, 83300)

    def __init__(self):
        self.config = configparser.ConfigParser()
        self.scriptDir = path.dirname(path.abspath(__file__))
        self.configFile = path.join(self.scriptDir, 'can_config.ini')
        self.selected = CanConfig.Interface.udp_multicast
        self.dbcFile = path.join(self.scriptDir, '../nv1_can_gen/dbc/testbench.dbc')
        self.options : list[dict[str, str]] = [
            {'interface': CanConfig.Interface.slcan.name,
            'channel': '/dev/tty.usbmodem3946375033311',
            'bitrate': '500000',
            'receive_own_messages': 'False',
            'listen_mode': 'False'},
            {'interface': CanConfig.Interface.udp_multicast.name,
            'channel': '239.0.0.1',
            'port': '10000',
            'receive_own_messages': 'False',
            'listen_mode': 'False'},
            {'interface': CanConfig.Interface.socketcan.name,
            'channel': 'vcan0',
            'receive_own_messages': 'False',
            'listen_mode': 'False'},
            {'interface': "Logging",
             'log_file': '.'}
        ]
        self.initConfig()

    def initConfig(self):
        try:
            self.readConfig()
        except Exception as error:
            self.writeConfig()

    def writeConfig(self):
        self.config['General'] = {
            'default_interface': self.selected.name,
            'dbc_file': self.dbcFile
        }
        for interface in CanConfig.Interface:
            self.config[interface.name] = self.options[interface.value]
            with open(self.configFile, 'w') as configfile:
                self.config.write(configfile)

    def readConfig(self):
        self.config.read(self.configFile)
        general = self.config['General']
        if general.get('default_interface', None) is not None:
            self.selected = CanConfig.Interface[general['default_interface']]
        if general.get('dbc_file', None) is not None:
            self.dbcFile = general['dbc_file']
        for interface in CanConfig.Interface:
            for key in self.options[interface.value]:
                if self.config[interface.name][key]:
                    self.options[interface.value][key] = self.config[interface.name][key]

    def index(self) -> int:
        return self.selected.value

    def option(self):
        return self.options[self.index()]

    def setInterface(self, interface: int | Interface):
        if type(interface) == int:
            self.selected = CanConfig.Interface(interface)
        elif type(interface) == CanConfig.Interface:
            self.selected = interface

    def setChannel(self, channel: str):
        if 'channel' in self.option():
            self.option()['channel'] = channel

    def setBitrate(self, bitrate: int):
        if ('bitrate' in self.option() and
            bitrate in CanConfig.SLCAN_BITRATES):
            self.option()['bitrate'] = str(bitrate)

    def setPort(self, port: str | int):
        if 'port' in self.option():
            self.option()['port'] = str(port)


    def setDbc(self, file: str):
        self.dbcFile = file

    def setLog(self, file: str):
        if 'log_file' in self.option():
            self.option()['log_file'] = file

    def setListenMode(self, mode: bool) -> None:
        if 'listen_mode' in self.option():
            self.option()['listen_mode'] = str(mode)

    def getListenMode(self) -> bool:
        return self.option()['listen_mode'].lower() == 'true'

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
        if(file[1] != 'DBC file (*.dbc)'):
            return
        self.config.setDbc(file[0])
        self.updateBoxes()
        self.dbcOpened.emit()

    def openLog(self):
        file = QFileDialog.getOpenFileName(caption = "Open CAN log file", dir = self.config.option()['log_file'], filter = "Log file (*.log)")
        if(file[1] != 'Log file (*.log)'):
            return
        self.config.setLog(file[0])
        self.updateBoxes()

    def connectEnabled(self, bool):
        style = "color: base" if bool else "color: red"
        self.dbcBox.setStyleSheet(style)
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

    def setListenMode(self, state) -> None:
        if state == 2:
            self.config.setListenMode(True)
        elif state == 0:
            self.config.setListenMode(False)

    def updateBoxes(self):
        opts = self.config.option()
        self.dbcBox.setText(path.abspath(self.config.dbcFile))

        logFile = opts.get("log_file")
        if(logFile is not None):
            self.logBox.setText(path.abspath(logFile))
            self.logBox.setEnabled(True)
            self.logButton.setEnabled(True)
        else:
            self.logBox.setText("Only used with logging interface")
            self.logBox.setEnabled(False)
            self.logButton.setEnabled(False)

        channel = opts.get('channel')

        if(channel is not None):
            self.channelBox.setText(channel)
            self.channelBox.setEnabled(True)
        else:
            self.channelBox.setText("")
            self.channelBox.setDisabled(True)

        bitrate = opts.get('bitrate')
        if(bitrate is not None):
            self.baudBox.setCurrentText(bitrate)
            self.baudBox.setEnabled(True)
        else:
            self.baudBox.setDisabled(True)

        port = opts.get('port')
        if(port is not None):
            self.portBox.setText(port)
            self.portBox.setEnabled(True)
        else:
            self.portBox.setText("")
            self.portBox.setDisabled(True)

        listenMode = opts.get('listen_mode')
        if(listenMode is not None):
            self.listenModeSelector.setChecked(listenMode.lower() == 'true')
            self.listenModeSelector.setEnabled(True)
        else:
            self.listenModeSelector.setChecked(False)
            self.listenModeSelector.setDisabled(True)

    def initBaseUI(self):
        self.mainLayout = QVBoxLayout()
        self.horizontalLayout = QHBoxLayout()
        self.mainLayout.addStretch(1)
        self.mainLayout.addLayout(self.horizontalLayout, stretch = 0)
        self.mainLayout.addStretch(5)

        self.configLayout = QGridLayout()
        self.configLayout.setVerticalSpacing(10)
        self.horizontalLayout.addStretch(10)
        self.horizontalLayout.addLayout(self.configLayout, stretch=50)
        self.horizontalLayout.addStretch(10)

        dbcLabel = QLabel()
        dbcLabel.setText('DBC File:')
        self.configLayout.addWidget(dbcLabel, 1, 1)

        self.dbcBox = QLineEdit()
        self.dbcButton = QPushButton()
        self.dbcButton.setText('...')
        self.dbcButton.clicked.connect(self.openDbc)
        self.configLayout.addWidget(self.dbcBox, 1, 2)
        self.configLayout.addWidget(self.dbcButton, 1, 3)

        logLabel = QLabel()
        logLabel.setText('Log File:')
        self.configLayout.addWidget(logLabel, 2, 1)

        self.logBox = QLineEdit()
        self.logButton = QPushButton()
        self.logButton.setText('...')
        self.logButton.clicked.connect(self.openLog)
        self.configLayout.addWidget(self.logBox, 2, 2)
        self.configLayout.addWidget(self.logButton, 2, 3)

        interfaceLabel = QLabel()
        interfaceLabel.setText('Interface Type:')
        self.configLayout.addWidget(interfaceLabel, 3, 1)

        self.interfaceBox = QComboBox()
        for i in CanConfig.Interface:
            self.interfaceBox.addItem(i.name)
        self.interfaceBox.setCurrentIndex(self.config.index())
        self.interfaceBox.activated.connect(self.changeInterface)
        self.configLayout.addWidget(self.interfaceBox, 3, 2)

        channelLabel = QLabel()
        channelLabel.setText('Channel:')
        self.configLayout.addWidget(channelLabel, 4, 1)

        self.channelBox = QLineEdit()
        self.channelBox.editingFinished.connect(self.applyChannel)
        self.configLayout.addWidget(self.channelBox, 4, 2)

        self.listenModeSelector = QCheckBox('Listen Mode')
        self.configLayout.addWidget(self.listenModeSelector, 4, 3)
        self.listenModeSelector.stateChanged.connect(self.setListenMode)

        baudLabel = QLabel()
        baudLabel.setText('Bit Rate:')
        self.configLayout.addWidget(baudLabel, 5, 1)

        self.baudBox = QComboBox()
        for num in CanConfig.SLCAN_BITRATES:
            self.baudBox.addItem(str(num))
        self.baudBox.activated.connect(self.changeBitrate)
        self.configLayout.addWidget(self.baudBox, 5, 2)

        portLabel = QLabel()
        portLabel.setText('Port:')
        self.configLayout.addWidget(portLabel, 6, 1)

        self.portBox = QLineEdit()
        self.portBox.editingFinished.connect(self.applyPort)
        self.configLayout.addWidget(self.portBox, 6, 2)

        self.connectButton = QPushButton('Connect')
        self.connectButton.clicked.connect(self.connectPressed)
        self.connectButton.setDisabled(True)
        self.dbcBox.setStyleSheet("color: red")
        self.configLayout.addWidget(self.connectButton, 7, 2)

        self.updateBoxes()

        self.setLayout(self.mainLayout)

    def initUI(self):
        self.initBaseUI()

class SearchBar(QWidget):
    """
    A search bar implemented as a QWidget

    Attributes:
    search (QtCore.Signal): Signal sent when search requested
    loseFocus (QtCore.Signal): Signal sent when widget loses focus
    hideSearch (QtCore.Signal): Signal sent when bar should be hidden
    searchLine (SearchLineEdit): The text entry field of the search bar
    """
    search = QtCore.Signal(str)
    loseFocus = QtCore.Signal()
    prevPressed = QtCore.Signal()
    nextPressed = QtCore.Signal()
    hideSearch = QtCore.Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.barLayout = QHBoxLayout()

        self.searchLine = self.SearchLineEdit()
        self.searchLine.textEdited.connect(self.search)
        self.setFocusProxy(self.searchLine)
        self.setMaximumWidth(500)
        sizePolicy = self.sizePolicy()
        sizePolicy.setRetainSizeWhenHidden(True)
        self.setSizePolicy(sizePolicy)
        self.barLayout.addWidget(self.searchLine, Qt.AlignmentFlag.AlignLeft)

        self.searchLabel = QLabel(self)
        self.barLayout.addWidget(self.searchLabel)
        self.setCount(0)

        self.prevButton = QPushButton('⌃')
        self.prevButton.setMaximumWidth(30)
        self.prevButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.prevButton.pressed.connect(self.prev)
        self.nextButton = QPushButton('⌄')
        self.nextButton.setMaximumWidth(30)
        self.nextButton.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.nextButton.pressed.connect(self.next)
        self.barLayout.addWidget(self.prevButton)
        self.barLayout.addWidget(self.nextButton)
        self.setLayout(self.barLayout)

    def selectAll(self):
        self.searchLine.selectAll()

    def setCount(self, count):
        self.count = count
        self.index = 1 if count else 0
        self.searchLabel.setText(f"{self.index}/{self.count}")

    def prev(self):
        if self.count == 0:
            return

        if self.index == 1:
            self.index = self.count
        else:
            self.index = self.index - 1
        self.searchLabel.setText(f"{self.index}/{self.count}")
        self.prevPressed.emit()

    def next(self):
        if self.count == 0:
            return

        if self.index == self.count:
            self.index = 1
        else:
            self.index = self.index + 1
        self.searchLabel.setText(f"{self.index}/{self.count}")
        self.nextPressed.emit()

    def text(self):
        return self.searchLine.text()

    def keyPressEvent(self, event):
        key = event.key()
        match key:
            case Qt.Key.Key_Escape:
                self.hide()
                self.hideSearch.emit()
                self.previousInFocusChain().setFocus()
                self.loseFocus.emit()
            case Qt.Key.Key_Return:
                if (event.modifiers() == Qt.KeyboardModifier.ShiftModifier):
                    self.prev()
                else:
                    self.next()
            case Qt.Key.Key_Up:
                self.prev()
            case Qt.Key.Key_Down:
                self.next()
            case _:
                super().keyPressEvent(event)

    def sizeHint(self):
        size = super().sizeHint()
        size.setWidth(300)
        return size

    class SearchLineEdit(QLineEdit):
        """
        QLineEdit implementing the text box for search bar

        Attributes:
        """
        def __init__(self):
            super().__init__()
            self.selStart = 0
            self.selLength = 0
            self.cursorPos = 0

        def focusInEvent(self, arg__1):
            super().focusInEvent(arg__1)
            if self.selStart >= 0:
                self.setSelection(self.selStart, self.selLength)
            else:
                self.setCursorPosition(self.cursorPos)

        def focusOutEvent(self, arg__1):
            self.cursorPos = self.cursorPosition()
            self.selStart = self.selectionStart()
            self.selLength = self.selectionLength()
            super().focusOutEvent(arg__1)

class CanTab(QWidget):
    """
    Holds layout and UI elements for a tab managing messages for a can connection

    Attributes:
    msgList (list[DbcMessage]): Messages associated with the tab
    config (CanConfig): Config settings
    searchResults (collections.deque): Cache for search results that can rotate
    msgTables (dict[msgModel, messageLayout]): List of logic layout pairs for the message tables associated with the tab
    """
    def __init__(self, msgList, config):
        super().__init__()
        self.messages = msgList
        self.config = config
        self.searchResults = collections.deque()
        self.msgTables = {}
        self.setupTab()

    def setupTab(self):
        scrollContent = QWidget()
        self.scrollArea = QScrollArea(self)
        self.scrollArea.setWidgetResizable(True)
        self.scrollArea.setWidget(scrollContent)
        self.tabLayout = QVBoxLayout(scrollContent)

        layout = QVBoxLayout(self)  # This is the layout for the tab itself
        layout.addWidget(self.scrollArea)  # Add the scrollArea to the tab's layout
        layout.setSpacing(0)

        topHorizontal = QHBoxLayout()
        label = ''
        options = self.config.option()

        for k in options:
            if not k == 'receive_own_messages':
                label += options[k] + ':'
        label += path.basename(self.config.dbcFile)

        infoLabel = QLabel(label)
        topHorizontal.addWidget(infoLabel, alignment=Qt.AlignmentFlag.AlignLeft)

        self.clock = QLabel('     Time: ')
        topHorizontal.addWidget(self.clock, Qt.AlignmentFlag.AlignLeft)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.setTime)
        self.timer.start()

        self.searchBar = SearchBar(self)
        self.searchBar.search.connect(self.search)
        self.searchBar.loseFocus.connect(self.searchFocus)
        self.searchBar.prevPressed.connect(self.searchPrev)
        self.searchBar.nextPressed.connect(self.searchNext)
        self.searchBar.hideSearch.connect(self.hideSearch)
        topHorizontal.addWidget(self.searchBar, Qt.AlignmentFlag.AlignRight)
        layout.insertLayout(0, topHorizontal)

    def setTime(self):
        time = '     Time: ' + datetime.datetime.now().strftime('%H:%M:%S')
        self.clock.setText(time)

    def search(self, text):
        self.searchResults.clear()
        for key in self.msgTables:
            matchIndexs = self.msgTables[key][0].search(text)
            for index in matchIndexs:
                self.searchResults.append((self.msgTables[key][1], index))
        if self.searchResults:
            self.scrollTo(self.searchResults[0][0].selectRow(self.searchResults[0][1].row()))

        self.searchBar.setCount(len(self.searchResults))

    def hideSearch(self):
        for key in self.msgTables:
            self.msgTables[key][0].search("")

    def showSearch(self):
        self.searchBar.show()
        self.searchBar.setFocus()
        self.searchBar.selectAll()
        if self.searchResults:
            for key in self.msgTables:
                self.msgTables[key][0].search(self.searchBar.text())
                self.msgTables[key][1].clearSelection()
            self.scrollTo(self.searchResults[0][0].selectRow(self.searchResults[0][1].row()))

    def searchPrev(self):
        if self.searchResults:
            for key in self.msgTables:
                self.msgTables[key][1].clearSelection()
            self.searchResults.rotate(1)
            if self.searchResults:
                self.scrollTo(self.searchResults[0][0].selectRow(self.searchResults[0][1].row()))

    def searchNext(self):
        if self.searchResults:
            for key in self.msgTables:
                self.msgTables[key][1].clearSelection()
            self.searchResults.rotate(-1)
            if self.searchResults:
                self.scrollTo(self.searchResults[0][0].selectRow(self.searchResults[0][1].row()))

    def searchFocus(self):
        if self.searchResults:
            self.searchResults[0][0].focusRow(self.searchResults[0][1].row())

    def scrollTo(self, y):
        self.scrollArea.verticalScrollBar().setValue(y)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        if(event.key() == Qt.Key.Key_F and event.modifiers() == Qt.KeyboardModifier.ControlModifier):
            self.showSearch()

class TxTab(CanTab):
    """
    Holds layout and UI elements for a tab managing transmitted messages for a can connection

    Attributes:
    msgList (list[DbcMessage]): Messages associated with the tab
    canBus (CanBusHandler): canBus associated with the tab
    config (CanConfig): Config settings
    """
    def __init__(self, msgList, canBus, config):
        super().__init__(msgList, config)
        self.canBus = canBus
        self.setupTxTab()

    def setupTxTab(self):
        for msg in self.messages:
            msgTable = TxMsgModel(self.canBus, msg)
            msgLayout = TxMessageLayout(msgTable, msg)

            msgLayout.applyPressed.connect(msgTable.applyChange)
            msgTable.setSend.connect(msgLayout.setSend)
            msgTable.setMsgLabel.connect(msgLayout.setMsgLabel)
            msgTable.setTimeLabel.connect(msgLayout.setTimeLabel)
            msgTable.changeQueued.connect(msgLayout.onChangeQueued)
            self.msgTables[msg.message.frame_id] = (msgTable, msgLayout)

            self.tabLayout.addWidget(msgLayout)

class RxTab(CanTab):
    """
    Holds layout and UI elements for a tab managing received messages for a can connection

    Attributes:
    msgList (list[DbcMessage]): Messages associated with the tab
    canBus (CanBusHandler): canBus associated with the tab
    config (CanConfig): Config settings
    graphWindows (set[MsgGraphWindow]): Set of currently open graph windows
    """
    def __init__(self, msgList, canBus, config):
        super().__init__(msgList, config)
        self.graphWindows = set()
        self.canBus = canBus
        self.canBus.messageReceived.connect(self.handleRxCanMsg)
        self.setupRxTab()

    def setupRxTab(self):
        self.searchBar.search.connect(self.search)
        for msg in self.messages:
            msgTable = RxMsgModel(msg)
            msgLayout = RxMessageLayout(msgTable, msg)

            msgTable.signalGraphedChanged.connect(self.onSignalGraphedChanged)
            msgTable.setMsgLabel.connect(msgLayout.setMsgLabel)
            msgTable.setTimeLabel.connect(msgLayout.setTimeLabel)
            msgTable.setDeltaLabel.connect(msgLayout.setDeltaLabel)
            self.msgTables[msg.message.frame_id] = (msgTable, msgLayout)

            self.tabLayout.addWidget(msgLayout)

    def handleRxCanMsg(self, canMsg: pycan.Message, channel: str):
        if self.canBus.channel != channel:
            return
        logging.debug(f'{channel}: Received CAN message ID: {canMsg.arbitration_id:x}')
        rxMsgTable = self.msgTables.get(canMsg.arbitration_id)
        if rxMsgTable is not None:
            rxMsgTable[0].updateSignalValues(canMsg)

    def onSignalGraphedChanged(self, msg: DbcMessage, row: int, graphed: bool, stopGraph):
        if graphed:
            if msg.graphWindow is None:
                msg.graphWindow = MsgGraphWindow(msg, stopGraph)
                self.graphWindows.add(msg.graphWindow)
                msg.graphWindow.show()
        else:
            if msg.graphWindow is not None:
                closeGraphWindow = True

                # close window if no signals are plotted
                for signal in msg.signals:
                    if signal.graphed:
                        closeGraphWindow = False

                if closeGraphWindow:
                    msg.graphWindow.close()
                    msg.graphWindow = None

    def deleteLater(self):
        for graph in self.graphWindows:
            graph.deleteLater()
        super().deleteLater()

class LogTab(CanTab):
    def __init__(self, msgList, config):
        super().__init__(msgList, config)
        self.graphs = {}
        self.setupLogTab()

    def setupLogTab(self):
        self.searchBar.search.connect(self.search)
        for msg in self.messages:
            msgTable = RxMsgModel(msg)
            msgLayout = RxMessageLayout(msgTable, msg)

            msgTable.signalGraphedChanged.connect(self.onSignalGraphedChanged)
            msgTable.setMsgLabel.connect(msgLayout.setMsgLabel)
            msgTable.setTimeLabel.connect(msgLayout.setTimeLabel)
            msgTable.setDeltaLabel.connect(msgLayout.setDeltaLabel)
            self.msgTables[msg.message.frame_id] = (msgTable, msgLayout)

            if len(msg.timestamps) > 0:
                msgLayout.setTimeLabel(msgTable.calcTimeLabel(datetime.datetime.fromtimestamp(msg.timestamps[-1])))
            self.tabLayout.addWidget(msgLayout)

    def onSignalGraphedChanged(self, msg: DbcMessage, row: int, graphed: bool, stopGraph):
        if graphed:
            if msg.graph is None:
                data = {
                    "timestamps": [datetime.datetime.fromtimestamp(x) for x in msg.timestamps],
                }
                # Add each signal's values and names to the data dictionary
                for sig in msg.signals:
                    data[sig.signal.name] = sig.graphValues

                # Create a DataFrame from the dictionary
                df = pd.DataFrame(data)
                # Melt the DataFrame to long format for plotly.express
                df_long = df.melt(id_vars="timestamps", var_name="Signal", value_name="Value")
                # Create the plot with custom legends
                msg.graph = px.line(df_long, x="timestamps", y="Value", color="Signal", title=msg.message.name)
                self.graphs[msg.message.name] = msg.graph
                print(msg.graph)
                msg.graph.show()
        else:
            if msg.graph is not None:
                closeGraphWindow = True

                # close window if no signals are plotted
                for signal in msg.signals:
                    if signal.graphed:
                        closeGraphWindow = False

                if closeGraphWindow:
                    # msg.graph.close()
                    msg.graph = None

    def deleteLater(self):
        for name, graph in self.graphs:
            graph.deleteLater()
        super().deleteLater()

class TabManager():
    "Class to manage an rx tx tab pair for a dbc file"
    def __init__(self, config: CanConfig, dbcDb):
        self.config = config
        self.txMsgs = []
        self.rxMsgs = []
        self.txTab = None
        self.rxTab = None

        try:
            self.setupMessages(dbcDb)
        except Exception as error:
            self.shutdown()

    def setupMessages(self, dbcDb):
        for msg in dbcDb.messages:
            message = DbcMessage(message=msg, signals=[])
            for sig in msg.signals:
                if isinstance(sig.initial, namedsignalvalue.NamedSignalValue):
                    value = sig.initial.name
                elif(sig.scale == int(sig.scale)):
                    value = int(sig.initial) if sig.initial is not None else 0
                else:
                    value = float(sig.initial) if sig.initial is not None else 0.0
                signal = DbcSignal(signal=sig, value=value)
                message.signals.append(signal)
            opts = self.config.option()
            if opts.get('interface') == 'Logging':
                if msg.senders is not None and 'VCU' in msg.senders:
                    self.txMsgs.append(message)
                else:
                    self.rxMsgs.append(message)
            else:
                if msg.senders is not None and 'VCU' in msg.senders and not self.config.getListenMode():
                    self.txMsgs.append(message)
                else:
                    self.rxMsgs.append(message)

    def shutdown(self):
        if self.txTab:
            self.txTab.deleteLater()
        if self.rxTab:
            self.rxTab.deleteLater()

class CanTabManager(TabManager):
    """
    A class to manage tabs and logic for a connected CAN

    Attributes:
    config (CanConfig): Source of truth for current config
    channel (str): Channel that the associated bus is connected to
    bus (pycan.bus): Associated bus
    dbcDb (Database): Dbc data containing messages we will use
    tabWidget (QTabWidget): The tab widget to add tabs to
    logFile (str): Name of file used for logging
    """
    def __init__(self, config: CanConfig, channel: str, bus: pycan.bus, dbcDb, tabWidget: QTabWidget):
        super().__init__(config, dbcDb)
        self.channel = channel
        self.logFile = ""
        self.initLogFile()
        self.canBus = CanBusHandler(bus, self.channel, self.logFile)
        self.initTabs(tabWidget)

    def initTabs(self, tabWidget: QTabWidget):
        self.txTab = TxTab(self.txMsgs, self.canBus, self.config)
        self.rxTab = RxTab(self.rxMsgs, self.canBus, self.config)
        tabWidget.addTab(self.txTab, 'VCU TX ' + self.channel)
        tabWidget.setTabWhatsThis(tabWidget.count() - 1 , self.channel)
        tabWidget.addTab(self.rxTab, 'VCU RX ' + self.channel)
        tabWidget.setTabWhatsThis(tabWidget.count() - 1 , self.channel)

    def initLogFile(self):
        counter = 1
        scriptDir = path.dirname(path.abspath(__file__))
        logDir = path.join(scriptDir, 'logs/')
        dbcName = sanitizeFileName(os.path.basename(self.config.dbcFile))
        logName = path.join(logDir, f"logfile_{datetime.datetime.now().date()}_{dbcName}")
        logType = "log"
        while os.path.isfile(f"{logName}_{counter:02}.{logType}"):
            counter += 1
        self.logFile = f"{logName}_{counter:02}.{logType}"

    def shutdown(self):
        super().shutdown()
        self.canBus.shutdown()

class LogTabManager(TabManager):
    """
    A class to manage tabs and logic for a dbc file opened in logging mode

    Attributes:
    config (CanConfig): Source of truth for current config
    channel (str): Channel that the associated bus is connected to
    bus (pycan.bus): Associated bus
    dbcDb (Database): Dbc data containing messages we will use
    tabWidget (QTabWidget): The tab widget to add tabs to
    """
    def __init__(self, config: CanConfig, dbcDb, tabWidget: QTabWidget, log_file):
        super().__init__(config, dbcDb)
        self.log_file = log_file
        self.setupLogMessages(log_file)
        self.initTabs(tabWidget)

    def setupLogMessages(self, log_file):
        rx_dict = {}
        tx_dict = {}
        for msg in self.rxMsgs:
            rx_dict[msg.message.frame_id] = msg
        for msg in self.txMsgs:
            tx_dict[msg.message.frame_id] = msg
        with open(log_file) as f:
            for msg in pycan.CanutilsLogReader(f):
                if msg.is_rx:
                    key = rx_dict.get(msg.arbitration_id)
                else:
                    key = tx_dict.get(msg.arbitration_id)
                if key:
                    key.timestamps.append(msg.timestamp)
                    signalValues = key.message.decode(msg.data)
                    for sig in key.signals:
                        value = signalValues.get(sig.signal.name)
                        if value is not None:
                            if isinstance(value, namedsignalvalue.NamedSignalValue):
                                value = value.value
                            sig.graphValues.append(value)

    def initTabs(self, tabWidget: QTabWidget):
        self.txTab = LogTab(self.txMsgs, self.config)
        self.rxTab = LogTab(self.rxMsgs, self.config)
        tabWidget.addTab(self.txTab, 'Log TX ' + os.path.basename(self.log_file))
        tabWidget.setTabWhatsThis(tabWidget.count() - 1 , self.log_file)
        tabWidget.addTab(self.rxTab, 'Log RX ' + os.path.basename(self.log_file))
        tabWidget.setTabWhatsThis(tabWidget.count() - 1 , self.log_file)

class MainApp(QMainWindow):
    """
    A class that represents the main application

    Attributes:
    config (CanConfig): Source of truth for config settings
    configLayout (ConfigLayout): Initial tab for user to set config
    dbcDb (Database): Message data for loaded DBC file
    openTabs (Dict): All connected tabManagers and their associated identifier
    """
    def __init__(self):
        super().__init__()
        self.setWindowTitle('CAN Testbench')

        self.config = CanConfig()
        self.configLayout = ConfigLayout(self.config)
        self.configLayout.dbcOpened.connect(self.openDbc)
        self.configLayout.connectPressed.connect(self.connectCan)

        self.dbcDb = None
        self.openTabs = {}
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
        rightButton = tabBar.tabButton(0, QTabBar.ButtonPosition.RightSide)
        leftButton = tabBar.tabButton(0, QTabBar.ButtonPosition.LeftSide)
        if rightButton is not None:
            rightButton.resize(0,0)
        if leftButton is not None:
            leftButton.resize(0, 0)

        if path.isfile(self.config.dbcFile):
            self.openDbc()

    def errorDialog(self, error):
        print(error)
        messageBox = QMessageBox()
        messageBox.critical(self, "Error:", repr(error))
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
        opts = self.config.option()
        if opts.get('interface') == 'Logging':
            try:
                canManager = LogTabManager(self.config, self.dbcDb, self.tabWidget, opts.get('log_file'))
            except Exception as error:
                self.errorDialog(error)
                return
            self.openTabs[f"{opts.get('log_file')}"] = canManager
            self.config.writeConfig()
            return

        channel = opts.get('channel')

        if channel:
            self.closeCan(channel)
            try:
                bus = pycan.Bus(**opts)
            except Exception as error:
                self.errorDialog(error)
                return
        else:
            self.errorDialog("Channel is none")
            return

        try:
            canManager = CanTabManager(self.config, channel, bus, self.dbcDb, self.tabWidget)
        except Exception as error:
            self.errorDialog(error)
            return
        self.openTabs[channel] = canManager
        self.config.writeConfig()

    def closeCan(self, id: str):
        can = self.openTabs.pop(id, None)
        if can is not None:
            can.shutdown()

    def removeTab(self, index: int):
        id = self.tabWidget.tabWhatsThis(index)
        self.closeCan(id)

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.tabWidget.setTabsClosable(True)
        self.tabWidget.tabCloseRequested.connect(self.removeTab)
        self.setCentralWidget(self.tabWidget)
        self.setupLaunchTab()

    def closeEvent(self, event):
        # Perform any cleanup or save data here
        for can in self.openTabs:
            self.openTabs[can].shutdown()
        # Call the superclass's closeEvent method to proceed with the closing
        super().closeEvent(event)

def sanitizeFileName(name: str) -> str:
    keepcharacters = (' ','.','_')
    filename = "".join(c for c in name if c.isalnum() or c in keepcharacters).rstrip()
    return filename

if __name__ == '__main__':
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    logging.debug(sys.version)
    scriptDir = path.dirname(path.abspath(__file__))
    logDir = path.join(scriptDir, 'logs/')
    os.makedirs(logDir, exist_ok=True)

    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
