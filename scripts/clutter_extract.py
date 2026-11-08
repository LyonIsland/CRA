"""Contact-feedback extraction from RGB multiview heap estimates.

This skill only separates pieces. It does not assume a picked piece is upright
and cannot count sorting or visual proximity as completed manual assembly.
"""
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares
from live_assembly import StepController,angle_error
from tabletop import solve_checked
from clutter_perception import observe,projected_bbox,model_for,FACES
from wrist_vision import camera_pose,project

class HeapExtraction(StepController):
    def __init__(self,session,piece,goal):
        super().__init__(session)
        from isaacsim.core.api.sensors import RigidContactView
        self.piece=piece;self.color=piece['color'];self.source=np.array(piece['position_m'])
        self.model=model_for(self.color)
        self.hold_yaw=piece['yaw_deg'];self.goal=np.array(goal);self.task.goal=self.goal.copy()
        self.instruction={'id':'extract_'+self.color,'part':{'color':self.color}}
        self.task.brick=session.parts[self.color]
        self.task.contacts=RigidContactView(prim_paths_expr=['/World/Piper/link7','/World/Piper/link8'],
            filter_paths_expr=[[self.task.brick.prim_path],[self.task.brick.prim_path]],max_contact_count=128)
        self.task.contacts.initialize(self.task.world.physics_sim_view)
        self.table_contact=RigidContactView(prim_paths_expr=self.task.brick.prim_path,
            filter_paths_expr=[['/World/WorkSurface']],max_contact_count=128)
        self.table_contact.initialize(self.task.world.physics_sim_view)
        face=Rotation.from_euler('xyz',FACES[piece['face_hypothesis']],degrees=True).as_matrix()
        self.rest_z=-float((self.model@face.T)[:,2].min());self.goal[2]=self.rest_z
        self.grasp_z_offset=max(.0008,float((self.model@face.T)[:,2].max())-.0035)
        self.phase='approach';self.message='接近堆中可见零件';self.carry_offset=np.zeros(2)
        self.result_evidence=None;self.search_descent=0.
        self.grasp_opening=.025;self.recoverable_failure=False
        self.allow_heap_recovery=True;self.post_rotation_checks=0;self.progress_error=None
        self.pick_offset=np.zeros(2)
        self.reference_source=self.source.copy()

    def begin_safe_recovery(self,reason='bilateral contact not established'):
        self.recovery_diagnostics={'reason':reason,'phase':self.phase,
            'tcp_encoder_m':self.task.tcp.tolist(),'source_RGB_m':self.source.tolist(),
            'grasp_yaw_RGB_deg':self.grasp_yaw_deg,'grasp_offset_RGB_m':self.pick_offset.tolist(),
            'finger_joints_m':self.task.robot.get_joint_positions()[self.task.fingers].tolist(),
            'net_finger_forces_N':np.linalg.norm(np.asarray(self.task.contacts.get_net_contact_forces(dt=.001)),axis=-1).tolist(),
            'external_contacts_N':self.external_contacts()}
        self.recovery_xy=self.task.tcp[:2].copy();self.transition('recover_raise')

    def external_contacts(self):
        names=[*self.session.parts,'assembly_fixture','table']
        values=np.linalg.norm(np.asarray(self.debug_contact.get_contact_force_matrix(dt=.001)),axis=-1)[-2:]
        return {name:values[:,i].tolist() for i,name in enumerate(names)}

    def choose_grasp_rotation(self):
        kin=self.task.kin;choices=[];base=np.diag([-1.,1.,-1.]);yaw=angle_error(self.hold_yaw,0.)
        face=Rotation.from_euler('xyz',FACES[self.piece['face_hypothesis']],degrees=True).as_matrix()
        shape=self.model@face.T
        for candidate in [yaw,yaw-180,yaw+180,yaw+90,yaw-90]:
            transverse=abs(angle_error(candidate,yaw))>45
            half_width=float(np.max(abs(shape[:,0 if transverse else 1])))
            opening=max(.008,half_width+.005)
            if opening>.025:continue
            kin.desired_rotation=Rotation.from_euler('z',candidate,degrees=True).as_matrix()@base
            high=solve_checked(kin,np.r_[self.source[:2],.08],self.task.q)
            axis=Rotation.from_euler('z',self.hold_yaw,degrees=True).as_matrix()[:2,0]
            offsets=[0.,-.008,.008] if self.allow_heap_recovery and not transverse and np.ptp(shape[:,0])>.025 else [0.]
            for shift in offsets:
                offset=axis*shift
                low=solve_checked(kin,self.source+np.r_[offset,self.grasp_z_offset],high) if high is not None else None
                if low is not None:
                    clearance=self.grasp_clearance(candidate,opening,offset)
                    from clutter_perception import finger_visual_overlap
                    overlap=finger_visual_overlap(self.session.heap_views,self.session.heap_estimates,self.color,
                        self.source+np.r_[offset,self.grasp_z_offset],candidate,opening) if self.allow_heap_recovery else 0.
                    choices.append((overlap,-clearance,abs(shift),float(np.linalg.norm(high-self.task.q)),candidate,opening,offset))
        if not choices:kin.desired_rotation=base;self.fail('堆中目标的抓取姿态不可达。');return False
        self.grasp_visual_overlap,_,_,_,self.grasp_yaw_deg,self.grasp_opening,self.pick_offset=min(choices,key=lambda c:c[:4])
        kin.desired_rotation=Rotation.from_euler('z',self.grasp_yaw_deg,degrees=True).as_matrix()@base
        return True

    def grasp_clearance(self,yaw,opening,offset):
        """Conservative finger clearance against other RGB-fitted CAD shapes."""
        r=Rotation.from_euler('z',yaw,degrees=True).as_matrix()[:2,:2]
        z=self.source[2]+self.grasp_z_offset;clearance=.02
        for other in self.session.heap_estimates:
            if other['color']==self.color:continue
            if other['top_height_m']<z-.004 or other['bottom_height_m']>z+.004:continue
            points=model_for(other['color'])@np.asarray(other['rotation_matrix']).T+other['position_m']
            for side in [-1,1]:
                centre=self.source[:2]+offset+r[:,1]*side*(opening+.002)
                local=(points[:,:2]-centre)@r
                # Positive separating distance means no overlap with this pad.
                gap=max(float(local[:,0].min()-.010),float(-.010-local[:,0].max()),
                    float(local[:,1].min()-.002),float(-.002-local[:,1].max()))
                clearance=min(clearance,gap)
        return round(clearance,4)

    def refine_source(self):
        self.last_rgb=self.sensor.capture();pose=camera_pose(self.task.kin,self.task.q)
        observation=observe(self.last_rgb,pose).get(self.color)
        if observation is None:return False
        face=Rotation.from_euler('xyz',FACES[self.piece['face_hypothesis']],degrees=True).as_matrix()
        def residual(v):
            r=Rotation.from_euler('z',self.hold_yaw,degrees=True).as_matrix()@face
            points=self.model@r.T+np.r_[v,self.source[2]]
            return projected_bbox(points,pose)-observation['bbox']
        predicted=projected_bbox(self.model@(Rotation.from_euler('z',self.hold_yaw,degrees=True).as_matrix()@face).T+self.source,pose)
        expected_center=np.array([(predicted[0]+predicted[1])/2,(predicted[2]+predicted[3])/2])
        bbox=observation['bbox'];seen_center=np.array([(bbox[0]+bbox[1])/2,(bbox[2]+bbox[3])/2])
        if np.linalg.norm(seen_center-expected_center)*observation['pixel_scale']>8:return False
        # A single partly occluded bbox cannot replace multiview orientation.
        # Preserve that yaw and constrain corrections around the original RGB
        # position, rather than accumulating up to 8 mm on each reobservation.
        fit=least_squares(residual,self.source[:2],
            bounds=(self.reference_source[:2]-.002,self.reference_source[:2]+.002),max_nfev=40)
        if np.linalg.norm(fit.fun)<2.:
            self.source[:2]=fit.x
        return True

    def refresh_carry_offset(self):
        """Piper's two independent finger encoders locate the closing midpoint.

        Pad centres are TCP +/- Y*(opening+2 mm). With unequal q7/q8,
        their midpoint is TCP - Y*(q7+q8)/2. Retain the RGB grasp offset
        along the pads; update the closing direction from measured encoders.
        """
        rotation=self.task.kin.forward(self.task.q)[1];axis=rotation[:2,1]
        fingers=self.task.robot.get_joint_positions()[self.task.fingers]
        midpoint=-float(fingers.sum())/2
        self.carry_offset+=axis*(midpoint-float(axis@self.carry_offset))/max(1e-8,float(axis@axis))

    def step(self):
        if self.done:return
        self.steps+=1;self.phase_steps+=1;t=self.task;p=self.phase
        if self.phase_steps>(1400 if p=='lower' else 700) or self.steps>5000:
            self.fail('堆中取件阶段超时；未标记成功。');return
        labels={'approach':'接近堆中可见零件','align':'复查目标轮廓','orient_pick':'按目标朝向转爪',
            'descend':'下降到视觉估计的零件高度','close':'接触夹持','lift':'从零件堆抬起',
            'align_transport':'转到整理方向','via_source':'离开零件堆','via_goal':'搬运到整理区',
            'transfer':'移到整理位','lower':'放到整理台','release':'松开夹爪','retreat':'撤离并检查',
            'recover_raise':'抓取受阻，先垂直抬高','recover_open':'松爪后重新观察零件堆'}
        self.message=self.color+'：'+labels.get(p,p)
        if p=='approach':
            if self.move(np.r_[self.source[:2],.08],.025):self.transition('align')
        elif p=='align':
            if not self.refine_source():
                self.recoverable_failure=self.allow_heap_recovery;self.fail('近距离观察与目标位置不一致，要求重新扫描。');return
            if self.choose_grasp_rotation():self.transition('orient_pick')
        elif p=='orient_pick':
            if self.move(np.r_[self.source[:2]+self.pick_offset,.08],self.grasp_opening):
                self.post_rotation_checks+=1
                if not self.refine_source():
                    t.kin.desired_rotation=np.diag([-1.,1.,-1.]);self.recoverable_failure=self.allow_heap_recovery
                    self.fail('转爪后目标位置已变化，要求重新扫描。');return
                if abs(angle_error(self.hold_yaw,self.grasp_yaw_deg))>4 and self.post_rotation_checks<3:
                    self.choose_grasp_rotation();self.stable=0;return
                self.transition('descend')
        elif p=='descend':
            target=self.source+np.r_[self.pick_offset,self.grasp_z_offset]
            reached=self.move(target,self.grasp_opening)
            # Initial contact with the selected brick is expected at grasp
            # height. Stop on other obstacles; target-induced stalls are
            # checked separately below before allowing prolonged pushing.
            external=self.external_contacts()
            force=np.array([v for name,v in external.items() if name!=self.color])
            error=float(np.linalg.norm(t.tcp-target))
            if np.max(force)>.1 and error>.0015:
                self.begin_safe_recovery('early finger contact during descent');return
            if self.phase_steps%50==1:
                if self.progress_error is not None and self.progress_error-error<.0003 and error>.0015:
                    self.begin_safe_recovery('descent progress stalled');return
                self.progress_error=error
            if reached:self.transition('close')
        elif p=='close':
            self.move(self.source+np.r_[self.pick_offset,self.grasp_z_offset],max(.002,self.grasp_opening-self.phase_steps*.00025))
            self.contact_streak=self.contact_streak+1 if self.contacts() else 0
            if self.contact_streak>=10:self.transition('lift')
            elif self.phase_steps>130:
                self.begin_safe_recovery()
        elif p=='recover_raise':
            if self.move(np.r_[self.recovery_xy,.08],self.grasp_opening):self.transition('recover_open')
        elif p=='recover_open':
            if self.move(np.r_[self.recovery_xy,.08],.025):
                t.kin.desired_rotation=np.diag([-1.,1.,-1.])
                self.recoverable_failure=self.allow_heap_recovery
                reason=self.recovery_diagnostics['reason']
                label={'early finger contact during descent':'下降时碰到邻近零件或桌面',
                    'descent progress stalled':'下降受阻','bilateral contact not established':'双指接触未建立',
                    'grasp contact lost during transport':'搬运中夹持丢失'}.get(reason,reason)
                self.fail(label+'；已抬起松爪，要求重新观察。')
        elif p in ['lift','align_transport','via_source','via_goal','transfer']:
            self.lost_contact=0 if self.contacts() else self.lost_contact+1
            if self.lost_contact>15:
                if self.allow_heap_recovery:self.begin_safe_recovery('grasp contact lost during transport')
                else:self.fail('整理搬运中夹持丢失，停止确认。')
                return
            targets={'lift':np.r_[self.source[:2]+self.pick_offset,.08],'align_transport':np.r_[self.source[:2]+self.pick_offset,.08],
                'via_source':[.28,self.source[1],.08],'via_goal':[.28,self.goal[1],.08],
                'transfer':np.r_[self.goal[:2],.08]}
            if self.move(targets[p],.002):
                if p=='lift':
                    self.carry_offset=self.source[:2]-t.tcp[:2]
                    t.kin.desired_rotation=np.diag([-1.,1.,-1.]);self.transition('align_transport')
                else:
                    if p=='align_transport':
                        self.carry_offset=Rotation.from_euler('z',-self.grasp_yaw_deg,degrees=True).as_matrix()[:2,:2]@self.carry_offset
                        self.refresh_carry_offset()
                    self.transition({'align_transport':'via_source','via_source':'via_goal','via_goal':'transfer','transfer':'lower'}[p])
        elif p=='lower':
            self.refresh_carry_offset()
            z=self.goal[2]+self.grasp_z_offset-self.search_descent if self.seat_height is None else self.seat_height
            reached=self.move(np.r_[self.goal[:2]-self.carry_offset,z],.002)
            force=float(np.linalg.norm(np.asarray(self.table_contact.get_contact_force_matrix(dt=.001))))
            if force>.002 and self.seat_height is None:self.seat_height=float(t.tcp[2])-.0001
            self.seat_steps=self.seat_steps+1 if force>.002 else 0
            if self.seat_height is not None and force<.002 and self.phase_steps%8==0:
                floor=self.goal[2]+self.grasp_z_offset-.005
                self.seat_height=max(floor,self.seat_height-.00005)
            # Independent jaws can shift their midpoint while XY tracks it.
            # Do not deadlock vertical contact search on full XY settling.
            if abs(t.tcp[2]-z)<.0012 and force<.002 and self.phase_steps%8==0:
                self.search_descent=min(.005,self.search_descent+.0001)
            if self.seat_steps>=8:self.transition('release')
        elif p=='release':
            self.move(np.r_[self.goal[:2]-self.carry_offset,self.release_height],.025)
            if self.phase_steps>=25:self.transition('retreat')
        elif p=='retreat':
            if self.move(np.r_[self.goal[:2]-self.carry_offset,.085],.025):
                self.last_rgb=self.sensor.capture();pose=camera_pose(t.kin,t.q)
                observation=observe(self.last_rgb,pose).get(self.color)
                if observation is None:self.fail('整理位视觉复查未找到目标。');return
                expected=project(self.goal,pose)[0]
                if np.linalg.norm(observation['center_uv']-expected)>12:
                    if not self.color.endswith('_distractor'):
                        from clutter_perception import released_table_piece
                        self.placement_correction=released_table_piece(self.last_rgb,pose,self.color,self.goal[:2])
                    self.fail('整理位视觉误差过大。');return
                self.result_evidence={'color':self.color,'goal_m':self.goal.tolist(),
                    'source':'current wrist RGB multiview geometry','source_face_hypothesis':self.piece['face_hypothesis'],
                    'orientation_confirmed':False,'normalization_completed':False,'attachment_used':False,
                    'grasp_yaw_from_RGB_deg':self.grasp_yaw_deg,'control_steps':self.steps}
                self.done=True;self.phase='extracted';self.message='已物理取出 '+self.color+'，正反面仍需单独确认。'
