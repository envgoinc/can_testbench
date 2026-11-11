"""
python-can bus for a cannelloni TCP server, e.g. a Raspberry Pi bridging its can0:

    pi$ cannelloni -I can0 -C s -l 20000 -R <this PC's IP>

The PC needs no SocketCAN, vcan or cannelloni of its own, so this works on Windows, Linux and macOS.

Wire format (cannelloni v2.x, TCP mode; tcpthread.cpp and decoder.cpp):
  - Both ends send the 12 ASCII bytes "CANNELLONIv1" on connect and check that the peer sent the same.
  - Then a stream of frames, each:
      can_id  4 bytes, big-endian, Linux flags (EFF 0x80000000, RTR 0x40000000, ERR 0x20000000)
      len     1 byte; bit 0x80 (CANFD_FRAME) marks CAN FD, the rest is the data length
      flags   1 byte, CAN FD frames only (BRS 0x01, ESI 0x02)
      data    len & 0x7F bytes, absent for RTR frames
Cannelloni sends no timestamps; received frames are stamped on arrival.

listen_mode (default True) makes send() refuse, so nothing reaches the remote bus.
"""
from __future__ import annotations

import logging
import queue
import socket
import struct
import threading
import time
from typing import Any, Optional, Tuple

import can

log = logging.getLogger(__name__)

HANDSHAKE = b"CANNELLONIv1"
CAN_EFF_FLAG = 0x80000000
CAN_RTR_FLAG = 0x40000000
CAN_ERR_FLAG = 0x20000000
CAN_EFF_MASK = 0x1FFFFFFF
CAN_SFF_MASK = 0x000007FF
CANFD_FRAME = 0x80
CANFD_BRS = 0x01
CANFD_ESI = 0x02
CANFD_MAX_DLEN = 64


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def encode_frame(msg: can.Message) -> bytes:
    """One cannelloni frame for msg."""
    if msg.is_extended_id:
        can_id = (msg.arbitration_id & CAN_EFF_MASK) | CAN_EFF_FLAG
    else:
        can_id = msg.arbitration_id & CAN_SFF_MASK
    if msg.is_remote_frame:
        can_id |= CAN_RTR_FLAG
    if msg.is_error_frame:
        can_id |= CAN_ERR_FLAG
    data = bytes(msg.data or b"")
    if msg.is_fd:
        if len(data) > CANFD_MAX_DLEN:
            raise ValueError("CAN FD data longer than 64 bytes")
        flags = (CANFD_BRS if msg.bitrate_switch else 0) | (CANFD_ESI if msg.error_state_indicator else 0)
        return struct.pack("!IBB", can_id, len(data) | CANFD_FRAME, flags) + data
    if msg.is_remote_frame:
        return struct.pack("!IB", can_id, msg.dlc)
    if len(data) > 8:
        raise ValueError("classic CAN data longer than 8 bytes")
    return struct.pack("!IB", can_id, len(data)) + data


class FrameDecoder:
    """Incremental decoder: feed() bytes in any chunking, get whole messages back."""

    def __init__(self, channel: str = ""):
        self.buf = bytearray()
        self.channel = channel

    def feed(self, chunk: bytes) -> list[can.Message]:
        self.buf += chunk
        out = []
        while True:
            if len(self.buf) < 5:
                return out
            can_id, length = struct.unpack_from("!IB", self.buf, 0)
            fd = bool(length & CANFD_FRAME)
            dlen = length & ~CANFD_FRAME & 0xFF
            head = 6 if fd else 5
            rtr = bool(can_id & CAN_RTR_FLAG)
            if dlen > CANFD_MAX_DLEN or (not fd and dlen > 8 and not rtr):
                raise can.CanOperationError("cannelloni: invalid frame length %d" % dlen)
            size = head + (0 if rtr else dlen)
            if len(self.buf) < size:
                return out
            flags = self.buf[5] if fd else 0
            data = bytes(self.buf[head:size])
            del self.buf[:size]
            ext = bool(can_id & CAN_EFF_FLAG)
            out.append(can.Message(
                timestamp=time.time(),
                arbitration_id=can_id & (CAN_EFF_MASK if ext else CAN_SFF_MASK),
                is_extended_id=ext,
                is_remote_frame=rtr,
                is_error_frame=bool(can_id & CAN_ERR_FLAG),
                is_fd=fd,
                bitrate_switch=bool(flags & CANFD_BRS),
                error_state_indicator=bool(flags & CANFD_ESI),
                dlc=dlen if rtr else len(data),
                data=data,
                channel=self.channel,
                is_rx=True,
            ))


class CannelloniBus(can.BusABC):
    """
    :param channel: host of the cannelloni TCP server (name or IP)
    :param port: its TCP port (cannelloni -l), default 20000
    :param listen_mode: True (default) refuses every send()
    :param connect_timeout: seconds to wait for the TCP connection and handshake
    :param keepalive_s: seconds of silence before TCP keepalive probes start (0 disables); a server
        that vanished without closing is reported as a lost connection about keepalive_s + 3 s later
    """

    def __init__(self, channel: str, port: int | str = 20000, listen_mode: bool | str = True,
                 connect_timeout: float | str = 5.0, keepalive_s: int | str = 3, **kwargs: Any):
        self._is_shutdown = True  # until BusABC.__init__ below: a failed connect has nothing to shut down
        self.host = str(channel)
        self.port = int(port)
        self.listen_mode = _as_bool(listen_mode)
        self.channel_info = "cannelloni %s:%d%s" % (self.host, self.port, " (listen only)" if self.listen_mode else "")
        for key in ("interface", "bustype", "receive_own_messages"):
            kwargs.pop(key, None)  # meaningless here; the test bench passes them for every interface

        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=float(connect_timeout))
        except OSError as error:
            raise can.CanInitializationError(
                "cannelloni: cannot connect to %s:%d: %s" % (self.host, self.port, error)) from error
        try:
            self._sock.sendall(HANDSHAKE)
            peer = b""
            while len(peer) < len(HANDSHAKE):
                part = self._sock.recv(len(HANDSHAKE) - len(peer))
                if not part:
                    break
                peer += part
        except socket.timeout as error:
            # The kernel completes the TCP connect even while cannelloni is busy with another client,
            # so a busy server shows up as a handshake that never comes.
            self._sock.close()
            raise can.CanInitializationError(
                "cannelloni: %s:%d accepted the connection but did not answer within %s s. A cannelloni server "
                "serves one client at a time: is another client already connected?" % (self.host, self.port, connect_timeout)
            ) from error
        except OSError as error:
            self._sock.close()
            raise can.CanInitializationError("cannelloni: handshake failed: %s" % error) from error
        if peer != HANDSHAKE:
            self._sock.close()
            raise can.CanInitializationError(
                "cannelloni: %s:%d did not answer the cannelloni handshake (got %r)" % (self.host, self.port, peer))
        self._sock.settimeout(None)
        self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self._enable_keepalive(int(keepalive_s))

        self._rx: "queue.Queue[can.Message | BaseException]" = queue.Queue()
        self._send_lock = threading.Lock()
        self._closing = threading.Event()
        self._reader = threading.Thread(target=self._read_loop, name="cannelloni-rx", daemon=True)
        self._reader.start()
        super().__init__(channel=self.host, **kwargs)
        log.info("connected to %s", self.channel_info)

    def _enable_keepalive(self, idle_s: int) -> None:
        """
        Detect a server that vanished without closing: power loss, a reboot, Wi-Fi gone. No FIN or RST
        ever arrives then, so without keepalive recv() would wait forever while the bus looks idle.
        After idle_s seconds of silence, probe every second; three unanswered probes end the connection,
        which _read_loop reports as a lost connection.
        """
        if idle_s <= 0:
            return
        sock = self._sock
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, idle_s)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 1)
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except (AttributeError, OSError):
            if hasattr(sock, "ioctl") and hasattr(socket, "SIO_KEEPALIVE_VALS"):  # older Windows
                sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, idle_s * 1000, 1000))
            elif hasattr(socket, "TCP_KEEPALIVE"):  # macOS: idle time only
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPALIVE, idle_s)
        if hasattr(socket, "TCP_USER_TIMEOUT"):  # Linux: also bound unacknowledged sends
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_USER_TIMEOUT, (idle_s + 3) * 1000)

    def _read_loop(self) -> None:
        decoder = FrameDecoder(self.host)
        try:
            while not self._closing.is_set():
                chunk = self._sock.recv(65536)
                if not chunk:
                    raise can.CanOperationError("cannelloni: %s:%d closed the connection" % (self.host, self.port))
                for msg in decoder.feed(chunk):
                    self._rx.put(msg)
        except BaseException as error:  # handed to recv() so the caller sees it
            if not self._closing.is_set():
                if not isinstance(error, can.CanError):
                    error = can.CanOperationError("cannelloni: connection lost: %s" % error)
                self._rx.put(error)

    def _recv_internal(self, timeout: Optional[float]) -> Tuple[Optional[can.Message], bool]:
        try:
            item = self._rx.get(timeout=timeout)
        except queue.Empty:
            return None, False
        if isinstance(item, BaseException):
            # Raised once. Afterwards recv() returns None like an idle bus, so a python-can Notifier
            # whose listener handled the error does not spin on it. send() still fails on the closed socket.
            raise item
        return item, False

    def send(self, msg: can.Message, timeout: Optional[float] = None) -> None:
        if self.listen_mode:
            raise can.CanOperationError("cannelloni: listen mode is on; nothing is sent to %s" % self.host)
        frame = encode_frame(msg)
        with self._send_lock:
            try:
                self._sock.sendall(frame)
            except OSError as error:
                raise can.CanOperationError("cannelloni: send failed: %s" % error) from error

    def shutdown(self) -> None:
        self._closing.set()
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()
        super().shutdown()
