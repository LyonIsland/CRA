"""Physical heap commissioning and RGB multiview inspection session."""
import json
import numpy as np
from types import SimpleNamespace
from live_assembly import LiveAssemblySession,StepController
from tabletop import solve_checked
from wrist_vision import camera_pose
from clutter_scene import drop_heap,audit_heap,BUFFER_POINTS,HEAP_BOUNDS
from clutter_perception import observe,reconstruct
from assembly_agent import ROOT

OUT=ROOT/'outputs/clutter_human'
SURVEY_POSES=[[.24,-.08,.09],[.30,-.18,.09],[.34,-.10,.09],[.22,-.20,.09],[.28,-.13,.095]]
ALTERNATE_POSES=[[.21,-.10,.09],[.32,-.22,.09],[.36,-.15,.085],[.25,-.25,.085],[.31,-.045,.085]]

HUMAN_POINT=np.array([.20,-.04,.0048])
COLOR_NAMES={'red':'红色','blue':'蓝色','green':'绿色','yellow':'黄色','orange':'橙色','purple':'紫色',
    'cyan_distractor':'青色干扰','black_distractor':'黑色干扰'}

class HumanRetreat(StepController):
    def __init__(self,session):
        super().__init__(session)
        self.phase='human_retreat';self.message='机器人撤离，准备请求人工帮助'
        self.target=np.r_[self.task.tcp[:2],max(.11,float(self.task.tcp[2]))]
    def step(self):
        self.phase_steps+=1
        if self.move(self.target,.025):self.done=True
        elif self.phase_steps>650:self.fail('人工协作前撤离失败，请先检查机器人。')

class HeapSurvey(StepController):
    def __init__(self,session):
        super().__init__(session)
        self.instruction={'id':'heap_survey','part':{'color':'red'}}
        poses=ALTERNATE_POSES if session.survey_round%2 else SURVEY_POSES
        self.scan_poses=[p for p in poses if solve_checked(self.task.kin,p,self.task.q) is not None]
        if len(self.scan_poses)<3:raise RuntimeError('Insufficient collision-clear survey viewpoints')
        self.views=[];self.index=0;self.phase='heap_survey';self.message='多视角观察零件堆'
        self.manifest=[]
    def step(self):
        if self.done:return
        self.steps+=1;self.phase_steps+=1
        if self.phase_steps>650:self.fail('零件堆观察姿态未到位。');return
        if self.move(self.scan_poses[self.index],.025):
            from PIL import Image
            self.last_rgb=self.sensor.capture();pose=camera_pose(self.task.kin,self.task.q)
            self.views.append(observe(self.last_rgb,pose))
            name=f'heap_{self.session.seed}_round_{self.session.survey_round}_view_{self.index}.png'
            Image.fromarray(self.last_rgb).save(OUT/name)
            self.manifest.append({'rgb':name,'camera_to_world':pose.tolist()})
            self.index+=1;self.phase_steps=0;self.stable=0
            if self.index>=len(self.scan_poses):
                self.session.heap_estimates=reconstruct(self.views)
                self.session.heap_views=self.views
                (OUT/f'views_{self.session.seed}_{self.session.survey_round}.json').write_text(json.dumps(self.manifest,indent=2))
                self.session.heap_observations={'source':'multiview_wrist_RGB_only','view_count':len(self.views),
                    'pieces':self.session.heap_estimates,'controller_body_pose_access':False}
                (OUT/f'observation_{self.session.seed}.json').write_text(json.dumps(self.session.heap_observations,indent=2))
                self.done=True;self.phase='heap_inspection';self.message='零件堆多视角扫描完成'

class ClutterSession(LiveAssemblySession):
    def __init__(self,app,world,robot,brick,stage,args):
        self.max_extractions=max(1,min(6,args.clutter_extractions))
        self.regripper=args.rotary_regripper
        self.assembly_surrogate_active=False
        super().__init__(app,world,robot,brick,stage,args)
    def reset(self,seed=None):
        if self.assembly_surrogate_active:
            from clutter_scene import restore_heap_collision_model
            restore_heap_collision_model(self.task.stage,self.parts);self.assembly_surrogate_active=False
        super().reset(seed)
        for point in BUFFER_POINTS:
            for height in [.006,.085]:
                if solve_checked(self.task.kin,np.r_[point,height],self.task.q) is None:
                    raise RuntimeError('Sorting buffer grasp/retreat pose is unreachable: '+str(point))
        OUT.mkdir(exist_ok=True);self.heap_estimates=[];self.heap_observations={};self.heap_views=[]
        self.extracted=[];self.extraction_evidence=[];self.survey_round=0;self.active_skill='survey';self.heap_metrics={}
        self.normalized=[];self.normalization_evidence=[];self.load_evidence=[]
        self.removed_distractors=[]
        self.face_model_used=False
        self.pick_attempts={};self.recovery_events=[]
        self.staging_attempts={};self.staging_corrections=[]
        self.deferred_colors=set();self.extra_surveys=0;self.face_check_evaluation=[];self.last_face_check_count=0
        self.human_request=None;self.human_history=[];self.human_pose_writes=0;self.human_confirmed=set()
        if self.regripper:self.regripper.command(closed=False,roll_deg=0.,pitch_deg=0.)
        drop_heap(self,np.random.default_rng(self.seed))
        self.heap_audit=audit_heap(self.parts)
        self.layout_evaluation=self.heap_audit['parts']
        (OUT/f'scene_{self.seed}.json').write_text(json.dumps(self.heap_audit,indent=2))
        self.message='重叠、倒扣和侧躺零件堆已自然落定。开始后进行腕部 RGB 多视角观察。'
        self.visual=SimpleNamespace(phase='ready',last_rgb=self.sensor.capture())
    def request_human(self,color,reason):
        self.human_request={'id':len(self.human_history)+1,'color':color,'reason':reason,
            'target_m':HUMAN_POINT.tolist(),'state':'retreating',
            'instruction':f'请将{COLOR_NAMES.get(color,color)}积木凸点朝上，单独放在绿色目标标记处（X=0.20、Y=-0.04 米），与其他零件分开，然后撤手并确认。'}
        self.controller=HumanRetreat(self);self.active_skill='human_retreat'
        self.task.goal=HUMAN_POINT.copy()
        self.message=self.controller.message
    def event(self,event):
        command=event.get('command',{});op=command.get('op')
        if op not in ['human_done','simulate_human']:return super().event(event)
        if event.get('client')!=self.client or event.get('event')!='command':return
        seq=command.get('seq')
        if not isinstance(seq,int) or seq<=self.last_seq:return
        self.last_seq=seq
        if not self.human_request or self.mode!='waiting_human' or command.get('request_id')!=self.human_request['id']:return
        record={**self.human_request,'completion_source':'simulated_human' if op=='simulate_human' else 'human_confirmation'}
        if op=='simulate_human':
            color=self.human_request['color']
            if color is None:return
            # Explicit human-surrogate action, never a robot skill or success evidence.
            self.task.world.step(render=True)
            part=self.parts[color];part.set_world_pose(position=HUMAN_POINT.copy(),orientation=np.array([1.,0,0,0]))
            part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
            self.human_pose_writes+=1;self.task.world.render()
        self.human_history.append(record);self.human_request['state']='verifying'
        self.mode='robot';self.status='running';self.active_skill='survey'
        self.survey_round+=1;self.controller=HeapSurvey(self)
        self.message='人已撤手；重新进行 RGB 观察，不直接认定整理成功。';self.write_report()
    def tick(self):
        if self.active_skill=='assembly':
            super().tick();return
        if self.mode!='robot':
            if self.mode in ['ready','done']:
                for _ in range(20):self.task.world.step(render=False)
            return
        try:
            if self.active_skill=='human_retreat':
                self.controller.step();self.visual=self.controller
                if self.controller.done:
                    if self.controller.failed:
                        self.mode='paused';self.status='failed';self.message=self.controller.message
                    else:
                        self.mode='waiting_human';self.status='waiting_human';self.human_request['state']='waiting'
                        self.message=self.human_request['reason']+'。'+self.human_request['instruction']
                    self.write_report()
                return
            if self.controller is None:self.controller=HeapSurvey(self)
            self.controller.step();self.visual=self.controller;self.message=self.controller.message
            # Body state is independent evaluation only, never a selection input.
            if self.active_skill in ['extract','load','unload']:
                color=self.controller.color;metric=self.heap_metrics.setdefault(color,{'peak_height_m':0.,'bilateral_lift_steps':0})
                z=float(self.parts[color].get_world_pose()[0][2]);metric['peak_height_m']=max(metric['peak_height_m'],z)
                if z>.055 and self.controller.contacts():metric['bilateral_lift_steps']+=1
            if self.active_skill=='normalize' and len(self.controller.checks)>self.last_face_check_count:
                from scipy.spatial.transform import Rotation
                p,q=self.parts[self.controller.color].get_world_pose();r=Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()
                self.face_check_evaluation.append({'color':self.controller.color,'check':self.controller.checks[-1],
                    'evaluation_only_normal_world':r[:,2].tolist(),'evaluation_only_position_m':p.tolist()})
                self.last_face_check_count=len(self.controller.checks)
            if self.controller.done:
                if self.controller.failed:
                    color=self.controller.color
                    correction=getattr(self.controller,'placement_correction',None)
                    if correction and self.active_skill=='unload' and self.staging_attempts.get(color,0)<2:
                        from clutter_extract import HeapExtraction
                        goal=self.controller.goal.copy();self.staging_attempts[color]=self.staging_attempts.get(color,0)+1
                        self.staging_corrections.append({'color':color,'source_RGB':correction,'goal_m':goal.tolist(),
                            'attempt':self.staging_attempts[color],'action':'physical RGB regrasp and placement; no pose reset'})
                        self.controller=HeapExtraction(self,correction,goal);self.controller.allow_heap_recovery=False
                        self.write_report();return
                    self.pick_attempts[color]=self.pick_attempts.get(color,0)+1
                    if getattr(self.controller,'recoverable_failure',False) and self.pick_attempts[color]<=2:
                        self.deferred_colors.add(color)
                        self.recovery_events.append({'color':color,'action':'raise, open and reacquire RGB; no body reset',
                            'attempt':self.pick_attempts[color],
                            'diagnostics':getattr(self.controller,'recovery_diagnostics',{})})
                        self.survey_round+=1;self.controller=HeapSurvey(self);self.active_skill='survey'
                    else:self.request_human(color,'重复抓取失败，需要人工分离并翻正零件')
                elif self.active_skill=='survey':
                    if self.human_request and self.human_request['state']=='verifying':
                        color=self.human_request['color']
                        observed=next((p for p in self.heap_estimates if p['color']==color and p['safe_candidate']
                            and p['face_hypothesis']=='up' and np.linalg.norm(np.array(p['position_m'])[:2]-HUMAN_POINT[:2])<.025
                            and all(other['color']==color or np.linalg.norm(np.array(other['position_m'])[:2]-np.array(p['position_m'])[:2])>.04
                                for other in self.heap_estimates)),None)
                        if observed is None:
                            self.human_history[-1]['RGB_verification_passed']=False
                            self.request_human(color,'重新观察未确认目标零件已正面朝上且单独摆放');self.write_report();return
                        self.human_history[-1].update({'RGB_verification_passed':True,'RGB_observation':observed})
                        self.human_confirmed.add(color);self.deferred_colors.discard(color);self.human_request=None
                    candidates=[p for p in self.heap_estimates if p['color'] not in self.extracted+self.removed_distractors
                        and p['color'] not in self.deferred_colors and p['safe_candidate']
                        and np.all(np.array(p['position_m'])[:2]>HEAP_BOUNDS[0])
                        and np.all(np.array(p['position_m'])[:2]<HEAP_BOUNDS[1])]
                    if not candidates:
                        if self.extra_surveys<2:
                            self.extra_surveys+=1;self.survey_round+=1;self.deferred_colors.clear()
                            self.controller=HeapSurvey(self);self.message='换一个观察方向重新检查遮挡。'
                        else:
                            remaining=[c for c in self.parts if c not in self.extracted+self.removed_distractors]
                            self.request_human(remaining[0] if remaining else None,'多视角观察后仍无可靠抓取姿态，需要人工分开遮挡零件')
                    else:
                        selected=max(candidates,key=lambda p:(p['top_height_m'],p['visible_bbox_fill'],-p['score_px']))
                        goal=np.r_[BUFFER_POINTS[len(self.extracted)],.0048]
                        if selected['color'].endswith('_distractor'):
                            from clutter_extract import HeapExtraction
                            goal=np.array([.13,.20 if not self.removed_distractors else -.20,.0048])
                            self.controller=HeapExtraction(self,selected,goal);self.active_skill='extract'
                        elif selected['face_hypothesis']!='up' or (selected['color'] not in self.human_confirmed and
                            len(selected.get('face_hypotheses',[]))>1 and selected['face_hypotheses'][1]['score_px']-selected['score_px']<.15):
                            self.request_human(selected['color'],'零件倒扣、侧躺或正反面判断不可靠')
                        else:
                            from clutter_extract import HeapExtraction
                            self.controller=HeapExtraction(self,selected,goal);self.active_skill='extract'
                elif self.active_skill=='load':
                    color=self.controller.color;self.load_evidence.append(self.controller.result_evidence)
                    from clutter_normalize import FixtureNormalize
                    self.face_model_used=True
                    self.last_face_check_count=0
                    self.controller=FixtureNormalize(self,color);self.active_skill='normalize'
                elif self.active_skill=='normalize':
                    from scipy.spatial.transform import Rotation
                    color=self.controller.color;_,q=self.parts[color].get_world_pose()
                    up=float(Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()[2,2])
                    if up<.85:raise RuntimeError('Independent evaluation rejected the RGB face decision')
                    self.normalization_evidence.append({**self.controller.result_evidence,'evaluation_only_up_z':up})
                    from clutter_normalize import FixtureUnload
                    self.controller=FixtureUnload(self,color,np.r_[BUFFER_POINTS[len(self.extracted)],.0048]);self.active_skill='unload'
                else:
                    color=self.controller.color
                    if color.endswith('_distractor'):self.removed_distractors.append(color)
                    else:self.extracted.append(color)
                    self.extraction_evidence.append(self.controller.result_evidence)
                    self.deferred_colors.clear();self.extra_surveys=0;self.pick_attempts={}
                    if self.active_skill in ['unload','extract'] and not color.endswith('_distractor'):
                        from scipy.spatial.transform import Rotation
                        _,q=self.parts[color].get_world_pose()
                        up=float(Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()[2,2])
                        if up<.98:raise RuntimeError('Independent evaluation: sorted piece did not settle top-face-up')
                        self.controller.result_evidence['evaluation_only_settled_up_z']=up
                        self.controller.result_evidence.update({'orientation_confirmed':True,'normalization_completed':True,
                            'face_verification_source':'multiview RGB geometry and optional human orientation confirmation; independent settled-pose audit'})
                        self.normalized.append(color)
                    if len(self.extracted)>=self.max_extractions:
                        if len(self.normalized)==6:
                            from clutter_scene import activate_assembly_surrogate
                            from assembly_perception import Inventory
                            self.task.world.render();activate_assembly_surrogate(self.task.stage,self.parts,self.normalized)
                            self.assembly_surrogate_active=True
                            self.inventory=Inventory();self.controller=None;self.active_skill='assembly'
                            self.message='六块零件已取出并整理为正面朝上，开始按说明书概念装配。'
                        else:
                            self.mode='paused';self.status='normalization_complete' if self.normalized else 'normalization_required'
                            self.message='已取出 '+str(len(self.extracted))+' 块，已确认并整理 '+str(len(self.normalized))+' 块；尚未完成整套装配。'
                    else:
                        self.task.kin.desired_rotation=np.diag([-1.,1.,-1.])
                        self.survey_round+=1;self.controller=HeapSurvey(self);self.active_skill='survey'
                self.write_report()
        except (RuntimeError,ValueError) as error:
            self.status='failed';self.mode='paused';self.message=str(error);self.write_report()
    def snapshot(self):
        data=super().snapshot()
        data.update({'scene_mode':'physical_heap','heap_piece_count':len(self.parts),
            'heap_observation':self.heap_observations,
            'extracted_colors':list(self.extracted),'extraction_goal':self.max_extractions,
            'normalized_colors':list(self.normalized),
            'removed_distractors':list(self.removed_distractors),
            'active_skill':self.active_skill,
            'collaboration_mode':'human_assisted_no_turning_fixture','human_request':self.human_request,
            'human_assistance_count':len(self.human_history),
            'trained_face_model_used':self.face_model_used,
            'normalization_completed':len(self.normalized)==6,'heap_to_assembly_completed':self.status=='complete' and len(self.normalized)==6})
        return data
    def write_report(self):
        if self.active_skill=='assembly':super().write_report()
        diagnostics={}
        if self.controller is not None and self.active_skill in ['load','extract','unload','normalize']:
            diagnostics={'source_RGB_m':self.controller.source.tolist(),'tcp_encoder_m':self.task.tcp.tolist(),
                'grasp_yaw_RGB_deg':self.controller.grasp_yaw_deg,
                'grasp_offset_RGB_m':self.controller.pick_offset.tolist(),
                'finger_mask_overlap_fraction':getattr(self.controller,'grasp_visual_overlap',None),
                'seat_height_encoder_m':self.controller.seat_height,
                'seat_contact_ticks':self.controller.seat_steps,
                'search_descent_m':getattr(self.controller,'search_descent',None),
                'table_contact_force_N':float(np.linalg.norm(np.asarray(self.controller.table_contact.get_contact_force_matrix(dt=.001)))),
                'finger_joints_m':self.task.robot.get_joint_positions()[self.task.fingers].tolist(),
                'finger_forces_N':np.linalg.norm(np.asarray(self.task.contacts.get_contact_force_matrix(dt=.001)),axis=-1).sum(axis=-1).tolist(),
                'evaluation_only_actual_body_position_m':self.parts[self.controller.color].get_world_pose()[0].tolist()}
        (OUT/f'run_{self.seed}.json').write_text(json.dumps({**self.snapshot(),
            'evaluation_only_scene':self.heap_audit,'robot_observation':self.heap_observations,
            'extraction_evidence':self.extraction_evidence,'physics_evaluation':self.heap_metrics,
            'fixture_load_evidence':self.load_evidence,'normalization_evidence':self.normalization_evidence,
            'recoveries':self.recovery_events,'active_diagnostics':diagnostics,
            'human_assistance':self.human_history,'simulated_human_pose_writes':self.human_pose_writes,
            'staging_corrections':self.staging_corrections,
            'evaluation_only_face_checks':self.face_check_evaluation,
            'manual_assembly_evidence':self.trace,
            'trained_face_model_used':self.face_model_used,
            'training_method':'RGB upright verification CNN; geometric pose and contact-feedback motion' if self.face_model_used else 'geometric multiview pose and contact-feedback motion only',
            'grasp_attachment_used':False,'body_pose_writes_after_reset':self.human_pose_writes,
            'robot_body_pose_writes_after_reset':0},indent=2))
