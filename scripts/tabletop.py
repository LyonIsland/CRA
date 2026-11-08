"""Active wrist RGB search and feedback-driven tabletop pick/place.

No source position is passed to the controller. Object truth is restricted to
scene setup, supervised labels and independent evaluation. Motion is geometric
feedback control, not a claim that the old local BC generalizes globally.
"""
import json
from pathlib import Path
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares
from scipy.ndimage import label
from wrist_vision import WristRGB,camera_pose,project,unproject,ROOT,CONFIG

SETTINGS=json.loads((ROOT/'config/tabletop.json').read_text())
OUT=ROOT/'outputs/tabletop'
SEED=np.array([0.,1.5,-1.2,0.,1.2,0.])

def solve_checked(kin,point,seed=None):
    yaw=float(np.arctan2(point[1],point[0]))
    guesses=[np.asarray(seed) if seed is not None else np.r_[yaw,SEED[1:5],yaw],
             np.r_[yaw,1.8,-1.5,0.,1.2,yaw]]
    for guess in guesses:
        q,e=kin.solve(point,guess)
        rot_error=np.linalg.norm(Rotation.from_matrix(kin.desired_rotation@kin.forward(q)[1].T).as_rotvec())
        if e<.0008 and rot_error<.012:return q
    return None

def admitted(kin,xy):
    xy=np.asarray(xy,dtype=float)
    lo,hi=np.array(SETTINGS['candidate_bounds_xy'])
    if xy.shape!=(2,) or not np.isfinite(xy).all() or np.any(xy<lo) or np.any(xy>hi):return False
    if np.linalg.norm(xy)<SETTINGS['minimum_base_distance_m']:return False
    return all(solve_checked(kin,np.r_[xy,z]) is not None for z in [.0056,.08,.09])

def workspace_points(kin):
    return [list(map(float,[x,y])) for x in np.linspace(.12,.39,10) for y in np.linspace(-.28,.28,15)
            if admitted(kin,[x,y])]

def setup(task,source,goal=None):
    """Environment setup only, never called from controller.step()."""
    task.reset(0)
    home=solve_checked(task.kin,SETTINGS['home'])
    full=task.robot.get_joint_positions();full[task.arm]=home
    task.robot.set_joint_positions(full);task.robot.set_joint_velocities(np.zeros(8))
    task.brick.set_world_pose(position=np.r_[source[:2],.0068],orientation=np.array([1.,0,0,0]))
    task.brick.set_linear_velocity(np.zeros(3));task.brick.set_angular_velocity(np.zeros(3))
    task.goal=np.array(goal if goal is not None else SETTINGS['default_goal'],dtype=float)
    from pxr import UsdGeom,Gf
    ops=UsdGeom.Xformable(task.stage.GetPrimAtPath('/World/Goal')).GetOrderedXformOps()
    ops[0].Set(Gf.Vec3d(float(task.goal[0]),float(task.goal[1]),.0005))
    for _ in range(15):task.advance(home,.025)

class TabletopController:
    def __init__(self,task,sensor,goal):
        import torch
        from vision_model import Localizer
        torch.set_num_threads(2);self.torch=torch
        self.task=task;self.sensor=sensor;self.goal=np.asarray(goal,dtype=float).copy()
        if not admitted(task.kin,self.goal[:2]):raise RuntimeError('指定放置位置不可达，请在工作区内选择。')
        self.model=Localizer().cpu()
        self.model.load_state_dict(torch.load(OUT/'localizer.pt',map_location='cpu',weights_only=True));self.model.eval()
        self.phase='search';self.scan=0;self.steps=0;self.phase_steps=0;self.stable=0
        self.source=None;self.last_rgb=sensor.capture();self.last_uv=None;self.confidence=0.
        self.done=False;self.failed=False;self.message='正在用腕部相机搜索积木。'
        self.found_from_scan=None;self.history=[];self.contact_lift_steps=0;self.lost_contact=0
        self.alignment_checks=0;self.last_ik_error=0.;self.contact_streak=0
        self.command=task.tcp.copy()
        self.carry_offset=np.zeros(2);self.detections=[]
        self.grasp_offset=np.zeros(2);self.carry_estimate_method=None
        self.retries=0;self.unilateral_streak=0;self.recovery_xy=None
        from isaacsim.core.api.sensors import RigidContactView
        self.table_contact=RigidContactView(prim_paths_expr='/World/Brick',
            filter_paths_expr=[['/World/WorkSurface']],max_contact_count=64)
        self.table_contact.initialize(task.world.physics_sim_view)

    def transition(self,phase):
        self.history.append({'phase':self.phase,'control_steps':self.phase_steps})
        self.phase=phase;self.phase_steps=0;self.stable=0
        if phase=='lift':self.grasp_offset=self.source[:2]-self.task.tcp[:2]
        if phase=='release':
            self.release_height=max(.012,float(self.task.tcp[2])+.006)
            self.command=self.task.tcp.copy()
        labels={'search':'搜索积木','approach':'已找到积木，移动至上方','align':'视觉精确对准',
                'descend':'下降抓取','close':'闭合夹爪并确认接触','lift':'抬起积木',
                'via_source':'搬运至通道','via_goal':'沿通道搬运','transfer':'移动到指定位置上方',
                'lower':'下降放置','release':'松开夹爪','retreat':'撤离夹爪','done':'搬运完成。'}
        self.message=labels.get(phase,phase)

    def fail(self,message):
        self.failed=True;self.done=True;self.message=message

    def detect(self,held=False):
        from vision_model import decode
        torch=self.torch;rgb=self.sensor.capture();self.last_rgb=rgb
        x=torch.from_numpy(rgb.copy()).permute(2,0,1)[None].float()/255
        with torch.no_grad():
            logits=self.model(torch.nn.functional.avg_pool2d(x,2));uv=decode(logits)[0].numpy()
            confidence=logits.sigmoid().max().item()
        self.confidence=confidence;self.last_uv=uv
        self.detections.append({'phase':self.phase,'scan':self.scan,'confidence':confidence,'uv':uv.tolist()})
        if confidence<.75 or np.any(uv<[10,10]) or np.any(uv>np.array(CONFIG['resolution'])-10):return None
        # An appearance gate rejects a spurious network peak on robot/table.
        u,v=np.rint(uv).astype(int);patch=rgb[max(0,v-5):v+6,max(0,u-5):u+6].astype(float)
        if not np.any((patch[:,:,0]>patch[:,:,1]*1.5)&(patch[:,:,0]>patch[:,:,2]*1.5)&(patch[:,:,0]>60)):return None
        pose=camera_pose(self.task.kin,self.task.q)
        try:initial=unproject(uv,pose)
        except ValueError:return None
        # Known brick geometry refines the CNN detection. Connected components
        # are selected by the learned peak, never by simulated object position.
        image=rgb.astype(float)
        mask=(image[:,:,0]>image[:,:,1]*1.5)&(image[:,:,0]>image[:,:,2]*1.5)&(image[:,:,0]>40)
        components,count=label(mask)
        candidates=[]
        for index in range(1,count+1):
            yy,xx=np.where(components==index)
            if len(xx)>=12:
                distance=np.min((xx-uv[0])**2+(yy-uv[1])**2)
                candidates.append((distance,xx,yy))
        if not candidates:return None
        distance,xx,yy=min(candidates,key=lambda item:item[0])
        if distance>100:return None
        observed=np.array([xx.min()-.5,xx.max()+.5,yy.min()-.5,yy.max()+.5])
        corners=np.array([[x,y,z] for x in [-.0159,.0159] for y in [-.0079,.0079] for z in [-.0048,.0048]])
        covariance=np.cov(np.vstack([xx,yy]))
        axis=np.linalg.eigh(covariance)[1][:,-1]
        direction=pose[:3,0]*axis[0]-pose[:3,1]*axis[1]
        yaw=float((np.arctan2(direction[1],direction[0])+np.pi/2)%np.pi-np.pi/2)
        def residual(values):
            center=np.asarray(values[:3]) if held else np.r_[values[:2],.0048]
            rotation=Rotation.from_euler('z',values[-1]).as_matrix()
            pixels=np.array([project(center+rotation@corner,pose)[0] for corner in corners])
            return np.r_[np.array([pixels[:,0].min(),pixels[:,0].max(),pixels[:,1].min(),pixels[:,1].max()])-observed,
                         2*np.sin(values[-1]-yaw)]
        if held:
            initial=np.r_[self.task.tcp[:2],max(.01,self.task.tcp[2]-.0008),yaw]
            fit=least_squares(residual,initial,bounds=([-.3,-.4,.005,yaw-.35],[.7,.4,.3,yaw+.35]),max_nfev=60)
            result=fit.x[:3]
        else:
            fit=least_squares(residual,np.r_[initial[:2],yaw],bounds=([-.3,-.4,yaw-.35],[.7,.4,yaw+.35]),max_nfev=60)
            result=np.r_[fit.x[:2],.0048]
        if np.linalg.norm(fit.fun)>5:return None
        return result

    def contacts(self):
        force=np.asarray(self.task.contacts.get_contact_force_matrix(dt=.001))
        values=np.linalg.norm(force,axis=-1).sum(axis=-1)
        return len(values)==2 and bool(np.all(values>.001))

    def begin_recovery(self):
        if self.retries>=2:
            self.fail('抓取重试次数已用尽，已停止。');return
        self.retries+=1;self.recovery_xy=self.task.tcp[:2].copy()
        self.command=self.task.tcp.copy();self.transition('recover_open')
        self.message='夹持未稳定：松爪抬高，并重新用相机搜索。'

    def move(self,point,opening):
        task=self.task;point=np.asarray(point,dtype=float)
        current=task.tcp;delta=point-self.command
        target=self.command+delta*min(1.,SETTINGS['max_cartesian_step_m']/(np.linalg.norm(delta)+1e-9))
        lead=target-current
        target=current+lead*min(1.,.012/(np.linalg.norm(lead)+1e-9))
        self.command=target.copy()
        q,error=task.kin.solve(target,task.q);self.last_ik_error=error
        if error>.002:
            self.fail('运动路径不可达，已停止。');return False
        q=task.q+np.clip(q-task.q,-SETTINGS['max_joint_step_rad'],SETTINGS['max_joint_step_rad'])
        task.advance(q,opening)
        reached=np.linalg.norm(task.tcp-point)<.0012 and np.max(abs(task.robot.get_joint_velocities()[task.arm]))<.08
        self.stable=self.stable+1 if reached else 0
        return self.stable>=5

    def step(self):
        if self.done:return
        self.steps+=1;self.phase_steps+=1
        if self.phase_steps>500 or self.steps>6000:
            self.fail('阶段超时，已停止。');return
        t=self.task;p=self.phase
        if p=='search':
            if self.move(SETTINGS['scan_poses'][self.scan],.025):
                source=self.detect()
                if source is not None:
                    if not admitted(t.kin,source[:2]):
                        self.fail('已看到积木，但该位置超出当前可抓取区域。');return
                    self.source=source;self.found_from_scan=self.scan;self.transition('approach')
                else:
                    self.scan+=1;self.stable=0;self.phase_steps=0
                    if self.scan>=len(SETTINGS['scan_poses']):self.fail('搜索结束：未找到可识别的完整红色积木。')
        elif p=='approach':
            if self.move(np.r_[self.source[:2],.08],.025):self.transition('align')
        elif p=='align':
            seen=self.detect()
            if seen is None:self.fail('对准时积木不可见，已停止。');return
            if np.linalg.norm(seen[:2]-self.source[:2])>.025:
                self.fail('视觉位置不一致，已停止。');return
            self.source=seen;self.alignment_checks+=1
            if self.alignment_checks<2:self.transition('approach')
            else:self.transition('descend')
        elif p=='descend':
            if self.move(np.r_[self.source[:2],.0056],.025):self.transition('close')
        elif p=='close':
            opening=max(.003,.025-self.phase_steps*.0004)
            self.move(np.r_[self.source[:2],.0056],opening)
            self.contact_streak=self.contact_streak+1 if self.contacts() else 0
            values=np.linalg.norm(np.asarray(t.contacts.get_contact_force_matrix(dt=.001)),axis=-1).sum(axis=-1)
            self.unilateral_streak=self.unilateral_streak+1 if np.count_nonzero(values>.001)==1 else 0
            if self.contact_streak>=10 and self.phase_steps>=20:self.transition('lift')
            elif self.unilateral_streak>12 or self.phase_steps>100:self.begin_recovery()
        elif p=='recover_open':
            if self.move(np.r_[self.recovery_xy,.08],.025):
                self.source=None;self.scan=0;self.alignment_checks=0
                self.contact_streak=0;self.unilateral_streak=0;self.lost_contact=0
                self.transition('search')
        elif p=='verify_carry':
            seen=self.detect(held=True)
            if seen is None:
                # A held object can be occluded by the original visual fingers.
                # With maintained bilateral contact, retain the encoder-based
                # grasp transform established at the visual pickup point.
                if not self.contacts():self.fail('视觉被遮挡且夹持接触丢失，已停止。');return
                self.carry_offset=self.grasp_offset.copy();self.carry_estimate_method='encoder_grasp_transform_when_occluded'
                self.transition('lower');return
            offset=seen[:2]-t.tcp[:2]
            if np.linalg.norm(offset)>.035:self.fail('积木相对夹爪偏移过大，已停止。');return
            self.carry_offset=offset;self.carry_estimate_method='RGB_geometry';self.transition('lower')
        elif p in ['lift','via_source','via_goal','transfer','lower']:
            contact=self.contacts()
            self.contact_lift_steps+=int(contact and p!='lower')
            self.lost_contact=0 if contact else self.lost_contact+1
            if self.lost_contact>15:self.begin_recovery();return
            points={'lift':np.r_[self.source[:2],.08],
                    'via_source':np.array([.28,self.source[1],.08]),
                    'via_goal':np.array([.28,self.goal[1],.08]),
                    'transfer':np.r_[self.goal[:2],.08], 'lower':np.r_[self.goal[:2]-self.carry_offset,.0056]}
            reached=self.move(points[p],.003)
            table_force=np.asarray(self.table_contact.get_contact_force_matrix(dt=.001))
            on_table=np.linalg.norm(table_force)>.002
            if p=='lower' and on_table and np.linalg.norm(t.tcp[:2]-points[p][:2])<.002:
                self.transition('release')
            elif reached:
                self.transition({'lift':'via_source','via_source':'via_goal','via_goal':'transfer','transfer':'verify_carry','lower':'release'}[p])
        elif p=='release':
            # Hold the achieved contact height rather than pushing into the table.
            self.move(np.r_[self.goal[:2]-self.carry_offset,self.release_height],.025)
            fingers=abs(t.robot.get_joint_positions()[t.fingers])
            # A measured jaw gap wider than the known brick is a release signal.
            # Lift slightly while opening so low finger pads cannot scrape the table.
            if min(fingers)>.022 and self.phase_steps>=20 and t.tcp[2]>self.release_height-.002:
                self.transition('retreat')
        elif p=='retreat':
            if self.move(np.r_[self.goal[:2]-self.carry_offset,.09],.025):
                self.transition('done');self.done=True

def collect(task,sensor,args):
    from PIL import Image
    rng=np.random.default_rng(args.seed);points=workspace_points(task.kin)
    images=[];pixels=[];poses=[];sources=[]
    for i in range(args.samples):
        xy=np.array(points[rng.integers(len(points))])+rng.uniform(-.008,.008,2)
        source=np.r_[xy,.0048]
        if i%2==0:
            aim=np.array(SETTINGS['scan_poses'][rng.integers(len(SETTINGS['scan_poses']))])
        else:aim=np.r_[xy+rng.uniform(-.015,.015,2),rng.uniform(.012,.095)]
        q=solve_checked(task.kin,aim)
        if q is None:continue
        task.brick.set_world_pose(position=source,orientation=np.array([1.,0,0,0]))
        task.brick.set_linear_velocity(np.zeros(3));task.brick.set_angular_velocity(np.zeros(3))
        full=task.robot.get_joint_positions();full[task.arm]=q
        task.robot.set_joint_positions(full);task.robot.set_joint_velocities(np.zeros(8));task.advance(q,.025)
        task.world.render();rgb=sensor.capture();pose=camera_pose(task.kin,task.q)
        source=task.object.copy();uv,depth=project(source+[0,0,.0048],pose)
        if depth<=0 or np.any(uv<[12,12]) or np.any(uv>np.array(CONFIG['resolution'])-12):continue
        images.append(rgb);pixels.append(uv);poses.append(pose);sources.append(source)
        if i%64==0:
            Image.fromarray(rgb).save(OUT/f'sample_{i:04}.png')
            print(json.dumps({'sample':i,'accepted':len(images)}),flush=True)
    if len(images)<64:raise RuntimeError('Too few full-view labeled frames')
    np.savez_compressed(OUT/'localization.npz',images=np.array(images),pixels=np.array(pixels),
                        camera_to_world=np.array(poses),points=np.array(sources))
    (OUT/'dataset.json').write_text(json.dumps({'samples':len(images),'attempts':args.samples,
        'workspace_points':points,'sensor':'wrist RGB','labels':'simulated top-center projections',
        'source':'wide reachable-workspace scan and close-up views; fixed red brick yaw'},indent=2))
    print(json.dumps({'dataset_samples':len(images)}),flush=True)

def evaluate(task,sensor,args):
    rng=np.random.default_rng(args.seed);points=workspace_points(task.kin)
    # Stratified positions include scan-required corners; no source-relative reset.
    tests=[[.18,-.24],[.18,.24],[.36,-.10],[.36,.10],[.22,-.18],[.22,.18],
           [.28,-.25],[.28,.25],[.32,-.04],[.32,.18],[.15,-.16],[.15,.16]]
    tests=[p for p in tests if admitted(task.kin,p)]
    while len(tests)<args.episodes:tests.append(points[rng.integers(len(points))])
    if args.tabletop_negative:tests=[[.22,-.18],[.42,0.]]
    if args.tabletop_regression:tests=[[.36,.10],[.28,-.25],[.32,.18],[.18,-.24],[.22,.18]]
    if args.tabletop_recovery:tests=[[.15,.16],[.15,.16]]
    results=[]
    for ep,xy in enumerate(tests if args.tabletop_negative or args.tabletop_regression or args.tabletop_recovery else tests[:args.episodes]):
        setup(task,np.r_[xy,.0048])
        if args.tabletop_negative:
            from pxr import UsdGeom
            imageable=UsdGeom.Imageable(task.stage.GetPrimAtPath('/World/Brick'))
            if ep==0:imageable.MakeInvisible()
            else:imageable.MakeVisible()
        controller=TabletopController(task,sensor,task.goal)
        peak=.0048;lift_contacts=0;det_error=None;max_speed=0.
        injected=False
        for _ in range(6000):
            if args.tabletop_recovery and ep==1 and not injected and controller.phase=='close' and controller.phase_steps>=20:
                # Explicit test-only interruption, independent of object truth.
                controller.begin_recovery();injected=True
            controller.step()
            pos=task.object.copy();peak=max(peak,float(pos[2]))
            if pos[2]>.04 and controller.contacts():lift_contacts+=1
            if controller.source is not None and det_error is None:
                det_error=float(np.linalg.norm(controller.source[:2]-pos[:2]))
            if controller.done:break
        for _ in range(20):task.advance(task.q,.025)
        pos=task.object;error=float(np.linalg.norm(pos[:2]-task.goal[:2]))
        _,quat=task.brick.get_world_pose()
        upright=Rotation.from_quat(np.r_[quat[1:],quat[0]]).as_matrix()[2,2]>.98
        success=not controller.failed and peak>.055 and lift_contacts>=5 and error<.012 and .002<pos[2]<.012 and upright
        result={'source_xy_m':list(map(float,xy)),'success':bool(success),'controller_failed':controller.failed,
                'message':controller.message,'phase':controller.phase,'steps':controller.steps,
                'found_from_scan':controller.found_from_scan,'first_visual_error_m':det_error,
                'aligned_visual_error_m':float(np.linalg.norm(controller.source[:2]-xy)) if controller.source is not None else None,
                'carry_offset_xy_m':controller.carry_offset.tolist(),'detections':controller.detections,
                'carry_estimate_method':controller.carry_estimate_method,
                'peak_height_m':peak,'bilateral_lift_steps':lift_contacts,'goal_error_m':error,
                'final_brick_position_m':pos.tolist(),'phases':controller.history}
        result['final_finger_opening_m']=abs(task.robot.get_joint_positions()[task.fingers]).tolist()
        result['final_tcp_m']=task.tcp.tolist()
        result['grasp_retries']=controller.retries;result['test_only_grasp_interruption']=injected
        if args.tabletop_negative:
            result['case']='missing_visual_object' if ep==0 else 'visible_unreachable_object'
            result['rejected_without_grasp']=bool(controller.failed and controller.source is None and all(p['phase']=='search' for p in controller.history))
        results.append(result);print(json.dumps(result),flush=True)
        report_name='negative.json' if args.tabletop_negative else ('recovery.json' if args.tabletop_recovery else ('regression.json' if args.tabletop_regression else 'evaluation.json'))
        (OUT/report_name).write_text(json.dumps({'episodes':results,'successes':sum(r['success'] for r in results),
            'controller':'wrist_RGB_search_feedback','policy_object_truth_used':False,'fixed_phase_clock':False,
            'workspace':SETTINGS,'release_signal':'measured open jaws plus upward clearance',
            'finger_collision_model':'box pads only; imported collision instances made editable and disabled',
            'finger_drive':{'stiffness':500.,'damping':12.,'max_force_N':1.5},
            'runtime_inputs':['wrist RGB','joint encoders','camera calibration','known brick dimensions','commanded goal','simulated finger/table contact sensors'],
            'limits':['fixed yaw and color','known table plane','no full arm collision planning','simulation only']},indent=2))

def run(app,world,robot,brick,stage,args):
    from pick_place import Task
    OUT.mkdir(exist_ok=True)
    task=Task(app,world,robot,brick,stage);task.reset(0)
    sensor=WristRGB(world)
    if args.tabletop_mode=='collect':collect(task,sensor,args)
    else:evaluate(task,sensor,args)
