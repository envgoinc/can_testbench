import can
import socket
import site

def receive_messages():
    # Configure the bus with the multicast group and port
    bus = can.Bus(interface='udp_multicast', channel='239.0.0.1', port=10000, receive_own_messages=False)

    print(f"Listening for messages...")
    while True:
        message = bus.recv()  # Block until a message is received
        if message:
            print(f"Received: {message}")

if __name__ == '__main__':
    receive_messages()
