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

### Installation

1. Clone the repository:

    ```bash
    git clone https://github.com/your-username/can-testbench.git
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