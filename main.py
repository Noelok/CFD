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



//#define D2Q9 // choose D2Q9 velocity set for 2D; allocates 53 (FP32) or 35 (FP16) Bytes/cell
//#define D3Q15 // choose D3Q15 velocity set for 3D; allocates 77 (FP32) or 47 (FP16) Bytes/cell
#define D3Q19 // choose D3Q19 velocity set for 3D; allocates 93 (FP32) or 55 (FP16) Bytes/cell; (default)
//#define D3Q27 // choose D3Q27 velocity set for 3D; allocates 125 (FP32) or 71 (FP16) Bytes/cell

#define SRT // choose single-relaxation-time LBM collision operator; (default)
//#define TRT // choose two-relaxation-time LBM collision operator

#define FP16S // optional for 2x speedup and 2x VRAM footprint reduction: compress LBM DDFs to range-shifted IEEE-754 FP16; number conversion is done in hardware; all arithmetic is still done in FP32
//#define FP16C // optional for 2x speedup and 2x VRAM footprint reduction: compress LBM DDFs to more accurate custom FP16C format; number conversion is emulated in software; all arithmetic is still done in FP32


//#define BENCHMARK // disable all extensions and setups and run benchmark setup instead

//#define VOLUME_FORCE // enables global force per volume in one direction (equivalent to a pressure gradient); specified in the LBM class constructor; the force can be changed on-the-fly between time steps at no performance cost
//#define FORCE_FIELD // enables computing the forces on solid boundaries with lbm.update_force_field(); and enables setting the force for each lattice point independently (enable VOLUME_FORCE too); allocates an extra 12 Bytes/cell
#define EQUILIBRIUM_BOUNDARIES // enables fixing the velocity/density by marking cells with TYPE_E; can be used for inflow/outflow; does not reflect shock waves
//#define MOVING_BOUNDARIES // enables moving solids: set solid cells to TYPE_S and set their velocity u unequal to zero
//#define SURFACE // enables free surface LBM: mark fluid cells with TYPE_F; at initialization the TYPE_I interface and TYPE_G gas domains will automatically be completed; allocates an extra 12 Bytes/cell
//#define TEMPERATURE // enables temperature extension; set fixed-temperature cells with TYPE_T (similar to EQUILIBRIUM_BOUNDARIES); allocates an extra 32 (FP32) or 18 (FP16) Bytes/cell
#define SUBGRID // enables Smagorinsky-Lilly subgrid turbulence LES model to keep simulations with very large Reynolds number stable
//#define PARTICLES // enables particles with immersed-boundary method (for 2-way coupling also activate VOLUME_FORCE and FORCE_FIELD; only supported in single-GPU)

#define INTERACTIVE_GRAPHICS // enable interactive graphics; start/pause the simulation by pressing P; either Windows or Linux X11 desktop must be available; on Linux: change to "compile on Linux with X11" command in make.sh
//#define INTERACTIVE_GRAPHICS_ASCII // enable interactive graphics in ASCII mode the console; start/pause the simulation by pressing P
//#define GRAPHICS // run FluidX3D in the console, but still enable graphics functionality for writing rendered frames to the hard drive

#define GRAPHICS_FRAME_WIDTH 1920 // set frame width if only GRAPHICS is enabled
#define GRAPHICS_FRAME_HEIGHT 1080 // set frame height if only GRAPHICS is enabled
#define GRAPHICS_BACKGROUND_COLOR 0x000000 // set background color; black background (default) = 0x000000, white background = 0xFFFFFF
#define GRAPHICS_U_MAX 0.18f // maximum velocity for velocity coloring in units of LBM lattice speed of sound (c=1/sqrt(3)) (default: 0.18f)
#define GRAPHICS_RHO_DELTA 0.001f // coloring range for density rho will be [1.0f-GRAPHICS_RHO_DELTA, 1.0f+GRAPHICS_RHO_DELTA] (default: 0.001f)
#define GRAPHICS_T_DELTA 1.0f // coloring range for temperature T will be [1.0f-GRAPHICS_T_DELTA, 1.0f+GRAPHICS_T_DELTA] (default: 1.0f)
#define GRAPHICS_F_MAX 0.001f // maximum force in LBM units for visualization of forces on solid boundaries if VOLUME_FORCE is enabled and lbm.update_force_field(); is called (default: 0.001f)
#define GRAPHICS_Q_CRITERION 0.0001f // Q-criterion value for Q-criterion isosurface visualization (default: 0.0001f)
#define GRAPHICS_STREAMLINE_SPARSE 8 // set how many streamlines there are every x lattice points
#define GRAPHICS_STREAMLINE_LENGTH 128 // set maximum length of streamlines
#define GRAPHICS_RAYTRACING_TRANSMITTANCE 0.25f // transmitted light fraction in raytracing graphics ("0.25f" = 1/4 of light is transmitted and 3/4 is absorbed along longest box side length, "1.0f" = no absorption)
#define GRAPHICS_RAYTRACING_COLOR 0x005F7F // absorption color of fluid in raytracing graphics

//#define GRAPHICS_TRANSPARENCY 0.7f // optional: comment/uncomment this line to disable/enable semi-transparent rendering (looks better but reduces framerate), number represents transparency (equal to 1-opacity) (default: 0.7f)




{user_defines}
// #############################################################################################################

#define TYPE_S 0b00000001 // (stationary or moving) solid boundary
#define TYPE_E 0b00000010 // equilibrium boundary (inflow/outflow)
#define TYPE_T 0b00000100 // temperature boundary
#define TYPE_F 0b00001000 // fluid
#define TYPE_I 0b00010000 // interface
#define TYPE_G 0b00100000 // gas
#define TYPE_X 0b01000000 // reserved type X
#define TYPE_Y 0b10000000 // reserved type Y

#define VIS_FLAG_LATTICE  0b00000001 // lbm.graphics.visualization_modes = VIS_...|VIS_...|VIS_...;
#define VIS_FLAG_SURFACE  0b00000010
#define VIS_FIELD         0b00000100
#define VIS_STREAMLINES   0b00001000
#define VIS_Q_CRITERION   0b00010000
#define VIS_PHI_RASTERIZE 0b00100000
#define VIS_PHI_RAYTRACE  0b01000000
#define VIS_PARTICLES     0b10000000

#if defined(FP16S) || defined(FP16C)
#define fpxx ushort
#else // FP32
#define fpxx float
#endif // FP32

#ifdef BENCHMARK
#undef UPDATE_FIELDS
#undef VOLUME_FORCE
#undef FORCE_FIELD
#undef MOVING_BOUNDARIES
#undef EQUILIBRIUM_BOUNDARIES
#undef SURFACE
#undef TEMPERATURE
#undef SUBGRID
#undef PARTICLES
#undef INTERACTIVE_GRAPHICS
#undef INTERACTIVE_GRAPHICS_ASCII
#undef GRAPHICS
#endif // BENCHMARK

#ifdef SURFACE // (rho, u) need to be updated exactly every LBM step
#define UPDATE_FIELDS // update (rho, u, T) in every LBM step
#endif // SURFACE

#ifdef TEMPERATURE
#define VOLUME_FORCE
#endif // TEMPERATURE

#ifdef PARTICLES // (rho, u) need to be updated exactly every LBM step
#define UPDATE_FIELDS // update (rho, u, T) in every LBM step
#endif // PARTICLES

#if defined(INTERACTIVE_GRAPHICS) || defined(INTERACTIVE_GRAPHICS_ASCII)
#define GRAPHICS
#define UPDATE_FIELDS // to prevent flickering artifacts in interactive graphics
#endif // INTERACTIVE_GRAPHICS || INTERACTIVE_GRAPHICS_ASCII"""

# TEMPLATE SETUP: 
# - Calculates Center safely (no ambiguous max calls)
# - Forces camera update on first frame
TEMPLATE_GRAPHICS = """#pragma once

#define WINDOW_NAME "FluidX3D"
//#define INTERACTIVE_GRAPHICS
//#define INTERACTIVE_GRAPHICS_ASCII
//#define GRAPHICS

#include "defines.hpp"
#include "utilities.hpp"
#include <atomic>
#include <mutex>

extern vector<string> main_arguments; // console arguments
extern std::atomic_bool running;

#ifdef GRAPHICS
void main_label(const double frametime); // implement these three
void main_graphics();
void main_physics();

class Camera {{
public:
	int* bitmap = nullptr;
	int* zbuffer = nullptr;
	uint width = 1920u; // screen width
	uint height = 1080u; // screen height
	uint fps_limit = 60u; // default value for screen frames per second limit
	float fov = 100.0f; // field of view, default: 100
	float zoom=0.5f*(float)min(width, height), dis=0.5f*(float)width/tan(fov*pif/360.0f); // zoom, distance from camera to rotation center
	float3x3 R = float3x3(1.0f); // camera rotation matrix
	double rx=0.5*pi, ry=pi; // rotation angles
	float3 pos = float3(0.0f); // free camera position
	bool free = true; // free camera mode
	double free_camera_velocity = 1.0; // free camera speed; default: 1 cell per second
	bool vr=false, tv=false; // virtual reality mode (enables stereoscopic rendering), VR TV mode
	float eye_distance = 8.0f; // distance between cameras in VR mode
	bool autorotation = false; // autorotation
	bool lockmouse = false; // mouse movement won't change camera view when this is true
	std::atomic_bool key_update = true; // a key variable has been updated
	std::atomic_bool allow_rendering = false; // allows interactive redering if true
	std::atomic_bool allow_labeling = true; // allows drawing label if true
	std::mutex rendring_frame; // a frame for interactive graphics is currently rendered

private:
	float log_zoom=4.0f*log(zoom), target_log_zoom=log_zoom;
	double mouse_x=0.0, mouse_y=0.0, target_mouse_x=0.0, target_mouse_y=0.0; // mouse position
	double mouse_sensitivity = 1.0; // mouse sensitivity
	bool key_state[512] = {{ 0 }};

public:
	Camera(const uint width, const uint height, const uint fps_limit) {{
		this->width = width;
		this->height = height;
		this->fps_limit = fps_limit;
		bitmap = new int[width*height];
		zbuffer = new int[width*height];
		set_zoom(1.0f); // set initial zoom
		update_matrix();
	}}
	Camera() = default; // default constructor
	~Camera() {{
		delete[] bitmap;
		delete[] zbuffer;
	}}
	Camera& operator=(Camera&& camera) noexcept {{ // move assignment
		this->width = camera.width;
		this->height = camera.height;
		this->fps_limit = camera.fps_limit;
		std::swap(bitmap, camera.bitmap);
		std::swap(zbuffer, camera.zbuffer);
		set_zoom(1.0f); // set initial zoom
		update_matrix();
		return *this;
	}}

	void set_zoom(const float rad) {{
		zoom = 0.5f*(float)min(width, height)/rad;
		log_zoom = target_log_zoom = 4.0f*log(zoom);
	}}
	void update_matrix() {{
		dis = 0.5f*(float)width/tan(fov*pif/360.0f);
		const float sinrx=sin((float)rx), cosrx=cos((float)rx), sinry=sin((float)ry), cosry=cos((float)ry);
		R.xx =  cosrx;       R.xy =  sinrx;       R.xz = 0.0f;
		R.yx =  sinrx*sinry; R.yy = -cosrx*sinry; R.yz = cosry;
		R.zx = -sinrx*cosry; R.zy =  cosrx*cosry; R.zz = sinry;
		if(!free) {{
			pos.x = R.zx*dis/zoom;
			pos.y = R.zy*dis/zoom;
			pos.z = R.zz*dis/zoom;
		}}
	}}
	void set_key_state(const int key, const bool state) {{
		key_state[clamp(256+key, 0, 511)] = state;
	}}
	bool get_key_state(const int key) {{
		return key_state[clamp(256+key, 0, 511)];
	}}
	void input_key(const int key) {{
		key_update = true;
		switch(key) {{
			case 'R': input_R(); break;
			case 'U': input_U(); break;
			case 'I': input_I(); break;
			case 'J': input_J(); break;
			case 'K': input_K(); break;
			case 'L': input_L(); break;
			case 'V': input_V(); break;
			case 'B': input_B(); break;
			case '+': input_scroll_down(); break;
			case '-': input_scroll_up(); break;
			case 'F': input_F(); break;
			case 27: running=false; println(); exit(0);
		}}
#ifdef INTERACTIVE_GRAPHICS_ASCII
		if(free) {{ // move free camera
			if(key=='W') input_W();
			if(key=='A') input_A();
			if(key=='S') input_S();
			if(key=='D') input_D();
			if(key==' ') input_Space();
			if(key=='C') input_C();
		}}
		if(!lockmouse) {{
			if(key=='I') input_I(); // rotating camera with keys
			if(key=='J') input_J();
			if(key=='K') input_K();
			if(key=='L') input_L();
		}}
		if(key=='Y') input_Y(); // adjusting field of view
		if(key=='X') input_X();
		if(key=='N') input_N(); // adjust camera.vr eye distance
		if(key=='M') input_M();
#endif // INTERACTIVE_GRAPHICS_ASCII
	}}
	void update_state(const double frametime) {{
		if(!free) {{
			log_zoom = (float)exp_decay((double)log_zoom, (double)target_log_zoom, frametime, 0.083); // smoothed zoom
			zoom = exp(log_zoom*0.25f);
		}} else {{ // move free camera
			if(get_key_state('W')) input_W(frametime);
			if(get_key_state('A')) input_A(frametime);
			if(get_key_state('S')) input_S(frametime);
			if(get_key_state('D')) input_D(frametime);
			if(get_key_state(' ')) input_Space(frametime);
			if(get_key_state('C')) input_C(frametime);
		}}
		if(!lockmouse) {{
			if(get_key_state('I')) input_I(frametime); // rotate camera with keys
			if(get_key_state('J')) input_J(frametime);
			if(get_key_state('K')) input_K(frametime);
			if(get_key_state('L')) input_L(frametime);
		}}
		if(autorotation) update_rotation(-45.0*frametime, 0.0); // 45 degrees per second
		if(get_key_state('Y')) input_Y(); // adjust field of view
		if(get_key_state('X')) input_X();
		if(get_key_state('N')) input_N(); // adjust vr eye distance
		if(get_key_state('M')) input_M();
		if(!lockmouse) {{
			mouse_x = exp_decay(mouse_x, target_mouse_x, frametime, 0.031); // smoothed mouse movement
			mouse_y = exp_decay(mouse_y, target_mouse_y, frametime, 0.031);
			update_rotation(mouse_x, mouse_y);
		}} else {{
			mouse_x = mouse_y = 0.0;
		}}
		target_mouse_x = target_mouse_y = 0.0;
	}}
	void clear_frame() {{
		std::fill(bitmap, bitmap+width*height, GRAPHICS_BACKGROUND_COLOR); // faster than "for(uint i=0u; i<width*height; i++) bitmap[i] = GRAPHICS_BACKGROUND_COLOR;"
		std::fill(zbuffer, zbuffer+width*height, min_int); // faster than "for(uint i=0u; i<width*height; i++) zbuffer[i] = min_int;"
	}}
	float data(const uint i) const {{ // returns all camera data required for rendering
		switch(i) {{
			case  0: return zoom   ; // camera zoom
			case  1: return dis    ; // distance from camera to rotation center
			case  2: return free ? pos.x : 0.0f; // camera position
			case  3: return free ? pos.y : 0.0f;
			case  4: return free ? pos.z : 0.0f;
			case  5: return R.xx; // camera rotation matrix
			case  6: return R.xy;
			case  7: return R.xz;
			case  8: return R.yx;
			case  9: return R.yy;
			case 10: return R.yz;
			case 11: return R.zx;
			case 12: return R.zy;
			case 13: return R.zz;
			case 14: return as_float((uint)vr<<31|(uint)tv<<30|((uint)float_to_half(eye_distance)&0xFFFF)); // stereoscopic rendering parameters
			default: return 0.0f;
		}}
	}}

	void input_mouse_moved(const int x, const int y) {{
		if(!lockmouse) {{
			target_mouse_x = mouse_sensitivity*(double)((int)width /2-x);
			target_mouse_y = mouse_sensitivity*(double)((int)height/2-y);
		}}
	}}
	void input_mouse_dragged(const int dx, const int dy) {{
		if(!lockmouse) {{
			target_mouse_x -= mouse_sensitivity*(double)(dx);
			target_mouse_y -= mouse_sensitivity*(double)(dy);
		}}
	}}
	void input_scroll_up() {{
		if(!free) {{ // zoom
			target_log_zoom -= 1.0f;
		}} else if(!lockmouse) {{
			free_camera_velocity *= 1.284;
		}}
		key_update = true;
	}}
	void input_scroll_down() {{
		if(!free) {{ // zoom
			target_log_zoom += 1.0f;
		}} else if(!lockmouse) {{
			free_camera_velocity /= 1.284;
		}}
		key_update = true;
	}}

private:
	void input_F() {{
		free = !free;
		if(!free) {{
			zoom = exp(log_zoom*0.25f);
		}} else {{
			pos.x = R.zx*dis/zoom;
			pos.y = R.zy*dis/zoom;
			pos.z = R.zz*dis/zoom;
			zoom = 1E16f;
		}}
	}}
	void input_V() {{
		vr = !vr;
	}}
	void input_B() {{
		tv = !tv;
	}}
	void input_W(const double frametime=1.0/60.0) {{
		pos.x += R.xy*R.yz*(float)(free_camera_velocity*frametime);
		pos.y -= R.xx*R.yz*(float)(free_camera_velocity*frametime);
		pos.z -= R.zz*(float)(free_camera_velocity*frametime);
	}}
	void input_A(const double frametime=1.0/60.0) {{
		pos.x -= R.xx*(float)(free_camera_velocity*frametime);
		pos.y -= R.xy*(float)(free_camera_velocity*frametime);
	}}
	void input_S(const double frametime=1.0/60.0) {{
		pos.x -= R.xy*R.yz*(float)(free_camera_velocity*frametime);
		pos.y += R.xx*R.yz*(float)(free_camera_velocity*frametime);
		pos.z += R.zz*(float)(free_camera_velocity*frametime);
	}}
	void input_D(const double frametime=1.0/60.0) {{
		pos.x += R.xx*(float)(free_camera_velocity*frametime);
		pos.y += R.xy*(float)(free_camera_velocity*frametime);
	}}
	void input_Space(const double frametime=1.0/60.0) {{
		pos.x -= R.xy*R.zz*(float)(free_camera_velocity*frametime);
		pos.y += R.xx*R.zz*(float)(free_camera_velocity*frametime);
		pos.z -= R.yz*(float)(free_camera_velocity*frametime);
	}}
	void input_C(const double frametime=1.0/60.0) {{
		pos.x += R.xy*R.zz*(float)(free_camera_velocity*frametime);
		pos.y -= R.xx*R.zz*(float)(free_camera_velocity*frametime);
		pos.z += R.yz*(float)(free_camera_velocity*frametime);
	}}
	void input_R() {{
		autorotation = !autorotation;
	}}
	void input_U() {{
		lockmouse = !lockmouse;
	}}
	void input_I(const double frametime=1.0/60.0) {{
		if(lockmouse) {{
			double d = (ry*18.0/pi)-(double)((int)(ry*18.0f/pi));
			d = d<1E-6 ? 1.0 : 1.0-d;
			update_rotation(0.0, 10.0*d);
		}} else {{
			target_mouse_y += mouse_sensitivity*frametime*60.0;
		}}
	}}
	void input_J(const double frametime=1.0/60.0) {{
		if(lockmouse) {{
			double d = (rx*18.0/pi)-(double)((int)(rx*18.0/pi));
			d = d<1E-6 ? 1.0 : 1.0-d;
			update_rotation(10.0*d, 0.0);
		}} else {{
			target_mouse_x += mouse_sensitivity*frametime*60.0;
		}}
	}}
	void input_K(const double frametime=1.0/60.0) {{
		if(lockmouse) {{
			double d = (ry*18.0/pi)-(double)((int)(ry*18.0/pi));
			d = d<1E-6 ? 1.0f : d;
			update_rotation(0.0, -10.0*d);
		}} else {{
			target_mouse_y -= mouse_sensitivity*frametime*60.0;
		}}
	}}
	void input_L(const double frametime=1.0/60.0) {{
		if(lockmouse) {{
			double d = (rx*18.0/pi)-(double)((int)(rx*18.0/pi));
			d = d<1E-6 ? 1.0 : d;
			update_rotation(-10.0*d, 0.0);
		}} else {{
			target_mouse_x -= mouse_sensitivity*frametime*60.0;
		}}
	}}
	void input_X() {{
		fov = fmax(fov-1.0f, 1E-6f);
		dis = 0.5f*(float)width/tan(fov*pif/360.0f);
	}}
	void input_Y() {{
		fov = fmin(fov<1.0f ? 1.0f : fov+1.0f, 179.0f);
		dis = 0.5f*(float)width/tan(fov*pif/360.0f);
	}}
	void input_N() {{
		eye_distance = fmax(eye_distance-0.2f, 0.0f);
	}}
	void input_M() {{
		eye_distance += 0.2f;
	}}

	void update_rotation(const double arx, const double ary) {{
		rx += radians(arx);
		ry += radians(ary);
		rx = fmod(rx, 2.0*pi);
		ry = clamp(ry, 0.5*pi, 1.5*pi);
		update_matrix();
	}}

	double exp_decay(const double a, const double b, const double frametime, const double halflife=1.0) {{
		return b+(a-b)*exp2(-frametime/halflife);
	}}
}};

extern Camera camera;
extern bool key_E, key_G, key_H, key_O, key_P, key_Q, key_T, key_Z; // defined in graphics.cpp
extern bool key_1, key_2, key_3, key_4, key_5, key_6, key_7, key_8, key_9, key_0; // defined in graphics.cpp

#define GRAPHICS_CONSOLE // open console additionally to graphics window
#define FONT_HEIGHT 11 // default: 11
#define FONT_WIDTH 6 // default: 6

void set_light(const uint i, const float3& p);

void draw_bitmap(int* bitmap);
void draw_label(const int x, const int y, const string& s, const int color);
void draw_line_label(const int x0, const int y0, const int x1, const int y1, const int color);

void draw_pixel(const int x, const int y, const int color); // 2D drawing functions
void draw_circle(const int x, const int y, const int r, const int color);
void draw_line(const int x0, const int y0, const int x1, const int y1, const int color);
void draw_triangle(const int x0, const int y0, const int x1, const int y1, const int x2, const int y2, const int color);
void draw_rectangle(const int x0, const int y0, const int x1, const int y1, const int color);
void draw_text(const int x, const int y, const string& s, const int color);

void draw_pixel(const float3& p, const int color); // 3D drawing functions
void draw_circle(const float3& p, const float r, const int color);
void draw_line(const float3& p0, const float3& p1, const int color);
void draw_triangle(const float3& p0, const float3& p1, const float3& p2, const int color, const bool translucent=false);
void draw_triangle(const float3& p0, const float3& p1, const float3& p2, const int c0, const int c1, const int c2, const bool translucent=false);
void draw_text(const float3& p, const float r, const string& s, const int color);

#endif // GRAPHICS"""

TEMPLATE_SETUP = """#include "setup.hpp"

void main_setup() {{ // Custom
    // ################################################################## define simulation box size, viscosity and volume force ###################################################################
    const uint3 lbm_N = resolution(float3({asp_x}f, {asp_y}f, {asp_z}f), {vram}u); 
    const float lbm_Re = {re};
    const float lbm_u = 0.075f;
    const ulong lbm_T = 108000ull;
    
    // Initialize LBM
    // Note: User template uses Multi-GPU constructor style. We adapt it.
    // We add force arguments if VOLUME_FORCE is enabled (handled by python injection of args if needed, or just 0s)
    // Actually, to be safe and simple, we'll use the constructor that we know works for this version,
    // but try to mimic the template's parameters.

    // Check if we need to support force injection.
    // We will use a placeholder {lbm_constructor}
    {lbm_constructor}

    // ###################################################################################### define geometry ######################################################################################
    const float size = {scale}f * lbm.size().x;
    // UI offsets
    const float3 center = lbm.center() + float3({off_x}f*lbm.size().x, {off_y}f*lbm.size().y, {off_z}f*lbm.size().z);
    const float3x3 rotation = float3x3(1.0f); // Rotation handled by UI STL export

    lbm.voxelize_stl(get_exe_path()+"../stl/{stl_filename}", center, rotation, size);

    const uint Nx=lbm.get_Nx(), Ny=lbm.get_Ny(), Nz=lbm.get_Nz(); 
    parallel_for(lbm.get_N(), [&](ulong n) {{ 
        uint x=0u, y=0u, z=0u; 
        lbm.coordinates(n, x, y, z);
        
        if(lbm.flags[n]!=TYPE_S) {{
             lbm.u.z[n] = lbm_u; // Z-axis flow as per UI
        }}

        if(x==0u||x==Nx-1u||y==0u||y==Ny-1u||z==0u||z==Nz-1u) lbm.flags[n] = TYPE_E; // all non periodic
    }});

    // ####################################################################### run simulation, export images and data ##########################################################################
    lbm.graphics.visualization_modes = VIS_FLAG_LATTICE|VIS_FLAG_SURFACE|VIS_Q_CRITERION;
    
    // Init
    lbm.run(0u);
    
    // Set initial camera to avoid black screen
    // "Black screen" happens when camera is inside object or looking away.
    // We set a free camera looking at the domain.
    bool first_frame = true;

    while(lbm.get_t() <= lbm_T) {{
        lbm.run(1u);
        if(lbm.graphics.next_frame(lbm_T, 30.0f)) {{
            if(first_frame) {{
                 // Position camera back (-Y) and up (+Z) or similar
                 float max_dim = (float)max(Nx, max(Ny, Nz));
                 float3 look_at = float3(Nx*0.5f, Ny*0.5f, Nz*0.5f);
                 float3 cam_pos = look_at + float3(0.0f, -1.5f * max_dim, 0.8f * max_dim);
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
            static int export_frame_counter = 0;
            if (export_frame_counter % 100 == 0) {
                const string data_path = get_exe_path() + "data/";
                lbm.rho.write_device_to_vtk(data_path);
                lbm.u.write_device_to_vtk(data_path);
                lbm.flags.write_device_to_vtk(data_path);
            }
            export_frame_counter++;
            """
        
# LBM Constructor Logic
        # If VOLUME_FORCE is enabled, we need to pass force args if the constructor requires it.
        # Assuming the standard FluidX3D Multi-GPU constructor (which seems to be what the template uses):
        # LBM(uint3 N, uint Nx, uint Ny, uint Nz, float nu) -- does it take force?
        # If VOLUME_FORCE is defined, it usually takes force.
        # We'll assume: LBM(N, 1, 1, 1, nu, fx, fy, fz) if VOLUME_FORCE is on.

        force_args = ""
        if params['vol_force']:
            force_args = f", 0.0f, 0.0f, {params['force_z']}f"

        lbm_constructor = f"LBM lbm(lbm_N, 1u, 1u, 1u, units.nu_from_Re(lbm_Re, (float)lbm_N.x, lbm_u){force_args});"

        setup_content = TEMPLATE_SETUP.format(
            lbm_constructor=lbm_constructor,
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
            gra_path = os.path.join(FLUIDX3D_ROOT, "src", "graphics.hpp")

            if os.path.exists(def_path): os.remove(def_path)
            if os.path.exists(set_path): os.remove(set_path)
            if os.path.exists(gra_path): os.remove(gra_path)

            with open(def_path, "w") as f: f.write(defines_content)
            with open(set_path, "w") as f: f.write(setup_content)
            with open(gra_path, "w") as f: f.write(TEMPLATE_GRAPHICS)
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
            # Create data directory for VTK export
            data_dir = os.path.join(os.path.dirname(self.exe_path), "data")
            if not os.path.exists(data_dir):
                os.makedirs(data_dir)

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
        self.results_viewer = visualizer.ResultsViewer()
        self.view_tabs.addTab(self.results_viewer, "📊 Results (VTK)")
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
        self.btn_save_svg.setEnabled(True)
        self.btn_export_mesh.setEnabled(True)
        self.btn_build_run.setEnabled(True)

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