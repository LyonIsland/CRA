"""Isaac Sim / PhysX basic Piper commissioning scene; no MuJoCo dependency."""
import argparse
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--headless',action='store_true')
    p.add_argument('--check',action='store_true')
    p.add_argument('--frames',type=int,default=240)
    p.add_argument('--reimport',action='store_true')
    p.add_argument('--task',choices=['scene','pick-place','xr','vision','tabletop','assembly'],default='scene')
    p.add_argument('--tabletop-mode',choices=['collect','evaluate'],default='evaluate')
    p.add_argument('--tabletop',action='store_true')
    p.add_argument('--tabletop-negative',action='store_true')
    p.add_argument('--tabletop-regression',action='store_true')
    p.add_argument('--tabletop-recovery',action='store_true')
    p.add_argument('--assembly-pick-prefix',action='store_true')
    p.add_argument('--assembly-live',action='store_true')
    p.add_argument('--assembly-random-yaw',action='store_true')
    p.add_argument('--assembly-clutter',action='store_true')
    p.add_argument('--clutter-extractions',type=int,default=6)
    p.add_argument('--clutter-fixture-test',action='store_true')
    p.add_argument('--clutter-gripper-test',action='store_true')
    p.add_argument('--clutter-collect-face',action='store_true')
    p.add_argument('--vision-mode',choices=['collect','evaluate'],default='collect')
    p.add_argument('--samples',type=int,default=256)
    p.add_argument('--wrist-vision',action='store_true')
    p.add_argument('--port',type=int,default=8875)
    p.add_argument('--seconds',type=float,default=0)
    p.add_argument('--episodes',type=int,default=1)
    p.add_argument('--seed',type=int,default=0)
    p.add_argument('--policy')
    p.add_argument('--record',action='store_true')
    p.add_argument('--baseline-open',action='store_true')
    p.add_argument('--result-name')
    p.add_argument('--graphics',choices=['vulkan','d3d12'],default='d3d12' if os.name=='nt' else 'vulkan')
    args=p.parse_args()
    if args.clutter_fixture_test or args.clutter_collect_face or args.clutter_gripper_test:args.assembly_clutter=True
    if args.assembly_clutter:args.assembly_live=True;args.assembly_random_yaw=True
    output=ROOT/'outputs'
    output.mkdir(exist_ok=True)
    if args.check:
        import datetime
        archive=output/'history'/datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
        for name in ['smoke.json','physics.json','workbench.png','failure.json']:
            path=output/name
            if path.exists():
                archive.mkdir(parents=True,exist_ok=True)
                path.replace(archive/name)
    for name in ['cache/kit','cache/config','logs']:
        (ROOT/name).mkdir(parents=True,exist_ok=True)
    # Process-scoped acceptance for the installation/use requested by the user.
    os.environ.setdefault('OMNI_KIT_ACCEPT_EULA','YES')
    from isaacsim import SimulationApp
    app=SimulationApp({'headless':args.headless,'width':1280,'height':720,
                       'renderer':'RaytracedLighting','anti_aliasing':0,'fast_shutdown':True,
                       'extra_args':[f'--/app/userConfigPath={(ROOT/"cache/config/user.config.json").as_posix()}',
                                     f'--/app/vulkan={str(args.graphics=="vulkan").lower()}',
                                     f'--/app/d3d12={str(args.graphics=="d3d12").lower()}',
                                     f'--/app/cachePath={(ROOT/"cache/kit").as_posix()}',
                                     f'--/app/logPath={(ROOT/"logs").as_posix()}']})
    try:
        import numpy as np
        import omni.kit.commands
        import omni.usd
        from pxr import UsdGeom, UsdPhysics, UsdLux, Gf, Sdf
        from isaacsim.core.api import World
        from isaacsim.core.prims import SingleArticulation, SingleRigidPrim
        from isaacsim.core.utils.extensions import enable_extension
        from isaacsim.core.utils.stage import add_reference_to_stage
        from isaacsim.core.utils.types import ArticulationAction
        from isaacsim.core.utils.viewports import set_camera_view

        robot_asset=ROOT/'generated/piper_basic.usd'
        if args.reimport or not robot_asset.exists():
            enable_extension('isaacsim.asset.importer.urdf')
            for _ in range(10): app.update()
            ok,config=omni.kit.commands.execute('URDFCreateImportConfig')
            if not ok: raise RuntimeError('URDF import configuration failed')
            config.set_fix_base(True)
            config.set_make_default_prim(True)
            config.set_create_physics_scene(False)
            config.set_merge_fixed_joints(False)
            config.set_self_collision(False)
            config.set_default_drive_strength(1000.)
            config.set_default_position_drive_damping(50.)
            ok,result=omni.kit.commands.execute('URDFParseAndImportFile',
                urdf_path=str(ROOT/'generated/piper_basic.urdf'),
                import_config=config,dest_path=str(robot_asset))
            if not ok or not robot_asset.exists():
                raise RuntimeError(f'URDF import failed: {result}')

        omni.usd.get_context().new_stage()
        stage=omni.usd.get_context().get_stage()
        UsdGeom.SetStageUpAxis(stage,UsdGeom.Tokens.z)
        UsdGeom.SetStageMetersPerUnit(stage,1.)
        world=World(stage_units_in_meters=1.,physics_dt=.001 if args.task!='scene' else 1/240.,rendering_dt=1/60.)
        add_reference_to_stage(str(robot_asset),'/World/Piper')
        roots=[str(prim.GetPath()) for prim in stage.Traverse()
               if str(prim.GetPath()).startswith('/World/Piper') and prim.HasAPI(UsdPhysics.ArticulationRootAPI)]
        if len(roots)!=1: raise RuntimeError(f'Expected one Piper articulation root, found {roots}')
        robot=world.scene.add(SingleArticulation(prim_path=roots[0],name='piper'))

        def cube(path,pos,size,color,collision=True):
            c=UsdGeom.Cube.Define(stage,path)
            c.CreateSizeAttr(1.)
            c.AddTranslateOp().Set(Gf.Vec3d(*pos))
            c.AddScaleOp().Set(Gf.Vec3f(*size))
            c.CreateDisplayColorAttr([Gf.Vec3f(*color)])
            if collision: UsdPhysics.CollisionAPI.Apply(c.GetPrim())
            return c

        # Local geometry only: no cloud asset downloads required for the table.
        cube('/World/WorkSurface',[.2,0,-.026],[1.,.8,.052],[.20,.23,.27])
        brick=UsdGeom.Xform.Define(stage,'/World/Brick')
        brick.AddTranslateOp().Set(Gf.Vec3d(.32,-.07,.035))
        UsdPhysics.RigidBodyAPI.Apply(brick.GetPrim())
        UsdPhysics.MassAPI.Apply(brick.GetPrim()).CreateMassAttr(.0023)
        cube('/World/Brick/Body',[0,0,0],[.0318,.0158,.0096],[.85,.05,.035])
        for i,x in enumerate([-.012,-.004,.004,.012]):
            for j,y in enumerate([-.004,.004]):
                stud=UsdGeom.Cylinder.Define(stage,f'/World/Brick/Stud_{i}_{j}')
                stud.CreateRadiusAttr(.0024)
                stud.CreateHeightAttr(.0018)
                stud.CreateAxisAttr('Z')
                stud.AddTranslateOp().Set(Gf.Vec3d(x,y,.0057))
                stud.CreateDisplayColorAttr([Gf.Vec3f(.85,.05,.035)])
                UsdPhysics.CollisionAPI.Apply(stud.GetPrim())
        rigid=world.scene.add(SingleRigidPrim(prim_path='/World/Brick',name='brick'))
        cube('/World/Goal',[.32,.08,.0005],[.05,.05,.001],[.05,.65,.18],False)
        assembly_parts=None
        if args.task=='assembly' or args.assembly_live:
            from assembly_scene import add_parts
            assembly_parts=add_parts(world,stage,cube,rigid)
        if args.assembly_live:
            from concept_connectors import add_fixture
            args.assembly_parts=assembly_parts
            args.assembly_fixture=add_fixture(world,stage,cube,assembly_parts)
            if args.assembly_clutter:
                from clutter_scene import add_hollow_geometry
                add_hollow_geometry(stage,cube,assembly_parts)
                args.rotary_regripper=None
                if args.clutter_fixture_test or args.clutter_collect_face:
                    from rotary_regripper import add_regripper
                    args.rotary_regripper=add_regripper(world,stage,cube)
        light=UsdLux.DomeLight.Define(stage,'/World/Light')
        light.CreateIntensityAttr(800.)
        light2=UsdLux.DistantLight.Define(stage,'/World/KeyLight')
        light2.CreateIntensityAttr(2000.)
        light2.AddRotateXYZOp().Set(Gf.Vec3f(25,-25,-30))
        camera=UsdGeom.Camera.Define(stage,'/World/Camera')
        camera.AddTransformOp().Set(Gf.Matrix4d().SetLookAt(Gf.Vec3d(.9,-.9,.7),Gf.Vec3d(.23,0,.18),Gf.Vec3d(0,0,1)).GetInverse())
        camera.CreateClippingRangeAttr(Gf.Vec2f(.01,10.))
        camera.CreateFocalLengthAttr(22.)
        camera.CreateHorizontalApertureAttr(24.)
        camera.CreateVerticalApertureAttr(18.)
        from wrist_vision import create_camera,CONFIG
        if args.assembly_clutter:CONFIG['resolution']=[640,480]
        create_camera(stage)
        import omni.kit.viewport.utility as viewport_utils
        viewport=viewport_utils.get_active_viewport()
        if viewport is not None: viewport.camera_path='/World/Camera'

        if args.task!='scene':
            from pick_place import configure_contacts
            configure_contacts(stage,roots[0],gentle=args.tabletop or args.assembly_live or args.task in ['tabletop','assembly'],couple_gripper=args.assembly_clutter)

        world.reset()
        names=list(robot.dof_names)
        print(json.dumps({'event':'articulation_ready','dof_names':names}),flush=True)
        expected=[f'joint{i}' for i in range(1,9)]
        if set(names)!=set(expected): raise RuntimeError(f'Unexpected DOFs {names}')
        home=dict(zip(expected,[0,1.2,-1.,0,.5,0,.025,-.025]))
        initial=np.array([home[n] for n in names],dtype=np.float32)
        robot.set_joint_positions(initial)
        robot.set_joint_velocities(np.zeros(len(names)))
        control=robot.get_articulation_controller()
        scene_name='workbench.usda' if args.task=='scene' else ('tabletop-negative.usda' if args.task=='tabletop' and args.tabletop_negative else ('tabletop-xr.usda' if args.task=='xr' and args.tabletop else 'pick_place.usda'))
        stage.GetRootLayer().Export(str(output/scene_name))
        if args.clutter_gripper_test:
            from commission_piper_gripper import commission
            commission(app,world,robot,rigid,stage,args)
            return
        if args.clutter_fixture_test:
            from rotary_regripper import commission
            commission(app,world,robot,rigid,stage,args)
            return
        if args.clutter_collect_face:
            from collect_clutter_face import collect
            collect(app,world,robot,rigid,stage,args)
            return
        if args.task=='assembly':
            from assembly_scene import run
            run(app,world,robot,rigid,stage,args,assembly_parts)
            return
        if args.task=='tabletop':
            from tabletop import run
            run(app,world,robot,rigid,stage,args)
            return
        if args.task=='vision':
            from wrist_vision import run
            run(app,world,robot,rigid,stage,args)
            return
        if args.task=='xr':
            from xr_bridge import run
            run(app,world,robot,rigid,stage,viewport,args)
            return
        if args.task=='pick-place':
            from pick_place import run
            run(app,world,robot,rigid,stage,viewport,args)
            return
        positions=[]
        peak_tracking=0.
        for frame in range(args.frames if args.check else 10**12):
            if not app.is_running(): break
            # A small joint1 motion validates the actual PhysX articulation.
            target=initial.copy()
            if args.check and frame>=120:
                target[names.index('joint1')]=.08*math.sin((frame-120)/120.*math.pi)
            control.apply_action(ArticulationAction(joint_positions=target))
            world.step(render=True)
            q=robot.get_joint_positions()
            pos,_=rigid.get_world_pose()
            if not np.isfinite(q).all() or not np.isfinite(pos).all():
                raise RuntimeError('Non-finite physics state')
            positions.append(pos.tolist())
            peak_tracking=max(peak_tracking,float(np.max(np.abs(q-target))))
        if args.check:
            if len(positions)!=args.frames: raise RuntimeError('Simulation ended early')
            z=positions[-1][2]
            if not .002<z<.009: raise RuntimeError(f'Brick did not settle on tabletop: {z}')
            if peak_tracking>.3: raise RuntimeError(f'Arm tracking error {peak_tracking}')
            (output/'physics.json').write_text(json.dumps({'frames':len(positions),
                'dof_names':names,'final_brick_position_m':positions[-1],
                'max_joint_tracking_error':peak_tracking,'status':'physx_passed'},indent=2))
            import omni.replicator.core as rep
            product=rep.create.render_product('/World/Camera',(960,720))
            rgb=rep.AnnotatorRegistry.get_annotator('rgb')
            rgb.attach([product])
            rep.orchestrator.set_capture_on_play(True)
            rep.orchestrator.step(rt_subframes=1,pause_timeline=False,wait_for_render=False)
            for _ in range(60): world.step(render=True)
            pixels=rgb.get_data()
            sensor_rgb_valid=pixels is not None and pixels.size>0 and pixels[:,:,:3].std()>=3
            capture_method='replicator_rgb'
            if not sensor_rgb_valid:
                rgb.detach([product.path])
                rgb=rep.AnnotatorRegistry.get_annotator('rgb',device='cuda')
                rgb.attach([product])
                rep.orchestrator.step(rt_subframes=1,pause_timeline=False,wait_for_render=False)
                for _ in range(45): world.step(render=True)
                device_pixels=rgb.get_data()
                pixels=device_pixels.numpy() if hasattr(device_pixels,'numpy') else np.asarray(device_pixels)
                sensor_rgb_valid=pixels is not None and pixels.size>0 and pixels.ndim==3 and pixels[:,:,:3].std()>=3
                capture_method='replicator_rgb_cuda' if sensor_rgb_valid else 'viewport_capture'
            from PIL import Image
            rgb_temporal_difference=None
            if sensor_rgb_valid:
                first_pixels=pixels[:,:,:3].copy()
                Image.fromarray(first_pixels).save(output/'camera_frame_a.png')
                moved=initial.copy();moved[names.index('joint1')]=.20
                for _ in range(60):
                    control.apply_action(ArticulationAction(joint_positions=moved))
                    world.step(render=True)
                next_pixels=rgb.get_data()
                pixels=next_pixels.numpy() if hasattr(next_pixels,'numpy') else np.asarray(next_pixels)
                rgb_temporal_difference=float(np.abs(pixels[:,:,:3].astype(float)-first_pixels.astype(float)).mean())
                if rgb_temporal_difference<.05:raise RuntimeError('RGB did not update after robot motion')
                Image.fromarray(pixels[:,:,:3]).save(output/'camera_frame_b.png')
                calibration={'resolution':[960,720],'K':[[880.,0.,480.],[0.,880.,360.],[0.,0.,1.]],
                             'camera_to_world':np.asarray(UsdGeom.Xformable(camera).ComputeLocalToWorldTransform(0.)).T.tolist(),
                             'camera_axes':'USD/OpenGL: +X right, +Y up, -Z forward',
                             'readback':'CUDA annotator to CPU NumPy; distortion-free perspective'}
                (output/'camera_calibration.json').write_text(json.dumps(calibration,indent=2))
                Image.fromarray(pixels[:,:,:3]).save(output/'workbench.png')
            else:
                # D3D12 sensor readback and viewport display are separate paths.
                import asyncio
                viewport.texture_resolution=(960,720)
                capture=viewport_utils.capture_viewport_to_file(viewport,str(output/'workbench.png'))
                async def wait_capture():
                    return await asyncio.wait_for(capture.wait_for_result(completion_frames=60),timeout=20.)
                captured=app.run_coroutine(wait_capture())
                if not captured or not (output/'workbench.png').exists():
                    raise RuntimeError('Both sensor RGB and viewport capture failed')
                pixels=np.asarray(Image.open(output/'workbench.png').convert('RGB'))
                if pixels.std()<3: raise RuntimeError('Viewport render lacks scene content')
                capture_method='viewport_capture'
            report={'platform':'Isaac Sim','engine':'NVIDIA PhysX','version':'5.1.0',
                    'frames':args.frames,'physics_dt':1/240.,'rendering_dt':1/60.,
                    'dof_names':names,'final_brick_position_m':positions[-1],
                    'max_joint_tracking_error':peak_tracking,
                    'status':'physics_and_viewport_render_passed',
                    'capture_method':capture_method,'sensor_rgb_passed':bool(sensor_rgb_valid),
                    'rgb_temporal_mean_absolute_difference':rgb_temporal_difference,
                    'graphics_api':args.graphics,
                    'limits':['solid-bottom brick approximation; no LEGO snap-fit',
                              'grasping, Quest Pro and BrickSim not yet validated',
                              'sensor RGB readback not validated when sensor_rgb_passed is false',
                              'robot self-collision disabled for commissioning']}
            (output/'smoke.json').write_text(json.dumps(report,indent=2))
            print(json.dumps(report),flush=True)
    except Exception as error:
        import traceback
        details=traceback.format_exc()
        print(details,flush=True)
        (output/'failure.json').write_text(json.dumps({'error':str(error),'traceback':details},indent=2))
        raise
    finally:
        app.close(wait_for_replicator=False)

if __name__=='__main__':
    main()
