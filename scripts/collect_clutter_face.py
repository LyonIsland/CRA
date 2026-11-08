"""Synthetic RGB labels for isolated upright-vs-non-upright verification only."""
import json
import numpy as np
from scipy.spatial.transform import Rotation
from assembly_agent import ROOT
from assembly_perception import COLORS
from clutter_perception import FACES,MODEL
from clutter_face_model import patch
from rotary_regripper import CENTER
from tabletop import solve_checked,SETTINGS
from wrist_vision import WristRGB,camera_pose

def collect(app,world,robot,brick,stage,args):
    from pxr import Usd,UsdGeom,UsdPhysics,Gf
    from pick_place import Task
    from PIL import Image
    UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath(brick.prim_path)).CreateKinematicEnabledAttr(True)
    for actor in args.rotary_regripper.actors.values():
        UsdPhysics.RigidBodyAPI(stage.GetPrimAtPath(actor.prim_path)).CreateKinematicEnabledAttr(True)
    for prim in Usd.PrimRange(stage.GetPrimAtPath('/World/RotaryRegripper')):
        if prim.IsA(UsdPhysics.Joint):UsdPhysics.Joint(prim).CreateJointEnabledAttr(False)
    task=Task(app,world,robot,brick,stage);task.reset(0)
    for i,part in enumerate(args.assembly_parts.values()):
        part.set_world_pose(position=np.array([.55,.30,.03+i*.025]),orientation=np.array([1.,0,0,0]))
        part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
    home=solve_checked(task.kin,SETTINGS['home']);q=robot.get_joint_positions();q[task.arm]=home;q[task.fingers]=[.025,-.025]
    robot.set_joint_positions(q);robot.set_joint_velocities(np.zeros(8));args.rotary_regripper.command(closed=False,roll_deg=0,pitch_deg=0)
    for _ in range(30):task.advance(home,.025)
    world.render();sensor=WristRGB(world);rng=np.random.default_rng(args.seed)
    out=ROOT/'outputs/clutter_face';out.mkdir(exist_ok=True)
    images=[];labels=[];records=[];names=list(COLORS);faces=list(FACES)
    gprims=[p for p in Usd.PrimRange(stage.GetPrimAtPath(brick.prim_path)) if p.IsA(UsdGeom.Gprim)]
    def place_render_actor(actor,position,rotation):
        quat=rotation.as_quat()
        actor.set_world_pose(position=position,orientation=np.r_[quat[3],quat[:3]])
        for op in UsdGeom.Xformable(stage.GetPrimAtPath(actor.prim_path)).GetOrderedXformOps():
            if op.GetOpType()==UsdGeom.XformOp.TypeTranslate:op.Set(Gf.Vec3d(*map(float,position)))
            elif op.GetOpType()==UsdGeom.XformOp.TypeOrient:
                value=Gf.Quatf(float(quat[3]),Gf.Vec3f(*map(float,quat[:3]))) if op.GetPrecision()==UsdGeom.XformOp.PrecisionFloat else Gf.Quatd(float(quat[3]),Gf.Vec3d(*map(float,quat[:3])))
                op.Set(value)
        actor._prim_view._physics_view.set_kinematic_targets(np.r_[position,quat][None].astype(np.float32),np.array([0],dtype=np.uint32))
    fixture_rotations=[Rotation.identity(),Rotation.from_euler('x',90,degrees=True),Rotation.from_euler('x',180,degrees=True),
        Rotation.from_euler('x',-90,degrees=True),Rotation.from_euler('y',90,degrees=True),Rotation.from_euler('y',-90,degrees=True)]
    for i in range(args.samples):
        color=names[(i//20)%len(names)]
        if i%20==0:
            for p in gprims:UsdGeom.Gprim(p).CreateDisplayColorAttr([Gf.Vec3f(*COLORS[color])])
        face='up' if rng.random()<.5 else str(rng.choice(faces[1:]))
        yaw=float(rng.uniform(-180,180));r=Rotation.from_euler('z',yaw,degrees=True)*Rotation.from_euler('xyz',FACES[face],degrees=True)
        r=r*Rotation.from_euler('xy',rng.uniform(-15,15,2),degrees=True)
        fixture_rotation=fixture_rotations[int(rng.integers(len(fixture_rotations)))];axis=fixture_rotation.as_matrix()[:,0]
        # Real friction grasps can hold a part off-centre across the jaw pads,
        # not only along their closing axis. Keep pads at the fixture's own
        # lateral centre so rendered occlusion matches those physical grasps.
        position=CENTER+rng.uniform([-.012,-.012,-.006],[.012,.012,.006])
        place_render_actor(brick,position,r)
        projections=(MODEL@r.as_matrix().T)@axis
        axial=float(axis@(position-CENTER))
        place_render_actor(args.rotary_regripper.actors['JawLeft'],CENTER+axis*(axial+projections.min()-.002),fixture_rotation)
        place_render_actor(args.rotary_regripper.actors['JawRight'],CENTER+axis*(axial+projections.max()+.002),fixture_rotation)
        world.step(render=False)
        actual=brick.get_world_pose()[0]
        if np.linalg.norm(actual-position)>.001:raise RuntimeError('Rendered-label kinematic pose did not reach requested station position: '+str(actual))
        rgb=sensor.capture();pose=camera_pose(task.kin,task.q);x=patch(rgb,pose,color)
        if int((x[0]>.5).sum())<60:
            Image.fromarray(rgb).save(out/'invalid-crop.png')
            continue
        images.append((x*255).round().astype(np.uint8));labels.append(int(face=='up'))
        records.append({'color':color,'face':face,'yaw_deg':yaw,'position_m':position.tolist(),
            'rotation_matrix':r.as_matrix().tolist(),'fixture_rotation_matrix':fixture_rotation.as_matrix().tolist()})
        if i<6 or i%200==0:Image.fromarray(rgb).save(out/f'sample_{i:04}.png')
        if i%100==0:print(json.dumps({'face_samples':i,'total':args.samples}),flush=True)
    if len(images)<args.samples*.85:raise RuntimeError('Too many rendered samples were not visibly inspectable')
    np.savez_compressed(out/'dataset.npz',images=np.stack(images),labels=np.array(labels,dtype=np.int64))
    (out/'dataset.json').write_text(json.dumps({'samples':len(images),'seed':args.seed,'camera':'ordinary wrist RGB',
        'scope':'isolated-station upright verification only; not pile pose or grasp training',
        'labels':'synthetic simulator orientation labels; not controller input',
        'kinematic_part_used_for_rendered_training_data':True,'physical_grasp_demonstrations':False,
        'kinematic_fixture_used_for_rendered_training_data':True,'closed_jaw_occlusion':True,
        'pads_follow_fixture_lateral_centre':True,'xyz_offset_range_m':[.012,.012,.006],
        'records':records},indent=2))
