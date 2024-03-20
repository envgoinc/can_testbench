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
    QLabel,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
)

CUSTOM_ROLE = Qt.UserRole + 1

class DbcVcuModel(QAbstractTableModel):
    def __init__(self, vcu_msg, parent=None):
        super().__init__(parent)
        self.vcu_msg = vcu_msg

    def rowCount(self, parent=None):
        # number of signals in message
        return len(self.vcu_msg)

    def columnCount(self, parent=None):


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

    def getVcuMsgNames(self):
        vcu_msg = []
        for msg in self.dbc_db.messages:
            if msg.senders is not None and 'VCU' in msg.senders:
                vcu_msg.append(msg.name)
        return vcu_msg

    def initUI(self):
        self.tabWidget = QTabWidget(self)
        self.setCentralWidget(self.tabWidget)

        # Create the first tab
        self.firstTab = QWidget()
        self.firstTabLayout = QVBoxLayout()
        self.firstTab.setLayout(self.firstTabLayout)

        # Message selection
        self.messageComboBox = QComboBox()
        self.messageComboBox.addItems(self.getVcuMsgNames())
        self.messageComboBox.currentIndexChanged.connect(self.onMessageSelected)
        self.firstTabLayout.addWidget(self.messageComboBox)

        # Message description
        self.messageDescription = QLabel()
        self.firstTabLayout.addWidget(self.messageDescription)

        # Initialize the table for signals
        self.tableWidget = QTableWidget()
        self.firstTabLayout.addWidget(self.tableWidget)
        self.configureTable()

        self.tabWidget.addTab(self.firstTab, 'TX CAN Messages')

        # Add a second blank tab
        self.secondTab = QWidget()
        self.tabWidget.addTab(self.secondTab, 'RX CAN Messages')

        self.onMessageSelected()  # Load initial message

    def onItemChanged(self, item):
        # Check if the changed item is in the "Value" column
        if item.column() == 4:  # Assuming the "Value" column is at index 4
            newValue = item.text()  # This is the new value entered by the user

            # Retrieve the signal object from the first column of the same row
            signal_item = self.tableWidget.item(item.row(), 0)
            signal = signal_item.data(CUSTOM_ROLE)

            # Now you can act upon the new value. For example:
            print(f"Signal '{signal.name}' has a new value: {newValue}")

    def configureTable(self):
        self.tableWidget.setColumnCount(6)  # Signal Name, Description, Unit, Minimum, Value, Maximum
        self.tableWidget.setHorizontalHeaderLabels(
            ['Signal Name', 'Description', 'Unit', 'Minimum', 'Value', 'Maximum']
        )
        self.tableWidget.setEditTriggers(QTableWidget.EditTrigger.AllEditTriggers)

        # Connect the itemChanged signal to your handler method
        self.tableWidget.itemChanged.connect(self.onItemChanged)

    def onMessageSelected(self):
        selected_message = self.dbc_db.get_message_by_name(self.messageComboBox.currentText())

        signals = selected_message.signals

        # todo: figure out what to show here
        #self.messageDescription.setText(selected_message.messages)

        self.tableWidget.clearContents()
        self.tableWidget.setRowCount(len(signals))

        for row, signal in enumerate(signals):
            signal_item = QTableWidgetItem(signal.name)
            signal_item.setFlags(signal_item.flags() & ~Qt.ItemIsEditable)  # Making sure the item is not editable
            signal_item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            self.tableWidget.setItem(row, 0, signal_item)
            signal_item.setData(CUSTOM_ROLE, signal)
            self.tableWidget.setItem(row, 1, QTableWidgetItem(signal.comment))
            self.tableWidget.setItem(row, 2, QTableWidgetItem(signal.unit))
            self.tableWidget.setItem(row, 3, QTableWidgetItem(str(signal.minimum)))

            # Correctly make the value cell editable
            initial = signal.initial if signal.initial is not None else 0
            value_item = QTableWidgetItem(str(initial))
            value_item.setFlags(
                value_item.flags() | Qt.ItemIsEditable
            )  # Correctly set flags to make the cell editable
            self.tableWidget.setItem(row, 4, value_item)
            self.tableWidget.setItem(row, 5, QTableWidgetItem(str(signal.maximum)))


        # Resize columns to fit their content
        for column in range(self.tableWidget.columnCount()):
            self.tableWidget.resizeColumnToContents(column)
            if self.tableWidget.columnWidth(column) > 500:
                self.tableWidget.setColumnWidth(column, 500)

        # Ensure rows are tall enough to display wrapped text
        self.tableWidget.resizeRowsToContents()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
