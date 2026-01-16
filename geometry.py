import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, Point, LineString
from shapely.ops import unary_union
import trimesh
import random

class FluidicDesign:
    def __init__(self, side_length):
        self.side_length = side_length
        self.canvas_box = Polygon([(0,0), (side_length,0), (side_length,side_length), (0,side_length)])
        self.points = None
        self.vor = None

    def initialize_points(self, num_seeds):
        self.points = np.random.rand(num_seeds, 2) * self.side_length
        for _ in range(3): 
            self.vor = Voronoi(self.points)
            new_pts = []
            for i, reg_idx in enumerate(self.vor.point_region):
                region = self.vor.regions[reg_idx]
                if -1 not in region and len(region) > 0:
                    verts = self.vor.vertices[region]
                    verts = np.clip(verts, 0, self.side_length)
                    if len(verts) >= 3:
                        poly = Polygon(verts)
                        new_pts.append([poly.centroid.x, poly.centroid.y])
                        continue
                new_pts.append(self.points[i])
            self.points = np.array(new_pts)

    def create_xy_flow_pattern(self, width):
        shapes = []
        for ridge in self.vor.ridge_vertices:
            v1, v2 = ridge
            if v1 != -1 and v2 != -1:
                p1, p2 = self.vor.vertices[v1], self.vor.vertices[v2]
                if (0 <= p1[0] <= self.side_length) or (0 <= p2[0] <= self.side_length):
                    ls = LineString([p1, p2])
                    shapes.append(ls.buffer(width/2))
        if not shapes: return Polygon()
        return unary_union(shapes).intersection(self.canvas_box)

    def create_z_pillar_pattern(self, radius):
        pillars = []
        for p in self.points:
            if random.random() > 0.2: 
                if 5 < p[0] < self.side_length-5 and 5 < p[1] < self.side_length-5:
                    pillars.append(Point(p).buffer(radius))
        if not pillars: return Polygon()
        return unary_union(pillars).intersection(self.canvas_box)

def generate_full_mesh(xy_poly, z_polys, side_length):
    if xy_poly is None or xy_poly.is_empty: return None
    
    meshes = []
    current_z = 0.0
    
    # --- CUBE CALCULATION ---
    # We want Total Height = Side Length (Cube)
    num_z_layers = len(z_polys)
    total_segments = (num_z_layers * 2) + 1
    
    # Height per layer to perfectly fill the cube
    h_layer = side_length / float(total_segments)
    
    def add_layer(poly, height, z_start):
        if poly.is_empty: return
        geoms = [poly] if poly.geom_type == 'Polygon' else list(poly.geoms)
        for g in geoms:
            # High res extrusion for smoother mesh
            m = trimesh.creation.extrude_polygon(g.simplify(0.2), height=height)
            m.apply_translation([0,0,z_start])
            meshes.append(m)

    # 1. Base XY Layer
    box = Polygon([(0,0), (side_length,0), (side_length,side_length), (0,side_length)])
    xy_mat = box.difference(xy_poly).buffer(0)
    
    add_layer(xy_mat, h_layer, current_z)
    current_z += h_layer

    # 2. Alternating Z and XY Layers
    for z_poly in z_polys:
        # Z-Pillar Layer
        add_layer(z_poly, h_layer, current_z)
        current_z += h_layer
        
        # XY Flow Layer
        add_layer(xy_mat, h_layer, current_z)
        current_z += h_layer

    if not meshes: return None
    
    combined = trimesh.util.concatenate(meshes)
    combined.merge_vertices()
    
    # Ensure correct data types before repair
    combined.vertices = combined.vertices.astype(np.float64)
    combined.faces = combined.faces.astype(np.int64)

    # --- FLUIDX3D PREP: Repair Mesh ---
    # Ensure normals are consistent and mesh is watertight.
    trimesh.repair.fix_normals(combined)
    trimesh.repair.fix_inversion(combined)
    trimesh.repair.fill_holes(combined)

    # Center at 0,0,0 (Important for FluidX3D centering)
    combined.apply_translation(-combined.centroid)
    
    return combined