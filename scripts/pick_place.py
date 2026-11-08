"""Isaac Sim physical grasp/place baseline, with explicit evidence and failures."""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from kinematics import PiperKinematics

ROOT=Path(__file__).resolve().parents[1]
PHASES=['approach','descend','close','lift','transfer','lower','release','retreat']
DURATIONS=[45,40,35,50,70,50,30,45]

def configure_contacts(stage,root,gentle=False,couple_gripper=False):
    from pxr import Usd,UsdGeom,UsdPhysics,PhysxSchema,Gf,UsdShade
    material=UsdShade.Material.Define(stage,'/World/GraspMaterial')
    physics_material=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics_material.CreateStaticFrictionAttr(1.2); physics_material.CreateDynamicFrictionAttr(1.)
    physics_material.CreateRestitutionAttr(0.)
    for name in ['link7','link8']:
        finger=stage.GetPrimAtPath('/World/Piper/'+name)
        if not finger.IsValid(): raise RuntimeError(f'Missing {name}')
        # Imported collision meshes live below instance roots. stage.Traverse()
        # skips their proxy children, so make only the collision instances local
        # before disabling them; visual instances remain shared.
        instances=[prim for prim in stage.Traverse()
                   if str(prim.GetPath()).startswith(str(finger.GetPath())+'/collisions') and prim.IsInstance()]
        for prim in instances:prim.SetInstanceable(False)
        for prim in list(stage.Traverse()):
            if str(prim.GetPath()).startswith(str(finger.GetPath())+'/') and prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI(prim).CreateCollisionEnabledAttr(False)
        for prim in Usd.PrimRange(finger,Usd.TraverseInstanceProxies()):
            if '/collisions/' in str(prim.GetPath()) and prim.HasAPI(UsdPhysics.CollisionAPI):
                if UsdPhysics.CollisionAPI(prim).GetCollisionEnabledAttr().Get():
                    raise RuntimeError(f'Original finger collision remained active: {prim.GetPath()}')
        pad=UsdGeom.Cube.Define(stage,str(finger.GetPath())+'/GraspPad')
        pad.CreateSizeAttr(1.)
        pad.AddTranslateOp().Set(Gf.Vec3d(0,-.005,.002))
        pad.AddScaleOp().Set(Gf.Vec3f(.020,.008,.004))
        pad.CreateDisplayColorAttr([Gf.Vec3f(.1,.1,.1)])
        UsdPhysics.CollisionAPI.Apply(pad.GetPrim())
        UsdShade.MaterialBindingAPI.Apply(pad.GetPrim()).Bind(material,materialPurpose='physics')
    for prim in stage.Traverse():
        path=str(prim.GetPath())
        if prim.HasAPI(UsdPhysics.CollisionAPI) and (path.startswith('/World/Brick') or path.endswith('/GraspPad')):
            collision=PhysxSchema.PhysxCollisionAPI.Apply(prim)
            collision.CreateContactOffsetAttr(.0004); collision.CreateRestOffsetAttr(0.)
            UsdShade.MaterialBindingAPI.Apply(prim).Bind(material,materialPurpose='physics')
        if prim.IsA(UsdPhysics.RevoluteJoint):
            # The importer authored acceleration drives with zero damping.
            # For k=625 s^-2, critical damping is 2*sqrt(k)=50 s^-1.
            drive=UsdPhysics.DriveAPI.Apply(prim,'angular')
            drive.CreateTypeAttr('acceleration'); drive.CreateStiffnessAttr(625.)
            drive.CreateDampingAttr(50.)
        if prim.IsA(UsdPhysics.PrismaticJoint):
            drive=UsdPhysics.DriveAPI.Apply(prim,'linear')
            drive.CreateTypeAttr('force'); drive.CreateStiffnessAttr(500. if gentle else 1500.)
            drive.CreateDampingAttr(12. if gentle else 5.); drive.CreateMaxForceAttr(1.5 if gentle else 8.)
    articulation=PhysxSchema.PhysxArticulationAPI.Apply(stage.GetPrimAtPath(root))
    articulation.CreateSolverPositionIterationCountAttr(32)
    articulation.CreateSolverVelocityIterationCountAttr(8)
    if couple_gripper:
        joints={p.GetName():p for p in stage.Traverse()
            if str(p.GetPath()).startswith('/World/Piper/') and p.IsA(UsdPhysics.PrismaticJoint)}
        master,follower=joints['joint7'],joints['joint8']
        # PhysX uses q_follower + gearing*q_master + offset = 0.
        # This models the parallel gripper transmission, never a brick joint.
        # As in PhysX's prismatic mimic test, single-DOF joints use rotX;
        # the instance/reference axis is ignored for this joint type.
        follower.RemoveAPI(UsdPhysics.DriveAPI,'linear')
        mimic=PhysxSchema.PhysxMimicJointAPI.Apply(follower,UsdPhysics.Tokens.rotX)
        mimic.CreateReferenceJointRel().SetTargets([master.GetPath()])
        mimic.CreateReferenceJointAxisAttr(UsdPhysics.Tokens.rotX)
        mimic.CreateGearingAttr(1.);mimic.CreateOffsetAttr(0.)

class Task:
    def __init__(self,app,world,robot,brick,stage):
        self.app,self.world,self.robot,self.brick,self.stage=app,world,robot,brick,stage
        self.kin=PiperKinematics(ROOT/'generated/piper_basic.urdf')
        self.names=list(robot.dof_names)
        self.arm=[self.names.index(f'joint{i}') for i in range(1,7)]
        self.fingers=[self.names.index('joint7'),self.names.index('joint8')]
        self.controller=robot.get_articulation_controller()
        from isaacsim.core.api.sensors import RigidContactView
        self.contacts=RigidContactView(prim_paths_expr=['/World/Piper/link7','/World/Piper/link8'],
            filter_paths_expr=[['/World/Brick'],['/World/Brick']],max_contact_count=64)

    @property
    def q(self): return self.robot.get_joint_positions()[self.arm]
    @property
    def tcp(self): return self.kin.forward(self.q)[0]
    @property
    def object(self): return self.brick.get_world_pose()[0]

    def advance(self,q,opening,render=False):
        from isaacsim.core.utils.types import ArticulationAction
        target=np.zeros(8,dtype=np.float32)
        target[self.arm]=q; target[self.fingers]=[opening,-opening]
        self.controller.apply_action(ArticulationAction(joint_positions=target))
        for _ in range(20): self.world.step(render=False)
        if render: self.world.render()

    def reset(self,seed):
        rng=np.random.default_rng(seed)
        self.world.reset()
        self.contacts.initialize(self.world.physics_sim_view)
        self.source=np.array([.32,-.07,.0048]);self.source[:2]+=rng.uniform(-.012,.012,2)
        self.goal=np.array([.32,.08,.0048]);self.goal[:2]+=rng.uniform(-.012,.012,2)
        self.brick.set_world_pose(position=self.source+np.array([0,0,.002]),orientation=np.array([1.,0,0,0]))
        self.brick.set_linear_velocity(np.zeros(3)); self.brick.set_angular_velocity(np.zeros(3))
        q,error=self.kin.solve(self.source+[0,0,.09],[-.2,1.5,-1.2,0,1.2,0])
        if error>.002: raise RuntimeError(f'Initial IK error {error}')
        full=np.zeros(8,dtype=np.float32);full[self.arm]=q;full[self.fingers]=[.025,-.025]
        self.robot.set_joint_positions(full);self.robot.set_joint_velocities(np.zeros(8))
        for _ in range(15): self.advance(q,.025)
        self.target=self.tcp.copy(); self.phase=0
        self.peak=self.object[2]; self.stable=0; self.lift_frames=0; self.bilateral_lift_frames=0
        self.steps=0; self.trace=[]

    def observation(self):
        q=self.robot.get_joint_positions(); v=self.robot.get_joint_velocities()
        ordered=[self.names.index(f'joint{i}') for i in range(1,9)]
        return np.r_[self.tcp,self.object,self.goal,q[ordered],self.object-self.tcp,
                     self.goal-self.object,np.eye(8)[self.phase],self.source,self.target,v[ordered]].astype(np.float32)

    def expert(self):
        if self.phase==0: target=self.source+[0,0,.075]
        elif self.phase in [1,2]: target=self.source+[0,0,.0008]
        elif self.phase==3: target=self.source+[0,0,.075]
        elif self.phase==4: target=self.goal+[0,0,.075]
        elif self.phase in [5,6]: target=self.goal+[0,0,.0008]
        else: target=self.goal+[0,0,.085]
        return np.r_[np.clip((target-self.target)/.004,-1,1),-1. if 2<=self.phase<=5 else 1.].astype(np.float32)

    def step(self,action,render=False):
        action=np.clip(action,-1,1)
        self.target=np.clip(self.target+action[:3]*.004,[.22,-.18,.0053],[.42,.18,.22])
        q,error=self.kin.solve(self.target,self.q)
        opening=.003+(action[3]+1)*.011
        self.advance(q,opening,render)
        pos=self.object; tcp=self.tcp
        self.peak=max(self.peak,pos[2])
        self.lift_frames+=int(pos[2]>.04)
        forces=np.asarray(self.contacts.get_contact_force_matrix(dt=.001))
        magnitudes=np.linalg.norm(forces,axis=-1).sum(axis=-1)
        bilateral=len(magnitudes)==2 and bool(np.all(magnitudes>.001))
        self.bilateral_lift_frames+=int(bilateral and pos[2]>.04)
        speed=np.linalg.norm(self.brick.get_linear_velocity())
        _,quat=self.brick.get_world_pose()
        upright=Rotation.from_quat(np.r_[quat[1:],quat[0]]).as_matrix()[2,2]>.98
        released=self.phase>=6 and min(abs(self.robot.get_joint_positions()[self.fingers]))>.020
        error_xy=np.linalg.norm(pos[:2]-self.goal[:2])
        stable=released and not bilateral and error_xy<.012 and .002<pos[2]<.012 and speed<.015 and upright
        self.stable=self.stable+1 if stable else 0
        clear=np.linalg.norm(tcp-pos)>.05
        success=self.peak>.055 and self.bilateral_lift_frames>=5 and self.stable>=15 and clear
        result={'success':bool(success),'peak_height_m':float(self.peak),'lift_frames':self.lift_frames,
                'goal_error_m':float(error_xy),'stable_steps':self.stable,'released':bool(released),
                'upright':bool(upright),'tcp_clear':bool(clear),'ik_error_m':error,
                'bilateral_lift_frames':self.bilateral_lift_frames,'finger_contact_forces_N':magnitudes.tolist(),
                'brick_position':pos.tolist(),'tcp':tcp.tolist()}
        self.trace.append(np.r_[self.world.current_time,self.phase,tcp,pos,action,self.robot.get_joint_positions()])
        self.steps+=1
        self.phase=min(7,int(np.searchsorted(np.cumsum(DURATIONS),self.steps,side='right')))
        return result

def run(app,world,robot,brick,stage,viewport,args):
    task=Task(app,world,robot,brick,stage)
    observations=[];actions=[];episode_ids=[];results=[]
    label=args.result_name or ('negative_open' if args.baseline_open else ('policy_evaluation' if args.policy else 'demonstrations'))
    if Path(label).name!=label:raise ValueError('Result name must be a simple filename stem')
    policy=None
    rgb=None;writer=None;video_frames=0
    if args.record:
        import omni.replicator.core as rep
        import imageio.v2 as imageio
        product=rep.create.render_product('/World/Camera',(960,720))
        rgb=rep.AnnotatorRegistry.get_annotator('rgb',device='cuda')
        rgb.attach([product])
        rep.orchestrator.set_capture_on_play(True)
        rep.orchestrator.step(rt_subframes=1,pause_timeline=False,wait_for_render=False)
        writer=imageio.get_writer(str(ROOT/'outputs'/f'{label}.mp4'),fps=25,codec='libx264')
    if args.policy:
        from policy import Policy
        policy=Policy(args.policy)
    for ep in range(args.episodes):
        task.reset(args.seed+ep)
        eo=[];ea=[]
        for step in range(sum(DURATIONS)):
            phase=task.phase
            obs=task.observation(); action=policy(obs) if policy else task.expert()
            if args.baseline_open: action[3]=1.
            eo.append(obs);ea.append(action)
            info=task.step(action,render=step%2==0 and (bool(writer) or not args.headless))
            if writer and step%2==0:
                pixels=rgb.get_data()
                pixels=pixels.numpy() if hasattr(pixels,'numpy') else np.asarray(pixels)
                if pixels.ndim==3 and pixels.size:
                    writer.append_data(pixels[:,:,:3])
                    video_frames+=1
            if ep==0 and step%25==0:
                print(json.dumps({'phase':PHASES[phase],'step':step,**info}),flush=True)
        result={'seed':args.seed+ep,'controller':'policy' if policy else 'expert',
                'arm_drive':{'type':'acceleration','stiffness':625.,'damping':50.},**info}
        results.append(result)
        print(json.dumps(result),flush=True)
        if info['success']:
            observations.extend(eo);actions.extend(ea);episode_ids.extend([ep]*len(eo))
        np.save(ROOT/'outputs'/f'{label}_trace_{args.seed+ep}.npy',np.array(task.trace))
    if writer:
        writer.close()
        (ROOT/'outputs'/f'{label}_video.json').write_text(json.dumps({'controller':'learned_policy' if policy else 'expert',
            'seeds':[r['seed'] for r in results],'frames':video_frames,'fps':25,'source':'Isaac Sim CUDA RGB annotator'},indent=2))
    (ROOT/'outputs'/f'{label}.json').write_text(json.dumps(results,indent=2))
    if not policy and not args.baseline_open:
        np.savez_compressed(ROOT/'outputs'/f'{label}.npz',observations=np.array(observations),
                            actions=np.array(actions),episode_ids=np.array(episode_ids))
    print(json.dumps({'episodes':len(results),'successes':sum(r['success'] for r in results),'artifact':label}),flush=True)
