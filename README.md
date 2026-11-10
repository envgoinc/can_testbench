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

### Remote CAN bus over cannelloni (any OS, including Windows)

Interface type **`cannelloni`** connects directly to a [cannelloni](https://github.com/mguentner/cannelloni)
TCP server. An example is the XV2 Pi, bridging its `can0`. The PC needs no SocketCAN, `vcan` or
cannelloni of its own, so this works on Windows as well as Linux and macOS. The client is in
`cannelloni_bus.py`, and its offline tests run with `python -m unittest test_cannelloni_bus`.

- **Channel** is the server's host (default `xv2-pi-0`); **Port** is its TCP port (default `20000`).
- **Listen Mode is on by default** for cannelloni, and then the bus refuses to send. Turn it off only
  when you mean to transmit onto the remote bus.
- cannelloni serves **one client at a time**. A server started with `-R <ip>` accepts only that peer
  address; the XV2 Pi's server runs with `-p` and accepts any client.

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