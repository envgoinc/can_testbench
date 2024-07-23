import can
import time
import cantools
import cantools.database
from cantools.database.can.database import Database
import random

bus = None

class msg_sender():
    
    def __init__(self, msg: cantools.database.Message, bus: can.bus):
        super().__init__()
        self.msg = msg
        self.bus = bus
        self.signal_values = {}
        self.signal_db = {}
        for signal in self.msg.signals:
            if not signal.minimum == None and not signal.maximum == None:
                self.signal_db[signal.name] = {'minimum':signal.conversion.numeric_scaled_to_raw(signal.minimum),
                                               'maximum':min(int(signal.conversion.numeric_scaled_to_raw(signal.maximum)),
                                                             pow(2, signal.length - int(signal.is_signed)) - 1)}
                self.signal_values[signal.name] = self.signal_db[signal.name]['maximum']
            elif signal.choices is not None:
                self.signal_db[signal.name] = list(signal.choices.keys())
                self.signal_values[signal.name] = random.choice(self.signal_db[signal.name])
            else:
                self.signal_values[signal.name] = 0
                self.signal_db[signal.name] = {'minimum':0, 'maximum':1}
        
    def send_message(self):
        # print(self.signal_values)
        data = self.msg.encode(self.signal_values, scaling=False)
        message = can.Message(arbitration_id=self.msg.frame_id, data=data, is_extended_id=True)
        self.bus.send(message)

        for key in self.signal_values:
            if isinstance(self.signal_db[key], dict):
                self.signal_values[key] -= 1
                if self.signal_values[key] < self.signal_db[key]['minimum']:
                    self.signal_values[key] = self.signal_db[key]['maximum']
            else:
                self.signal_values[key] = random.choice(self.signal_db[key])

if __name__ == '__main__':
    bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=10000, receive_own_messages=False)
    db = cantools.database.load_file('../envgo/dbc/testbench_hydraulics.dbc')

    assert(isinstance(db, Database))
    
    msg_senders = set()
    for msg in db.messages:
        if 'VCU' not in msg.senders:
            msg_senders.add(msg_sender(msg, bus))
        
    while True:
        for sender in msg_senders:
            sender.send_message()
            
        time.sleep(1)  # Send each message once a second
