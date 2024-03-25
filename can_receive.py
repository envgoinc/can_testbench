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
    print(site.getsitepackages())
    print(can.__file__)
    so_timestamp_value = getattr(socket, 'SO_TIMESTAMPNS', None)
    if so_timestamp_value is not None:
        print(f"SO_TIMESTAMP value is: {so_timestamp_value}")
    else:
        print("SO_TIMESTAMP is not available on this system.")
    receive_messages()
