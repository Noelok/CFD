import warp as wp
import numpy as np
import ctypes
import os

# --- Initialization & Fallback ---
WARP_AVAILABLE = False
WP_DEVICE = "cpu"

try:
    wp.init()
    if wp.is_cuda_available():
        WP_DEVICE = "cuda"
    WARP_AVAILABLE = True
except Exception as e:
    print(f"❌ Warp failed to initialize: {e}")

# --- WARP KERNEL (Run on GPU) ---
@wp.kernel
def trace_grid_streamlines(
    points: wp.array2d(dtype=wp.vec3),    # [NumLines, MaxSteps]
    colors: wp.array2d(dtype=wp.vec4),    # [NumLines, MaxSteps]
    velocity_field: wp.array4d(dtype=wp.vec3), # [Nx, Ny, Nz, 3]
    grid_res: int,
    dt: float,
    max_steps: int,
    emit_center: wp.vec3,
    emit_scale: float
):
    idx = wp.tid()
    
    # 1. Initialize Particle (Reset to Emitter)
    # We seed them randomly around the emitter center in Grid Space
    state = wp.rand_init(1234, idx)
    
    # Random offset in a disk perpendicular to Z (assuming flow is roughly Z)
    rx = wp.randf(state) * 2.0 - 1.0
    ry = wp.randf(state) * 2.0 - 1.0
    
    start_pos = emit_center + wp.vec3(rx, ry, 0.0) * emit_scale * 0.5
    
    p = start_pos
    
    # 2. Trace Loop
    for i in range(max_steps):
        # Store current position
        points[idx, i] = p
        
        # Color based on speed (placeholder)
        colors[idx, i] = wp.vec4(0.0, 0.8, 1.0, 1.0) # Cyan
        
        # 3. Sample Velocity from 3D Grid (Nearest Neighbor for speed)
        # Casting float position to int index
        ix = int(p[0])
        iy = int(p[1])
        iz = int(p[2])
        
        v = wp.vec3(0.0, 0.0, 0.0)
        
        # Bounds Check (0..256)
        if (ix >= 0 and ix < grid_res and 
            iy >= 0 and iy < grid_res and 
            iz >= 0 and iz < grid_res):
            
            # Read from FluidX3D field
            v = velocity_field[ix, iy, iz]
            
            # Speed coloring
            speed = wp.length(v)
            if speed > 0.05:
                colors[idx, i] = wp.vec4(1.0, 0.3, 0.0, 1.0) # Red/Orange for fast
            else:
                colors[idx, i] = wp.vec4(0.0, 0.5, 1.0, 0.5) # Blue for slow

        # 4. Advect
        p = p + v * dt

class FluidX3DSolver:
    def __init__(self, stl_path, mesh_max_dim, resolution=256):
        if not WARP_AVAILABLE:
            raise ImportError("Warp not available")

        self.resolution = resolution
        self.cells = resolution**3
        
        # --- 1. Load C++ DLL ---
        dll_name = "fluid_wrapper.dll"
        dll_path = os.path.abspath(dll_name)
        if not os.path.exists(dll_path):
             raise FileNotFoundError(f"DLL not found at {dll_path}")
             
        self.lib = ctypes.CDLL(dll_path)
        
        # Define Arguments
        self.lib.fluid_init.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float, ctypes.c_char_p]
        self.lib.fluid_step.argtypes = [ctypes.c_int]
        ptr_type = np.ctypeslib.ndpointer(dtype=np.float32, flags='C_CONTIGUOUS')
        self.lib.fluid_get_velocity.argtypes = [ptr_type, ptr_type, ptr_type]

        # --- 2. Initialize Simulation ---
        # Viscosity=0.01, Pump Force=0.0005
        print(f"🌊 Initializing FluidX3D with {resolution}^3 grid...")
        self.lib.fluid_init(resolution, 0.01, 0.0005, stl_path.encode('utf-8'))
        
        # --- 3. Coordinate Systems ---
        # FluidX3D scales the mesh to fit 90% of the box (N*0.9)
        # We need to calculate this scale to map World <-> Grid
        self.sim_scale_factor = (resolution * 0.9) / mesh_max_dim
        self.grid_center = resolution / 2.0
        
        # --- 4. Prepare Memory ---
        # CPU Buffers for transfer
        self.vx = np.ascontiguousarray(np.zeros(self.cells, dtype=np.float32))
        self.vy = np.ascontiguousarray(np.zeros(self.cells, dtype=np.float32))
        self.vz = np.ascontiguousarray(np.zeros(self.cells, dtype=np.float32))
        
        # Warp GPU Buffers
        self.device = WP_DEVICE
        self.wp_field = wp.zeros((resolution, resolution, resolution, 3), dtype=wp.vec3, device=self.device)
        
        self.num_lines = 2000
        self.steps = 200
        self.lines_pos = wp.zeros((self.num_lines, self.steps), dtype=wp.vec3, device=self.device)
        self.lines_col = wp.zeros((self.num_lines, self.steps), dtype=wp.vec4, device=self.device)

    def update(self):
        # A. Run Physics (C++)
        self.lib.fluid_step(20) # 20 LBM steps per frame
        
        # B. Get Velocity (GPU -> CPU)
        self.lib.fluid_get_velocity(self.vx, self.vy, self.vz)
        
        # C. Upload to Warp (CPU -> GPU)
        # Stack and reshape to 3D grid
        # FluidX3D layout: x + y*Nx + z*Nx*Ny. This matches numpy 'F' (Fortran) order reshape usually
        flat = np.stack((self.vx, self.vy, self.vz), axis=1)
        grid = flat.reshape((self.resolution, self.resolution, self.resolution, 3), order='F')
        
        wp.copy(self.wp_field, wp.array(grid, dtype=wp.vec3, device=self.device))
        
        # D. Trace Streamlines (Warp GPU)
        # Emitter: Start at bottom of grid (Z=10)
        emit_pos = wp.vec3(self.resolution/2, self.resolution/2, 10.0) 
        
        wp.launch(
            kernel=trace_grid_streamlines,
            dim=self.num_lines,
            inputs=[
                self.lines_pos, self.lines_col, self.wp_field, 
                self.resolution, 
                1.0, # dt for tracing (visual speed)
                self.steps,
                emit_pos,
                self.resolution * 0.5 # Emitter width
            ],
            device=self.device
        )
        wp.synchronize()

    def get_render_data(self):
        # Get points in Grid Space
        pts_grid = self.lines_pos.numpy()
        cols = self.lines_col.numpy().reshape(-1, 4)
        
        # Transform Grid Space -> World Space for VisPy
        # World = (Grid - Center) / Scale
        pts_world = (pts_grid - self.grid_center) / self.sim_scale_factor
        
        return pts_world.reshape(-1, 3), cols, self.num_lines, self.steps

    def cleanup(self):
        if self.lib:
            self.lib.fluid_cleanup()