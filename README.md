# CAN Test Bench

A graphical tool for interacting with and visualizing CAN (Controller Area Network) signals.  Uses dbc files to display messages and signals in the system.

## Features

- **Real-time Monitoring:** Plot and visualize CAN signals in real time.
- **Interacting on the CAN bus:** Application can act as the VCU (vehicle control unit) and specify signals and messages to send.
- **User-friendly Interface:** Simple GUI using `PySide6` and `pyqtgraph`.

## Requirements

### Python Packages

The tool requires the following Python packages:

- `cantools`
- `python-can`
- `pyqtgraph`
- `PySide6`
- `Plotly`

### Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/envgoinc/can_testbench.git
    cd can-testbench
    ```

2. Create a virtual environment (optional but recommended):

    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3. Install the required packages:

    ```bash
    pip install -r requirements.txt
    ```

### CAN Interface Setup

The CAN bus interface setup depends on the specific hardware you are using. Configure your CAN device according to its manufacturer instructions.  This program will support whatever CAN interfaces python-can supports.

### Quick start: watch the XV2 CAN bus (no programming needed)

1. Install [Tailscale](https://tailscale.com/download) and sign in with your ENVGO account. You need
   access to the boat Pi `xv2-pi-0`; ask the Tailscale admin if it doesn't appear in Tailscale.
2. Unzip the XV2 viewer bundle into a folder of your own (for example `Documents\CAN Test Bench`). It
   contains `can_testbench.exe`, `xv2.dbc` and a `can_config.ini` that selects the boat.
3. Double-click `can_testbench.exe` and press **Connect**. The VCU RX tab shows the live signals.

Listen Mode is on, so nothing is sent to the boat. Settings and CAN logs (`logs\`) are kept in that
folder. If the boat is off or out of reach, an error says so. Only one person can be connected to the
boat at a time.

### Remote CAN bus over cannelloni (any OS, including Windows)

Interface type **`cannelloni`** connects directly to a [cannelloni](https://github.com/mguentner/cannelloni)
TCP server. An example is the XV2 Pi, bridging its `can0`. The PC needs no SocketCAN, `vcan` or
cannelloni of its own, so this works on Windows as well as Linux and macOS. The client is in
`cannelloni_bus.py`, and its offline tests run with `python -m unittest test_cannelloni_bus`.

- **Channel** is the server's host (default `xv2-pi-0`); **Port** is its TCP port (default `20000`).
- **Listen Mode is on by default** for cannelloni, and then the bus refuses to send. Turn it off only
  when you mean to transmit onto the remote bus.
- cannelloni serves **one client at a time**. A second client gets "accepted the connection but did
  not answer… is another client already connected?" after 5 s. A server started with `-R <ip>` accepts
  only that peer address; the XV2 Pi's server runs with `-p` and accepts any client.
- **A lost connection is reported.** If the server stops, the Pi reboots or the network drops, an error
  dialog names the channel and the tabs are marked "(disconnected)". They keep their last values;
  press Connect again. A server that vanishes without closing (power loss, Wi-Fi drop) is detected by
  TCP keepalive after about 6 s.
- **After a network drop, the server may refuse a reconnect for a while.** When the Pi stays up but
  the network drops, cannelloni still holds the dead connection. It only frees its one client slot
  once its own TCP gives up on the old client. With Linux defaults (`net.ipv4.tcp_retries2 = 15`)
  that took about 16½ minutes on a bench Pi, and the server then exited (SIGPIPE). With
  `net.ipv4.tcp_retries2 = 5` on the server, reconnecting worked 1–2 s after the network returned.
  Restarting the server (`sudo systemctl restart xv2-start-canneloni` on the Pi) frees it at once.
- cannelloni itself drops the length of remote (RTR) frames that a client sends (its decoder sets it
  to 0). Received RTR frames keep their length.
- Older CAN Test Bench versions share `can_config.ini`, but they don't know the cannelloni interface.
  If cannelloni was the last interface selected, an older version resets that file's settings to
  its defaults.

The XV2 Pi runs the server permanently as the systemd service `xv2-start-canneloni.service`
(`cannelloni -I can0 -C s -l 20000 -p`), so connecting needs nothing else. On Windows,
`xv2_testbench.ps1` checks over SSH (read-only) that the service is active, `can0` is UP and no other
client is connected, then opens CAN Test Bench:

```powershell
.\xv2_testbench.ps1                                   # from source (venv, below)
.\xv2_testbench.ps1 -Exe C:\path\to\can_testbench.exe  # with a built executable
.\xv2_testbench.ps1 -CheckOnly                        # the checks only
```

Source setup on Windows, with the CI's Python 3.10 (the pinned PySide6 6.6.2 has no wheels for
Python 3.13):

```powershell
uv venv --python 3.10.11 --seed venv
venv\Scripts\python -m pip install -r requirements.txt
```

### Usage

1. Make sure your CAN interface is correctly configured and connected.
2. Launch the tool using:

    ```bash
    python can_testbench.py
    ```

3. Use the GUI to interact with the CAN signals.

### File Structure

- `can_testbench.py`: Main application file containing the GUI logic and CAN communication.

### Example Configuration

To visualize and interact with specific CAN signals, you need to provide a CAN database file in `.dbc` format. Once the application is running, load your `.dbc` file via the GUI.

### Contributing

Contributions are welcome! Please follow these steps to contribute:

1. Fork the repository.
2. Create a new feature branch.
3. Commit your changes.
4. Open a pull request.

### License

This project is licensed under the MIT License. See the `LICENSE` file for details.