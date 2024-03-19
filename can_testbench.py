import sys
import cantools
import os
import logging
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QLabel,
    QComboBox,
    QTableWidget,
    QTableWidgetItem,
)


# Placeholder for a function that parses the .dbc file and returns message details.
def parse_dbc_file(dbc_filename):
    dbc_dict = {}
    dbc_db = cantools.database.load_file(dbc_filename)

    for msg in dbc_db.messages:
        msg_dict = {}
        if msg.senders is not None and 'VCU' in msg.senders:
            for signal in msg.signals:
                signal_dict = {}
                signal_dict['comment'] = None
                if isinstance(signal.comments, dict):
                    if 'English' in signal.comments:
                        signal_dict['comment'] = signal.comments['English']
                    elif None in signal.comments:
                        signal_dict['comment'] = signal.comments[None]
                signal_dict['unit'] = signal.unit
                signal_dict['initial'] = signal.initial
                signal_dict['minimum'] = signal.minimum
                signal_dict['maximum'] = signal.maximum
                msg_dict[signal.name] = signal_dict
            msg_dict['description'] = msg.description
            dbc_dict[msg.name] = msg_dict

    return dbc_dict


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
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)
        self.layout = QVBoxLayout()
        self.centralWidget.setLayout(self.layout)

        # Message selection
        self.messageComboBox = QComboBox()
        self.messageComboBox.addItems([msg.name for msg in self.dbc_db.messages])
        self.messageComboBox.currentIndexChanged.connect(self.onMessageSelected)
        self.layout.addWidget(self.messageComboBox)

        # Message description
        self.messageDescription = QLabel()
        self.layout.addWidget(self.messageDescription)

        # Initialize the table for signals
        self.tableWidget = QTableWidget()
        self.layout.addWidget(self.tableWidget)
        self.configureTable()

        self.onMessageSelected()  # Load initial message

    def configureTable(self):
        self.tableWidget.setColumnCount(4)  # Signal Name, Description, Unit, Value
        self.tableWidget.setHorizontalHeaderLabels(
            ['Signal Name', 'Description', 'Unit', 'Value']
        )
        self.tableWidget.setEditTriggers(QTableWidget.EditTrigger.SelectedClicked)

    def onMessageSelected(self):
        print(f'hello!{self.messageComboBox.currentText()}')
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
            self.tableWidget.setItem(row, 0, QTableWidgetItem(signal.name))
            self.tableWidget.setItem(row, 1, QTableWidgetItem(signal.comment))
            self.tableWidget.setItem(row, 2, QTableWidgetItem(signal.unit))

            # Correctly make the value cell editable
            value_item = QTableWidgetItem(str(signal.initial))
            value_item.setFlags(
                value_item.flags() | Qt.ItemIsEditable
            )  # Correctly set flags to make the cell editable
            self.tableWidget.setItem(row, 3, value_item)

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
