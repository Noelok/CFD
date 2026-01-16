#include "setup.hpp"

void main_setup() { // Custom; required extensions in defines.hpp: FP16S, EQUILIBRIUM_BOUNDARIES, SUBGRID, INTERACTIVE_GRAPHICS or GRAPHICS
    // ################################################################## define simulation box size, viscosity and volume force ###################################################################
    const uint3 lbm_N = resolution(float3(2.0f, 1.0f, 1.0f), 3000u); // input: simulation box aspect ratio and VRAM occupation in MB, output: grid resolution
    const float lbm_Re = 10000000.0f;
    const float lbm_u = 0.075f;
    const ulong lbm_T = 108000ull;
    LBM lbm(lbm_N, 1u, 1u, 1u, units.nu_from_Re(lbm_Re, (float)lbm_N.x, lbm_u)); // run on 1x1x1 = 1 GPU
    // ###################################################################################### define geometry ######################################################################################
    const float size = 0.5f*lbm.size().z;
    const float3 center = float3(lbm.center().x + -0.25f*lbm.size().x, lbm.center().y + 0.0f*lbm.size().y, lbm.center().z + 0.0f*lbm.size().z);
    const float3x3 rotation = float3x3(float3(1, 0, 0), radians(0.0f))*float3x3(float3(0, 1, 0), radians(0.0f))*float3x3(float3(0, 0, 1), radians(0.0f));
    Clock clock;
    lbm.voxelize_stl(get_exe_path()+"../stl/sim_geometry_1768548057.stl", center, rotation, size);
    println(print_time(clock.stop()));
    const uint Nx=lbm.get_Nx(), Ny=lbm.get_Ny(), Nz=lbm.get_Nz(); parallel_for(lbm.get_N(), [&](ulong n) { uint x=0u, y=0u, z=0u; lbm.coordinates(n, x, y, z);
        if(lbm.flags[n]!=TYPE_S) lbm.u.x[n] = lbm_u;
        if(x==0u||x==Nx-1u||y==0u||y==Ny-1u||z==0u||z==Nz-1u) lbm.flags[n] = TYPE_E; // all non periodic
    }); // ####################################################################### run simulation, export images and data ##########################################################################
    lbm.graphics.visualization_modes = VIS_FLAG_LATTICE|VIS_FLAG_SURFACE|VIS_Q_CRITERION;
    
    // FORCE CUSTOM LOOP (Removed preprocessor checks to ensure this runs)
    lbm.write_status();
    lbm.run(0u, lbm_T); // initialize simulation
    
    while(lbm.get_t()<=lbm_T && running) { // main simulation loop
        // Handle VTK Export Trigger (key_9)
        if(key_9) {
            print_info("Export triggered by key_9. Saving snapshot...");
            string manual_path = R"(D:/projects/vinci4d/CFD/FluidX3D-master/bin/export/)";
            
            lbm.u.write_device_to_vtk(manual_path);
            lbm.rho.write_device_to_vtk(manual_path);
            lbm.flags.write_device_to_vtk(manual_path);
            #ifdef FORCE_FIELD
            lbm.F.write_device_to_vtk(manual_path);
            #endif
            
            key_9 = false; // Reset trigger
            print_info("Snapshot saved to " + manual_path);
        }

        // Handle Pause locally (since we removed it from LBM::run)
        if(!key_P) {
            sleep(0.016);
            continue;
        }

        lbm.run(20u, lbm_T); // Run slightly larger batches for better efficiency
    }
    lbm.write_status();
} /**/
