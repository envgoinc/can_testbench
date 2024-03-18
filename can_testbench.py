import sys
import cantools
import os
import logging
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                               QHBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFormLayout)



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
      dbc_dict[msg.name] = msg_dict

  return dbc_dict

class MainApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('VCU Message Viewer')
        self.messages = parse_dbc_file('../envgo/dbc/xerotech_battery_j1939.dbc')
        self.currentSignalsWidgets = []
        self.initUI()

    def initUI(self):
        self.centralWidget = QWidget()
        self.setCentralWidget(self.centralWidget)
        self.layout = QVBoxLayout()
        self.centralWidget.setLayout(self.layout)

        # Message selection
        self.messageComboBox = QComboBox()
        self.messageComboBox.addItems(self.messages.keys())
        self.messageComboBox.currentIndexChanged.connect(self.onMessageSelected)
        self.layout.addWidget(self.messageComboBox)

        # Placeholder for signals form
        self.signalsLayout = QVBoxLayout()
        self.layout.addLayout(self.signalsLayout)

        self.onMessageSelected()  # Load initial message

    def clearLayout(self, layout):
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
                else:
                    self.clearLayout(item.layout())

    def onMessageSelected(self):
        # Clear previous signals
        self.clearLayout(self.signalsLayout)

        selected_message = self.messageComboBox.currentText()
        signals = self.messages[selected_message]

        formLayout = QFormLayout()
        self.signalsLayout.addLayout(formLayout)

        for signal_name, signal_info in signals.items():
            signal_description = QLabel(f"{signal_name}: {signal_info['comment']} ({signal_info['unit']})")
            signal_value_input = QLineEdit()
            signal_value_input.setText(str(signal_info['initial']))
            formLayout.addRow(signal_description, signal_value_input)
            self.currentSignalsWidgets += [signal_description, signal_value_input]

if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainApp = MainApp()
    mainApp.show()
    sys.exit(app.exec())
