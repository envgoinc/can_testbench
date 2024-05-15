import can
import time
import cantools
import cantools.database
from cantools.database.can.database import Database

bus = None

class msg_sender():
    
    def __init__(self, msg: cantools.database.Message):
        super().__init__()
        self.msg = msg
        self.signal_values = {}
        self.signal_db = {}
        for signal in self.msg.signals:
            if signal.minimum is not None:
                self.signal_values[signal.name] = signal.minimum
                self.signal_db[signal.name] = {'minimum':signal.minimum, 'maximum':signal.maximum}
            else:
                self.signal_values[signal.name] = 0
                self.signal_db[signal.name] = {'minimum':0, 'maximum':1}
        
    def send_message(self):
        data = self.msg.encode(self.signal_values)
        message = can.Message(arbitration_id=self.msg.frame_id, data=data, is_extended_id=True)
        bus.send(message)

        for key in self.signal_values:
            self.signal_values[key] += 1
            if self.signal_values[key] > self.signal_db[key]['maximum']:
                self.signal_values[key] = self.signal_db[key]['minimum']

if __name__ == '__main__':
    bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=10000, receive_own_messages=False)
    db = cantools.database.load_file('../envgo/dbc/nv1_syscan.dbc')

    assert(isinstance(db, Database))
    
    msg_senders = set()
    for msg in db.messages:
        if 'VCU' not in msg.senders:
            msg_senders.add(msg_sender(msg))
        
    while True:
        for sender in msg_senders:
            sender.send_message()
            
        time.sleep(1)  # Send each message once a second
