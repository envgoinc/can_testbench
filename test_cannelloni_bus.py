"""Offline tests for cannelloni_bus: a fake cannelloni server on localhost.  python -m unittest test_cannelloni_bus"""
import socket
import struct
import threading
import unittest

import can

from cannelloni_bus import HANDSHAKE, CannelloniBus, FrameDecoder, encode_frame


def frame(can_id, data=b"", fd=False, flags=0, rtr_dlc=None):
    if fd:
        return struct.pack("!IBB", can_id, len(data) | 0x80, flags) + data
    if rtr_dlc is not None:
        return struct.pack("!IB", can_id, rtr_dlc)
    return struct.pack("!IB", can_id, len(data)) + data


class FakeServer:
    """Accepts one client, does the handshake, sends `to_send` in 3-byte chunks, records what it receives."""

    def __init__(self, to_send=b"", handshake=HANDSHAKE):
        self.srv = socket.socket()
        self.srv.bind(("127.0.0.1", 0))
        self.srv.listen(1)
        self.port = self.srv.getsockname()[1]
        self.to_send, self.handshake = to_send, handshake
        self.received = b""
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        conn, _ = self.srv.accept()
        conn.sendall(self.handshake)
        hello = b""
        while len(hello) < len(HANDSHAKE):
            hello += conn.recv(len(HANDSHAKE) - len(hello))
        self.client_hello = hello
        for i in range(0, len(self.to_send), 3):
            conn.sendall(self.to_send[i:i + 3])
        conn.settimeout(1.0)
        try:
            while True:
                part = conn.recv(4096)
                if not part:
                    break
                self.received += part
        except OSError:
            pass
        conn.close()
        self.srv.close()


class CodecTest(unittest.TestCase):
    def test_round_trip(self):
        msgs = [
            can.Message(arbitration_id=0x123, data=b"\x01\x02", is_extended_id=False),
            can.Message(arbitration_id=0x18FF50E5, data=bytes(range(8)), is_extended_id=True),
            can.Message(arbitration_id=0x7FF, is_remote_frame=True, dlc=4, is_extended_id=False),
            can.Message(arbitration_id=0x1ABCDE, data=bytes(range(20)), is_fd=True, bitrate_switch=True,
                        is_extended_id=True),
            can.Message(arbitration_id=0x10, data=b"", is_extended_id=False),
        ]
        stream = b"".join(encode_frame(m) for m in msgs)
        dec, got = FrameDecoder(), []
        for b in stream:  # one byte at a time
            got += dec.feed(bytes([b]))
        self.assertEqual(len(got), len(msgs))
        for a, b in zip(msgs, got):
            self.assertEqual((a.arbitration_id, a.is_extended_id, a.is_remote_frame, a.is_fd, a.dlc, bytes(a.data)),
                             (b.arbitration_id, b.is_extended_id, b.is_remote_frame, b.is_fd, b.dlc, bytes(b.data)))
        self.assertTrue(got[3].bitrate_switch)

    def test_wire_bytes(self):
        m = can.Message(arbitration_id=0x18FF50E5, data=b"\xAA", is_extended_id=True)
        self.assertEqual(encode_frame(m), bytes.fromhex("98FF50E5" "01" "AA"))


class BusTest(unittest.TestCase):
    def test_receive_send_listen(self):
        srv = FakeServer(frame(0x100, b"\x11\x22") + frame(0x80000000 | 0x1234567, bytes(8))
                         + frame(0x40000000 | 0x200, rtr_dlc=3) + frame(0x300, bytes(12), fd=True, flags=1))
        bus = CannelloniBus("127.0.0.1", port=srv.port, listen_mode="False", interface="cannelloni",
                            receive_own_messages="False")
        got = [bus.recv(2) for _ in range(4)]
        self.assertEqual([m.arbitration_id for m in got], [0x100, 0x1234567, 0x200, 0x300])
        self.assertEqual(bytes(got[0].data), b"\x11\x22")
        self.assertTrue(got[1].is_extended_id)
        self.assertTrue(got[2].is_remote_frame and got[2].dlc == 3)
        self.assertTrue(got[3].is_fd and got[3].bitrate_switch and len(got[3].data) == 12)
        bus.send(can.Message(arbitration_id=0x42, data=b"\x01", is_extended_id=False))
        bus.shutdown()
        srv.thread.join(3)
        self.assertEqual(srv.client_hello, HANDSHAKE)
        self.assertEqual(srv.received, bytes.fromhex("00000042" "01" "01"))

    def test_listen_mode_refuses_send(self):
        srv = FakeServer()
        bus = CannelloniBus("127.0.0.1", port=srv.port)  # listen_mode defaults to True
        with self.assertRaises(can.CanOperationError):
            bus.send(can.Message(arbitration_id=0x42, data=b"\x01"))
        bus.shutdown()
        srv.thread.join(3)
        self.assertEqual(srv.received, b"")

    def test_bad_handshake(self):
        srv = FakeServer(handshake=b"HTTP/1.1 400")
        with self.assertRaises(can.CanInitializationError):
            CannelloniBus("127.0.0.1", port=srv.port)

    def test_connection_closed_is_reported(self):
        srv = FakeServer(frame(0x1, b"\x01"))
        bus = CannelloniBus("127.0.0.1", port=srv.port)
        self.assertEqual(bus.recv(2).arbitration_id, 0x1)
        srv.thread.join(3)  # server closes after its 1 s read timeout
        with self.assertRaises(can.CanOperationError):
            bus.recv(3)
        # Reported once; afterwards an idle bus, so a Notifier that handled the error does not spin.
        self.assertIsNone(bus.recv(0.2))
        bus.shutdown()

    def test_busy_server_names_the_cause(self):
        srv = FakeServer(handshake=b"")  # accepts the TCP connection, never answers (cannelloni with a client)
        with self.assertRaises(can.CanInitializationError) as ctx:
            CannelloniBus("127.0.0.1", port=srv.port, connect_timeout=1)
        self.assertIn("another client", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
