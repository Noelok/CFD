import sys
import os
import time
import subprocess
import shutil
import math
import numpy as np
import trimesh
import trimesh.transformations as tf

# PyQt Imports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QGroupBox, 
                             QSpinBox, QDoubleSpinBox, QTabWidget, QSplitter, 
                             QFileDialog, QMessageBox, QCheckBox, QStackedWidget,
                             QGridLayout, QProgressDialog, QScrollArea, QFrame, QSlider)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QPalette, QColor, QWindow, QPainter, QLinearGradient, QBrush, QPen

# Windows Specific Imports
import win32gui
import win32con
import win32api

# Local Modules
import geometry
import visualizer

# --- CONFIGURATION ---
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))

POSSIBLE_PATHS = [
    os.path.join(CURRENT_DIR, "FluidX3D-master"),  # Same folder as script
    os.path.join(CURRENT_DIR, "..", "FluidX3D-master"),  # Parent folder
    r"D:\projects\vinci4d\CFD\FluidX3D-master",  # Your actual path
    r"D:\projects\FluidX3D-master",
    CURRENT_DIR
]

FLUIDX3D_ROOT = None
for p in POSSIBLE_PATHS:
    if os.path.exists(os.path.join(p, "src", "setup.cpp")):
        FLUIDX3D_ROOT = p
        break

if not FLUIDX3D_ROOT:
    FLUIDX3D_ROOT = r"D:\projects\FluidX3D-master" 
    print(f"⚠️ Could not detect FluidX3D. Defaulting to: {FLUIDX3D_ROOT}")
else:
    print(f"✅ FluidX3D detected at: {FLUIDX3D_ROOT}")

FLUIDX3D_EXE = os.path.join(FLUIDX3D_ROOT, "bin", "FluidX3D.exe")
FLUIDX3D_STL_DIR = os.path.join(FLUIDX3D_ROOT, "stl")

# Auto-Detect CUDA
CUDA_BASE = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
CUDA_INCLUDE = ""
CUDA_LIB = ""

if os.path.exists(CUDA_BASE):
    versions = [d for d in os.listdir(CUDA_BASE) if d.startswith("v")]
    if versions:
        latest_cuda = sorted(versions)[-1]
        CUDA_PATH = os.path.join(CUDA_BASE, latest_cuda)
        CUDA_INCLUDE = os.path.join(CUDA_PATH, "include")
        CUDA_LIB = os.path.join(CUDA_PATH, "lib", "x64", "OpenCL.lib")
        print(f"✅ CUDA detected: {latest_cuda}")

if not CUDA_INCLUDE:
    CUDA_INCLUDE = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\include"
    CUDA_LIB = r"C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\lib\x64\OpenCL.lib"

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

# --- C++ TEMPLATES (FIXED) ---

TEMPLATE_SETUP = """#include "setup.hpp"

void main_setup() {{
    // Simple flow simulation with custom STL geometry
    // Grid resolution: 256^3 cells
    const uint Nx = 256u;
    const uint Ny = 256u; 
    const uint Nz = 256u;
    
    // Reynolds number and flow velocity
    const float Re = 10000.0f;
    const float u_max = 0.075f;
    
    // Create LBM instance
    LBM lbm(Nx, Ny, Nz, units.nu_from_Re(Re, (float)Nx, u_max));
    
    // Load and voxelize the STL geometry
    const float size = 0.9f * (float)Nx;  // Scale mesh to 90% of domain
    const float3 center = float3(lbm.center().x, lbm.center().y, lbm.center().z);
    const float3x3 rotation = float3x3(float3(1, 0, 0), 0.0f);  // No rotation
    
    lbm.voxelize_stl(get_exe_path() + "../stl/{stl_filename}", center, rotation, size);
    
    // Set boundary conditions
    for(uint n=0u; n<lbm.get_N(); n++) {{
        uint x=0u, y=0u, z=0u;
        lbm.coordinates(n, x, y, z);
        
        // Set flow velocity in empty cells
        if(lbm.flags[n] != TYPE_S) {{
            lbm.u.y[n] = u_max;
        }}
        
        // Set domain boundaries to equilibrium BC
        if(x==0u || x==Nx-1u || y==0u || y==Ny-1u || z==0u || z==Nz-1u) {{
            lbm.flags[n] = TYPE_E;
        }}
    }}
    
    // Run the simulation (graphics are handled automatically if GRAPHICS is defined)
    lbm.run();
}}
"""

class CompileWorker(QThread):
    finished = pyqtSignal(bool, str)

    def __init__(self, parent=None):
        super().__init__(parent)

    def run(self):
        try:
            ok, msg = FluidX3DCompiler.compile()
            self.finished.emit(ok, msg)
        except Exception as e:
            self.finished.emit(False, str(e))

class FluidX3DCompiler:
    @staticmethod
    def backup_originals():
        setup_orig = os.path.join(FLUIDX3D_ROOT, "src", "setup.cpp")
        if os.path.exists(setup_orig) and not os.path.exists(setup_orig + ".bak"):
            shutil.copy(setup_orig, setup_orig + ".bak")

    @staticmethod
    def generate_files(params):
        try:
            # Define template directly here to avoid Python module caching issues
            template = """#include "setup.hpp"

void main_setup() {{ // Custom; required extensions in defines.hpp: FP16S, EQUILIBRIUM_BOUNDARIES, SUBGRID, INTERACTIVE_GRAPHICS or GRAPHICS
    // ################################################################## define simulation box size, viscosity and volume force ###################################################################
    const uint3 lbm_N = resolution(float3({asp_x}f, {asp_y}f, {asp_z}f), {vram}u); // input: simulation box aspect ratio and VRAM occupation in MB, output: grid resolution
    const float lbm_Re = {re}f;
    const float lbm_u = 0.075f;
    const ulong lbm_T = 108000ull;
    LBM lbm(lbm_N, 1u, 1u, 1u, units.nu_from_Re(lbm_Re, (float)lbm_N.x, lbm_u)); // run on 1x1x1 = 1 GPU
    // ###################################################################################### define geometry ######################################################################################
    const float size = {scale}f*lbm.size().z;
    const float3 center = float3(lbm.center().x + {off_x}f*lbm.size().x, lbm.center().y + {off_y}f*lbm.size().y, lbm.center().z + {off_z}f*lbm.size().z);
    const float3x3 rotation = float3x3(float3(1, 0, 0), radians({rot_x}f))*float3x3(float3(0, 1, 0), radians({rot_y}f))*float3x3(float3(0, 0, 1), radians({rot_z}f));
    Clock clock;
    lbm.voxelize_stl(get_exe_path()+"../stl/{stl_filename}", center, rotation, size);
    println(print_time(clock.stop()));
    const uint Nx=lbm.get_Nx(), Ny=lbm.get_Ny(), Nz=lbm.get_Nz(); parallel_for(lbm.get_N(), [&](ulong n) {{ uint x=0u, y=0u, z=0u; lbm.coordinates(n, x, y, z);
        if(lbm.flags[n]!=TYPE_S) lbm.u.x[n] = lbm_u;
        if(x==0u||x==Nx-1u||y==0u||y==Ny-1u||z==0u||z==Nz-1u) lbm.flags[n] = TYPE_E; // all non periodic
    }}); // ####################################################################### run simulation, export images and data ##########################################################################
    lbm.graphics.visualization_modes = VIS_FLAG_LATTICE|VIS_FLAG_SURFACE|VIS_Q_CRITERION;
    
    // FORCE CUSTOM LOOP (Removed preprocessor checks to ensure this runs)
    lbm.write_status();
    lbm.run(0u, lbm_T); // initialize simulation
    
    while(lbm.get_t()<=lbm_T && running) {{ // main simulation loop
        // Handle VTK Export Trigger (key_9)
        if(key_9) {{
            print_info("Export triggered by key_9. Saving snapshot...");
            string manual_path = R"({export_path_abs})";
            
            lbm.u.write_device_to_vtk(manual_path);
            lbm.rho.write_device_to_vtk(manual_path);
            lbm.flags.write_device_to_vtk(manual_path);
            #ifdef FORCE_FIELD
            lbm.F.write_device_to_vtk(manual_path);
            #endif
            
            key_9 = false; // Reset trigger
            print_info("Snapshot saved to " + manual_path);
        }}

        // Handle Pause locally (since we removed it from LBM::run)
        if(!key_P) {{
            sleep(0.016);
            continue;
        }}

        lbm.run(20u, lbm_T); // Run slightly larger batches for better efficiency
    }}
    lbm.write_status();
}} /**/
"""
            
            # Debug: Show first line of template
            lines = template.split('\n')
            if len(lines) > 4:
                print(f"🔍 Template line 5: {lines[4]}")
            
            setup_content = template.format(
                stl_filename=params['stl_filename'],
                vram=params['vram'],
                asp_x=params['asp_x'],
                asp_y=params['asp_y'],
                asp_z=params['asp_z'],
                scale=params['scale'],
                off_x=params['off_x'],
                off_y=params['off_y'],
                off_z=params['off_z'],
                rot_x=params['rot_x'],
                rot_y=params['rot_y'],
                rot_z=params['rot_z'],
                re=params['re'],
                export_path_abs=os.path.join(FLUIDX3D_ROOT, "bin", "export").replace("\\", "/") + "/"
            )
            
            setup_path = os.path.join(FLUIDX3D_ROOT, "src", "setup.cpp")
            
            # Force delete if exists
            if os.path.exists(setup_path):
                try:
                    os.remove(setup_path)
                    time.sleep(0.1)  # Give OS time to release file
                    print(f"🗑️ Deleted old setup.cpp")
                except Exception as e:
                    print(f"⚠️ Could not delete old setup.cpp: {e}")
            
            # Write new file
            with open(setup_path, "w", encoding='utf-8', newline='\n') as f:
                f.write(setup_content)
            
            time.sleep(0.1)  # Give OS time to flush
            
            # Verify it was written
            if os.path.exists(setup_path):
                with open(setup_path, 'r', encoding='utf-8') as f:
                    verify = f.read()
                    if "resolution(float3(" in verify:
                        print(f"✅ setup.cpp written with resolution() function!")
                        return True
                    else:
                        print(f"❌ setup.cpp written but doesn't contain resolution()!")
                        print("First 20 lines of what was written:")
                        for i, line in enumerate(verify.split('\n')[:20], 1):
                            print(f"   {i:2d}: {line}")
                        return False
            else:
                print(f"❌ setup.cpp file not found after write!")
                return False
            
        except Exception as e:
            print(f"❌ Gen Error: {e}")
            import traceback
            traceback.print_exc()
            return False

    @staticmethod
    def compile():
        # 1. Check for cl.exe directly
        cl_in_path = shutil.which("cl") is not None
        
        vcvars_path = None
        if not cl_in_path:
            # 2. Search for vcvars64.bat in standard locations
            print("⚠️ 'cl.exe' not in PATH. Searching for Visual Studio Build Tools...")
            pf_x86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
            pf = os.environ.get("ProgramFiles", r"C:\Program Files")
            
            # Common paths for VS 2022 and 2019
            search_paths = [
                os.path.join(pf, r"Microsoft Visual Studio\2022\Professional\VC\Auxiliary\Build\vcvars64.bat"),
                os.path.join(pf, r"Microsoft Visual Studio\2022\Community\VC\Auxiliary\Build\vcvars64.bat"),
                os.path.join(pf_x86, r"Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
                os.path.join(pf, r"Microsoft Visual Studio\2022\Enterprise\VC\Auxiliary\Build\vcvars64.bat"),
                os.path.join(pf_x86, r"Microsoft Visual Studio\2019\BuildTools\VC\Auxiliary\Build\vcvars64.bat"),
                os.path.join(pf, r"Microsoft Visual Studio\2019\Community\VC\Auxiliary\Build\vcvars64.bat"),
            ]
            
            for path in search_paths:
                if os.path.exists(path):
                    vcvars_path = path
                    print(f"✅ Found VS Build Tools: {vcvars_path}")
                    break
            
            if not vcvars_path:
                 return False, "❌ 'cl.exe' not found and Visual Studio Build Tools could not be auto-detected.\nPlease run in 'x64 Native Tools Command Prompt'."

        exe_path = os.path.join(FLUIDX3D_ROOT, "bin", "FluidX3D.exe")
        if os.path.exists(exe_path):
            try:
                os.remove(exe_path)
            except PermissionError:
                return False, "❌ Cannot remove old FluidX3D.exe. Close open simulations."

        bat_path = os.path.join(FLUIDX3D_ROOT, "compile_debug.bat")
        
        # Ensure bin directory exists
        bin_dir = os.path.join(FLUIDX3D_ROOT, "bin")
        if not os.path.exists(bin_dir):
            os.makedirs(bin_dir)

        compile_cmd = (
            f'@echo off\n'
            f'cd /d "{FLUIDX3D_ROOT}"\n'
            f'echo Compiling...\n'
            f'cl /std:c++17 /O2 /EHsc src/main.cpp src/lbm.cpp src/setup.cpp src/graphics.cpp '
            f'src/info.cpp src/kernel.cpp src/lodepng.cpp src/shapes.cpp '
            f'/Fe:bin\\FluidX3D.exe /Fobin\\ /I. /Isrc '
            f'/I "{CUDA_INCLUDE}" '
            f'"{CUDA_LIB}" '
            f'User32.lib Gdi32.lib Shell32.lib\n'
            f'if %errorlevel% neq 0 exit /b %errorlevel%\n'
            f'echo Build Success.\n'
        )
        
        with open(bat_path, "w") as f:
            f.write(compile_cmd)

        try:
            # If we need to set up the environment, wrap the call
            if not cl_in_path and vcvars_path:
                # Use call logic to setup env then run header
                cmd = f'call "{vcvars_path}" && "{bat_path}"'
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
            else:
                # Standard run 
                result = subprocess.run([bat_path], cwd=FLUIDX3D_ROOT, capture_output=True, text=True)
                
            if result.returncode != 0:
                return False, f"COMPILER LOG:\n{result.stdout}\n\nERROR LOG:\n{result.stderr}"
            if not os.path.exists(exe_path):
                return False, "Compiler finished but FluidX3D.exe was not created."
            return True, "Success"
        except Exception as e:
            return False, str(e)

class EmbeddedFluidX3D(QWidget):
    def __init__(self, exe_path, parent=None):
        super().__init__(parent)
        self.exe_path = exe_path
        self.process = None
        self.embedded_window = None
        self.hwnd = 0 
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_info = QLabel("Simulation View")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.layout.addWidget(self.lbl_info)

    def launch(self):
        if self.process: 
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                pass
            self.process = None
        
        if self.embedded_window:
            self.embedded_window.setParent(None)
            self.embedded_window = None
        
        self.lbl_info.setText("Launching Simulation...")
        QApplication.processEvents()
        
        # Check if exe exists
        if not os.path.exists(self.exe_path):
            QMessageBox.critical(self, "Error", f"FluidX3D.exe not found at:\n{self.exe_path}")
            self.lbl_info.setText("Error: Executable not found")
            return
        
        try:
            self.process = subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path))
            print(f"✅ Process started with PID: {self.process.pid}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Launch failed:\n{e}")
            self.lbl_info.setText("Launch Failed")
            return

        # Wait for window with shorter timeout
        self.hwnd = 0
        attempts = 0
        max_attempts = 30  # 6 seconds total
        
        def enum_window_callback(hwnd, windows):
            if win32gui.IsWindowVisible(hwnd):
                title = win32gui.GetWindowText(hwnd)
                if title:
                    windows.append((hwnd, title))
            return True
        
        while self.hwnd == 0 and attempts < max_attempts:
            time.sleep(0.2)
            
            # Get all visible windows
            windows = []
            win32gui.EnumWindows(enum_window_callback, windows)
            
            # Look for FluidX3D window (try various possible titles)
            for hwnd, title in windows:
                title_lower = title.lower()
                if 'fluidx3d' in title_lower or 'opencl' in title_lower or 'fluid' in title_lower:
                    print(f"Found window: '{title}' (hwnd: {hwnd})")
                    self.hwnd = hwnd
                    break
            
            attempts += 1
            QApplication.processEvents()
            
            # Check if process died
            if self.process.poll() is not None:
                self.lbl_info.setText("Simulation exited unexpectedly")
                QMessageBox.warning(self, "Error", "Simulation process terminated. Check console for errors.")
                return

        if self.hwnd == 0:
            self.lbl_info.setText("Window not found - Running in separate window")
            print("⚠️ Could not find FluidX3D window for embedding")
            print("Available windows:")
            windows = []
            win32gui.EnumWindows(enum_window_callback, windows)
            for hwnd, title in windows[:10]:
                print(f"  - {title}")
            QMessageBox.information(self, "Simulation Running", 
                "FluidX3D is running in a separate window.\n"
                "Press ESC in the simulation window to exit fullscreen mode.\n"
                "You can interact with it directly.")
            return

        self.embed_window(self.hwnd)
        self.lbl_info.setText("Simulation Running")

    def embed_window(self, hwnd):
        window = QWindow.fromWinId(hwnd)
        self.embedded_window = QWidget.createWindowContainer(window, self)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = style & ~win32con.WS_POPUP & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
        
        self.layout.addWidget(self.embedded_window)
        self.embedded_window.show()

    def closeEvent(self, event):
        if self.process:
            self.process.terminate()
        super().closeEvent(event)

class VolumeTransferPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(100)
        self.threshold = 0.2
        self.opacity = 0.5
        
    def set_params(self, t, o):
        self.threshold = t
        self.opacity = o
        self.update()
        
    def paintEvent(self, event):
        painter = QPainter(self)
        rect = self.rect()
        w = rect.width()
        h = rect.height()
        
        # 1. Background Gradient (Pseudo Scalar Field)
        grad = QLinearGradient(0, 0, w, 0)
        grad.setColorAt(0.0, QColor(0, 0, 128))   # Deep Blue
        grad.setColorAt(0.3, QColor(0, 128, 255)) # Cyan
        grad.setColorAt(0.6, QColor(255, 255, 0)) # Yellow
        grad.setColorAt(1.0, QColor(128, 0, 0))   # Red
        painter.fillRect(rect, grad)
        
        # 2. Transfer Function Line (Opacity)
        # Visualizes masking below threshold, then curving up scaled by opacity
        t_x = self.threshold * w
        
        pen = QPen(Qt.white, 3)
        painter.setPen(pen)
        
        # Draw base line (masked region)
        painter.drawLine(0, h, int(t_x), h)
        
        # Draw curve for remaining region
        pts = [0.1, 0.3, 0.6, 1.0] # Matches visualizer logic roughly
        pass_w = w - t_x
        
        if pass_w > 0:
            prev_x = t_x
            prev_y = h
            step_w = pass_w / len(pts)
            
            for val in pts:
                eff_val = val * self.opacity
                curr_x = prev_x + step_w
                curr_y = h - (eff_val * h)
                painter.drawLine(int(prev_x), int(prev_y), int(curr_x), int(curr_y))
                prev_x = curr_x
                prev_y = curr_y

class WindTunnelApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FluidSim")
        self.resize(1700, 1000)
        self.setup_dark_theme()
        
        FluidX3DCompiler.backup_originals()
        self.mesh_data = None
        self.xy_poly = None
        self.zs_polys = []
        self.simulation_started = False
        self.settings_changed = False
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- LEFT: 3D VIEWS & RESULTS ---
        container_3d = QWidget()
        l3d = QVBoxLayout(container_3d)
        l3d.setContentsMargins(0,0,0,0)
        self.view_tabs = QTabWidget()
        
        # Tab 1: Mesh Preview
        self.vis = visualizer.Visualizer3D()
        self.view_tabs.addTab(self.vis, "🔷 Mesh Preview")
        
        # Tab 2: Simulation
        self.sim_runner = EmbeddedFluidX3D(FLUIDX3D_EXE)
        self.view_tabs.addTab(self.sim_runner, "🌊 FluidX3D Simulation")
        
        # Tab 3: Results
        self.results_view = visualizer.ResultsViewer()
        self.view_tabs.addTab(self.results_view, "📊 Results Analysis")
        
        l3d.addWidget(self.view_tabs)
        splitter.addWidget(container_3d)
        
        # --- RIGHT: SIDEBAR CONTROLS ---
        sidebar = QWidget()
        l_sidebar = QVBoxLayout(sidebar)
        l_sidebar.setContentsMargins(0, 0, 0, 0)
        
        # Scroll Area for Controls
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.controls_stack = QStackedWidget()
        self.controls_stack.setMinimumWidth(450)
        self.controls_stack.setMaximumWidth(500)
        
        # Page 1: Design
        self.page_design = QWidget()
        self.setup_design_ui(self.page_design)
        self.controls_stack.addWidget(self.page_design)
        
        # Page 2: Simulation
        self.page_sim = QWidget()
        self.setup_sim_ui(self.page_sim)
        self.controls_stack.addWidget(self.page_sim)
        
        # Page 3: Results Controls
        self.page_results = QWidget()
        l_res = QVBoxLayout(self.page_results)
        l_res.setSpacing(15)
        
        l_res.addWidget(QLabel("<h3>Results Analysis</h3>"))
        self.lbl_res_hint = QLabel("Select 'Slice' or 'Volume' mode in the view to enable controls.")
        self.lbl_res_hint.setWordWrap(True)
        l_res.addWidget(self.lbl_res_hint)
        
        # --- Slice Controls Group ---
        self.grp_slice = QGroupBox("Slice Planes Position")
        g_layout = QGridLayout()
        g_layout.setVerticalSpacing(10)
        
        self.sl_res_x = QSlider(Qt.Horizontal); self.sl_res_x.setRange(0, 1000); self.sl_res_x.setValue(500)
        self.sl_res_y = QSlider(Qt.Horizontal); self.sl_res_y.setRange(0, 1000); self.sl_res_y.setValue(500)
        self.sl_res_z = QSlider(Qt.Horizontal); self.sl_res_z.setRange(0, 1000); self.sl_res_z.setValue(500)
        
        g_layout.addWidget(QLabel("X Plane"), 0, 0); g_layout.addWidget(self.sl_res_x, 0, 1)
        g_layout.addWidget(QLabel("Y Plane"), 1, 0); g_layout.addWidget(self.sl_res_y, 1, 1)
        g_layout.addWidget(QLabel("Z Plane"), 2, 0); g_layout.addWidget(self.sl_res_z, 2, 1)
        
        self.btn_res_cut = QPushButton("✂️ Cut Volume (Calculated)")
        self.btn_res_cut.clicked.connect(self.apply_res_cut)
        self.btn_res_cut.setStyleSheet("background-color: #d94a4a; color: white; padding: 8px; font-weight: bold; margin-top: 10px;")
        g_layout.addWidget(self.btn_res_cut, 3, 0, 1, 2)
        
        self.grp_slice.setLayout(g_layout)
        l_res.addWidget(self.grp_slice)
        
        # --- Volume Controls Group ---
        self.grp_vol = QGroupBox("Volume Rendering")
        v_layout = QVBoxLayout() # Changed to VBox to stack Preview + Grid + Button
        v_layout.setSpacing(10)
        
        # Preview Widget (Gradient + Transfer Function)
        self.vol_preview = VolumeTransferPreview()
        v_layout.addWidget(self.vol_preview)
        
        # Sliders Grid
        grid_vol = QGridLayout()
        self.sl_vol_op = QSlider(Qt.Horizontal); self.sl_vol_op.setRange(0, 100); self.sl_vol_op.setValue(50)
        grid_vol.addWidget(QLabel("Opacity:"), 0, 0); grid_vol.addWidget(self.sl_vol_op, 0, 1)
        
        self.sl_vol_th = QSlider(Qt.Horizontal); self.sl_vol_th.setRange(0, 100); self.sl_vol_th.setValue(20)
        grid_vol.addWidget(QLabel("Threshold:"), 1, 0); grid_vol.addWidget(self.sl_vol_th, 1, 1)
        v_layout.addLayout(grid_vol)
        
        # Apply Button
        self.btn_vol_apply = QPushButton("🔄 Apply Adjustments")
        self.btn_vol_apply.clicked.connect(self.apply_vol_params)
        self.btn_vol_apply.setStyleSheet("background-color: #2da44e; color: white; padding: 8px; font-weight: bold;")
        v_layout.addWidget(self.btn_vol_apply)
        
        self.grp_vol.setLayout(v_layout)
        l_res.addWidget(self.grp_vol)
        
        l_res.addStretch()
        self.controls_stack.addWidget(self.page_results)
        
        # Connect Sliders
        self.sl_res_x.valueChanged.connect(self.update_res_preview)
        self.sl_res_y.valueChanged.connect(self.update_res_preview)
        self.sl_res_z.valueChanged.connect(self.update_res_preview)
        
        self.sl_vol_op.valueChanged.connect(self.update_vol_preview_ui)
        self.sl_vol_th.valueChanged.connect(self.update_vol_preview_ui)
        
        # Connect Mode Change
        self.results_view.btn_surf.clicked.connect(self.update_results_ui_state)
        self.results_view.btn_slice.clicked.connect(self.update_results_ui_state)
        self.results_view.btn_vol.clicked.connect(self.update_results_ui_state)
        
        # Init state
        self.grp_slice.setVisible(False)
        self.grp_vol.setVisible(False)
        
        scroll.setWidget(self.controls_stack)
        l_sidebar.addWidget(scroll)
        
        # --- GLOBAL FOOTER (Exit Button) ---
        f_frame = QFrame()
        f_frame.setStyleSheet("background-color: #2b2b2b; border-top: 1px solid #444;")
        l_footer = QVBoxLayout(f_frame)
        self.btn_exit = QPushButton("❌ Exit Application")
        self.btn_exit.setStyleSheet("background-color: #550000; color: white; padding: 5px; border-radius: 3px;")
        self.btn_exit.clicked.connect(self.close)
        l_footer.addWidget(self.btn_exit)
        l_sidebar.addWidget(f_frame)
        
        splitter.addWidget(sidebar)
        splitter.setSizes([1200, 500])
        
        self.view_tabs.currentChanged.connect(self.on_tab_changed)

        # --- KEYBOARD POLLING REMOVED (Legacy Status UI) ---


    # poll_keys removed


    def update_preview_transform(self):
        """Updates the visualizer mesh transform based on current UI settings."""
        if not hasattr(self, 'vis'): return
        
        # Get UI values
        scale = self.sb_scale.value()
        off_x = self.sb_off_x.value()
        off_y = self.sb_off_y.value()
        off_z = self.sb_off_z.value()
        rot_x = self.sb_rot_x.value()
        rot_y = self.sb_rot_y.value()
        rot_z = self.sb_rot_z.value()
        
        # Domain Dimensions (Relative to Z=200 base unit or similar)
        # We need consistent visualization units.
        base_z = 200.0 
        dx = self.sb_ax.value() * base_z
        dy = self.sb_ay.value() * base_z
        dz = self.sb_az.value() * base_z
        
        # Update Domain Box
        self.vis.draw_domain_box(dx, dy, dz, center=(0,0,0))
        
        # Update Mesh Transform
        self.vis.update_transform(scale, off_x, off_y, off_z, rot_x, rot_y, rot_z, (dx, dy, dz))

    # update_status_ui removed


    def setup_dark_theme(self):
        app = QApplication.instance()
        app.setStyle("Fusion")
        
        # Force cursor visibility
        app.setOverrideCursor(Qt.ArrowCursor)
        app.restoreOverrideCursor()
        
        # Set stylesheet to fix cursor visibility and styling
        app.setStyleSheet("""
            * {
                color: white;
            }
            QSpinBox, QDoubleSpinBox, QLineEdit {
                background-color: #3a3a3a;
                border: 1px solid #555;
                padding: 5px;
                color: white;
                selection-background-color: #4a90d9;
                selection-color: white;
            }
            QSpinBox:hover, QDoubleSpinBox:hover, QLineEdit:hover {
                border: 1px solid #4a90d9;
                background-color: #454545;
            }
            QSpinBox:focus, QDoubleSpinBox:focus, QLineEdit:focus {
                border: 2px solid #4a90d9;
                background-color: #2a2a2a;
            }

            QSpinBox::up-button, QDoubleSpinBox::up-button {
                subcontrol-origin: border;
                subcontrol-position: top right;
                width: 16px;
                background: #555;
                border-left: 1px solid #333;
                border-bottom: 1px solid #333;
            }
            QSpinBox::down-button, QDoubleSpinBox::down-button {
                subcontrol-origin: border;
                subcontrol-position: bottom right;
                width: 16px;
                background: #555;
                border-left: 1px solid #333;
                border-top: 1px solid #333;
            }
            QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
            QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
                background: #4a90d9;
            }
            QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
                width: 7px;
                height: 7px;
                background: white; /* Fallback if no image */
            }
            QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
                width: 7px;
                height: 7px;
                background: white;
            }
        """)
        
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.white)
        app.setPalette(palette)

    def setup_design_ui(self, parent):
        layout = QVBoxLayout(parent)
        g1 = QGroupBox("1. Geometry Settings")
        l1 = QVBoxLayout(g1)
        h1 = QHBoxLayout()
        self.sb_side = QDoubleSpinBox()
        self.sb_side.setRange(50, 2000)
        self.sb_side.setValue(200.0)
        h1.addWidget(QLabel("Size:"))
        h1.addWidget(self.sb_side)
        l1.addLayout(h1)
        h2 = QHBoxLayout()
        self.sb_seeds = QSpinBox()
        self.sb_seeds.setRange(10, 5000)
        self.sb_seeds.setValue(150)
        h2.addWidget(QLabel("Seeds:"))
        h2.addWidget(self.sb_seeds)
        l1.addLayout(h2)
        h3 = QHBoxLayout()
        self.sb_layers = QSpinBox()
        self.sb_layers.setRange(1, 10)
        self.sb_layers.setValue(2)
        h3.addWidget(QLabel("Layers:"))
        h3.addWidget(self.sb_layers)
        l1.addLayout(h3)
        btn_gen = QPushButton("Generate Geometry")
        btn_gen.setStyleSheet("background-color: #00ADB5; color: black; font-weight: bold; padding: 10px;")
        btn_gen.clicked.connect(self.generate_geometry)
        l1.addWidget(btn_gen)
        layout.addWidget(g1)
        
        g_tabs = QGroupBox("2. Layers Preview")
        lt = QVBoxLayout(g_tabs)
        self.layer_tabs = QTabWidget()
        self.layer_tabs.setMinimumHeight(200)
        lt.addWidget(self.layer_tabs)
        self.btn_save_svg = QPushButton("💾 Save SVGs")
        self.btn_save_svg.setEnabled(False)
        self.btn_save_svg.clicked.connect(self.save_svg_data)
        lt.addWidget(self.btn_save_svg)
        layout.addWidget(g_tabs)
        
        g_io = QGroupBox("3. Mesh Import/Export")
        l_io = QVBoxLayout(g_io)
        h_io = QHBoxLayout()
        btn_load = QPushButton("📂 Load STL")
        btn_load.clicked.connect(self.load_custom_stl)
        h_io.addWidget(btn_load)
        self.btn_export_mesh = QPushButton("💾 Export Mesh")
        self.btn_export_mesh.setEnabled(False)
        self.btn_export_mesh.clicked.connect(self.export_mesh_user)
        h_io.addWidget(self.btn_export_mesh)
        l_io.addLayout(h_io)
        layout.addWidget(g_io)
        
        # --- NEW: Shared Geometry Transform Controls for Preview ---
        g_geo = QGroupBox("4. Mesh Transform (Preview)")
        l_geo = QVBoxLayout(g_geo)
        
        # Scale
        h_scale = QHBoxLayout()
        self.sb_scale = QDoubleSpinBox()
        self.sb_scale.setRange(0.1, 5.0)
        self.sb_scale.setValue(0.5)
        self.sb_scale.setSingleStep(0.05)
        self.sb_scale.valueChanged.connect(self.update_preview_transform) # Connect to preview update
        h_scale.addWidget(QLabel("Mesh Scale:"))
        h_scale.addWidget(self.sb_scale)
        l_geo.addLayout(h_scale)
        
        # Offset
        h_off = QHBoxLayout()
        h_off.addWidget(QLabel("Offset (X/Y/Z):"))
        self.sb_off_x = QDoubleSpinBox()
        self.sb_off_x.setRange(-1.0, 1.0)
        self.sb_off_x.setValue(-0.25)
        self.sb_off_x.setSingleStep(0.05)
        self.sb_off_x.valueChanged.connect(self.update_preview_transform)
        self.sb_off_y = QDoubleSpinBox()
        self.sb_off_y.setRange(-1.0, 1.0)
        self.sb_off_y.setValue(0.0)
        self.sb_off_y.setSingleStep(0.05)
        self.sb_off_y.valueChanged.connect(self.update_preview_transform)
        self.sb_off_z = QDoubleSpinBox()
        self.sb_off_z.setRange(-1.0, 1.0)
        self.sb_off_z.setValue(0.0)
        self.sb_off_z.setSingleStep(0.05)
        self.sb_off_z.valueChanged.connect(self.update_preview_transform)
        h_off.addWidget(self.sb_off_x)
        h_off.addWidget(self.sb_off_y)
        h_off.addWidget(self.sb_off_z)
        l_geo.addLayout(h_off)
        
        # Rotation
        h_rot = QHBoxLayout()
        h_rot.addWidget(QLabel("Rotation (°):"))
        self.sb_rot_x = QDoubleSpinBox()
        self.sb_rot_x.setRange(-360, 360)
        self.sb_rot_x.setValue(0.0)
        self.sb_rot_x.valueChanged.connect(self.update_preview_transform)
        self.sb_rot_y = QDoubleSpinBox()
        self.sb_rot_y.setRange(-360, 360)
        self.sb_rot_y.setValue(0.0)
        self.sb_rot_y.valueChanged.connect(self.update_preview_transform)
        self.sb_rot_z = QDoubleSpinBox()
        self.sb_rot_z.setRange(-360, 360)
        self.sb_rot_z.setValue(0.0)
        self.sb_rot_z.valueChanged.connect(self.update_preview_transform)
        h_rot.addWidget(self.sb_rot_x)
        h_rot.addWidget(self.sb_rot_y)
        h_rot.addWidget(self.sb_rot_z)
        l_geo.addLayout(h_rot)
        
        layout.addWidget(g_geo)
        # -------------------------------------------------------
        
        layout.addStretch()

    def setup_sim_ui(self, parent):
        layout = QVBoxLayout(parent)
        # Title removed to match Mesh Preview tab style
        # layout.addWidget(lbl_title)
        
        g_grid = QGroupBox("1. Grid & Memory")
        l_grid = QVBoxLayout(g_grid)
        h_vram = QHBoxLayout()
        self.sb_vram = QSpinBox()
        self.sb_vram.setRange(500, 24000)
        self.sb_vram.setValue(3000)
        self.sb_vram.setSingleStep(500)
        self.sb_vram.valueChanged.connect(self.on_setting_changed)
        h_vram.addWidget(QLabel("VRAM (MB):"))
        h_vram.addWidget(self.sb_vram)
        l_grid.addLayout(h_vram)
        h_asp = QHBoxLayout()
        h_asp.addWidget(QLabel("Aspect Ratio (X:Y:Z):"))
        self.sb_ax = QDoubleSpinBox()
        self.sb_ax.setRange(0.1, 10.0)
        self.sb_ax.setValue(2.0)
        self.sb_ax.setSingleStep(0.1)
        self.sb_ax.valueChanged.connect(self.on_setting_changed)
        self.sb_ay = QDoubleSpinBox()
        self.sb_ay.setRange(0.1, 10.0)
        self.sb_ay.setValue(1.0)
        self.sb_ay.setSingleStep(0.1)
        self.sb_ay.valueChanged.connect(self.on_setting_changed)
        self.sb_az = QDoubleSpinBox()
        self.sb_az.setRange(0.1, 10.0)
        self.sb_az.setValue(1.0)
        self.sb_az.setSingleStep(0.1)
        self.sb_az.valueChanged.connect(self.on_setting_changed)
        h_asp.addWidget(self.sb_ax)
        h_asp.addWidget(self.sb_ay)
        h_asp.addWidget(self.sb_az)
        l_grid.addLayout(h_asp)
        layout.addWidget(g_grid)
        
        # Geometry/Transform controls moved to Mesh Preview tab for interactive adjustment
        
        g_info = QGroupBox("2. Setup Info")
        l_info = QVBoxLayout(g_info)
        l_info.addWidget(QLabel("ℹ️ Use 'Mesh Preview' tab to adjust Scale/Rotation/Offset"))
        layout.addWidget(g_info)
         
        
        
        g_vis = QGroupBox("3. Visualization & Controls (Shortcut Keys)")
        # Style removed to match Steps 1 & 2
        l_vis = QGridLayout(g_vis)
        
        
        # Helper to create buttons
        def mk_btn(text, cmd, checkable=True):
            b = QPushButton(text)
            b.setCheckable(checkable)
            b.setStyleSheet("""
                QPushButton { background-color: #444; color: #BBB; padding: 8px; border: 1px solid #555; border-radius: 4px; }
                QPushButton:checked { background-color: #4a90d9; color: white; border: 1px solid #6ab0f9; }
                QPushButton:hover { background-color: #555; }
                QPushButton:pressed { background-color: #333; }
            """)
            b.clicked.connect(lambda: self.send_key(cmd))
            return b

        # Row 0: Help & Display Mode
        l_vis.addWidget(mk_btn("❓ Show/Hide Help (H)", 0x48), 0, 0)
        l_vis.addWidget(mk_btn("🧊 Wireframe/Solid (1)", 0x31), 0, 1)
        
        # Row 1: Fields
        l_vis.addWidget(mk_btn("🌊 Velocity Field (2)", 0x32), 1, 0)
        l_vis.addWidget(mk_btn("➰ Streamlines (3)", 0x33), 1, 1)
        
        # Row 2: Advanced
        l_vis.addWidget(mk_btn("🌪️ Q-Criterion (4)", 0x34), 2, 0)
        l_vis.addWidget(mk_btn("🔪 Slice Mode (T)", 0x54), 2, 1)
        
        # Row 3: Interactions
        l_vis.addWidget(mk_btn("🔍 Field Mode (Z)", 0x5A), 3, 0)
        
        # Row 4: Slice Movement (Not Checkable, triggers action)
        b_q = mk_btn("◀️ Move Slice (Q)", 0x51, False)
        l_vis.addWidget(b_q, 4, 0)
        
        b_e = mk_btn("▶️ Move Slice (E)", 0x45, False)
        l_vis.addWidget(b_e, 4, 1) 
        # Actually E is usually export unless overridden.
        # User requested "Move Slice right or up or forward (E)".
        # FluidX3D default key 'E' is indeed Move Slice Forward in Slice Mode.
        # BUT 'E' is ALSO often Export. 
        # Wait, usually FluidX3D uses 'F' for Export? Or 'E'?
        # Looking at help text in previous steps: "Q/E Move Slice".
        # So 'E' is Move Slice.
        # Then how do we Export?
        # The user's previous "Export Button" logic sent 'E' (0x45).
        # IF E is Move Slice, then the Export button was just Moving Slice!
        # That explains why "VTK data export seems to be stucked".
        # FluidX3D uses 'F5' or something else for screenshot/export?
        # Or maybe 'P' writes data?
        # Let's check `setup.cpp` or default keys.
        # Usually 'F' or 'O' or 'P'.
        
        # IMPORTANT: 'E' is definitely Move Slice if Q is the other pair.
        # So the Export logic was WRONG.
        # We need to find the correct key for VTK Export.
        # In FluidX3D source: `if(key(0x45))` -> Move Slice.
        # VTK Export is often manual or automated in loop.
        # Is there a key for VTK export?
        # Often it's 'O' (Output) or 'F' (File).
        # Without source code for `graphics.cpp` handling keys, we guess.
        # Wait, the user previously had `chk_export` which used `setup.cpp` definition `p.output = true`.
        # This exports periodically?
        # If we want a Snapshot, we might need a specific key.
        # Assuming we don't know the key, maybe we can't trigger it via Key Press unless we add it to C++.
        # BUT, if `setup.cpp` has `p.output = true`, it writes files every `p.output_frequency`.
        # To force one NOW?
        # Main.cpp loop usually checks keys.
        # If I can't find a key, I might need to re-enable the checkbox to "Enable Timer Output".
        
        # Re-reading user request: "keep the export button but add the option to choose location".
        # User says "VTK data export seems to be stucked".
        # Because 'E' was just moving the slice!
        
        # Let's look for a standard FluidX3D key map.
        # Or look at `graphics.cpp` if I viewed it.
        # I viewed `graphics.cpp` in step 345? YES.
        # Let's use `grep_search` to find export key in `graphics.cpp` or `main.cpp`.
        
        layout.addWidget(g_vis)
        
        
        # Toggle & Export
        h_ctrl = QHBoxLayout()
        self.btn_start = QPushButton("▶ Start Simulation (P)") # Renamed for clarity in toggle logic
        self.btn_start.setStyleSheet("""
            QPushButton { background-color: #2da44e; color: white; padding: 12px; font-weight: bold; border-radius: 6px; }
            QPushButton:hover { background-color: #2c974b; }
        """)
        self.btn_start.clicked.connect(self.toggle_simulation)
        h_ctrl.addWidget(self.btn_start)
        
        self.btn_export_vtk = QPushButton("💾 Export VTK")
        self.btn_export_vtk.setStyleSheet("""
            QPushButton { background-color: #2a5a8a; padding: 10px; font-weight: bold; border-radius: 4px; }
            QPushButton:hover { background-color: #3b7bc4; }
            QPushButton:disabled { background-color: #444; color: #888; }
        """)
        self.btn_export_vtk.clicked.connect(self.export_snapshot_as)
        # Initially enabled/disabled? Simulation starts paused, so enabled.
        # But we default simulation_running to False in init usually? we should check.
        # Assuming starts paused:
        self.btn_export_vtk.setEnabled(True)
        h_ctrl.addWidget(self.btn_export_vtk)
        
        layout.addLayout(h_ctrl)

        self.btn_build_run = QPushButton("🛠 Restart Simulation")
        self.btn_build_run.setStyleSheet("""
            QPushButton { background-color: #555; color: #999; font-weight: bold; padding: 15px; font-size: 14px; border-radius: 5px; }
            QPushButton:enabled { background-color: #e07a1f; color: white; }
            QPushButton:enabled:hover { background-color: #ff9d4d; }
        """)
        self.btn_build_run.clicked.connect(self.on_build_and_run)
        self.btn_build_run.setEnabled(False)
        layout.addWidget(self.btn_build_run)
        layout.addStretch()

    def send_key(self, vk_code):
        if not self.sim_runner.hwnd: return
        win32api.PostMessage(self.sim_runner.hwnd, win32con.WM_KEYDOWN, vk_code, 0)
        time.sleep(0.05)
        win32api.PostMessage(self.sim_runner.hwnd, win32con.WM_KEYUP, vk_code, 0)
    
    def toggle_simulation(self):
        """Toggles simulation start/pause and updates UI"""
        self.send_key(0x50) # 'P' key
        # Initialize if missing
        if not hasattr(self, 'simulation_running'):
             self.simulation_running = False
             
        self.simulation_running = not self.simulation_running
        
        # Update Start Button Style
        if self.simulation_running:
            self.btn_start.setText("⏸ Pause Simulation (P)")
            self.btn_start.setStyleSheet("""
                QPushButton { background-color: #d94a4a; color: white; padding: 12px; font-weight: bold; border-radius: 6px; }
                QPushButton:hover { background-color: #ff6666; }
            """)
            self.btn_export_vtk.setEnabled(False)
            self.btn_export_vtk.setToolTip("Pause simulation to export.")
        else:
            self.btn_start.setText("▶ Start Simulation (P)")
            self.btn_start.setStyleSheet("""
                QPushButton { background-color: #2da44e; color: white; padding: 12px; font-weight: bold; border-radius: 6px; }
                QPushButton:hover { background-color: #2c974b; }
            """)
            self.btn_export_vtk.setEnabled(True)
            self.btn_export_vtk.setToolTip("Export current state to VTK.")

    def export_snapshot_as(self):
        # Ensure simulation is paused? Users requested export only when stops.
        if hasattr(self, 'simulation_running') and self.simulation_running:
            QMessageBox.warning(self, "Simulation Running", "Please pause the simulation (P) before exporting.")
            return

        selected_dir = QFileDialog.getExistingDirectory(self, "Select Export Folder", "")
        if not selected_dir:
            return

        # Trigger Export in C++
        self.send_key(0x39) # Send '9' (The custom key we set in setup.cpp)
        
        # Robust Logic
        data_dir = os.path.join(FLUIDX3D_ROOT, "bin", "export")
        if not os.path.exists(data_dir): os.makedirs(data_dir)

        try: existing = set(os.listdir(data_dir))
        except: existing = set()
        
        from PyQt5.QtWidgets import QProgressDialog
        pd = QProgressDialog("Waiting for simulation to write files...", "Cancel", 0, 100, self)
        pd.setWindowModality(Qt.WindowModal)
        pd.setMinimumDuration(0)
        pd.setValue(10)
        
        # 1. New Files
        found_files = []
        start_t = time.time()
        while (time.time() - start_t) < 45.0:
            QApplication.processEvents()
            if pd.wasCanceled(): return
            time.sleep(0.5)
            try:
                current = set(os.listdir(data_dir))
                new = current - existing
                candidates = [os.path.join(data_dir, f) for f in new if f.endswith(('.vtk', '.bin'))]
                if candidates:
                    found_files = candidates
                    break
            except: pass
            
        if not found_files:
            pd.close()
            QMessageBox.warning(self, "Timeout", "No files generated after 45s.")
            return

        pd.setLabelText("Stabilizing file sizes...")
        
        # 2. Stability
        stable_cnt = 0
        last_sz = {f: -1 for f in found_files}
        
        while stable_cnt < 6:
            QApplication.processEvents()
            time.sleep(0.5)
            if pd.wasCanceled(): return
            
            # Dynamic Re-scan: Catch rho/flags if they appear later
            try:
                curr_scan = set(os.listdir(data_dir))
                new_scan = curr_scan - existing
                candidates_scan = [os.path.join(data_dir, f) for f in new_scan if f.endswith(('.vtk', '.bin'))]
                
                for nf in candidates_scan:
                    if nf not in found_files:
                        found_files.append(nf)
                        last_sz[nf] = -1
                        stable_cnt = 0 # Reset to ensure we wait for this new file
            except: pass

            all_stable = True
            for f in found_files:
                try: 
                    if not os.path.exists(f): 
                        all_stable = False; break
                    s = os.path.getsize(f)
                    if f not in last_sz or last_sz[f] != s:
                        last_sz[f] = s; all_stable = False
                except: all_stable = False
            
            if all_stable and all(v > 0 for v in last_sz.values()): stable_cnt += 1
            else: stable_cnt = 0

        # 3. Safety
        pd.setLabelText("Finalizing buffer...")
        time.sleep(3.0)
        
        # 4. Copy
        import shutil
        moved = 0
        for src in found_files:
            fname = os.path.basename(src)
            dst = os.path.join(selected_dir, fname)
            pd.setLabelText(f"Copying {fname}...")
            
            copied = False
            for i in range(60):
                try:
                    # Method A: Python Shutil
                    try:
                        with open(src, 'rb'): pass
                        shutil.copy2(src, dst)
                        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                            copied = True; break
                    except: 
                        pass

                    # Method B: Windows System Copy (Fallback for locks)
                    if not copied:
                        import subprocess
                        # copy /Y source dest
                        cmd = f'copy /Y "{src}" "{dst}"' 
                        res = subprocess.run(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        if res.returncode == 0 and os.path.exists(dst):
                             copied = True; break
                except: pass
                
                time.sleep(1.0); QApplication.processEvents()
                if pd.wasCanceled(): break
            
            if copied: 
                moved += 1
                try: os.remove(src) # Delete source (Move)
                except: pass
            else: print(f"Failed {fname}")
            
        pd.close()
        if moved>0: QMessageBox.information(self, "Success", f"Saved {moved} files.")
        else: QMessageBox.critical(self, "Error", "Failed to copy (File Lock).")

    
    def on_setting_changed(self):
        """Called when any simulation setting changes"""
        if self.simulation_started:
            self.settings_changed = True
            self.btn_build_run.setEnabled(True)



    def generate_geometry(self):
        self.layer_tabs.clear()
        QApplication.processEvents()
        try:
            side, seeds, layers = self.sb_side.value(), self.sb_seeds.value(), self.sb_layers.value()
            design = geometry.FluidicDesign(side)
            design.initialize_points(seeds)
            self.xy_poly = design.create_xy_flow_pattern(4.0)
            self.zs_polys = [design.create_z_pillar_pattern(3.0) for _ in range(layers)]
            
            full_area = side * side
            
            xy_area = self.xy_poly.area
            solid_pct_xy = ((full_area - xy_area) / full_area) * 100.0
            
            c1 = visualizer.PreviewCanvas()
            c1.plot(self.xy_poly, "XY", invert=True)
            self.layer_tabs.addTab(c1, f"XY ({solid_pct_xy:.1f}% Solid)")
            
            for i, p in enumerate(self.zs_polys):
                solid_pct_z = (p.area / full_area) * 100.0
                c = visualizer.PreviewCanvas()
                c.plot(p, f"Z{i+1}", invert=False)
                self.layer_tabs.addTab(c, f"Z{i+1} ({solid_pct_z:.1f}% Solid)")
            
            mesh = geometry.generate_full_mesh(self.xy_poly, self.zs_polys, side)
            if mesh:
                self.update_mesh(mesh)
        except Exception as e:
            print(e)

    def load_custom_stl(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load STL", "", "STL (*.stl)")
        if path:
            try:
                mesh = trimesh.load(path)
                if isinstance(mesh, trimesh.Scene):
                    if len(mesh.geometry) == 0:
                        return
                    mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
                self.update_mesh(mesh)
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def update_mesh(self, mesh):
        self.mesh_data = mesh
        min_bound, max_bound = mesh.bounds
        center_offset = (min_bound + max_bound) / 2.0
        mesh.apply_translation(-center_offset)
        self.vis.set_mesh(mesh.vertices, mesh.faces)
        
        self.btn_save_svg.setEnabled(True)
        self.btn_export_mesh.setEnabled(True)
        self.btn_build_run.setEnabled(True)

    def on_build_and_run(self):
        if self.sim_runner.process:
            self.sim_runner.process.terminate()
            self.sim_runner.process.wait()
            self.sim_runner.process = None
            time.sleep(1.0)

        if not self.mesh_data:
            QMessageBox.warning(self, "No Mesh", "Please generate or load a mesh first!")
            return
        
        # Prepare mesh for export (Center it so 0,0,0 is the middle)
        sim_mesh = self.mesh_data.copy()
        min_bound, max_bound = sim_mesh.bounds
        center_offset = (min_bound + max_bound) / 2.0
        sim_mesh.apply_translation(-center_offset)
        
        # We do NOT apply rotation/scale here in Python. 
        # C++ handles Rotation and Scaling relative to this centered mesh.
        # This matches the Visualizer logic where we center the mesh at 0,0,0.

        if os.path.exists(FLUIDX3D_STL_DIR):
            for f in os.listdir(FLUIDX3D_STL_DIR):
                if f.startswith("sim_geometry_") or f.endswith(".bin"):
                    try:
                        os.remove(os.path.join(FLUIDX3D_STL_DIR, f))
                    except:
                        pass
        else:
            os.makedirs(FLUIDX3D_STL_DIR)

        unique_id = int(time.time())
        stl_filename = f"sim_geometry_{unique_id}.stl"
        full_stl_path = os.path.join(FLUIDX3D_STL_DIR, stl_filename)
        sim_mesh.export(full_stl_path)
        
        print(f"✅ STL exported to: {full_stl_path}")
        print(f"   File exists: {os.path.exists(full_stl_path)}")

        params = {
            'stl_filename': stl_filename,
            'vram': self.sb_vram.value(),
            'asp_x': self.sb_ax.value(), 
            'asp_y': self.sb_ay.value(), 
            'asp_z': self.sb_az.value(),
            'scale': self.sb_scale.value(),
            'off_x': self.sb_off_x.value(), 
            'off_y': self.sb_off_y.value(), 
            'off_z': self.sb_off_z.value(),
            'rot_x': self.sb_rot_x.value(), 
            'rot_y': self.sb_rot_y.value(), 
            'rot_z': self.sb_rot_z.value(),
            're': 10000000.0,
            'force_z': -0.0005,
            'vol_force': True,
            'particles': False,
            'export_data': False # Manual export only
        }

        QApplication.processEvents()
        
        print("📝 Writing setup.cpp...")
        print(f"   Domain aspect ratio: {params['asp_x']}:{params['asp_y']}:{params['asp_z']}")
        print(f"   VRAM: {params['vram']} MB")
        print(f"   Mesh scale: {params['scale']}")
        print(f"   Offset: ({params['off_x']}, {params['off_y']}, {params['off_z']})")
        print(f"   Rotation: ({params['rot_x']}, {params['rot_y']}, {params['rot_z']})")
        print(f"   Reynolds: {params['re']}")
        
        if not FluidX3DCompiler.generate_files(params): 
            QMessageBox.critical(self, "Error", "Failed to write setup.cpp")
            return
        
        print("🔨 Compiling FluidX3D...")
        QApplication.processEvents()
        
        # Verify setup.cpp exists and show its content
        setup_path = os.path.join(FLUIDX3D_ROOT, "src", "setup.cpp")
        if os.path.exists(setup_path):
            with open(setup_path, 'r') as f:
                content = f.read()
                # Check for our custom code
                if f"resolution(float3({params['asp_x']}f, {params['asp_y']}f, {params['asp_z']}f)" in content:
                    print(f"✅ Verified setup.cpp contains correct aspect ratio {params['asp_x']}:{params['asp_y']}:{params['asp_z']}")
                else:
                    print(f"⚠️ WARNING: setup.cpp doesn't contain expected aspect ratio!")
        
        
        # Async Compilation
        self.progress = QProgressDialog("Compiling FluidX3D... Please wait.", None, 0, 0, self)
        self.progress.setWindowTitle("Building Simulation")
        self.progress.setWindowModality(Qt.WindowModal)
        self.progress.setCancelButton(None)
        self.progress.setMinimumDuration(0)
        self.progress.show()

        self.worker = CompileWorker()
        self.worker.finished.connect(self.on_compilation_finished)
        self.worker.start()

    def on_compilation_finished(self, ok, out):
        self.progress.close()
        
        if not ok:
            QMessageBox.critical(self, "Compile Error", f"{out}")
            return
        
        print(f"✅ Compilation successful!")
        print(f"   Exe path: {FLUIDX3D_EXE}")
        print(f"   Exe exists: {os.path.exists(FLUIDX3D_EXE)}")
        
        if not os.path.exists(FLUIDX3D_EXE):
            QMessageBox.critical(self, "Error", f"Compilation succeeded but executable not found at:\n{FLUIDX3D_EXE}")
            return
            
        print("🚀 Launching simulation...")
        self.simulation_started = True
        self.settings_changed = False
        self.btn_build_run.setEnabled(True) # Allow restart at any time
        self.sim_runner.launch()

    def update_results_ui_state(self):
        is_slice = (self.results_view.mode == 'slice')
        is_vol = (self.results_view.mode == 'volume')
        
        self.grp_slice.setVisible(is_slice)
        self.grp_vol.setVisible(is_vol)
        self.lbl_res_hint.setVisible(not is_slice and not is_vol)
        
        if is_slice:
            self.update_res_preview()
        if is_vol:
            self.update_vol_preview_ui()

    def update_res_preview(self):
        if self.results_view.mode != 'slice': return
        x = self.sl_res_x.value()
        y = self.sl_res_y.value()
        z = self.sl_res_z.value()
        self.results_view.update_slice_preview(x, y, z)
        
    def update_vol_preview_ui(self):
        t = self.sl_vol_th.value() / 100.0
        o = self.sl_vol_op.value() / 100.0
        self.vol_preview.set_params(t, o)

    def apply_vol_params(self):
        # Progress Feedback
        progress = QProgressDialog("Updating Volume Rendering... (May take a moment)", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        
        try:
            t = self.sl_vol_th.value() / 100.0
            o = self.sl_vol_op.value() / 100.0
            self.results_view.update_volume_params(t, o)
        finally:
            progress.close()

    def apply_res_cut(self):
        x = self.sl_res_x.value()
        y = self.sl_res_y.value()
        z = self.sl_res_z.value()
        self.results_view.apply_cut(x, y, z)

    def save_svg_data(self):
        if not self.xy_poly:
            return
        folder = QFileDialog.getExistingDirectory(self, "Select SVG Export Folder")
        if not folder: return
        
        # User requested resolution matching the input "Size" (sb_side)
        # We interpret this as the pixel dimension of the square output image.
        target_res = int(self.sb_side.value())
        dpi = 100 
        size_in = target_res / dpi
        
        count = 0
        for i in range(self.layer_tabs.count()):
            widget = self.layer_tabs.widget(i)
            # widget is PreviewCanvas
            if hasattr(widget, 'fig'):
                title = self.layer_tabs.tabText(i)
                fname = "".join([c for c in title if c.isalnum() or c in ('-','_',' ')]).strip()
                path = os.path.join(folder, f"{fname}.svg")
                try:
                    ax = widget.ax
                    fig = widget.fig
                    
                    # Store original state
                    orig_title = ax.get_title()
                    orig_pos = ax.get_position()
                    orig_size = fig.get_size_inches()
                    
                    # Apply Export Settings (Clean Look + Exact Resolution)
                    ax.set_title("")
                    ax.axis('off')
                    fig.set_size_inches(size_in, size_in)
                    ax.set_position([0, 0, 1, 1]) # Full bleed, no margins
                    
                    # Save (bbox_inches=None to respect exact figsize)
                    fig.savefig(path, dpi=dpi, format='svg')
                    
                    # Restore State
                    ax.set_title(orig_title)
                    ax.axis('on') # Restore axis visibility (default was on due to clear())
                    ax.set_position(orig_pos)
                    fig.set_size_inches(orig_size)
                    widget.draw() # Refresh
                    
                    count += 1
                except Exception as e:
                    print(f"Error saving {fname}: {e}")
                    
        if count > 0:
            QMessageBox.information(self, "Success", f"Saved {count} SVG files to:\n{folder}\nResolution: {target_res}x{target_res}px")
        else:
            QMessageBox.warning(self, "Warning", "No valid plots found to save.")
    def export_mesh_user(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "mesh.stl", "STL (*.stl);;OBJ (*.obj)")
        if path:
            self.mesh_data.export(path)

    def on_tab_changed(self, index):
        self.controls_stack.setCurrentIndex(index)
        
        # If switching to simulation tab and simulation hasn't been started yet
        if index == 1 and not self.simulation_started and self.mesh_data is not None:
            print("📋 Auto-starting simulation on tab switch...")
            QTimer.singleShot(100, self.on_build_and_run)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WindTunnelApp()
    window.show()
    sys.exit(app.exec_())