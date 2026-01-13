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
                             QFileDialog, QMessageBox, QCheckBox, QSlider)
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPalette, QColor, QWindow

# Windows Specific Imports
import win32gui
import win32con

# Local Modules
import geometry
import visualizer

# --- CONFIGURATION ---
# UPDATE THIS PATH to your actual FluidX3D installation folder
FLUIDX3D_ROOT = r"D:\projects\FluidX3D-master"
FLUIDX3D_EXE = os.path.join(FLUIDX3D_ROOT, "bin", "FluidX3D.exe")
FLUIDX3D_STL_DIR = os.path.join(FLUIDX3D_ROOT, "stl")

os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"

class EmbeddedFluidX3D(QWidget):
    """
    Launches and embeds the FluidX3D window.
    """
    def __init__(self, exe_path, parent=None):
        super().__init__(parent)
        self.exe_path = exe_path
        self.process = None
        self.embedded_window = None
        
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        self.btn_launch = QPushButton("Click 'Launch Simulation' in Sidebar to Start")
        self.btn_launch.setEnabled(False)
        self.btn_launch.setStyleSheet("background-color: #333; color: #888; border: none; font-size: 16px;")
        self.layout.addWidget(self.btn_launch)

    def start_simulation(self):
        if self.process:
            return

        # Check path
        if not os.path.exists(self.exe_path):
            QMessageBox.critical(self, "Error", f"FluidX3D Executable not found at:\n{self.exe_path}")
            return

        # Remove placeholder
        for i in range(self.layout.count()): 
            self.layout.itemAt(i).widget().setParent(None)

        self.lbl_loading = QLabel("Searching for FluidX3D window...", alignment=Qt.AlignCenter)
        self.layout.addWidget(self.lbl_loading)
        QApplication.processEvents()
        
        # 1. Launch Process
        try:
            self.process = subprocess.Popen(
                [self.exe_path], 
                cwd=os.path.dirname(self.exe_path)
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not launch process:\n{e}")
            return

        # 2. Find Window
        hwnd = 0
        attempts = 0
        while hwnd == 0 and attempts < 25:
            time.sleep(0.2)
            hwnd = win32gui.FindWindow(None, "FluidX3D")
            attempts += 1
            QApplication.processEvents()

        if hwnd == 0:
            QMessageBox.warning(self, "Timeout", "FluidX3D started, but the window was not detected.")
            return

        # 3. Embed
        self.embed_window(hwnd)

    def embed_window(self, hwnd):
        window = QWindow.fromWinId(hwnd)
        self.embedded_window = QWidget.createWindowContainer(window, self)
        
        # Strip Borders
        style = win32gui.GetWindowLong(hwnd, win32con.GWL_STYLE)
        style = style & ~win32con.WS_POPUP & ~win32con.WS_CAPTION & ~win32con.WS_THICKFRAME
        win32gui.SetWindowLong(hwnd, win32con.GWL_STYLE, style)
        
        # Cleanup Layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            widget = item.widget()
            if widget: widget.setParent(None)
            
        self.layout.addWidget(self.embedded_window)
        self.embedded_window.show()

    def closeEvent(self, event):
        if self.process:
            self.process.terminate()
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
        
        # --- LEFT SIDE: 3D Views ---
        container_3d = QWidget()
        l3d = QVBoxLayout(container_3d); l3d.setContentsMargins(0,0,0,0)
        
        self.view_tabs = QTabWidget()
        
        # Tab 1: Static Mesh Preview
        self.vis = visualizer.Visualizer3D()
        self.view_tabs.addTab(self.vis, "📐 Mesh Preview")
        
        # Tab 2: Simulation
        self.sim_runner = EmbeddedFluidX3D(FLUIDX3D_EXE)
        self.view_tabs.addTab(self.sim_runner, "🌊 FluidX3D Simulation")
        
        l3d.addWidget(self.view_tabs)
        splitter.addWidget(container_3d)
        
        # --- RIGHT SIDE: Controls ---
        controls_panel = QWidget()
        controls_panel.setMinimumWidth(450)
        controls_panel.setMaximumWidth(500)
        c_layout = QVBoxLayout(controls_panel)
        splitter.addWidget(controls_panel)
        
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
        c_layout.addWidget(g1)
        
        # 2. Layers Preview & SVG Save
        g_tabs = QGroupBox("2. Layers Preview")
        lt = QVBoxLayout(g_tabs)
        self.layer_tabs = QTabWidget()
        self.layer_tabs.setMinimumHeight(250)
        lt.addWidget(self.layer_tabs)
        
        self.btn_save_svg = QPushButton("💾 Save SVGs")
        self.btn_save_svg.setEnabled(False)
        self.btn_save_svg.clicked.connect(self.save_svg_data)
        lt.addWidget(self.btn_save_svg)
        c_layout.addWidget(g_tabs)
        
        # 3. Import / Export
        g_io = QGroupBox("3. Import / Export Mesh")
        l_io = QVBoxLayout(g_io)
        
        h_io_btns = QHBoxLayout()
        self.btn_load_stl = QPushButton("📂 Load Custom STL")
        self.btn_load_stl.clicked.connect(self.load_custom_stl)
        h_io_btns.addWidget(self.btn_load_stl)
        
        self.btn_export_mesh = QPushButton("💾 Export (OBJ/STL)")
        self.btn_export_mesh.setEnabled(False)
        self.btn_export_mesh.clicked.connect(self.export_mesh_user)
        h_io_btns.addWidget(self.btn_export_mesh)
        
        l_io.addLayout(h_io_btns)
        c_layout.addWidget(g_io)

        # 4. Simulation
        g_sim = QGroupBox("4. Simulation")
        l_sim = QVBoxLayout(g_sim)
        
        self.btn_launch_sim = QPushButton("🚀 Launch Simulation")
        self.btn_launch_sim.setEnabled(False) # Disabled until mesh exists
        self.btn_launch_sim.setStyleSheet("""
            QPushButton { background-color: #555; color: #aaa; font-weight: bold; padding: 12px; font-size: 14px; border-radius: 6px;}
            QPushButton:enabled { background-color: #e07a1f; color: white; }
            QPushButton:hover:enabled { background-color: #ff9d4d; }
        """)
        self.btn_launch_sim.clicked.connect(self.on_launch_clicked)
        l_sim.addWidget(self.btn_launch_sim)
        c_layout.addWidget(g_sim)
        
        # Status Bar
        self.lbl_status = QLabel("Status: Idle")
        self.lbl_status.setStyleSheet("font-weight: bold; color: #aaa;")
        c_layout.addWidget(self.lbl_status)
        c_layout.addStretch()
        
        splitter.setSizes([1100, 500])

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

    # --- LOGIC ---

    def generate_geometry(self):
        self.lbl_status.setText("Status: Generating Geometry...")
        self.layer_tabs.clear()
        QApplication.processEvents()
        try:
            side = self.sb_side.value()
            seeds = self.sb_seeds.value()
            num_layers = self.sb_layers.value()
            
            # 1. Generate Logic
            design = geometry.FluidicDesign(side)
            design.initialize_points(seeds)
            self.xy_poly = design.create_xy_flow_pattern(4.0)
            self.zs_polys = [design.create_z_pillar_pattern(3.0) for _ in range(num_layers)]
            
            # 2. Update 2D Tabs
            c1 = visualizer.PreviewCanvas()
            c1.plot(self.xy_poly, "XY Flow", invert=True)
            self.layer_tabs.addTab(c1, "XY")
            for i, z_poly in enumerate(self.zs_polys):
                c = visualizer.PreviewCanvas()
                c.plot(z_poly, f"Z Layer {i+1}", invert=False)
                self.layer_tabs.addTab(c, f"Z{i+1}")
            
            self.btn_save_svg.setEnabled(True)

            # 3. Generate 3D Mesh
            mesh = geometry.generate_full_mesh(self.xy_poly, self.zs_polys, side)
            if mesh:
                self.update_mesh_preview(mesh)
                # Note: We stay on the current tab (Mesh Preview) as requested
            else:
                self.lbl_status.setText("Status: Failed to generate mesh")
                
        except Exception as e:
            self.lbl_status.setText(f"Error: {str(e)}")
            print(e)

    def load_custom_stl(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load STL", "", "STL Files (*.stl)")
        if path:
            try:
                self.lbl_status.setText(f"Loading: {path}...")
                mesh = trimesh.load(path)
                
                # Cleanup if necessary (optional, but good for FluidX3D)
                if isinstance(mesh, trimesh.Scene):
                    if len(mesh.geometry) == 0: raise ValueError("Empty Scene")
                    mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
                
                # Center it (FluidX3D requirement)
                mesh.apply_translation(-mesh.centroid)
                
                self.update_mesh_preview(mesh)
                self.lbl_status.setText(f"Loaded: {os.path.basename(path)}")
                
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to load STL:\n{e}")

    def update_mesh_preview(self, mesh):
        """Helper to update visualizer and prepare for simulation"""
        self.mesh_data = mesh
        self.vis.set_mesh(mesh.vertices, mesh.faces)
        
        # Enable Buttons
        self.btn_export_mesh.setEnabled(True)
        self.btn_launch_sim.setEnabled(True)
        
        # Auto-Export for FluidX3D (Silent background step)
        self.prepare_simulation_files()

    def prepare_simulation_files(self):
        """Saves cube.stl specifically for FluidX3D"""
        if not self.mesh_data: return
        try:
            if not os.path.exists(FLUIDX3D_STL_DIR):
                os.makedirs(FLUIDX3D_STL_DIR)
            target_path = os.path.join(FLUIDX3D_STL_DIR, "cube.stl")
            self.mesh_data.export(target_path)
            print(f"Simulation Mesh Ready: {target_path}")
        except Exception as e:
             QMessageBox.critical(self, "Error", f"Could not save internal simulation file:\n{e}")

    def export_mesh_user(self):
        """User-facing export (OBJ, STL)"""
        if not self.mesh_data: return
        path, filter = QFileDialog.getSaveFileName(self, "Export Mesh", "mesh.stl", "STL Files (*.stl);;OBJ Files (*.obj)")
        if path:
            try:
                self.mesh_data.export(path)
                self.lbl_status.setText(f"Exported: {path}")
                QMessageBox.information(self, "Success", f"Mesh saved to:\n{path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export:\n{e}")

    def on_launch_clicked(self):
        # Switch to Sim Tab and Launch
        self.view_tabs.setCurrentWidget(self.sim_runner)
        self.sim_runner.start_simulation()

    def save_svg_data(self):
        if not self.xy_poly: return
        folder = QFileDialog.getExistingDirectory(self, "Select Directory for SVGs")
        if not folder: return
        try:
            def save_poly_svg(poly, filename, invert=False):
                fig = plt.figure(figsize=(6,6))
                ax = fig.add_subplot(111); ax.axis('off'); ax.set_aspect('equal')
                bg_col = 'black' if invert else 'white'
                fill_col = 'white' if invert else 'black'
                fig.patch.set_facecolor(bg_col)
                if poly.geom_type == 'Polygon': polys = [poly]
                elif poly.geom_type == 'MultiPolygon': polys = list(poly.geoms)
                else: polys = []
                for p in polys:
                    x, y = p.exterior.xy
                    ax.fill(x, y, color=fill_col)
                    for interior in p.interiors:
                        xi, yi = interior.xy
                        ax.fill(xi, yi, color=bg_col)
                path = os.path.join(folder, filename)
                fig.savefig(path, format='svg', facecolor=fig.get_facecolor(), edgecolor='none')
                plt.close(fig)

            save_poly_svg(self.xy_poly, "layer_xy_flow.svg", invert=True)
            for i, z_poly in enumerate(self.zs_polys):
                save_poly_svg(z_poly, f"layer_z{i+1}_pillar.svg", invert=False)
                
            QMessageBox.information(self, "Success", f"Saved SVGs to:\n{folder}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save:\n{str(e)}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = WindTunnelApp()
    window.show()
    sys.exit(app.exec_())