import can
import time
import cantools

bus = None

def send_message(msg):
    signal_values = {}
    signal_db = {}
    for signal in msg.signals:
        signal_values[signal.name] = signal.minimum
        signal_db[signal.name] = {'minimum':signal.minimum, 'maximum':signal.maximum}

    while True:
        data = msg.encode(signal_values)
        message = can.Message(arbitration_id=msg.frame_id, data=data, is_extended_id=True)
        bus.send(message)

        for key in signal_values:
            signal_values[key] += 1
            if signal_values[key] > signal_db[key]['maximum']:
                signal_values[key] = signal_db[key]['minimum']

        time.sleep(1)  # Send a message every second

if __name__ == '__main__':
    bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=10000, receive_own_messages=False)
    db = cantools.database.load_file('../envgo/dbc/xerotech_battery_j1939.dbc')

    for msg in db.messages:
        if 'VCU' not in msg.senders:
            send_message(msg)
            break
