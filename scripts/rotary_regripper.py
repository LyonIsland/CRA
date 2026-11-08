"""Physical two-axis fixture prototype; loose bricks are never attached to it.

The motor drives only fixture joints. Jaw/brick friction transfers rotation.
No loose-part pose setters or brick-to-fixture joints are used by this module.
"""
import numpy as np

CENTER=np.array([.30,0.,.04])
PATH='/World/RotaryRegripper'

def add_regripper(world,stage,cube):
    from pxr import UsdGeom,UsdPhysics,PhysxSchema,UsdShade,Gf,Sdf
    from isaacsim.core.prims import SingleRigidPrim
    actors={};drives={}
    material=UsdShade.Material.Define(stage,PATH+'/PadMaterial')
    physics=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(1.5);physics.CreateDynamicFrictionAttr(1.2);physics.CreateRestitutionAttr(0.)
    for name,offset,mass in [('Pitch',[0,0,0],.06),('Roll',[0,0,0],.04),
                             ('JawLeft',[-.023,0,0],.01),('JawRight',[.023,0,0],.01)]:
        path=PATH+'/'+name;root=UsdGeom.Xform.Define(stage,path)
        root.AddTranslateOp().Set(Gf.Vec3d(*map(float,CENTER+offset)))
        UsdPhysics.RigidBodyAPI.Apply(root.GetPrim());m=UsdPhysics.MassAPI.Apply(root.GetPrim())
        m.CreateMassAttr(mass);m.CreateDiagonalInertiaAttr(Gf.Vec3f(.00002,.00002,.00002))
        actors[name]=world.scene.add(SingleRigidPrim(prim_path=path,name='regripper_'+name))
        if name.startswith('Jaw'):
            pad=cube(path+'/Pad',[0,0,0],[.004,.008,.012],[.18,.18,.18])
            contact=PhysxSchema.PhysxCollisionAPI.Apply(pad.GetPrim())
            contact.CreateContactOffsetAttr(.0001);contact.CreateRestOffsetAttr(0.)
            UsdShade.MaterialBindingAPI.Apply(pad.GetPrim()).Bind(material,materialPurpose='physics')
    for name,parent,axis in [('Pitch',None,'Y'),('Roll','Pitch','X')]:
        joint=UsdPhysics.RevoluteJoint.Define(stage,PATH+'/'+name+'Motor')
        if parent:joint.CreateBody0Rel().SetTargets([Sdf.Path(actors[parent].prim_path)])
        joint.CreateBody1Rel().SetTargets([Sdf.Path(actors[name].prim_path)])
        joint.CreateAxisAttr(axis);joint.CreateLocalPos0Attr(Gf.Vec3f(*(map(float,CENTER) if parent is None else [0,0,0])))
        joint.CreateLocalPos1Attr(Gf.Vec3f(0,0,0))
        joint.CreateLowerLimitAttr(-180.);joint.CreateUpperLimitAttr(180.)
        drive=UsdPhysics.DriveAPI.Apply(joint.GetPrim(),'angular');drive.CreateTypeAttr('acceleration')
        drive.CreateStiffnessAttr(400.);drive.CreateDampingAttr(40.);drive.CreateMaxForceAttr(.2)
        drive.CreateTargetPositionAttr(0.);drives[name]=drive
    for name,sign in [('JawLeft',-1),('JawRight',1)]:
        joint=UsdPhysics.PrismaticJoint.Define(stage,PATH+'/'+name+'Motor')
        joint.CreateBody0Rel().SetTargets([Sdf.Path(actors['Roll'].prim_path)])
        joint.CreateBody1Rel().SetTargets([Sdf.Path(actors[name].prim_path)])
        joint.CreateAxisAttr('X');joint.CreateLocalPos0Attr(Gf.Vec3f(sign*.023,0,0));joint.CreateLocalPos1Attr(Gf.Vec3f(0,0,0))
        joint.CreateLowerLimitAttr(-.019);joint.CreateUpperLimitAttr(.019)
        drive=UsdPhysics.DriveAPI.Apply(joint.GetPrim(),'linear');drive.CreateTypeAttr('force')
        drive.CreateStiffnessAttr(500.);drive.CreateDampingAttr(12.);drive.CreateMaxForceAttr(1.5)
        drive.CreateTargetPositionAttr(0.);drives[name]=drive
    # Visible stand, separate from rotating gripping pads.
    cube(PATH+'/Stand',[float(CENTER[0]),.028,.018],[.075,.012,.036],[.32,.32,.32])
    return RotaryRegripper(actors,drives)

class RotaryRegripper:
    def __init__(self,actors,drives):self.actors=actors;self.drives=drives;self.contact=None
    def command(self,closed=None,roll_deg=None,pitch_deg=None):
        if closed is not None:
            for name,sign in [('JawLeft',-1),('JawRight',1)]:
                self.drives[name].GetTargetPositionAttr().Set(float(-sign*.018 if closed else 0.))
        for name,value in [('Roll',roll_deg),('Pitch',pitch_deg)]:
            if value is not None:self.drives[name].GetTargetPositionAttr().Set(float(value))
    def watch(self,world,part_path):
        from isaacsim.core.api.sensors import RigidContactView
        self.contact=RigidContactView(prim_paths_expr=[PATH+'/JawLeft',PATH+'/JawRight'],
            filter_paths_expr=[[part_path],[part_path]],max_contact_count=128)
        self.contact.initialize(world.physics_sim_view)
    def forces(self):
        if self.contact is None:return [0.,0.]
        force=np.asarray(self.contact.get_contact_force_matrix(dt=.001))
        return np.linalg.norm(force,axis=-1).sum(axis=-1).tolist()
    def bilateral(self):return bool(np.all(np.array(self.forces())>.005))

def commission(app,world,robot,brick,stage,args):
    """Fixture-only physical test. Initial brick loading is test setup, not a robot skill."""
    import json
    from scipy.spatial.transform import Rotation
    from pick_place import Task,ROOT
    from tabletop import solve_checked,SETTINGS
    from PIL import Image
    from wrist_vision import WristRGB
    task=Task(app,world,robot,brick,stage);task.reset(0);fixture=args.rotary_regripper
    for i,part in enumerate(args.assembly_parts.values()):
        part.set_world_pose(position=np.array([.55,.3,.008+i*.025]),orientation=np.array([1.,0,0,0]))
        part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
    home=solve_checked(task.kin,SETTINGS['home']);q=robot.get_joint_positions();q[task.arm]=home;q[task.fingers]=[.025,-.025]
    robot.set_joint_positions(q);robot.set_joint_velocities(np.zeros(8))
    fixture.command(closed=False,roll_deg=0,pitch_deg=0)
    fixture.watch(world,brick.prim_path)
    for _ in range(30):task.advance(home,.025)
    brick.set_world_pose(position=CENTER.copy(),orientation=np.array([0.,1.,0,0]))
    brick.set_linear_velocity(np.zeros(3));brick.set_angular_velocity(np.zeros(3))
    world.render()
    fixture.command(closed=True)
    initial=brick.get_world_pose()[0].copy()
    if np.linalg.norm(initial-CENTER)>.001:raise RuntimeError('Fixture test initial loading did not reach fixture center')
    bilateral=0;trace=[]
    for step in range(180):
        if step==60:fixture.command(roll_deg=180.)
        task.advance(home,.025)
        p,q=brick.get_world_pose();up=float(Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()[2,2])
        if fixture.bilateral():bilateral+=1
        trace.append({'step':step,'position_m':p.tolist(),'up_z':up,'jaw_forces_N':fixture.forces()})
    final=trace[-1];passed=final['up_z']>.95 and np.linalg.norm(np.array(final['position_m'])-CENTER)<.005 and bilateral>100
    out=ROOT/'outputs/clutter';out.mkdir(exist_ok=True)
    sensor=WristRGB(world);Image.fromarray(sensor.capture()).save(out/'fixture-test.png')
    report={'passed':bool(passed),'test_scope':'fixture-only; brick initial loading is test setup, not robot loading',
        'upside_down_to_upright':final['up_z']>.95,'bilateral_contact_steps':bilateral,
        'brick_attachment_used':False,'brick_pose_writes_during_test_motion':0,
        'final':final,'trace':trace}
    (out/'fixture-test.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='trace'}),flush=True)
