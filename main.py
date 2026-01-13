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
                             QGridLayout)
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPalette, QColor, QWindow

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
    r"D:\projects\FluidX3D-master",
    os.path.join(CURRENT_DIR, "FluidX3D-master"),
    os.path.join(CURRENT_DIR, "..", "FluidX3D-master"),
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

COMPILE_CMD = (
    f'cd /d "{FLUIDX3D_ROOT}" && '
    'if not exist bin mkdir bin && '
    'cl /std:c++17 /O2 /EHsc src/main.cpp src/lbm.cpp src/setup.cpp src/graphics.cpp '
    'src/info.cpp src/kernel.cpp src/lodepng.cpp src/shapes.cpp '
    '/Fe:bin/FluidX3D.exe /Fobin/ /I. '
    f'/I "{CUDA_INCLUDE}" '
    f'"{CUDA_LIB}" '
    'User32.lib Gdi32.lib Shell32.lib'
)

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

# --- C++ TEMPLATES ---

TEMPLATE_DEFINES = """#pragma once

#define D3Q19 
#define SRT
#define FP16S 
#define GRAPHICS 
#define INTERACTIVE_GRAPHICS

#define EQUILIBRIUM_BOUNDARIES 
#define SUBGRID                

{user_defines}

#define GRAPHICS_FRAME_WIDTH 1920 
#define GRAPHICS_FRAME_HEIGHT 1080
#define GRAPHICS_BACKGROUND_COLOR 0x000000
#define GRAPHICS_U_MAX 0.18f
#define GRAPHICS_RHO_DELTA 0.001f
#define GRAPHICS_T_DELTA 1.0f
#define GRAPHICS_F_MAX 0.001f
#define GRAPHICS_Q_CRITERION 0.0001f
#define GRAPHICS_STREAMLINE_SPARSE 8
#define GRAPHICS_STREAMLINE_LENGTH 128
#define GRAPHICS_RAYTRACING_TRANSMITTANCE 0.25f
#define GRAPHICS_RAYTRACING_COLOR 0x005F7F

#define TYPE_S 0b00000001 
#define TYPE_E 0b00000010 
#define TYPE_T 0b00000100 
#define TYPE_F 0b00001000 
#define TYPE_I 0b00010000 
#define TYPE_G 0b00100000 
#define TYPE_X 0b01000000 
#define TYPE_Y 0b10000000 

#define VIS_FLAG_LATTICE  0b00000001
#define VIS_FLAG_SURFACE  0b00000010
#define VIS_FIELD         0b00000100
#define VIS_STREAMLINES   0b00001000
#define VIS_Q_CRITERION   0b00010000
#define VIS_PHI_RASTERIZE 0b00100000
#define VIS_PHI_RAYTRACE  0b01000000
#define VIS_PARTICLES     0b10000000

#if defined(FP16S) || defined(FP16C)
#define fpxx ushort
#else
#define fpxx float
#endif

#if defined(INTERACTIVE_GRAPHICS) || defined(INTERACTIVE_GRAPHICS_ASCII)
#define UPDATE_FIELDS
#endif

#ifdef PARTICLES 
#define UPDATE_FIELDS 
#endif
"""

# TEMPLATE SETUP: 
# - Calculates Center safely (no ambiguous max calls)
# - Forces camera update on first frame
TEMPLATE_SETUP = """#include "setup.hpp"

void main_setup() {{ 
    const uint3 lbm_N = resolution(float3({asp_x}f, {asp_y}f, {asp_z}f), {vram}u); 
    const float lbm_Re = {re};     
    const float lbm_u = 0.075f; 
    const float lbm_nu = units.nu_from_Re(lbm_Re, (float)lbm_N.x, lbm_u);
    const ulong lbm_T = 108000ull;
    
    LBM lbm(lbm_N, lbm_nu, 0.0f, 0.0f, {force_z}f);

    // Mesh Scaling and Positioning
    const float size = {scale}f * (float)lbm_N.x; 
    const float3 center = lbm.center() + float3(
        {off_x}f * (float)lbm_N.x, 
        {off_y}f * (float)lbm_N.y, 
        {off_z}f * (float)lbm_N.z
    );

    const float3x3 rotation = float3x3(float3(1, 0, 0), radians(0.0f));

    const string stl_path = get_exe_path() + "../stl/{stl_filename}";
    lbm.voxelize_stl(stl_path, center, rotation, size); 

    const uint Nx=lbm.get_Nx(), Ny=lbm.get_Ny(), Nz=lbm.get_Nz(); 
    parallel_for(lbm.get_N(), [&](ulong n) {{ 
        uint x=0u, y=0u, z=0u; 
        lbm.coordinates(n, x, y, z);
        
        if(lbm.flags[n]!=TYPE_S) {{
             lbm.u.z[n] = lbm_u; 
        }}

        if(x==0u || x==Nx-1u || y==0u || y==Ny-1u || z==0u || z==Nz-1u) {{
            lbm.flags[n] = TYPE_E; 
        }}
    }});

    // Default Visuals
    lbm.graphics.visualization_modes = VIS_FLAG_LATTICE | VIS_FLAG_SURFACE | VIS_Q_CRITERION;
    
    // --- RECENTER CAMERA (FIXED) ---
    // Calculate max dimension explicitly to avoid compiler ambiguity
    float fx = (float)Nx; 
    float fy = (float)Ny; 
    float fz = (float)Nz;
    float max_dim = fx;
    if(fy > max_dim) max_dim = fy;
    if(fz > max_dim) max_dim = fz;

    float3 look_at = float3(fx*0.5f, fy*0.5f, fz*0.5f);
    
    // Position camera back (-Y) and up (+Z)
    float3 cam_pos = look_at + float3(0.0f, -1.5f * max_dim, 0.8f * max_dim);

    // --- MAIN LOOP ---
    lbm.run(0u); // Init
    
    bool first_frame = true;
    
    while(lbm.get_t() < lbm_T) {{
        lbm.run(1u);
        
        // Render
        if(lbm.graphics.next_frame(lbm_T, 30.0f)) {{
            
            // Apply Camera ONCE when window is definitely ready
            if(first_frame) {{
                lbm.graphics.set_camera_free(cam_pos, -30.0f, 0.0f, 0.0f);
                first_frame = false;
            }}
            
            {export_code}
        }}
    }}
}}
"""

class FluidX3DCompiler:
    @staticmethod
    def backup_originals():
        defines_orig = os.path.join(FLUIDX3D_ROOT, "src", "defines.hpp")
        setup_orig = os.path.join(FLUIDX3D_ROOT, "src", "setup.cpp")
        if os.path.exists(defines_orig) and not os.path.exists(defines_orig + ".bak"):
            shutil.copy(defines_orig, defines_orig + ".bak")
        if os.path.exists(setup_orig) and not os.path.exists(setup_orig + ".bak"):
            shutil.copy(setup_orig, setup_orig + ".bak")

    @staticmethod
    def generate_files(params):
        defines_list = []
        if params['vol_force']: defines_list.append("#define VOLUME_FORCE")
        if params['particles']: 
            defines_list.append("#define PARTICLES")
            if not params['vol_force']: defines_list.append("#define VOLUME_FORCE")
        
        defines_content = TEMPLATE_DEFINES.format(user_defines="\n".join(defines_list))
        
        # EXPORT CODE INJECTION
        export_code = ""
        if params['export_data']:
            export_code = """
            if (lbm.graphics.frame % 100 == 0) {
                lbm.write_data(get_exe_path() + "data/");
            }
            """
        
        setup_content = TEMPLATE_SETUP.format(
            stl_filename=params['stl_filename'],
            vram=int(params['vram']),
            asp_x="{:.4f}".format(params['asp_x']), 
            asp_y="{:.4f}".format(params['asp_y']), 
            asp_z="{:.4f}".format(params['asp_z']),
            re="{:.4f}".format(params['re']),
            force_z="{:.6f}".format(params['force_z']),
            scale="{:.4f}".format(params['scale']),
            off_x="{:.4f}".format(params['off_x']), 
            off_y="{:.4f}".format(params['off_y']), 
            off_z="{:.4f}".format(params['off_z']),
            export_code=export_code
        )
        
        try:
            def_path = os.path.join(FLUIDX3D_ROOT, "src", "defines.hpp")
            set_path = os.path.join(FLUIDX3D_ROOT, "src", "setup.cpp")
            if os.path.exists(def_path): os.remove(def_path)
            if os.path.exists(set_path): os.remove(set_path)
            with open(def_path, "w") as f: f.write(defines_content)
            with open(set_path, "w") as f: f.write(setup_content)
            return True
        except Exception as e:
            print(f"Gen Error: {e}")
            return False

    @staticmethod
    def compile():
        try:
            subprocess.run(["cl"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except FileNotFoundError:
            return False, "❌ 'cl.exe' not found! Run in x64 Native Tools Command Prompt."

        exe_path = os.path.join(FLUIDX3D_ROOT, "bin", "FluidX3D.exe")
        if os.path.exists(exe_path):
            try: os.remove(exe_path)
            except PermissionError: return False, "❌ Cannot remove old FluidX3D.exe. Close open simulations."

        bat_path = os.path.join(FLUIDX3D_ROOT, "compile_debug.bat")
        compile_cmd = (
            f'@echo off\n'
            f'cd /d "{FLUIDX3D_ROOT}"\n'
            f'if not exist bin mkdir bin\n'
            f'echo Compiling...\n'
            f'cl /std:c++17 /O2 /EHsc src/main.cpp src/lbm.cpp src/setup.cpp src/graphics.cpp '
            f'src/info.cpp src/kernel.cpp src/lodepng.cpp src/shapes.cpp '
            f'/Fe:bin\\FluidX3D.exe /Fobin\\ /I. '
            f'/I "{CUDA_INCLUDE}" '
            f'"{CUDA_LIB}" '
            f'User32.lib Gdi32.lib Shell32.lib\n'
            f'if %errorlevel% neq 0 exit /b %errorlevel%\n'
            f'echo Build Success.\n'
        )
        with open(bat_path, "w") as f: f.write(compile_cmd)

        try:
            result = subprocess.run([bat_path], cwd=FLUIDX3D_ROOT, capture_output=True, text=True)
            if result.returncode != 0: return False, f"COMPILER LOG:\n{result.stdout}\n\nERROR LOG:\n{result.stderr}"
            if not os.path.exists(exe_path): return False, "Compiler finished but FluidX3D.exe was not created."
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
            self.process.terminate()
            self.process.wait() 
            self.process = None
        
        if self.embedded_window:
            self.embedded_window.setParent(None)
            self.embedded_window = None
        
        self.lbl_info.setText("Simulation Running...")
        QApplication.processEvents()
        
        try:
            self.process = subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Launch failed:\n{e}")
            return

        self.hwnd = 0
        attempts = 0
        while self.hwnd == 0 and attempts < 100:
            time.sleep(0.2)
            self.hwnd = win32gui.FindWindow(None, "FluidX3D")
            attempts += 1
            QApplication.processEvents()

        if self.hwnd == 0:
            QMessageBox.warning(self, "Timeout", "Window not found.")
            return

        self.embed_window(self.hwnd)

    def embed_window(self, hwnd):
        window = QWindow.fromWinId(hwnd)
        self.embedded_window = QWidget.createWindowContainer(window, self)
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = style & ~win32con.WS_POPUP & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().setParent(None)
        
        self.layout.addWidget(self.embedded_window)
        self.embedded_window.show()

    def closeEvent(self, event):
        if self.process: self.process.terminate()
        super().closeEvent(event)

class WindTunnelApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fluid Design & Simulation Studio")
        self.resize(1600, 950)
        self.setup_dark_theme()
        
        FluidX3DCompiler.backup_originals()
        self.mesh_data = None
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # LEFT
        container_3d = QWidget()
        l3d = QVBoxLayout(container_3d); l3d.setContentsMargins(0,0,0,0)
        self.view_tabs = QTabWidget()
        self.vis = visualizer.Visualizer3D()
        self.view_tabs.addTab(self.vis, "📐 Mesh Preview")
        self.sim_runner = EmbeddedFluidX3D(FLUIDX3D_EXE)
        self.view_tabs.addTab(self.sim_runner, "🌊 FluidX3D Simulation")
        l3d.addWidget(self.view_tabs)
        splitter.addWidget(container_3d)
        
        # RIGHT
        self.controls_stack = QStackedWidget()
        self.controls_stack.setMinimumWidth(450)
        self.controls_stack.setMaximumWidth(500)
        self.page_design = QWidget(); self.setup_design_ui(self.page_design)
        self.controls_stack.addWidget(self.page_design)
        self.page_sim = QWidget(); self.setup_sim_ui(self.page_sim)
        self.controls_stack.addWidget(self.page_sim)
        splitter.addWidget(self.controls_stack)
        splitter.setSizes([1100, 500])
        self.view_tabs.currentChanged.connect(self.on_tab_changed)

        # --- KEYBOARD POLLING TIMER ---
        self.key_timer = QTimer(self)
        self.key_timer.timeout.connect(self.poll_keys)
        self.key_timer.start(100)

    def poll_keys(self):
        keys_to_check = {
            0x50: 'P', 0x48: 'H',
            0x31: '1', 0x32: '2', 0x33: '3', 0x34: '4',
            0x35: '5', 0x36: '6', 0x37: '7',
            0x54: 'T', 0x5A: 'Z'
        }
        for vk, key_char in keys_to_check.items():
            if win32api.GetAsyncKeyState(vk) & 1:
                self.update_status_ui(key_char)

    def update_status_ui(self, key):
        if key in self.status_widgets:
            w = self.status_widgets[key]
            w['state'] = not w['state'] 
            txt = w['t1'] if w['state'] else w['t0']
            color = "#00FF00" if w['state'] else "#AAA"
            w['lbl'].setText(f"<span style='color:{color}'>{txt}</span>")

    def setup_dark_theme(self):
        app = QApplication.instance()
        app.setStyle("Fusion")
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(53, 53, 53))
        palette.setColor(QPalette.WindowText, Qt.white)
        palette.setColor(QPalette.Button, QColor(53, 53, 53))
        palette.setColor(QPalette.ButtonText, Qt.white)
        palette.setColor(QPalette.Base, QColor(25, 25, 25))
        palette.setColor(QPalette.AlternateBase, QColor(53, 53, 53))
        palette.setColor(QPalette.Text, Qt.white)
        palette.setColor(QPalette.Highlight, QColor(42, 130, 218))
        palette.setColor(QPalette.HighlightedText, Qt.black)
        app.setPalette(palette)

    def setup_design_ui(self, parent):
        layout = QVBoxLayout(parent)
        g1 = QGroupBox("1. Geometry Settings")
        l1 = QVBoxLayout(g1)
        h1 = QHBoxLayout(); 
        self.sb_side = QDoubleSpinBox(); self.sb_side.setRange(50, 2000); self.sb_side.setValue(200.0)
        h1.addWidget(QLabel("Size:")); h1.addWidget(self.sb_side)
        l1.addLayout(h1)
        h2 = QHBoxLayout()
        self.sb_seeds = QSpinBox(); self.sb_seeds.setRange(10, 5000); self.sb_seeds.setValue(150)
        h2.addWidget(QLabel("Seeds:")); h2.addWidget(self.sb_seeds)
        l1.addLayout(h2)
        h3 = QHBoxLayout()
        self.sb_layers = QSpinBox(); self.sb_layers.setRange(1, 10); self.sb_layers.setValue(2)
        h3.addWidget(QLabel("Layers:")); h3.addWidget(self.sb_layers)
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
        btn_load = QPushButton("📂 Load STL"); btn_load.clicked.connect(self.load_custom_stl)
        h_io.addWidget(btn_load)
        self.btn_export_mesh = QPushButton("💾 Export Mesh"); self.btn_export_mesh.setEnabled(False); self.btn_export_mesh.clicked.connect(self.export_mesh_user)
        h_io.addWidget(self.btn_export_mesh)
        l_io.addLayout(h_io)
        layout.addWidget(g_io)
        
        layout.addStretch()

    def setup_sim_ui(self, parent):
        layout = QVBoxLayout(parent)
        lbl_title = QLabel("🌊 FluidX3D Configuration")
        lbl_title.setStyleSheet("font-size: 16px; font-weight: bold; color: #00ADB5;")
        layout.addWidget(lbl_title)
        
        g_grid = QGroupBox("1. Grid & Memory")
        l_grid = QVBoxLayout(g_grid)
        h_vram = QHBoxLayout()
        self.sb_vram = QSpinBox(); self.sb_vram.setRange(500, 24000); self.sb_vram.setValue(2000); self.sb_vram.setSingleStep(500)
        h_vram.addWidget(QLabel("VRAM (MB):")); h_vram.addWidget(self.sb_vram)
        l_grid.addLayout(h_vram)
        h_asp = QHBoxLayout()
        h_asp.addWidget(QLabel("Aspect Ratio (X:Y:Z):"))
        self.sb_ax = QDoubleSpinBox(); self.sb_ax.setRange(0.1, 10.0); self.sb_ax.setValue(2.0); self.sb_ax.setSingleStep(0.1)
        self.sb_ay = QDoubleSpinBox(); self.sb_ay.setRange(0.1, 10.0); self.sb_ay.setValue(1.0); self.sb_ay.setSingleStep(0.1)
        self.sb_az = QDoubleSpinBox(); self.sb_az.setRange(0.1, 10.0); self.sb_az.setValue(1.0); self.sb_az.setSingleStep(0.1)
        h_asp.addWidget(self.sb_ax); h_asp.addWidget(self.sb_ay); h_asp.addWidget(self.sb_az)
        l_grid.addLayout(h_asp)
        layout.addWidget(g_grid)
        
        g_geo = QGroupBox("2. Geometry Transform")
        l_geo = QVBoxLayout(g_geo)
        h_scale = QHBoxLayout()
        self.sb_scale = QDoubleSpinBox(); self.sb_scale.setRange(0.1, 5.0); self.sb_scale.setValue(0.50); self.sb_scale.setSingleStep(0.05)
        h_scale.addWidget(QLabel("Mesh Scale:")); h_scale.addWidget(self.sb_scale)
        l_geo.addLayout(h_scale)
        
        h_off = QHBoxLayout()
        h_off.addWidget(QLabel("Offset (X/Y/Z):"))
        self.sb_off_x = QDoubleSpinBox(); self.sb_off_x.setRange(-1.0, 1.0); self.sb_off_x.setValue(-0.25); self.sb_off_x.setSingleStep(0.05)
        self.sb_off_y = QDoubleSpinBox(); self.sb_off_y.setRange(-1.0, 1.0); self.sb_off_y.setValue(0.0); self.sb_off_y.setSingleStep(0.05)
        self.sb_off_z = QDoubleSpinBox(); self.sb_off_z.setRange(-1.0, 1.0); self.sb_off_z.setValue(0.0); self.sb_off_z.setSingleStep(0.05)
        h_off.addWidget(self.sb_off_x); h_off.addWidget(self.sb_off_y); h_off.addWidget(self.sb_off_z)
        l_geo.addLayout(h_off)
        
        h_rot = QHBoxLayout()
        h_rot.addWidget(QLabel("Rotation (°):"))
        self.sb_rot_x = QDoubleSpinBox(); self.sb_rot_x.setRange(-360, 360); self.sb_rot_x.setValue(0.0); 
        self.sb_rot_y = QDoubleSpinBox(); self.sb_rot_y.setRange(-360, 360); self.sb_rot_y.setValue(0.0); 
        self.sb_rot_z = QDoubleSpinBox(); self.sb_rot_z.setRange(-360, 360); self.sb_rot_z.setValue(0.0); 
        h_rot.addWidget(self.sb_rot_x); h_rot.addWidget(self.sb_rot_y); h_rot.addWidget(self.sb_rot_z)
        l_geo.addLayout(h_rot)
        layout.addWidget(g_geo)

        # Connect signals for live preview
        for sb in [self.sb_ax, self.sb_ay, self.sb_az,
                   self.sb_scale,
                   self.sb_off_x, self.sb_off_y, self.sb_off_z,
                   self.sb_rot_x, self.sb_rot_y, self.sb_rot_z]:
            sb.valueChanged.connect(self.update_preview)

        # Initial update
        self.update_preview()
        
        g_phys = QGroupBox("3. Physics")
        l_phys = QVBoxLayout(g_phys)
        h_re = QHBoxLayout()
        self.sb_re = QDoubleSpinBox(); self.sb_re.setRange(1, 10000000); self.sb_re.setValue(1000.0)
        h_re.addWidget(QLabel("Reynolds (Re):")); h_re.addWidget(self.sb_re)
        l_phys.addLayout(h_re)
        h_force = QHBoxLayout()
        self.sb_force = QDoubleSpinBox(); self.sb_force.setRange(-1.0, 1.0); self.sb_force.setValue(-0.0005); self.sb_force.setDecimals(5)
        h_force.addWidget(QLabel("Pump Force Z:")); h_force.addWidget(self.sb_force)
        l_phys.addLayout(h_force)
        self.chk_particles = QCheckBox("Enable Particles"); self.chk_particles.setChecked(False)
        self.chk_vol_force = QCheckBox("Enable Volume Force"); self.chk_vol_force.setChecked(True)
        l_phys.addWidget(self.chk_vol_force)
        l_phys.addWidget(self.chk_particles)
        
        # EXPORT CHECKBOX
        self.chk_export = QCheckBox("Export Simulation Data (VTK)")
        self.chk_export.setChecked(False)
        l_phys.addWidget(self.chk_export)
        
        layout.addWidget(g_phys)

        # --- SHORTCUTS & STATUS ---
        g_help = QGroupBox("4. Controls & Status")
        l_help = QGridLayout(g_help)
        
        self.status_widgets = {}
        
        shortcuts = [
            ("P", "Start/Pause", "(Paused)", "(Running)"),
            ("H", "Show/Hide Help", "(Shown)", "(Hidden)"),
            ("1", "Wireframe / Solid", "(Both)", "(Both)"),
            ("2", "Velocity Field", "(Inactive)", "(Active)"),
            ("3", "Streamlines", "(Inactive)", "(Active)"),
            ("4", "Q-Criterion", "(Active)", "(Inactive)"),
            ("5", "Raster Free Surf", "(Disabled)", "(Active)"),
            ("6", "Raytraced Surf", "(Disabled)", "(Active)"),
            ("7", "Particles", "(Disabled)", "(Active)"),
            ("T", "Slice Mode", "(Disabled)", "(Active)"),
            ("Z", "Field Mode", "(Disabled)", "(Active)"),
            ("Q/E", "Move Slice", "", "")
        ]
        
        for i, (key, desc, def_stat, act_stat) in enumerate(shortcuts):
            l_help.addWidget(QLabel(f"<b>{key}</b>"), i, 0)
            l_help.addWidget(QLabel(desc), i, 1)
            stat_lbl = QLabel(f"<span style='color:#AAA'>{def_stat}</span>")
            l_help.addWidget(stat_lbl, i, 2)
            self.status_widgets[key] = {
                'lbl': stat_lbl, 
                'state': False, # False = Default
                't0': def_stat, 
                't1': act_stat
            }
            
        layout.addWidget(g_help)

        self.btn_build_run = QPushButton("🛠 Update Settings & Restart Simulation")
        self.btn_build_run.setStyleSheet("""
            QPushButton { background-color: #e07a1f; color: white; font-weight: bold; padding: 15px; font-size: 14px; border-radius: 5px; }
            QPushButton:hover { background-color: #ff9d4d; }
        """)
        self.btn_build_run.clicked.connect(self.on_build_and_run)
        layout.addWidget(self.btn_build_run)
        layout.addStretch()

    def keyPressEvent(self, event):
        key = event.text().upper()
        if key in self.status_widgets:
            self.update_status_ui(key)
        super().keyPressEvent(event)

    def generate_geometry(self):
        self.lbl_status = self.findChild(QLabel, "") 
        self.layer_tabs.clear()
        QApplication.processEvents()
        try:
            side, seeds, layers = self.sb_side.value(), self.sb_seeds.value(), self.sb_layers.value()
            design = geometry.FluidicDesign(side)
            design.initialize_points(seeds)
            self.xy_poly = design.create_xy_flow_pattern(4.0)
            self.zs_polys = [design.create_z_pillar_pattern(3.0) for _ in range(layers)]
            
            # --- BLACK % CALCULATION ---
            full_area = side * side
            
            xy_area = self.xy_poly.area
            solid_pct_xy = ((full_area - xy_area) / full_area) * 100.0
            
            c1 = visualizer.PreviewCanvas(); c1.plot(self.xy_poly, "XY", invert=True)
            self.layer_tabs.addTab(c1, f"XY ({solid_pct_xy:.1f}% Solid)")
            
            for i, p in enumerate(self.zs_polys):
                solid_pct_z = (p.area / full_area) * 100.0
                c = visualizer.PreviewCanvas(); c.plot(p, f"Z{i+1}", invert=False)
                self.layer_tabs.addTab(c, f"Z{i+1} ({solid_pct_z:.1f}% Solid)")
            
            mesh = geometry.generate_full_mesh(self.xy_poly, self.zs_polys, side)
            if mesh: self.update_mesh(mesh)
        except Exception as e:
            print(e)

    def load_custom_stl(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load STL", "", "STL (*.stl)")
        if path:
            try:
                mesh = trimesh.load(path)
                if isinstance(mesh, trimesh.Scene):
                    if len(mesh.geometry) == 0: return
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
        # Ensure preview config is applied (in case set_mesh reset it or needs it)
        self.update_preview()

        self.btn_save_svg.setEnabled(True)
        self.btn_export_mesh.setEnabled(True)
        self.btn_build_run.setEnabled(True)

    def update_preview(self):
        try:
            aspect = (self.sb_ax.value(), self.sb_ay.value(), self.sb_az.value())
            scale = self.sb_scale.value()
            offset = (self.sb_off_x.value(), self.sb_off_y.value(), self.sb_off_z.value())
            rot = (self.sb_rot_x.value(), self.sb_rot_y.value(), self.sb_rot_z.value())
            self.vis.update_config(aspect, scale, offset, rot)
        except Exception as e:
            print(f"Preview Error: {e}")

    def on_build_and_run(self):
        if self.sim_runner.process:
            if self.lbl_status: self.lbl_status.setText("Stopping previous simulation...")
            self.sim_runner.process.terminate()
            self.sim_runner.process.wait()
            self.sim_runner.process = None
            time.sleep(1.0)

        if not self.mesh_data: return
        
        sim_mesh = self.mesh_data.copy()
        
        rot_x = np.radians(self.sb_rot_x.value())
        rot_y = np.radians(self.sb_rot_y.value())
        rot_z = np.radians(self.sb_rot_z.value())
        
        if rot_x != 0 or rot_y != 0 or rot_z != 0:
            matrix = tf.euler_matrix(rot_x, rot_y, rot_z, axes='sxyz')
            sim_mesh.apply_transform(matrix)
            
        min_bound, max_bound = sim_mesh.bounds
        center_offset = (min_bound + max_bound) / 2.0
        sim_mesh.apply_translation(-center_offset)

        if os.path.exists(FLUIDX3D_STL_DIR):
            for f in os.listdir(FLUIDX3D_STL_DIR):
                if f.startswith("sim_geometry_") or f.endswith(".bin"):
                    try: os.remove(os.path.join(FLUIDX3D_STL_DIR, f))
                    except: pass
        else:
            os.makedirs(FLUIDX3D_STL_DIR)

        unique_id = int(time.time())
        stl_filename = f"sim_geometry_{unique_id}.stl"
        full_stl_path = os.path.join(FLUIDX3D_STL_DIR, stl_filename)
        sim_mesh.export(full_stl_path)

        params = {
            'stl_filename': stl_filename,
            'vram': self.sb_vram.value(),
            'asp_x': self.sb_ax.value(), 'asp_y': self.sb_ay.value(), 'asp_z': self.sb_az.value(),
            'scale': self.sb_scale.value(),
            'off_x': self.sb_off_x.value(), 'off_y': self.sb_off_y.value(), 'off_z': self.sb_off_z.value(),
            'rot_x': 0, 'rot_y': 0, 'rot_z': 0,
            're': self.sb_re.value(),
            'force_z': self.sb_force.value(),
            'vol_force': self.chk_vol_force.isChecked(),
            'particles': self.chk_particles.isChecked(),
            'export_data': self.chk_export.isChecked()
        }

        self.lbl_status = self.findChild(QLabel, "")
        if self.lbl_status: self.lbl_status.setText("Writing Config...")
        QApplication.processEvents()
        
        if not FluidX3DCompiler.generate_files(params): 
            QMessageBox.critical(self, "Error", "Failed to write setup.cpp")
            return
        
        if self.lbl_status: self.lbl_status.setText("Compiling...")
        QApplication.processEvents()
        
        ok, out = FluidX3DCompiler.compile()
        if not ok:
            QMessageBox.critical(self, "Compile Error", f"{out}")
            if self.lbl_status: self.lbl_status.setText("Compile Failed")
            return
            
        if self.lbl_status: self.lbl_status.setText("Launching...")
        self.sim_runner.launch()

    def save_svg_data(self):
        if not self.xy_poly: return
        folder = QFileDialog.getExistingDirectory(self, "SVG Folder")

    def export_mesh_user(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "mesh.stl", "STL (*.stl);;OBJ (*.obj)")
        if path: self.mesh_data.export(path)

    def on_tab_changed(self, index):
        self.controls_stack.setCurrentIndex(index)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WindTunnelApp()
    window.show()
    sys.exit(app.exec_())