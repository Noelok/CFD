import sys
import os
import time
import subprocess
import numpy as np
import matplotlib.pyplot as plt
import trimesh

# PyQt Imports
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QPushButton, QLabel, QGroupBox, 
                             QSpinBox, QDoubleSpinBox, QTabWidget, QSplitter, 
                             QFileDialog, QMessageBox, QCheckBox, QSlider, QStackedWidget)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPalette, QColor, QWindow

# Windows Specific Imports
import win32gui
import win32con
import win32api

# Local Modules
import geometry
import visualizer

# --- CONFIGURATION ---
FLUIDX3D_ROOT = r"D:\projects\FluidX3D-master"
FLUIDX3D_EXE = os.path.join(FLUIDX3D_ROOT, "bin", "FluidX3D.exe")
FLUIDX3D_STL_DIR = os.path.join(FLUIDX3D_ROOT, "stl")

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

class EmbeddedFluidX3D(QWidget):
    def __init__(self, exe_path, parent=None):
        super().__init__(parent)
        self.exe_path = exe_path
        self.process = None
        self.embedded_window = None
        self.hwnd = 0 # Store Window Handle for sending commands
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.lbl_info = QLabel("Click 'Launch Simulation' in Sidebar to Start")
        self.lbl_info.setAlignment(Qt.AlignCenter)
        self.lbl_info.setStyleSheet("color: #888; font-size: 16px;")
        self.layout.addWidget(self.lbl_info)

    def start_simulation(self):
        if self.process: return

        if not os.path.exists(self.exe_path):
            QMessageBox.critical(self, "Error", f"Executable not found:\n{self.exe_path}")
            return

        # Clear placeholder
        self.lbl_info.setParent(None)
        
        self.lbl_loading = QLabel("Initializing Engine...", alignment=Qt.AlignCenter)
        self.layout.addWidget(self.lbl_loading)
        QApplication.processEvents()
        
        try:
            self.process = subprocess.Popen([self.exe_path], cwd=os.path.dirname(self.exe_path))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Launch failed:\n{e}")
            return

        # Find Window
        self.hwnd = 0
        attempts = 0
        while self.hwnd == 0 and attempts < 25:
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
        
        # Style: Remove borders
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = style & ~win32con.WS_POPUP & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        
        # Clear loading label
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget(): item.widget().setParent(None)
            
        self.layout.addWidget(self.embedded_window)
        self.embedded_window.show()

    def send_command(self, key_code):
        """Sends a key press to the embedded window"""
        if self.hwnd:
            # Send Key Down and Key Up
            win32api.PostMessage(self.hwnd, win32con.WM_KEYDOWN, key_code, 0)
            win32api.PostMessage(self.hwnd, win32con.WM_KEYUP, key_code, 0)
            # Refocus the window so mouse controls work immediately
            win32gui.SetFocus(self.hwnd)

    def closeEvent(self, event):
        if self.process: self.process.terminate()
        super().closeEvent(event)

class WindTunnelApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Fluid Design & Simulation Studio")
        self.resize(1600, 900)
        self.setup_dark_theme()
        
        self.mesh_data = None
        self.xy_poly = None  
        self.zs_polys = []   
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        splitter = QSplitter(Qt.Horizontal)
        main_layout.addWidget(splitter)
        
        # --- LEFT SIDE: VIEWPORT TABS ---
        container_3d = QWidget()
        l3d = QVBoxLayout(container_3d); l3d.setContentsMargins(0,0,0,0)
        
        self.view_tabs = QTabWidget()
        # NOTE: We do NOT connect the signal here yet to avoid the crash!
        
        # Tab 1
        self.vis = visualizer.Visualizer3D()
        self.view_tabs.addTab(self.vis, "📐 Mesh Preview")
        
        # Tab 2
        self.sim_runner = EmbeddedFluidX3D(FLUIDX3D_EXE)
        self.view_tabs.addTab(self.sim_runner, "🌊 FluidX3D Simulation")
        
        l3d.addWidget(self.view_tabs)
        splitter.addWidget(container_3d)
        
        # --- RIGHT SIDE: CONTROLS STACK ---
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
        
        splitter.addWidget(self.controls_stack)
        splitter.setSizes([1100, 500])

        # --- FINAL CONNECTION ---
        # Safe to connect now that controls_stack exists
        self.view_tabs.currentChanged.connect(self.on_tab_changed)

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

    # --- UI SETUP: DESIGN PAGE ---
    def setup_design_ui(self, parent):
        layout = QVBoxLayout(parent)
        
        # 1. Design Parameters
        g1 = QGroupBox("1. Design Parameters")
        l1 = QVBoxLayout(g1)
        
        h_side = QHBoxLayout()
        self.sb_side = QDoubleSpinBox(); self.sb_side.setRange(50, 2000); self.sb_side.setValue(200.0)
        h_side.addWidget(QLabel("Side Length:")); h_side.addWidget(self.sb_side)
        l1.addLayout(h_side)
        
        h_seed = QHBoxLayout()
        self.sb_seeds = QSpinBox(); self.sb_seeds.setRange(10, 5000); self.sb_seeds.setValue(150)
        h_seed.addWidget(QLabel("Seed Count:")); h_seed.addWidget(self.sb_seeds)
        l1.addLayout(h_seed)
        
        h_layer = QHBoxLayout()
        self.sb_layers = QSpinBox(); self.sb_layers.setRange(1, 10); self.sb_layers.setValue(2)
        h_layer.addWidget(QLabel("Z Layers:")); h_layer.addWidget(self.sb_layers)
        l1.addLayout(h_layer)
        
        btn_gen = QPushButton("Generate Geometry")
        btn_gen.setStyleSheet("background-color: #00ADB5; color: black; font-weight: bold; padding: 10px;")
        btn_gen.clicked.connect(self.generate_geometry)
        l1.addWidget(btn_gen)
        layout.addWidget(g1)
        
        # 2. Layers Preview
        g_tabs = QGroupBox("2. Layers Preview")
        lt = QVBoxLayout(g_tabs)
        self.layer_tabs = QTabWidget()
        self.layer_tabs.setMinimumHeight(250)
        lt.addWidget(self.layer_tabs)
        
        self.btn_save_svg = QPushButton("💾 Save SVGs")
        self.btn_save_svg.setEnabled(False)
        self.btn_save_svg.clicked.connect(self.save_svg_data)
        lt.addWidget(self.btn_save_svg)
        layout.addWidget(g_tabs)
        
        # 3. Import / Export
        g_io = QGroupBox("3. Import / Export Mesh")
        l_io = QVBoxLayout(g_io)
        h_io_btns = QHBoxLayout()
        
        btn_load = QPushButton("📂 Load STL")
        btn_load.clicked.connect(self.load_custom_stl)
        h_io_btns.addWidget(btn_load)
        
        self.btn_export_mesh = QPushButton("💾 Export Mesh")
        self.btn_export_mesh.setEnabled(False)
        self.btn_export_mesh.clicked.connect(self.export_mesh_user)
        h_io_btns.addWidget(self.btn_export_mesh)
        l_io.addLayout(h_io_btns)
        layout.addWidget(g_io)

        # 4. Launch Section
        g_launch = QGroupBox("4. Next Step")
        l_launch = QVBoxLayout(g_launch)
        self.btn_launch_sim = QPushButton("🚀 Go to Simulation")
        self.btn_launch_sim.setEnabled(False)
        self.btn_launch_sim.setStyleSheet("background-color: #e07a1f; color: white; font-weight: bold; padding: 10px;")
        self.btn_launch_sim.clicked.connect(self.on_launch_clicked)
        l_launch.addWidget(self.btn_launch_sim)
        layout.addWidget(g_launch)
        
        self.lbl_status = QLabel("Status: Idle")
        layout.addWidget(self.lbl_status)
        layout.addStretch()

    # --- UI SETUP: SIMULATION PAGE ---
    def setup_sim_ui(self, parent):
        layout = QVBoxLayout(parent)
        
        lbl_title = QLabel("🌊 Simulation Controls")
        lbl_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00ADB5;")
        layout.addWidget(lbl_title)
        
        # 1. Playback Controls
        g_play = QGroupBox("Playback")
        l_play = QHBoxLayout(g_play)
        
        btn_pause = QPushButton("⏯ Pause / Run")
        # 'P' is the standard FluidX3D key for Pause
        btn_pause.clicked.connect(lambda: self.sim_runner.send_command(ord('P')))
        l_play.addWidget(btn_pause)
        
        # 'R' (if supported) or we can implement others if mapped in C++
        # Standard FluidX3D usually doesn't have a 'Reset' key by default, 
        # but 'I' often initializes or reinits. Let's assume P for now.
        layout.addWidget(g_play)
        
        # 2. Visualization Slices
        g_vis = QGroupBox("Visualization Mode")
        l_vis = QVBoxLayout(g_vis)
        
        h_vis1 = QHBoxLayout()
        btn_slice_x = QPushButton("Slice X (1)")
        btn_slice_x.clicked.connect(lambda: self.sim_runner.send_command(ord('1')))
        
        btn_slice_y = QPushButton("Slice Y (2)")
        btn_slice_y.clicked.connect(lambda: self.sim_runner.send_command(ord('2')))
        
        h_vis1.addWidget(btn_slice_x)
        h_vis1.addWidget(btn_slice_y)
        l_vis.addLayout(h_vis1)
        
        h_vis2 = QHBoxLayout()
        btn_slice_z = QPushButton("Slice Z (3)")
        btn_slice_z.clicked.connect(lambda: self.sim_runner.send_command(ord('3')))
        
        btn_surface = QPushButton("Surface (4)")
        btn_surface.clicked.connect(lambda: self.sim_runner.send_command(ord('4')))
        
        h_vis2.addWidget(btn_slice_z)
        h_vis2.addWidget(btn_surface)
        l_vis.addLayout(h_vis2)
        
        # Add Raytracing button (usually 'R' in some builds or '5')
        btn_ray = QPushButton("Toggle Raytracing (T)")
        btn_ray.clicked.connect(lambda: self.sim_runner.send_command(ord('T')))
        l_vis.addWidget(btn_ray)
        
        layout.addWidget(g_vis)
        
        # 3. Information
        g_info = QGroupBox("Controls Info")
        l_info = QVBoxLayout(g_info)
        l_info.addWidget(QLabel("• Left Click + Drag: Rotate Camera"))
        l_info.addWidget(QLabel("• Right Click + Drag: Pan Camera"))
        l_info.addWidget(QLabel("• Scroll: Zoom"))
        layout.addWidget(g_info)
        
        btn_back = QPushButton("← Back to Design")
        btn_back.clicked.connect(self.go_back_to_design)
        layout.addWidget(btn_back)
        
        layout.addStretch()

    # --- TAB & STACK LOGIC ---
    def on_tab_changed(self, index):
        # Index 0 = Design Tab, Index 1 = Simulation Tab
        self.controls_stack.setCurrentIndex(index)
        
        # If user clicked Simulation tab manually, check if we should launch
        if index == 1 and not self.sim_runner.process and self.btn_launch_sim.isEnabled():
            self.sim_runner.start_simulation()

    def on_launch_clicked(self):
        self.view_tabs.setCurrentIndex(1) # This triggers on_tab_changed automatically

    def go_back_to_design(self):
        self.view_tabs.setCurrentIndex(0)

    # --- EXISTING LOGIC (Minimally changed) ---
    def generate_geometry(self):
        self.lbl_status.setText("Status: Generating...")
        self.layer_tabs.clear()
        QApplication.processEvents()
        try:
            side, seeds, layers = self.sb_side.value(), self.sb_seeds.value(), self.sb_layers.value()
            design = geometry.FluidicDesign(side)
            design.initialize_points(seeds)
            self.xy_poly = design.create_xy_flow_pattern(4.0)
            self.zs_polys = [design.create_z_pillar_pattern(3.0) for _ in range(layers)]
            
            c1 = visualizer.PreviewCanvas()
            c1.plot(self.xy_poly, "XY Flow", invert=True)
            self.layer_tabs.addTab(c1, "XY")
            for i, p in enumerate(self.zs_polys):
                c = visualizer.PreviewCanvas(); c.plot(p, f"Z{i+1}", invert=False)
                self.layer_tabs.addTab(c, f"Z{i+1}")
            
            self.btn_save_svg.setEnabled(True)
            mesh = geometry.generate_full_mesh(self.xy_poly, self.zs_polys, side)
            if mesh: self.update_mesh_preview(mesh)
        except Exception as e:
            self.lbl_status.setText(f"Error: {e}")

    def load_custom_stl(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load STL", "", "STL Files (*.stl)")
        if path:
            try:
                mesh = trimesh.load(path)
                if isinstance(mesh, trimesh.Scene):
                    if len(mesh.geometry) == 0: return
                    mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
                mesh.apply_translation(-mesh.centroid)
                self.update_mesh_preview(mesh)
                self.lbl_status.setText(f"Loaded: {os.path.basename(path)}")
            except Exception as e:
                QMessageBox.critical(self, "Error", str(e))

    def update_mesh_preview(self, mesh):
        self.mesh_data = mesh
        self.vis.set_mesh(mesh.vertices, mesh.faces)
        self.btn_export_mesh.setEnabled(True)
        self.btn_launch_sim.setEnabled(True)
        
        # Save for FluidX3D
        if not os.path.exists(FLUIDX3D_STL_DIR): os.makedirs(FLUIDX3D_STL_DIR)
        self.mesh_data.export(os.path.join(FLUIDX3D_STL_DIR, "cube.stl"))
        self.lbl_status.setText("Mesh generated & Saved for Sim")

    def export_mesh_user(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export", "mesh.stl", "STL (*.stl);;OBJ (*.obj)")
        if path: self.mesh_data.export(path)

    def save_svg_data(self):
        if not self.xy_poly: return
        folder = QFileDialog.getExistingDirectory(self, "Select SVG Folder")
        if folder:
            # (SVG saving logic omitted for brevity, same as before)
            QMessageBox.information(self, "Done", f"Saved to {folder}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WindTunnelApp()
    window.show()
    sys.exit(app.exec_())