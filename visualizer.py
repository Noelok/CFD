import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel
import matplotlib
matplotlib.use('Agg')
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from shapely.geometry import Polygon, MultiPolygon

try:
    import vispy.scene
    from vispy.scene import visuals
    from vispy.visuals import transforms
    VISPY_AVAILABLE = True
except ImportError:
    VISPY_AVAILABLE = False

class Visualizer3D(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0,0,0,0)
        
        if not VISPY_AVAILABLE:
            self.layout.addWidget(QLabel("Error: VisPy not installed."))
            return

        # 1. Main Canvas
        self.canvas = vispy.scene.SceneCanvas(keys='interactive', bgcolor='#111111')
        self.layout.addWidget(self.canvas.native)
        
        # 2. Main View
        self.view = self.canvas.central_widget.add_view()
        self.view.camera = 'turntable'
        self.view.camera.fov = 45
        self.view.camera.distance = 600
        
        # 3. Scene Nodes
        self.object_node = vispy.scene.Node(parent=self.view.scene)
        self.object_node.transform = transforms.STTransform(scale=(1, 1, -1))
        
        self.mesh_vis = None
        self.wire_vis = None
        
        # Lines for particles/streamlines
        self.lines_vis = visuals.Line(parent=self.object_node, width=4.0, antialias=True)
        
        # Grid
        self.grid = visuals.GridLines(color=(0.3, 0.3, 0.3, 0.5), parent=self.view.scene)
        self.grid.transform = transforms.STTransform(scale=(1, 1, -1)) 

    def set_mesh(self, vertices, faces):
        if self.mesh_vis: self.mesh_vis.parent = None
        if self.wire_vis: self.wire_vis.parent = None
        
        self.mesh_vis = visuals.Mesh(
            vertices=vertices, faces=faces,
            color=(0.7, 0.7, 0.7, 1.0), 
            shading='smooth',
            parent=self.object_node 
        )
        self.wire_vis = visuals.Mesh(
            vertices=vertices, faces=faces,
            color=(1.0, 1.0, 1.0, 0.1), 
            mode='lines',
            parent=self.object_node 
        )
        
        if len(vertices) > 0:
            self.view.camera.center = (0,0,0)
            self.view.camera.set_range() 

    def update_streamlines(self, positions, colors, num_lines, steps_per_line):
        if positions is None: return
        total_points = num_lines * steps_per_line
        idx = np.arange(total_points, dtype=np.uint32)
        grid = idx.reshape(num_lines, steps_per_line)
        starts = grid[:, :-1].flatten()
        ends = grid[:, 1:].flatten()
        connect = np.stack((starts, ends), axis=1)
        self.lines_vis.set_data(pos=positions, color=colors, connect=connect)

    def set_mesh_visibility(self, visible):
        if self.mesh_vis: self.mesh_vis.visible = visible
        if self.wire_vis: self.wire_vis.visible = visible

    def set_particles_visibility(self, visible):
        self.lines_vis.visible = visible

class PreviewCanvas(FigureCanvas):
    def __init__(self, parent=None):
        self.fig = Figure(figsize=(4, 4), dpi=100)
        super().__init__(self.fig)
        self.ax = self.fig.add_subplot(111); self.ax.axis('off')

    def plot(self, shape, title, invert=False):
        self.ax.clear()
        bg = '#2b2b2b'
        self.ax.set_facecolor(bg if invert else 'white')
        self.fig.patch.set_facecolor(bg if invert else 'white')
        if shape.geom_type == 'Polygon': polys = [shape]
        elif shape.geom_type == 'MultiPolygon': polys = list(shape.geoms)
        else: polys = []
        color = 'white' if invert else 'black'
        for poly in polys:
            x, y = poly.exterior.xy
            self.ax.fill(x, y, color=color)
            for interior in poly.interiors: 
                x, y = interior.xy
                self.ax.fill(x, y, color='black' if invert else 'white')
        self.ax.set_aspect('equal')
        self.ax.set_title(title, color='white' if invert else 'black')
        self.draw()