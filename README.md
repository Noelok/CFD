# FluidX3D Visualizer & Controller

This is a Python-based GUI frontend for **FluidX3D**, designed to facilitate setting up, running, and visualizing Computational Fluid Dynamics (CFD) simulations.

## Features
*   **Geometry Builder**: Design 2D cross-sections and extrude them to create 3D simulation domains.
*   **Simulation Control**: Start, pause, and stop simulations directly from the UI.
*   **Real-time Visualization**:
    *   **Surface**: View the 3D geometry.
    *   **Slice**: Interactive slicing planes (X, Y, Z) to inspect internal flow.
    *   **Volume**: 3D Volume rendering with adjustable opacity and thresholds.
*   **Result Analysis**:
    *   Load VTK/STL files.
    *   Export snapshots and meshes.
    *   Save SVG cross-sections.

## Requirements
*   Windows 10/11
*   Python 3.8+
*   **Visual Studio Build Tools (MSVC)**: Required for compiling the FluidX3D OpenCL kernels.
*   **NVIDIA GPU**: Required for FluidX3D OpenCL acceleration.

## Installation
1.  Install Python dependencies:
    ```bash
    pip install -r requirements.txt
    ```

## Usage
Double-click **`run_app.bat`** to start the application.
*   This script automatically sets up the MSVC environment variables needed for compilation.

### Controls
*   **Simulation**:
    *   `P`: Pause/Resume
    *   `R`: Reset
*   **Visualizer**:
    *   **Left Click**: Rotate
    *   **Right Click**: Pan
    *   **Scroll**: Zoom
    *   **Volume Mode**: Use Opacity/Threshold sliders to adjust the 3D flow visualization.

## Directory Structure
*   `main.py`: Main application entry point and UI logic.
*   `visualizer.py`: Visualization backend (PyVista/VisPy).
*   `geometry.py`: Geometry generation logic.
*   `FluidX3D-master/`: C++ Core source code.
*   `bin/`: Compiled binaries and export data.
