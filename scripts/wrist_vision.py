"""Eye-in-hand RGB localization; simulation truth is confined to labels/evaluation."""
import json
import time
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config/wrist_camera.json').read_text())

def create_camera(stage):
    from pxr import UsdGeom,Gf
    if not stage.GetPrimAtPath('/World/Piper/link6').IsValid():
        raise RuntimeError('Missing wrist link6')
    camera=UsdGeom.Camera.Define(stage,CONFIG['path'])
    camera.AddTranslateOp().Set(Gf.Vec3d(*CONFIG['mount_translation_m']))
    camera.AddRotateXYZOp().Set(Gf.Vec3f(*CONFIG['mount_rotation_xyz_deg']))
    camera.CreateClippingRangeAttr(Gf.Vec2f(.008,3.))
    camera.CreateFocalLengthAttr(CONFIG['focal_length_mm'])
    camera.CreateHorizontalApertureAttr(CONFIG['horizontal_aperture_mm'])
    camera.CreateVerticalApertureAttr(CONFIG['vertical_aperture_mm'])
    return camera

def camera_pose(kin,q):
    # Encoder FK + calibrated hand-eye transform, never object truth.
    tcp,r=kin.forward(q)
    wrist=tcp-r@np.array([0,0,.1308])
    t=np.eye(4);t[:3,:3]=r@Rotation.from_euler('xyz',CONFIG['mount_rotation_xyz_deg'],degrees=True).as_matrix()
    t[:3,3]=wrist+r@np.array(CONFIG['mount_translation_m'])
    return t

def intrinsics():
    w,h=CONFIG['resolution']
    return np.array([[w*CONFIG['focal_length_mm']/CONFIG['horizontal_aperture_mm'],0,w/2],
                     [0,h*CONFIG['focal_length_mm']/CONFIG['vertical_aperture_mm'],h/2],[0,0,1.]])

def project(point,pose):
    p=pose[:3,:3].T@(point-pose[:3,3])
    cv=p*np.array([1,-1,-1])
    uv=intrinsics()@cv
    return uv[:2]/uv[2],cv[2]

def unproject(uv,pose):
    ray=pose[:3,:3]@(np.linalg.inv(intrinsics())@np.r_[uv,1.]*[1,-1,-1])
    distance=(CONFIG['brick_top_z_m']-pose[2,3])/ray[2]
    if distance<=0:raise ValueError('Image ray does not intersect the work surface')
    point=pose[:3,3]+distance*ray
    point[2]=.0048
    return point

class WristRGB:
    def __init__(self,world):
        import omni.replicator.core as rep
        self.world=world
        self.last_rgb=None;self.last_capture_wall_time=0.;self.capture_sequence=0
        self.last_capture_ms=0.;self.preview_time_delta_max=0.
        self.product=rep.create.render_product(CONFIG['path'],tuple(CONFIG['resolution']))
        self.rgb=rep.AnnotatorRegistry.get_annotator('rgb',device='cuda')
        self.rgb.attach([self.product])
        # Explicit captures only. Automatic capture on every XR render can race
        # the CUDA buffer readback when rendering and inference are interleaved.
        rep.orchestrator.set_capture_on_play(False)
        rep.orchestrator.step(rt_subframes=1,pause_timeline=False,wait_for_render=False)
        for _ in range(8):world.render()
    def capture(self,preview=False):
        # Render only: taking an image must not advance the physical episode clock.
        import omni.replicator.core as rep
        started=time.monotonic();physics_time=self.world.current_time
        self.world.render()
        for i in range(3):
            rep.orchestrator.step(delta_time=0.,rt_subframes=1 if preview else 4,pause_timeline=False,wait_for_render=True)
            try:
                a=self.rgb.get_data();a=a.numpy() if hasattr(a,'numpy') else np.asarray(a)
                if a.ndim==3 and a.size:
                    self.last_rgb=a[:,:,:3].copy();self.last_capture_wall_time=time.monotonic()
                    self.last_capture_ms=(self.last_capture_wall_time-started)*1000
                    self.capture_sequence+=1
                    if preview:
                        delta=abs(self.world.current_time-physics_time)
                        self.preview_time_delta_max=max(self.preview_time_delta_max,float(delta))
                        if delta>1e-8:raise RuntimeError('Preview unexpectedly advanced physics time')
                    return self.last_rgb
            except RuntimeError:
                if i==2:raise
        raise RuntimeError('Wrist RGB readback empty')

class VisualController:
    """Replace privileged position observations with RGB and encoder estimates."""
    def __init__(self,task,sensor):
        import torch
        from vision_model import Localizer
        from policy import Policy
        torch.set_num_threads(2)
        self.torch=torch;self.task=task;self.sensor=sensor
        self.model=Localizer().cpu()
        self.model.load_state_dict(torch.load(ROOT/'outputs/vision/localizer.pt',map_location='cpu',weights_only=True))
        self.model.eval();self.policy=Policy(ROOT/'outputs/policy.npz')
        self.source=None;self.confidence=0.;self.last_rgb=None;self.last_uv=None
        self.goal=task.goal.copy()  # commanded destination, not sensed object state
        # Fixed scan pose independent of randomized brick location. Otherwise the
        # old reset's source-relative hover would leak object position via q.
        scan,error=task.kin.solve([.32,-.07,.095],[-.2,1.5,-1.2,0,1.2,0])
        if error>.001:raise RuntimeError('Fixed visual scan pose is unreachable')
        full=task.robot.get_joint_positions();full[task.arm]=scan
        task.robot.set_joint_positions(full);task.robot.set_joint_velocities(np.zeros(8))
        for _ in range(15):task.advance(scan,.025)
        task.target=task.tcp.copy()
        self.update()
    def update(self):
        from vision_model import decode
        torch=self.torch
        rgb=self.sensor.capture()
        x=torch.from_numpy(rgb.copy()).permute(2,0,1)[None].float()/255
        x=torch.nn.functional.avg_pool2d(x,2)
        with torch.no_grad():
            logits=self.model(x);uv=decode(logits)[0].numpy()
            confidence=logits.sigmoid().max().item()
        if confidence<.5:raise RuntimeError('Wrist visual detection uncertain; motion stopped')
        point=unproject(uv,camera_pose(self.task.kin,self.task.q))
        if not (.22<point[0]<.42 and -.18<point[1]<.18):
            raise RuntimeError('Visual estimate outside calibrated workspace; motion stopped')
        self.source=point;self.confidence=confidence;self.last_rgb=rgb;self.last_uv=uv
        return point
    def observation(self):
        task=self.task
        if task.phase<2 and task.steps%10==0:self.update()
        # During closed-finger transport, use a grasp-centered kinematic estimate.
        # The brick is not welded; physical success is measured independently.
        obj=self.source if task.phase<2 else (task.tcp-[0,0,.0008] if task.phase<=5 else self.goal)
        q=task.robot.get_joint_positions();v=task.robot.get_joint_velocities()
        ordered=[task.names.index(f'joint{i}') for i in range(1,9)]
        return np.r_[task.tcp,obj,self.goal,q[ordered],obj-task.tcp,
                     self.goal-obj,np.eye(8)[task.phase],self.source,task.target,v[ordered]].astype(np.float32)
    def action(self):return self.policy(self.observation())

def run(app,world,robot,brick,stage,args):
    from pick_place import Task
    from PIL import Image
    task=Task(app,world,robot,brick,stage);task.reset(args.seed)
    sensor=WristRGB(world)
    out=ROOT/'outputs/vision';out.mkdir(exist_ok=True)
    if args.vision_mode=='evaluate':
        return evaluate(task,sensor,args,out)
    rng=np.random.default_rng(args.seed)
    images=[];pixels=[];poses=[];points=[]
    for i in range(args.samples):
        source=np.array([rng.uniform(.30,.34),rng.uniform(-.10,-.04),.0048])
        aim=source+np.r_[rng.uniform(-.015,.015,2),rng.uniform(.065,.10)]
        q,error=task.kin.solve(aim,task.q)
        if error>.001:
            if i<8:print(json.dumps({'rejected_ik':i,'error_m':error,'aim':aim.tolist(),'q':task.q.tolist()}),flush=True)
            continue
        # Dataset-only interventions. These are not available to the visual controller.
        brick.set_world_pose(position=source,orientation=np.array([1.,0,0,0]))
        brick.set_linear_velocity(np.zeros(3));brick.set_angular_velocity(np.zeros(3))
        full=robot.get_joint_positions();full[task.arm]=q
        robot.set_joint_positions(full);robot.set_joint_velocities(np.zeros(8))
        task.advance(q,.025)
        # Flush PhysX transforms to the renderer before synchronizing image/label.
        world.render()
        pose=camera_pose(task.kin,task.q)
        rgb=sensor.capture()
        source=task.object.copy()  # dataset label only
        if i==0:
            from pxr import UsdGeom
            usd_pose=np.asarray(UsdGeom.Xformable(stage.GetPrimAtPath(CONFIG['path'])).ComputeLocalToWorldTransform(0.)).T
            if np.max(np.abs(pose-usd_pose))>1e-4:
                raise RuntimeError('Encoder FK / rendered camera pose mismatch; reject dataset')
            print(json.dumps({'fk_camera':pose.tolist(),'usd_camera':usd_pose.tolist(),'source':source.tolist()}),flush=True)
        uv,depth=project(source+[0,0,.0048],pose)
        if depth<=0 or np.any(uv<[12,12]) or np.any(uv>np.array(CONFIG['resolution'])-12):
            if i<8:print(json.dumps({'rejected_fov':i,'uv':uv.tolist(),'depth':float(depth)}),flush=True)
            continue
        images.append(rgb);pixels.append(uv);poses.append(pose);points.append(source)
        if i%32==0:
            Image.fromarray(rgb).save(out/f'wrist_sample_{i:04}.png')
            print(json.dumps({'sample':i,'uv':uv.tolist(),'captured':len(images)}),flush=True)
    if not images:raise RuntimeError('No valid labeled wrist RGB images collected')
    np.savez_compressed(out/'localization.npz',images=np.array(images),pixels=np.array(pixels),
                        camera_to_world=np.array(poses),points=np.array(points))
    (out/'dataset.json').write_text(json.dumps({'samples':len(images),'seed':args.seed,
        'sensor':'wrist RGB','label_source':'simulated brick top-center projection',
        'runtime_inputs':['RGB','joint encoders','camera intrinsics','hand-eye calibration'],
        'camera':CONFIG},indent=2))
    print(json.dumps({'dataset_samples':len(images)}),flush=True)

def evaluate(task,sensor,args,out):
    from pick_place import DURATIONS
    from PIL import Image,ImageDraw
    results=[]
    for ep in range(args.episodes):
        task.reset(args.seed+ep)
        try:
            controller=VisualController(task,sensor)
            error=float(np.linalg.norm(controller.source[:2]-task.object[:2]))  # evaluation only
            for step in range(sum(DURATIONS)):
                info=task.step(controller.action())
            result={'seed':args.seed+ep,'controller':'wrist_rgb_plus_BC',
                    'initial_visual_xy_error_m':error,'confidence':controller.confidence,**info}
            np.save(out/f'visual_trace_{args.seed+ep}.npy',np.array(task.trace))
            if ep==0:
                image=Image.fromarray(controller.last_rgb);draw=ImageDraw.Draw(image)
                u,v=controller.last_uv;draw.ellipse((u-4,v-4,u+4,v+4),outline='yellow',width=2)
                image.save(out/'detection.png')
        except RuntimeError as error:
            result={'seed':args.seed+ep,'success':False,'error':str(error),'stopped':True}
        results.append(result)
        print(json.dumps(result),flush=True)
    import hashlib
    report={'runtime_object_ground_truth_used':False,
            'truth_usage_scope':'labels, physics and success/error evaluation only; not action inputs',
            'fixed_scan_pose_independent_of_object':True,
            'localizer_sha256':hashlib.sha256((out/'localizer.pt').read_bytes()).hexdigest(),
            'runtime_inputs':['wrist RGB','joint encoders','calibration','commanded goal','phase clock'],
            'method':'trained RGB keypoint CNN + geometric unprojection + existing BC action policy',
            'episodes':results,'successes':sum(r['success'] for r in results),
            'limits':['fixed red 2x4 brick, fixed yaw, known tabletop height',
                      'kinematic object estimate during transport; no visual slip detection',
                      'no real camera or real robot validation']}
    (out/'evaluation.json').write_text(json.dumps(report,indent=2))
