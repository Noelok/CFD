@echo off
cd /d "D:\projects\vinci4d\CFD\FluidX3D-master"
echo Compiling...
cl /std:c++17 /O2 /EHsc src/main.cpp src/lbm.cpp src/setup.cpp src/graphics.cpp src/info.cpp src/kernel.cpp src/lodepng.cpp src/shapes.cpp /Fe:bin\FluidX3D.exe /Fobin\ /I. /Isrc /I "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\include" "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.6\lib\x64\OpenCL.lib" User32.lib Gdi32.lib Shell32.lib
if %errorlevel% neq 0 exit /b %errorlevel%
echo Build Success.
