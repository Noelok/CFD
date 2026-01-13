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
        
        self.domain_config = {
            'aspect': (2.0, 1.0, 1.0),
            'scale': 0.5,
            'offset': (-0.25, 0.0, 0.0),
            'rot': (0.0, 0.0, 0.0)
        }

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
        # Note: FluidX3D usually uses Z-up, but VisPy defaults can vary.
        # Keeping existing transform which seems to invert Z for some reason or match coordinate systems.
        self.object_node.transform = transforms.STTransform(scale=(1, 1, -1))
        
        self.mesh_vis = None
        self.wire_vis = None
        self.domain_box = None
        
        # Lines for particles/streamlines
        self.lines_vis = visuals.Line(parent=self.object_node, width=4.0, antialias=True)
        
        # Grid
        self.grid = visuals.GridLines(color=(0.3, 0.3, 0.3, 0.5), parent=self.view.scene)
        self.grid.transform = transforms.STTransform(scale=(1, 1, -1)) 

        # Initial Domain Draw
        self.draw_domain_box()

    def update_config(self, aspect, scale, offset, rot):
        """
        Updates the domain configuration and refreshes the view.
        aspect: tuple (x, y, z) - Aspect ratio of the domain
        scale: float - Mesh scale relative to domain X
        offset: tuple (x, y, z) - Mesh offset relative to domain dimensions
        rot: tuple (x, y, z) - Mesh rotation in degrees
        """
        self.domain_config['aspect'] = aspect
        self.domain_config['scale'] = scale
        self.domain_config['offset'] = offset
        self.domain_config['rot'] = rot

        self.draw_domain_box()
        self.update_mesh_transform()

    def draw_domain_box(self):
        if not VISPY_AVAILABLE: return

        ax, ay, az = self.domain_config['aspect']

        # Normalize dimensions. Let's say Y (height/width) is 100 units in VisPy world.
        # Actually, let's just use the aspect ratio directly scaled by some factor to make it visible.
        # Or better, keep it abstract. If we use 100 as base:
        base_size = 100.0
        dx = ax * base_size
        dy = ay * base_size
        dz = az * base_size

        # Center the box at (0,0,0)
        x1, x2 = -dx/2, dx/2
        y1, y2 = -dy/2, dy/2
        z1, z2 = -dz/2, dz/2

        vertices = np.array([
            [x1, y1, z1], [x2, y1, z1], [x2, y2, z1], [x1, y2, z1], # Bottom
            [x1, y1, z2], [x2, y1, z2], [x2, y2, z2], [x1, y2, z2]  # Top
        ])

        # Edges for a box
        edges = np.array([
            [0, 1], [1, 2], [2, 3], [3, 0], # Bottom face
            [4, 5], [5, 6], [6, 7], [7, 4], # Top face
            [0, 4], [1, 5], [2, 6], [3, 7]  # Verticals
        ], dtype=np.uint32)

        # Flatten for Line visual (segments)
        # visuals.Box is easier but wireframe mode might be tricky with transparency.
        # Let's use Line with connect.

        if self.domain_box:
            self.domain_box.parent = None

        self.domain_box = visuals.Line(pos=vertices, connect=edges, color='yellow', width=2, parent=self.object_node)

        # Adjust camera to fit domain
        # We can set the center to (0,0,0) and distance to fit the box
        # self.view.camera.center = (0,0,0)
        # Max dimension to set range
        max_dim = max(dx, dy, dz)
        # self.view.camera.scale_factor = max_dim * 1.5

    def update_mesh_transform(self):
        if not self.mesh_vis: return

        # We assume the mesh geometry itself is centered at (0,0,0) and unscaled (raw STL units)
        # because main.py's update_mesh calls apply_translation(-center_offset).

        # 1. Calculate Target Scale
        # In FluidX3D setup: size = scale * lbm_N.x
        # Here: target_size_x = scale * domain_width

        base_size = 100.0
        ax, ay, az = self.domain_config['aspect']
        domain_width = ax * base_size
        domain_height = ay * base_size
        domain_depth = az * base_size

        target_size_x = self.domain_config['scale'] * domain_width

        # Get current mesh bounds (unscaled)
        # We need the original vertices to know the bounds.
        # mesh_vis.mesh_data.get_bounds() returns bounds.
        # Note: VisPy MeshData bounds might be None if not computed.

        # Since we don't store original raw mesh data separately easily here without modifying set_mesh signature too much,
        # we can rely on what we have.
        # But wait, we are applying transform to the Node/Visual.
        # The visual has vertices.

        # Let's get the bounds of the vertices data in the visual
        verts = self.mesh_vis.mesh_data.get_vertices()
        if verts is None or len(verts) == 0: return

        min_v = np.min(verts, axis=0)
        max_v = np.max(verts, axis=0)
        mesh_dims = max_v - min_v
        max_mesh_dim = np.max(mesh_dims)

        # FluidX3D 'voxelize_stl(..., size)' logic:
        # Usually it scales the mesh so its Largest Dimension fits 'size'.
        # OR it scales it so X fits size?
        # "const float size = {scale}f * (float)lbm_N.x;"
        # "lbm.voxelize_stl(stl_path, center, rotation, size);"
        # Standard voxelizers often treat 'size' as the scaling factor or the target size of the largest dimension.
        # Let's assume 'size' is the target length of the largest dimension of the mesh.

        if max_mesh_dim > 0:
            scale_factor = target_size_x / max_mesh_dim
        else:
            scale_factor = 1.0

        # 2. Calculate Translation (Offset)
        # FluidX3D: center = lbm.center() + offset * lbm_N
        # lbm.center() is (Nx/2, Ny/2, Nz/2).
        # Our domain center is (0,0,0).
        # Offset is relative to domain dimensions (Nx, Ny, Nz).
        # So shift = (off_x * Dx, off_y * Dy, off_z * Dz)

        off_x, off_y, off_z = self.domain_config['offset']
        shift_x = off_x * domain_width
        shift_y = off_y * domain_height
        shift_z = off_z * domain_depth

        # 3. Apply Transform
        # We need to compose Scale -> Rotate -> Translate.
        # VisPy transforms are applied in order? STTransform is Scale then Translate.
        # We need Rotation too.

        rot_x, rot_y, rot_z = self.domain_config['rot']

        # Build MatrixTransform
        tr = transforms.MatrixTransform()
        tr.scale((scale_factor, scale_factor, scale_factor))
        tr.rotate(rot_x, (1, 0, 0))
        tr.rotate(rot_y, (0, 1, 0))
        tr.rotate(rot_z, (0, 0, 1))
        tr.translate((shift_x, shift_y, shift_z))

        self.mesh_vis.transform = tr
        if self.wire_vis:
            self.wire_vis.transform = tr

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
        
        # Apply current configuration
        self.update_mesh_transform()

        if len(vertices) > 0:
            # Re-center camera on the DOMAIN, not the mesh
            self.view.camera.center = (0,0,0)
            # Adjust range to fit domain
            ax, ay, az = self.domain_config['aspect']
            base_size = 100.0
            max_dim = max(ax, ay, az) * base_size
            # set_range uses x, y, z ranges.
            # self.view.camera.set_range(x=(-max_dim/2, max_dim/2), y=(-max_dim/2, max_dim/2), z=(-max_dim/2, max_dim/2))
            # Just resetting camera state is often enough if we manually set center.
            # But let's try to frame the domain.
            self.view.camera.scale_factor = max_dim * 1.2

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