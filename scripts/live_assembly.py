"""Live instruction -> RGB -> robot -> concept connector -> verification loop."""
import json,time
from types import SimpleNamespace
import numpy as np
from scipy.spatial.transform import Rotation
from assembly_agent import InstructionAgent,target_pose,ROOT
from assembly_perception import Inventory,detect
from tabletop import TabletopController,SETTINGS,workspace_points,solve_checked
from wrist_vision import WristRGB,camera_pose
from concept_connectors import ConceptConnectors,FIXTURE_ORIGIN

OUT=ROOT/'outputs/live_assembly'
CONCEPT_CAPS={k:True for k in ['visual_pick','concept_transport','concept_connection_model','placement_verification','fixture_registration']}

def angle_error(a,b):return float((a-b+90)%180-90)

class StepController(TabletopController):
    def __init__(self,session):
        self.session=session;self.instruction=session.agent.recipe['steps'][len(session.agent.completed)]
        self.color=self.instruction['part']['color'];self.plan=None;self.receipt=None;self.evidence=None
        task=session.task;task.kin.desired_rotation=np.diag([-1.,1.,-1.])
        from isaacsim.core.api.sensors import RigidContactView
        task.brick=session.parts[self.color]
        task.contacts=RigidContactView(prim_paths_expr=['/World/Piper/link7','/World/Piper/link8'],
            filter_paths_expr=[[task.brick.prim_path],[task.brick.prim_path]],max_contact_count=64)
        task.contacts.initialize(task.world.physics_sim_view)
        goal=FIXTURE_ORIGIN+np.array(target_pose(session.agent.recipe,self.instruction)['position_m'])
        task.goal=goal.copy();super().__init__(task,session.sensor,goal)
        parent_paths=[]
        for connection in self.instruction['connections']:
            parent=connection['support_step']
            if parent=='fixture':parent_paths.append(session.fixture.prim_path)
            else:
                color=next(s['part']['color'] for s in session.agent.recipe['steps'] if s['id']==parent)
                parent_paths.append(session.parts[color].prim_path)
        self.table_contact=RigidContactView(prim_paths_expr=task.brick.prim_path,
            filter_paths_expr=[parent_paths],max_contact_count=64)
        self.table_contact.initialize(task.world.physics_sim_view)
        self.debug_paths=['/World/Piper/link'+str(i) for i in range(1,9)]
        self.debug_filters=[part.prim_path for part in session.parts.values()]+[session.fixture.prim_path,'/World/WorkSurface']
        self.debug_contact=RigidContactView(prim_paths_expr=self.debug_paths,
            filter_paths_expr=[self.debug_filters for _ in self.debug_paths],max_contact_count=512)
        self.debug_contact.initialize(task.world.physics_sim_view)
        self.seat_steps=0;self.orientation_checks=0;self.hold_yaw=0.;self.last_seen=None;self.placement_refinements=0
        self.seat_descent=0.;self.seat_height=None;self.support_force=0.
        self.lower_trace=[]
        self.preseat_checks=0
        self.grasp_yaw_deg=0.

    def choose_grasp_rotation(self):
        base=np.diag([-1.,1.,-1.]);kin=self.task.kin
        choices=[]
        yaw=angle_error(self.hold_yaw,0.)
        for candidate in [yaw,yaw-180,yaw+180]:
            kin.desired_rotation=Rotation.from_euler('z',candidate,degrees=True).as_matrix()@base
            hover=solve_checked(kin,np.r_[self.source[:2],.08],self.task.q)
            low=solve_checked(kin,np.r_[self.source[:2],.0056],hover) if hover is not None else None
            if low is not None:choices.append((np.linalg.norm(hover-self.task.q),candidate))
        if not choices:
            kin.desired_rotation=base;self.fail('视觉识别的积木方向在当前夹持姿态下不可达。');return False
        self.grasp_yaw_deg=min(choices)[1]
        kin.desired_rotation=Rotation.from_euler('z',self.grasp_yaw_deg,degrees=True).as_matrix()@base
        return True

    def observe(self,center_z=.0048,free=False,held=False):
        rgb=self.sensor.capture();self.last_rgb=rgb
        pieces=detect(rgb,camera_pose(self.task.kin,self.task.q),center_z_m=center_z,free_height=free,
            held_color=self.color if held else None)
        return pieces

    def detect(self,held=False):
        if held:
            pieces=self.observe(max(.01,float(self.task.tcp[2]-.0008)),True,True)
            candidates=[p for p in pieces if p['color']==self.color and np.linalg.norm(np.array(p['pose']['position_m'])[:2]-self.task.tcp[:2])<.04]
        else:
            pieces=self.observe()
            for piece in pieces:
                x,y,_=piece['pose']['position_m']
                if .221<x<.359 and .071<y<.209:piece['region']='assembly'
            self.session.inventory.update(pieces)
            observation=self.session.inventory.observation()
            observation['fixture']={'registered':True,'confidence':1.,'registration_source':'configured_kinematic_sim_fixture',
                'pose':{'position_m':FIXTURE_ORIGIN.tolist(),'yaw_deg':0}}
            self.session.agent.observe(observation)
            plan=self.session.agent.next_plan(CONCEPT_CAPS)
            current_ids={p['track_id'] for p in self.session.inventory.tracks.values() if p['observed_frame']==self.session.inventory.frames}
            candidates=[p for p in self.session.inventory.tracks.values() if p['track_id'] in current_ids
                and p['color']==self.color and p.get('region')=='loose' and p['confidence']>=.85]
            if plan['status']=='ready' and plan['selected_track_id'] in {p['track_id'] for p in candidates}:self.plan=plan
            else:return None
        if not candidates:return None
        seen=max(candidates,key=lambda p:p['confidence']);self.last_seen=seen
        self.hold_yaw=seen['pose']['yaw_deg'];self.confidence=seen['confidence'];self.last_uv=np.array(seen['pixel_center'])
        return np.array(seen['pose']['position_m'])

    def move(self,point,opening):
        # Scale all joint increments together: independent per-joint clipping
        # bends a vertical Cartesian descent into the neighbouring structure.
        task=self.task;point=np.asarray(point,dtype=float);current=task.tcp
        delta=point-self.command
        target=self.command+delta*min(1.,SETTINGS['max_cartesian_step_m']/(np.linalg.norm(delta)+1e-9))
        lead=target-current;limit=.002 if self.phase in ['lower','descend'] else .006
        target=current+lead*min(1.,limit/(np.linalg.norm(lead)+1e-9));self.command=target.copy()
        if self.phase in ['lower','descend']:
            # Hold XY on the goal throughout descent. Chasing a short 3-D
            # lookahead otherwise trades horizontal registration for Z speed.
            target=np.r_[point[:2],max(point[2],current[2]-.0002)]
            self.command=target.copy()
        q,error=task.kin.solve(target,task.q);self.last_ik_error=error
        if error>.002:
            self.fail('Motion path is unreachable.');return False
        delta_q=q-task.q
        q=task.q+delta_q*min(1.,SETTINGS['max_joint_step_rad']/(np.max(abs(delta_q))+1e-9))
        task.advance(q,opening)
        rotation_error=np.linalg.norm(Rotation.from_matrix(task.kin.desired_rotation@task.kin.forward(task.q)[1].T).as_rotvec())
        coarse_phases=['lift','align_transport','via_source','via_goal','transfer','search','approach',
            'fixture_inspect','fixture_turn','recover_raise','recover_open','retreat','fixture_escape']
        # Survey geometry uses the measured camera pose, not this waypoint.
        tolerance=.003 if self.phase=='heap_survey' else (.002 if self.phase in coarse_phases else .0012)
        reached=np.linalg.norm(task.tcp-point)<tolerance and rotation_error<.012 and np.max(abs(task.robot.get_joint_velocities()[task.arm]))<.08
        self.stable=self.stable+1 if reached else 0
        return self.stable>=5

    def step(self):
        if self.done:return
        self.steps+=1;self.phase_steps+=1
        phase_limit=1400 if self.phase=='lower' else (1000 if self.phase=='descend' else 650)
        if self.phase_steps>phase_limit or self.steps>6500:self.fail('当前步骤超时，请重新散落后重试。');return
        t=self.task;p=self.phase
        if p=='search':
            if self.move(SETTINGS['scan_poses'][self.scan],.025):
                source=self.detect()
                if source is not None:
                    self.source=source;self.found_from_scan=self.scan;self.transition('approach')
                else:
                    self.scan+=1;self.stable=0;self.phase_steps=0
                    if self.scan>=len(SETTINGS['scan_poses']):self.fail('未找到当前步骤所需的 '+self.color+' 积木。')
        elif p=='approach':
            if self.move(np.r_[self.source[:2],.08],.025):self.transition('align')
        elif p=='align':
            seen=self.detect()
            if seen is None:self.fail('抓取前重新观察失败。');return
            self.source=seen;self.alignment_checks+=1
            if self.alignment_checks<2:self.transition('approach')
            elif self.session.random_yaw:
                if self.choose_grasp_rotation():self.transition('orient_pick')
            else:self.transition('descend')
        elif p=='orient_pick':
            if self.move(np.r_[self.source[:2],.08],.025):self.transition('descend')
        elif p=='descend':
            if self.move(np.r_[self.source[:2],.0056],.025):self.transition('close')
        elif p=='close':
            self.move(np.r_[self.source[:2],.0056],max(.003,.025-self.phase_steps*.0004))
            force=np.asarray(t.contacts.get_contact_force_matrix(dt=.001));values=np.linalg.norm(force,axis=-1).sum(axis=-1)
            self.contact_streak=self.contact_streak+1 if self.contacts() else 0
            self.unilateral_streak=self.unilateral_streak+1 if np.count_nonzero(values>.001)==1 else 0
            if self.contact_streak>=10:self.transition('lift')
            elif self.phase_steps>110 or self.unilateral_streak>12:self.begin_recovery()
        elif p=='recover_open':
            if self.move(np.r_[self.recovery_xy,.08],.025):
                t.kin.desired_rotation=np.diag([-1.,1.,-1.])
                self.source=None;self.scan=0;self.alignment_checks=0;self.contact_streak=0;self.unilateral_streak=0;self.lost_contact=0
                self.transition('search')
        elif p in ['lift','align_transport','via_source','via_goal','transfer','orient']:
            self.lost_contact=0 if self.contacts() else self.lost_contact+1
            if self.lost_contact>15:self.begin_recovery();return
            targets={'lift':np.r_[self.source[:2],.08],'via_source':[.28,self.source[1],.08],
                     'align_transport':np.r_[self.source[:2],.08],
                     'via_goal':[.28,self.goal[1],.08],'transfer':np.r_[self.goal[:2],.08],
                     'orient':np.r_[self.goal[:2],.08]}
            if self.move(targets[p],.003):
                if p=='lift' and self.session.random_yaw:
                    t.kin.desired_rotation=np.diag([-1.,1.,-1.]);self.transition('align_transport')
                else:self.transition({'lift':'via_source','align_transport':'via_source','via_source':'via_goal','via_goal':'transfer','transfer':'verify_carry','orient':'verify_carry'}[p])
        elif p=='verify_carry':
            seen=self.detect(held=True);self.orientation_checks+=1
            if seen is not None:
                # Rotation is determined from the unobstructed source RGB,
                # then normalized after lift. Held silhouettes only estimate XY;
                # released RGB and connector geometry independently gate yaw.
                self.carry_offset=seen[:2]-t.tcp[:2];self.carry_estimate_method='RGB_geometry'
            else:
                if not self.contacts():self.fail('物体被遮挡且夹持丢失。');return
                self.carry_offset=self.grasp_offset.copy();self.carry_estimate_method='encoder_grasp_transform_when_occluded'
            self.transition('preseat')
        elif p=='preseat':
            if self.move(np.r_[self.goal[:2]-self.carry_offset,self.goal[2]+.0258],.003):
                self.transition('register_carry')
        elif p=='register_carry':
            # Known grasp height avoids XYZ/depth ambiguity of a high held RGB
            # silhouette. Register again above the wall before entering its gap.
            pieces=self.observe(float(t.tcp[2]-.0008),held=True)
            matching=[x for x in pieces if x['color']==self.color]
            if not matching:self.fail('Pre-placement visual registration failed.');return
            observed=np.array(max(matching,key=lambda x:x['confidence'])['pose']['position_m'])
            self.carry_offset=observed[:2]-t.tcp[:2];self.preseat_checks+=1
            self.command=t.tcp.copy()
            self.transition('preseat' if self.preseat_checks<3 else 'lower')
        elif p=='lower':
            z=self.seat_height if self.seat_height is not None else self.goal[2]+.0008-self.seat_descent
            reached=self.move(np.r_[self.goal[:2]-self.carry_offset,z],.003)
            self.support_force=float(np.linalg.norm(np.asarray(self.table_contact.get_contact_force_matrix(dt=.001))))
            on_support=self.support_force>.002
            if self.phase_steps%10==1:
                self.lower_trace.append({'step':self.phase_steps,'tcp':t.tcp.tolist(),'command':self.command.tolist(),
                    'carry_offset':self.carry_offset.tolist(),'rotation':t.kin.forward(t.q)[1].tolist(),
                    'forces':np.linalg.norm(np.asarray(self.debug_contact.get_contact_force_matrix(dt=.001)),axis=-1).tolist()})
            if on_support and self.seat_height is None:self.seat_height=float(t.tcp[2])+.0002
            if reached and not on_support and self.phase_steps%8==0:
                self.seat_descent=min(.004,self.seat_descent+.0001)
            xy_close=np.linalg.norm(t.tcp[:2]-(self.goal[:2]-self.carry_offset))<.002
            self.seat_steps=self.seat_steps+1 if on_support and xy_close else 0
            # Once seated, neighbouring visual bodies can occlude the bbox.
            # Preserve the unobstructed preseat registration instead of trying
            # to servo on a truncated silhouette while pressing on the support.
            self.receipt=self.session.connectors.try_engage(self.color,on_support,self.seat_steps)
            if self.receipt:
                if self.receipt['anchor_stud']!=self.instruction['anchor_stud']:
                    self.fail('实际连接格位与说明书不符，已停止。');return
                self.transition('release')
        elif p=='release':
            self.move(np.r_[self.goal[:2]-self.carry_offset,self.release_height],.025)
            if min(abs(t.robot.get_joint_positions()[t.fingers]))>.022 and self.phase_steps>=20:self.transition('retreat')
        elif p=='retreat':
            if self.move(np.r_[self.goal[:2]-self.carry_offset,.085],.025):self.transition('verify_placement')
        elif p=='verify_placement':
            pieces=self.observe(self.goal[2]);matching=[x for x in pieces if x['color']==self.color]
            if not matching:self.fail('放置后视觉验收未找到当前零件。');return
            seen=max(matching,key=lambda x:x['confidence']);error=float(np.linalg.norm(np.array(seen['pose']['position_m'])-self.goal))
            yaw=abs(angle_error(seen['pose']['yaw_deg'],self.instruction['yaw_deg']))
            color_to_step={s['part']['color']:s['id'] for s in self.session.agent.recipe['steps']}
            connections={('fixture' if c=='fixture' else color_to_step[c]):n for c,n in self.receipt['support_colors'].items()}
            evidence={'step_id':self.instruction['id'],'track_id':self.plan['selected_track_id'],
                'position_error_m':error,'yaw_error_deg':yaw,'connections':connections,'connection_verified':True,
                'verification_source':'simulated_connector_surrogate','physical_snapfit_validated':False}
            if not self.session.agent.confirm(evidence):self.fail('放置或连接近似验收未通过。');return
            self.evidence=evidence;self.transition('done');self.done=True

class LiveAssemblySession:
    def __init__(self,app,world,robot,brick,stage,args):
        from pick_place import Task
        self.task=Task(app,world,robot,brick,stage);self.task.reset(0)
        self.parts=args.assembly_parts;self.fixture=args.assembly_fixture
        self.connectors=ConceptConnectors(stage,self.parts,self.fixture)
        self.sensor=WristRGB(world);self.visual=SimpleNamespace(phase='ready',last_rgb=self.sensor.last_rgb)
        self.tabletop=False;self.assembly_live=True;self.workspace=workspace_points(self.task.kin)
        self.client=None;self.last_seq=-1;self.events=[];self.holding=False;self.result={};self.policy=None
        self.seed=args.seed;self.random_yaw=args.assembly_random_yaw;self.trace=[];self.controller=None
        OUT.mkdir(exist_ok=True);self.reset(self.seed)
    def reset(self,seed=None):
        self.seed=int(seed if seed is not None else np.random.default_rng().integers(0,2**31))
        self.connectors.reset();self.task.world.reset();self.agent=InstructionAgent(execution_mode='concept')
        self.inventory=Inventory();self.trace=[];self.controller=None;self.result={};self.holding=False;self.metrics={}
        rng=np.random.default_rng(self.seed);placed=[];points=np.array(self.workspace)
        for color,part in self.parts.items():
            for _ in range(2500):
                xy=points[rng.integers(len(points))]+rng.uniform(-.002,.002,2)
                if .195<xy[0]<.38 and .045<xy[1]<.235:continue
                if all(np.linalg.norm(xy-p)>.055 for p in placed):break
            else:raise RuntimeError('Could not create collision-separated random layout')
            placed.append(xy);yaw=float(rng.uniform(-90.,90.)) if self.random_yaw else 0.
            quat=Rotation.from_euler('z',yaw,degrees=True).as_quat()
            part.set_world_pose(position=np.r_[xy,.007],orientation=np.r_[quat[3],quat[:3]])
            part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
        self.task.kin.desired_rotation=np.diag([-1.,1.,-1.]);home=solve_checked(self.task.kin,SETTINGS['home'])
        full=self.task.robot.get_joint_positions();full[self.task.arm]=home;full[self.task.fingers]=[.025,-.025]
        self.task.robot.set_joint_positions(full);self.task.robot.set_joint_velocities(np.zeros(8))
        for _ in range(15):self.task.advance(home,.025)
        self.layout_evaluation={color:{'position_m':part.get_world_pose()[0].tolist(),
            'yaw_deg':float(Rotation.from_quat(np.r_[part.get_world_pose()[1][1:],part.get_world_pose()[1][0]]).as_euler('xyz',degrees=True)[2])}
            for color,part in self.parts.items()}
        self.mode='ready';self.status='ready';self.message='已随机散落 8 个零件。点击开始按说明书概念搭建。'
        self.visual.phase='ready';self.visual.last_rgb=self.sensor.capture()
    def event(self,event):
        client=event.get('client');kind=event.get('event')
        if kind=='connect':self.client=client;self.last_seq=-1;return
        if client!=self.client:return
        if kind=='disconnect':
            if self.mode=='robot':self.mode='paused_robot';self.message='控制连接断开，任务已暂停。'
            return
        command=event.get('command',{});seq=command.get('seq')
        if not isinstance(seq,int) or seq<=self.last_seq:return
        self.last_seq=seq;op=command.get('op')
        if op not in ['reset','start','pause','resume']:return
        self.events.append({'wall_time':time.time(),'command':command})
        if op=='reset':
            seed=command.get('seed')
            if seed is not None and (not isinstance(seed,int) or not 0<=seed<2**31):return
            self.reset(seed)
        elif op=='start' and self.status=='ready':self.mode='robot';self.status='running';self.message='开始按说明书逐步选料和搭建。'
        elif op=='pause' and self.mode=='robot':self.mode='paused_robot';self.message='已暂停，可继续。'
        elif op in ['resume','start'] and self.mode=='paused_robot':self.mode='robot'
    def tick(self):
        if self.mode=='robot':
            try:
                if self.controller is None:self.controller=StepController(self)
                self.controller.step();self.visual=self.controller
                if self.connectors.broken:raise RuntimeError('Assembly connection broke: '+', '.join(self.connectors.broken))
                # Privileged physics state is used only for independent evaluation.
                color=self.controller.color
                metric=self.metrics.setdefault(color,{'peak_height_m':0.,'bilateral_lift_steps':0})
                z=float(self.parts[color].get_world_pose()[0][2])
                metric['peak_height_m']=max(metric['peak_height_m'],z)
                if z>.04 and self.controller.contacts():metric['bilateral_lift_steps']+=1
                self.message=self.controller.instruction['id']+' '+self.controller.color+'：'+self.controller.message
                if self.controller.done:
                    if self.controller.failed:self.status='failed';self.mode='paused'
                    else:
                        self.trace.append({'step_id':self.controller.instruction['id'],'evidence':self.controller.evidence,
                            'grasp_yaw_from_RGB_deg':self.controller.grasp_yaw_deg,
                            'control_steps':self.controller.steps,'retries':self.controller.retries,
                            'pick_source':'current wrist RGB','grasp_attachment_used':False})
                        self.controller=None
                        if len(self.agent.completed)==len(self.agent.recipe['steps']):
                            for _ in range(50):self.task.advance(self.task.q,.025)
                            final=self.evaluate_final()
                            passed=all(p['goal_error_m']<.0035 and p['tilt_deg']<6 and
                                p['speed_m_s']<.01 and p['bilateral_lift_steps']>=5 for p in final)
                            self.status='complete' if passed else 'failed';self.mode='done' if passed else 'paused'
                            self.result={'success':passed}
                            self.message=('概念搭建 6/6 完成：连接采用约束近似，真实卡接未验收。' if passed
                                else '最终结构稳定性检查未通过，已停止。')
                self.write_report()
            except (RuntimeError,ValueError) as error:
                self.status='failed';self.mode='paused';self.message=str(error);self.write_report()
        elif self.mode in ['ready','done']:
            for _ in range(20):self.task.world.step(render=False)
    def snapshot(self):
        return {'mode':'concept','status':self.status,'seed':self.seed,'random_yaw':self.random_yaw,
            'completed_steps':list(self.agent.completed),'total_steps':len(self.agent.recipe['steps']),
            'current_step':self.controller.instruction['id'] if self.controller else None,
            'phase':self.controller.phase if self.controller else self.status,
            'concept_build_completed':self.status=='complete','physical_assembly_completed':False,
            'connection_model':'flat support, 1.5 mm end-clearance collision proxy, contact-gated fixed-joint stud-grid surrogate',
            'broken_connections':list(self.connectors.broken),
            'joint_count':sum(len(r['joint_paths']) for r in self.connectors.latched.values()),
            'message':self.message}
    def evaluate_final(self):
        final=[]
        for step in self.agent.recipe['steps']:
            color=step['part']['color'];position,quat=self.parts[color].get_world_pose()
            target=FIXTURE_ORIGIN+np.array(target_pose(self.agent.recipe,step)['position_m'])
            rot=Rotation.from_quat(np.r_[quat[1:],quat[0]]).as_matrix()
            final.append({'step_id':step['id'],'color':color,'position_m':position.tolist(),
                'goal_error_m':float(np.linalg.norm(position-target)),
                'tilt_deg':float(np.rad2deg(np.arccos(np.clip(rot[2,2],-1,1)))),
                'speed_m_s':float(np.linalg.norm(self.parts[color].get_linear_velocity())),
                **self.metrics.get(color,{'peak_height_m':0.,'bilateral_lift_steps':0})})
        return final

    def write_report(self):
        # Periodic state is separate from the immutable recipe and source-layout files.
        report={**self.snapshot(),'trace':self.trace,'connectors':self.connectors.events,
                'layout_evaluation':self.layout_evaluation,
                'robot_control_source_poses':'wrist RGB only','body_pose_writes_after_reset':0}
        report['physics_evaluation']=self.metrics
        if len(self.agent.completed)==len(self.agent.recipe['steps']):
            report['final_parts_evaluation']=self.evaluate_final()
        if self.controller:
            report['active_step']={'id':self.controller.instruction['id'],'phase':self.controller.phase,
                'goal':self.controller.goal.tolist(),'tcp':self.task.tcp.tolist(),
                'carry_offset':self.controller.carry_offset.tolist(),'seat_steps':self.controller.seat_steps,
                'seat_descent':self.controller.seat_descent,'support_force_N':self.controller.support_force,
                'placement_refinements':self.controller.placement_refinements,'plan':self.controller.plan}
            if self.status=='failed':
                forces=np.linalg.norm(np.asarray(self.controller.debug_contact.get_contact_force_matrix(dt=.001)),axis=-1)
                report['collision_diagnostics']=[{'robot':self.controller.debug_paths[i],
                    'object':self.controller.debug_filters[j],'force_N':float(forces[i,j])}
                    for i,j in zip(*np.where(forces>.001))]
                report['body_diagnostics']={c:{'position':p.get_world_pose()[0].tolist(),
                    'quaternion':p.get_world_pose()[1].tolist()} for c,p in self.parts.items()}
                report['lower_trace']=self.controller.lower_trace
        if self.status in ['complete','failed'] or self.controller is None:
            (OUT/f'run_{self.seed}.json').write_text(json.dumps(report,indent=2))
