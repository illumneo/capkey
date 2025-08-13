#!/usr/bin/env python3
"""
Real-time serial data plotting script with matplotlib.
Reads timestamp (us), x, y, z values from serial port and plots them in real-time 3D.
Implements configurable time window for data fading.
"""

import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
from mpl_toolkits.mplot3d import Axes3D
from collections import deque
import time
import argparse
from datetime import datetime
import numpy as np

class RealtimePlotter:
    def __init__(self, port='/dev/ttyUSB0', baudrate=115200, time_window=10.0,
                 max_points=1000, fade_effect=True, update_interval=20):
        """
        Initialize the real-time plotter.

        Args:
            port (str): Serial port to connect to
            baudrate (int): Baud rate for serial communication
            time_window (float): Time window in seconds for data display
            max_points (int): Maximum number of points to store
            fade_effect (bool): Whether to enable fading effect for old data
            update_interval (int): Animation update interval in milliseconds
        """
        self.port = port
        self.baudrate = baudrate
        self.time_window = time_window
        self.max_points = max_points
        self.fade_effect = fade_effect
        self.update_interval = update_interval

        # Data storage
        self.timestamps = deque(maxlen=max_points)
        self.x_values = deque(maxlen=max_points)
        self.y_values = deque(maxlen=max_points)
        self.z_values = deque(maxlen=max_points)

        # Serial connection
        self.serial_conn = None

        # Plot setup - 3D plot
        self.fig = plt.figure(figsize=(12, 10))
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.fig.suptitle(f'Real-time 3D Serial Data Plot\nPort: {port}, Time Window: {time_window}s')

        # Initialize 3D plot
        self.setup_plots()

        # Animation
        self.ani = None

    def setup_plots(self):
        """Setup the 3D plot."""
        self.ax.set_xlabel('X Values')
        self.ax.set_ylabel('Y Values')
        self.ax.set_zlabel('Z Values')
        self.ax.set_title('Real-time 3D Data Plot')
        self.ax.grid(True, alpha=0.3)

        # Set initial view
        self.ax.view_init(elev=20, azim=45)

        # Set initial limits
        self.ax.set_xlim(-10, 10)
        self.ax.set_ylim(-10, 10)
        self.ax.set_zlim(0, 10)

        plt.tight_layout()

    def connect_serial(self):
        """Connect to the serial port."""
        try:
            self.serial_conn = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=1
            )
            print(f"Connected to {self.port} at {self.baudrate} baud")
            return True
        except serial.SerialException as e:
            print(f"Failed to connect to {self.port}: {e}")
            return False

    def disconnect_serial(self):
        """Disconnect from the serial port."""
        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()
            print(f"Disconnected from {self.port}")

    def parse_serial_data(self, line):
        """
        Parse serial data line.
        Expected format: "timestamp,x,y,z"
        """
        try:
            # Split by comma
            parts = line.strip().split(',')

            if len(parts) >= 4:  # Need 4 elements: timestamp + x + y + z
                timestamp_us = float(parts[0])  # First element is timestamp
                x = float(parts[1])            # Second element is x
                y = float(parts[2])            # Third element is y
                z = float(parts[3])            # Fourth element is z

                # Convert microseconds to seconds
                timestamp_s = timestamp_us / 1e6

                return timestamp_s, x, y, z
        except (ValueError, IndexError) as e:
            print(f"Error parsing line '{line.strip()}': {e}")

        return None, None, None, None

    def read_serial_data(self):
        """Read and parse all available data from serial port."""
        if not self.serial_conn or not self.serial_conn.is_open:
            return

        try:
            # Read all available data at once
            while self.serial_conn.in_waiting > 0:
                line = self.serial_conn.readline().decode('utf-8', errors='ignore')
                if line.strip():
                    timestamp_s, x, y, z = self.parse_serial_data(line)
                    if timestamp_s is not None:
                        self.add_data_point(timestamp_s, x, y, z)
        except Exception as e:
            print(f"Error reading serial data: {e}")

    def add_data_point(self, timestamp_s, x, y, z):
        """Add a new data point to the storage."""
        # Store data
        self.timestamps.append(timestamp_s)
        self.x_values.append(x)
        self.y_values.append(y)
        self.z_values.append(z)

        # Remove old data outside time window
        self.cleanup_old_data(timestamp_s)

    def cleanup_old_data(self, current_timestamp):
        """Remove data points outside the time window."""
        if not self.timestamps:
            return

        # Convert to numpy arrays for easier manipulation
        timestamps = np.array(self.timestamps)
        x_vals = np.array(self.x_values)
        y_vals = np.array(self.y_values)
        z_vals = np.array(self.z_values)

                # Find data within time window (compare timestamps directly)
        # Keep data within the time window from the most recent timestamp
        if len(timestamps) > 0:
            most_recent = np.max(timestamps)
            time_threshold = most_recent - self.time_window
            valid_indices = timestamps >= time_threshold

            # Update data storage
            self.timestamps = deque(timestamps[valid_indices], maxlen=self.max_points)
            self.x_values = deque(x_vals[valid_indices], maxlen=self.max_points)
            self.y_values = deque(y_vals[valid_indices], maxlen=self.max_points)
            self.z_values = deque(z_vals[valid_indices], maxlen=self.max_points)

    def update_plot(self, frame):
        """Update the 3D plot with new data."""
        # Read new data
        self.read_serial_data()

        if not self.timestamps:
            return

        # Convert to numpy arrays
        timestamps = np.array(self.timestamps)
        x_vals = np.array(self.x_values)
        y_vals = np.array(self.y_values)
        z_vals = np.array(self.z_values)

                        # Store current view before clearing
        current_elev = self.ax.elev
        current_azim = self.ax.azim

        # Clear the plot
        self.ax.clear()

        # Set basic plot properties (without hardcoded limits)
        self.ax.set_xlabel('X Values')
        self.ax.set_ylabel('Y Values')
        self.ax.set_zlabel('Z Values')
        self.ax.set_title('Real-time 3D Data Plot')
        self.ax.grid(True, alpha=0.3)

        # Restore the user's view (or set initial view if first time)
        if hasattr(self, '_view_set') and self._view_set:
            self.ax.view_init(elev=current_elev, azim=current_azim)
        else:
            self.ax.view_init(elev=20, azim=45)
            self._view_set = True

        if len(x_vals) > 0:
            # Plot the 3D data
            if self.fade_effect and len(x_vals) > 1:
                # Create fading effect based on time
                alpha_values = np.linspace(0.3, 1.0, len(x_vals))
                for i in range(len(x_vals)):
                    self.ax.scatter(x_vals[i], y_vals[i], z_vals[i],
                                  c='blue', alpha=alpha_values[i], s=20)
            else:
                # Plot all points with same alpha
                self.ax.scatter(x_vals, y_vals, z_vals, c='blue', alpha=0.8, s=20)

            # Auto-adjust limits with some padding
            x_min, x_max = np.min(x_vals), np.max(x_vals)
            y_min, y_max = np.min(y_vals), np.max(y_vals)
            z_min, z_max = np.min(z_vals), np.max(z_vals)

            x_range = x_max - x_min if x_max != x_min else 1
            y_range = y_max - y_min if y_max != y_min else 1
            z_range = z_max - z_min if z_max != z_min else 1

            self.ax.set_xlim(x_min - x_range * 0.1, x_max + x_range * 0.1)
            self.ax.set_ylim(y_min - y_range * 0.1, y_max + y_range * 0.1)
            self.ax.set_zlim(z_min - z_range * 0.1, z_max + z_range * 0.1)
        else:
            # Set default limits if no data
            self.ax.set_xlim(-10, 10)
            self.ax.set_ylim(-10, 10)
            self.ax.set_zlim(0, 10)

        plt.tight_layout()

    def start_plotting(self):
        """Start the real-time plotting."""
        if not self.connect_serial():
            return

        try:
            # Start animation with configurable update speed
            self.ani = animation.FuncAnimation(
                self.fig, self.update_plot, interval=self.update_interval, blit=False
            )

            print("Starting real-time 3D plot. Press Ctrl+C to stop.")
            print("Controls: Mouse drag to rotate, mouse wheel to zoom, right-click drag to pan")
            plt.show()

        except KeyboardInterrupt:
            print("\nStopping plot...")
        finally:
            self.disconnect_serial()

    def simulate_data(self, duration=30):
        """Simulate data for testing when no serial device is available."""
        print(f"Simulating data for {duration} seconds...")

        start_time = time.time()
        while time.time() - start_time < duration:
            current_time = time.time()
            timestamp_us = current_time * 1e6

            # Generate some sample data (3D spiral with noise)
            t = current_time - start_time
            radius = 30 + 10 * np.sin(2 * np.pi * 0.2 * t)
            x = radius * np.cos(2 * np.pi * 0.5 * t) + np.random.normal(0, 2)
            y = radius * np.sin(2 * np.pi * 0.5 * t) + np.random.normal(0, 2)
            z = 20 * np.sin(2 * np.pi * 0.3 * t) + np.random.normal(0, 2)

            self.add_data_point(current_time, x, y, z)
            time.sleep(0.01)  # 100 Hz simulation

        print("Simulation complete.")

def main():
    """Main function with command line argument parsing."""
    parser = argparse.ArgumentParser(description='Real-time 3D serial data plotting')
    parser.add_argument('--port', default='/dev/ttyUSB0', help='Serial port (default: /dev/ttyUSB0)')
    parser.add_argument('--baudrate', type=int, default=115200, help='Baud rate (default: 115200)')
    parser.add_argument('--time-window', type=float, default=10.0, help='Time window in seconds (default: 10.0)')
    parser.add_argument('--max-points', type=int, default=1000, help='Maximum data points (default: 1000)')
    parser.add_argument('--no-fade', action='store_true', help='Disable fading effect')
    parser.add_argument('--update-interval', type=int, default=20, help='Update interval in milliseconds (default: 20)')
    parser.add_argument('--simulate', action='store_true', help='Simulate data instead of reading from serial')
    parser.add_argument('--sim-duration', type=int, default=30, help='Simulation duration in seconds (default: 30)')

    args = parser.parse_args()

    # Create plotter
    plotter = RealtimePlotter(
        port=args.port,
        baudrate=args.baudrate,
        time_window=args.time_window,
        max_points=args.max_points,
        fade_effect=not args.no_fade,
        update_interval=args.update_interval
    )

    if args.simulate:
        # Run simulation in a separate thread
        import threading
        sim_thread = threading.Thread(target=plotter.simulate_data, args=(args.sim_duration,))
        sim_thread.daemon = True
        sim_thread.start()

        # Start plotting
        plotter.start_plotting()
    else:
        # Start real-time plotting from serial
        plotter.start_plotting()

if __name__ == "__main__":
    main()
