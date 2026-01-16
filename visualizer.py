import numpy as np
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout, QFileDialog, QButtonGroup, QGroupBox, QSlider, QGridLayout, QProgressDialog, QApplication
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

try:
    import pyvista as pv
    from pyvistaqt import QtInteractor
    PYVISTA_AVAILABLE = True
except ImportError:
    PYVISTA_AVAILABLE = False

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
        self.object_node = vispy.scene.Node(parent=self.view.scene)
        # self.object_node.transform = transforms.STTransform(scale=(1, 1, -1))
        
        self.mesh_vis = None
        self.wire_vis = None
        
        # Lines for particles/streamlines
        self.lines_vis = visuals.Line(parent=self.object_node, width=4.0, antialias=True)
        
        # Domain Box
        self.domain_box = None

        # Grid
        self.grid = visuals.GridLines(color=(0.3, 0.3, 0.3, 0.5), parent=self.view.scene)
        # self.grid.transform = transforms.STTransform(scale=(1, 1, -1))
 

    def set_mesh(self, vertices, faces):
        if self.mesh_vis: self.mesh_vis.parent = None
        if self.wire_vis: self.wire_vis.parent = None
        
        # Ensure faces are of an integer type for indexing, uint32 is safe
        faces = faces.astype(np.uint32)
        
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
            # Calculate bounds
            min_v = np.min(vertices, axis=0)
            max_v = np.max(vertices, axis=0)
            center_v = (min_v + max_v) / 2
            
            # CENTER THE MESH AT (0,0,0) LOCAL SPACE
            # This ensures rotations are around the center, matching FluidX3D
            vertices = vertices - center_v
            
            # Recalculate bounds after centering (should be symmetric around 0)
            self.mesh_bounds = (min_v - center_v, max_v - center_v)
            
            # Update mesh data with centered vertices
            self.mesh_vis.set_data(vertices=vertices, faces=faces)
            self.wire_vis.set_data(vertices=vertices, faces=faces)
            
            # Set camera to view the origin (where the mesh now is)
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

    def draw_domain_box(self, width, height, depth, center=(0,0,0)):
        """Draws a wireframe box representing the simulation domain boundaries."""
        if self.domain_box:
            self.domain_box.parent = None
        
        # VisPy Box is centered at (0,0,0) with given dimensions
        self.domain_box = visuals.Box(width=width, height=height, depth=depth, 
                                      color=(0, 1, 0, 0.1), edge_color=(0, 1, 0, 1.0),
                                      parent=self.view.scene)
        # Apply translation to position the box correctly
        # Note: 'center' arg here refers to the domain center in world coordinates
        self.domain_box.transform = transforms.STTransform(translate=center)

    def update_transform(self, scale, off_x, off_y, off_z, rot_x, rot_y, rot_z, domain_size):
        """
        Updates the transform of the object node relative to the domain.
        
        args:
            scale: float, uniform scale
            off_x, off_y, off_z: float, offset relative to domain size (e.g. 0.5 = half domain)
            rot_x, rot_y, rot_z: float, degrees
            domain_size: tuple (x, y, z) in world units
        """
        if not self.mesh_vis: return

        dx, dy, dz = domain_size
        
        # 1. Start with Identity
        tr = transforms.MatrixTransform()
        
        # 2. Scale (Mesh is scaled relative to Z-axis of domain as per FluidX3D logic)
        # In main.py: size = scale * lbm.size().z
        # So visual scale factor = (scale * dz) / mesh_original_z ??? 
        # No, FluidX3D scales the *entire mesh* such that its bounding box max dimension? 
        # Wait, let's look at setup.cpp template: 
        # "const float size = {scale}f*lbm.size().z;" -> This is the target size in simulation units.
        # "lbm.voxelize_stl(..., size);" -> The 'size' argument usually sets the max dimension of the mesh.
        
        # To simulate this in VisPy without re-voxelizing/re-loading:
        # We need to know the mesh's original bounding box.
        # But for 'preview' purposes, we can just apply a rough visual scale.
        # Let's assume the mesh is normalized or we just apply the relative scale x domain_z
        
        # SIMULATION LOGIC RECAP:
        # FluidX3D Voxelize: Scales mesh so its *largest dimension* equals `size`.
        # `size` is calculated as `scale_param * domain_depth`.
        
        # We don't have the mesh's original bbox here easily unless we stored it.
        # Let's store it in set_mesh.
        
        # Transformations are applied in order: Rotate -> Translate
        # FluidX3D logic: Voxelize at 'center', with 'rotation'.
        # Center = domain_center + offset * domain_size
        
        # Transformations are applied in order: Rotate -> Translate
        # FluidX3D logic defined in C++: float3x3(Rx) * float3x3(Ry) * float3x3(Rz) * v
        # This implies: v is rotated by Z, then by Y, then by X.
        # To replicate this in VisPy (where transforms accumulate):
        # We must apply Z, then Y, then X.
        
        tr.rotate(rot_z, (0, 0, 1))
        tr.rotate(rot_y, (0, 1, 0))
        tr.rotate(rot_x, (1, 0, 0))
        
        # Handle Scaling
        # We need to scale the mesh so its max dimension = scale * dz
        if hasattr(self, 'mesh_bounds'):
            max_dim = max(self.mesh_bounds[1] - self.mesh_bounds[0])
            if max_dim > 0:
                target_size = scale * dz
                s_factor = target_size / max_dim
                tr.scale((s_factor, s_factor, s_factor))
        
        # Handle Translation
        # Domain Center in world coords
        # Let's assume World Origin (0,0,0) is Domain Center for visualization simplicity?
        # Or if we draw the domain box at (0,0,0), then offsets are just relative to that.
        # Let's keep existing logic: The mesh is at (0,0,0) in object space.
        # We move it to:
        # tx = off_x * dx
        # ty = off_y * dy
        # tz = off_z * dz
        # (Assuming the domain box is centered at 0,0,0 in the view)
        
        tr.translate((off_x * dx, off_y * dy, off_z * dz))
        
        self.object_node.transform = tr



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

from PyQt5.QtCore import Qt

class ResultsViewer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        
        if not PYVISTA_AVAILABLE:
            self.layout.addWidget(QLabel("Error: PyVista not installed."))
            return

        # Top Bar
        h_bar = QHBoxLayout()
        self.btn_load = QPushButton("📂 Load VTK/VTI File")
        self.btn_load.clicked.connect(self.load_file)
        h_bar.addWidget(self.btn_load)
        self.lbl_info = QLabel("No file loaded.")
        h_bar.addWidget(self.lbl_info)
        
        # View Controls
        self.btn_surf = QPushButton("🧊 Surface")
        self.btn_surf.setCheckable(True)
        self.btn_surf.setChecked(True)
        self.btn_surf.clicked.connect(lambda: self.set_mode('surface'))
        h_bar.addWidget(self.btn_surf)
        
        self.btn_slice = QPushButton("🔪 Slice")
        self.btn_slice.setCheckable(True)
        self.btn_slice.clicked.connect(lambda: self.set_mode('slice'))
        h_bar.addWidget(self.btn_slice)
        
        self.btn_vol = QPushButton("☁️ Volume")
        self.btn_vol.setCheckable(True)
        self.btn_vol.clicked.connect(lambda: self.set_mode('volume'))
        h_bar.addWidget(self.btn_vol)

        # Exclusive buttons
        self.grp = QButtonGroup(self)
        self.grp.addButton(self.btn_surf)
        self.grp.addButton(self.btn_slice)
        self.grp.addButton(self.btn_vol)
        
        self.layout.addLayout(h_bar)
        
        # PyVista Plotter
        self.plotter = QtInteractor(self)
        self.layout.addWidget(self.plotter.interactor)
        self.plotter.add_axes()
        self.plotter.set_background("#2b2b2b")
        
        self.mesh = None
        self.mesh_bounds = None
        self.scalar_name = None
        self.mode = 'surface'
        self.manual_slice_active = False
        self.manual_slices = None
        self.slice_helpers_actors = []

    def load_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Load Result", "", "VTK Files (*.vtk *.vti *.vtu *.ply *.stl)")
        if path:
            self.show_data(path)
            
    def set_mode(self, mode):
        # Progress Feedback
        progress = QProgressDialog(f"Switching to {mode.title()} Mode...", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        
        try:
            self.mode = mode
            self.manual_slice_active = False 
            self.clear_slice_helpers()
            self.refresh_plot()
        finally:
            progress.close()

    def show_data(self, path):
        try:
            self.mesh = pv.read(path)
            self.mesh_bounds = self.mesh.bounds
            
            # Init Volume Defaults if missing
            if not hasattr(self, 'vol_threshold'): self.vol_threshold = 0.2
            if not hasattr(self, 'vol_opacity'): self.vol_opacity = 0.5
            
            self.scalar_name = None
            range_str = ""
            
            if self.mesh.n_arrays > 0:
                # Default to active scalars or the first available array
                raw_name = self.mesh.active_scalars_name if self.mesh.active_scalars_name else self.mesh.array_names[0]
                
                # Check if it's a vector (e.g., Velocity with 3 components)
                data = self.mesh[raw_name]
                if len(data.shape) > 1 and data.shape[1] == 3:
                     # Compute Magnitude
                     self.mesh['Magnitude'] = np.linalg.norm(data, axis=1)
                     self.scalar_name = 'Magnitude'
                     data_to_measure = self.mesh['Magnitude']
                else:
                     self.scalar_name = raw_name
                     data_to_measure = data
                
                # Check data range
                if data_to_measure is not None:
                    d_min, d_max = data_to_measure.min(), data_to_measure.max()
                    range_str = f"Min: {d_min:.4f}, Max: {d_max:.4f}"
                    if d_max == 0:
                        range_str += " [⚠️ EMPTY/ZERO]"
                else:
                    range_str = "No Data"
            
            self.lbl_info.setText(f"Loaded: {path.split('/')[-1]} | {self.scalar_name} | {range_str}")
            self.manual_slice_active = False
            self.refresh_plot()
            self.plotter.reset_camera()
            
        except Exception as e:
            self.lbl_info.setText(f"Error: {str(e)}")
            
    def update_volume_params(self, threshold, opacity):
        self.vol_threshold = threshold
        self.vol_opacity = opacity
        if self.mode == 'volume':
            self.refresh_plot()
            
    def clear_slice_helpers(self):
        for actor in self.slice_helpers_actors:
            self.plotter.remove_actor(actor)
        self.slice_helpers_actors.clear()

    def update_slice_preview(self, x_pct, y_pct, z_pct):
        if self.mesh is None or self.mesh_bounds is None: return
        
        # Clear previous
        self.clear_slice_helpers()
        
        xmin, xmax, ymin, ymax, zmin, zmax = self.mesh_bounds
        dx, dy, dz = xmax-xmin, ymax-ymin, zmax-zmin
        
        cx = xmin + dx * (x_pct/1000.0)
        cy = ymin + dy * (y_pct/1000.0)
        cz = zmin + dz * (z_pct/1000.0)
        
        # Helper to add plane and label
        def add_plane(center, direction, i_s, j_s, color, name):
            p = pv.Plane(center=center, direction=direction, i_size=i_s, j_size=j_s)
            a = self.plotter.add_mesh(p, color=color, opacity=0.25, show_edges=True, edge_color=color)
            self.slice_helpers_actors.append(a)
            # Add Label
            l = self.plotter.add_point_labels([center], [name], point_color=color, text_color=color, font_size=24, show_points=False)
            self.slice_helpers_actors.append(l)

        # X Plane (Red)
        add_plane((cx, ymin+dy/2, zmin+dz/2), (1,0,0), dy, dz, 'red', f"X Plane")
        
        # Y Plane (Green)
        add_plane((xmin+dx/2, cy, zmin+dz/2), (0,1,0), dx, dz, 'green', f"Y Plane")

        # Z Plane (Blue)
        add_plane((xmin+dx/2, ymin+dy/2, cz), (0,0,1), dx, dy, 'blue', f"Z Plane")

    def apply_cut(self, x_pct, y_pct, z_pct):
        if self.mesh is None or self.mesh_bounds is None: return
        
        xmin, xmax, ymin, ymax, zmin, zmax = self.mesh_bounds
        dx, dy, dz = xmax-xmin, ymax-ymin, zmax-zmin
        
        cx = xmin + dx * (x_pct/1000.0)
        cy = ymin + dy * (y_pct/1000.0)
        cz = zmin + dz * (z_pct/1000.0)
        
        # Progress Feedback
        progress = QProgressDialog("Computing Slices... (This may take a moment)", None, 0, 0, self)
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.show()
        QApplication.processEvents()
        
        try:
             # Generate 3 orthogonal slices
             s1 = self.mesh.slice(normal='x', origin=(cx, cy, cz))
             s2 = self.mesh.slice(normal='y', origin=(cx, cy, cz))
             s3 = self.mesh.slice(normal='z', origin=(cx, cy, cz))
             
             # Combine them
             self.manual_slices = s1 + s2 + s3
             self.manual_slice_active = True
             self.refresh_plot()
        except Exception as e:
            self.lbl_info.setText(f"Cut Error: {e}")
        finally:
            progress.close()

    def refresh_plot(self):
        if self.mesh is None: return
        self.plotter.clear()
        self.clear_slice_helpers()
        
        try:
            if self.mode == 'surface':
                self.plotter.add_mesh(self.mesh, scalars=self.scalar_name, show_edges=False, cmap="jet")
            elif self.mode == 'slice':
                if self.manual_slice_active and self.manual_slices:
                    # Show the computed data slices
                    self.plotter.add_mesh(self.manual_slices, scalars=self.scalar_name, cmap="jet")
                else:
                    # Show Outline only (User will use sliders to show planes)
                    self.plotter.add_mesh(self.mesh, style='wireframe', color='white', opacity=0.1)
            elif self.mode == 'volume':
                # Custom Opacity based on sliders
                # Sigmoid is good default, but let's shift it based on threshold
                # If threshold is 0.3, we want 0-0.3 to be transparent.
                # opacity=[0, ..., 0, val, ..., 1]
                t = getattr(self, 'vol_threshold', 0.2)
                o = getattr(self, 'vol_opacity', 0.5)
                
                # Simple logic: 5 points transfer function
                # 0.0 -> 0 opacity
                # t   -> 0 opacity
                # t+  -> o * 0.2
                # 1.0 -> o * 1.0
                # We need to map this to data range? PyVista maps automatically to scalar range.
                # But we need to ensure the "zero" part covers the threshold.
                # Actually, easier to use 'sigmoid' and shift the contrast? 
                # Let's use the list mapping:
                # [0, threshold, threshold+small, 1.0] -> [0, 0, opacity/2, opacity]
                
                # Better: [0, 0, 0, 0.1, 0.3, 0.6, 1.0] scaled by opacity multiplier.
                # And zero out the first N items based on threshold.
                
                base = [0.0, 0.0, 0.0, 0.1, 0.3, 0.6, 1.0]
                # Scale threshold to the length of the base list (e.g., 0.2 * 7 = 1.4, so first 1-2 elements are zeroed)
                cutoff_idx = int(t * len(base)) 
                
                final_op = []
                for i, val in enumerate(base):
                    if i < cutoff_idx:
                        final_op.append(0.0)
                    else:
                        final_op.append(val * o)
                
                self.plotter.add_volume(self.mesh, scalars=self.scalar_name, cmap="jet", opacity=final_op)
        except Exception as e:
            print(f"Plot error: {e}")
            self.plotter.add_mesh(self.mesh, scalars=self.scalar_name, cmap="jet")
