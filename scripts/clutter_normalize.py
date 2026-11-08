"""Robot loads/unloads a friction regripper; trained RGB verifies top face.

Only fixture actuator positions are commanded. Loose-part transforms are never
queried or written here. Independent evaluation belongs to ClutterSession.
"""
import json
import numpy as np
from clutter_extract import HeapExtraction
from clutter_face_model import UprightVerifier,station_observation
from clutter_perception import observe,fit_piece
from rotary_regripper import CENTER
from wrist_vision import camera_pose,intrinsics
from assembly_agent import ROOT

class FixtureLoad(HeapExtraction):
    def __init__(self,session,piece):
        super().__init__(session,piece,CENTER.copy())
        self.goal=CENTER.copy();self.task.goal=self.goal.copy();self.fixture=session.regripper
        self.fixture.watch(self.task.world,self.task.brick.prim_path)
        self.fixture.command(closed=False,roll_deg=0.,pitch_deg=0.)
        self.clamp_steps=0
    def step(self):
        if self.phase=='lower':
            self.steps+=1;self.phase_steps+=1;self.message='放入机械翻面夹具'
            self.refresh_carry_offset()
            target=np.r_[CENTER[:2]-self.carry_offset,CENTER[2]+self.grasp_z_offset]
            if self.move(target,.002):self.fixture.command(closed=True)
            self.clamp_steps=self.clamp_steps+1 if self.fixture.bilateral() else 0
            if self.clamp_steps>=10:self.transition('release')
            elif self.phase_steps>600:self.fail('翻面夹具未建立双侧接触。')
            return
        if self.phase=='retreat':
            self.steps+=1;self.phase_steps+=1;self.message='撤离夹爪，零件由机械夹具接触保持'
            if not self.fixture.bilateral():self.fail('翻面夹具保持接触丢失。');return
            if self.move(np.r_[CENTER[:2],.085],.025):
                self.done=True;self.phase='fixture_loaded'
                self.result_evidence={'color':self.color,'source':'RGB multiview heap pose',
                    'source_pose_from_RGB':self.piece,
                    'robot_loaded_fixture':True,'fixture_contact_forces_N':self.fixture.forces(),
                    'brick_attachment_used':False,'grasp_yaw_from_RGB_deg':self.grasp_yaw_deg}
            return
        super().step()

class FixtureNormalize(HeapExtraction):
    # Candidate actuator configurations, not simulator-derived object poses.
    ORIENTATIONS=[(0.,0.),(90.,0.),(180.,0.),(-90.,0.),(0.,90.),(0.,-90.)]
    def __init__(self,session,color):
        piece={'color':color,'position_m':CENTER.tolist(),'yaw_deg':0.,'face_hypothesis':'up'}
        super().__init__(session,piece,CENTER.copy())
        self.fixture=session.regripper;self.index=0;self.phase='fixture_inspect';self.checks=[];self.confirmations=0
        self.view_index=0;self.inspection_views=[[.28,0,.08],[.275,.003,.08],[.285,-.003,.08]]
        report=json.loads((ROOT/'outputs/clutter_face/training.json').read_text())
        if not report['approved_for_simulated_station_trial']:raise RuntimeError('RGB 正反面模型尚未通过独立验证集检查。')
        self.verifier=UprightVerifier(ROOT/'outputs/clutter_face/upright.pt')
    def step(self):
        if self.done:return
        self.steps+=1;self.phase_steps+=1
        if not self.fixture.bilateral():
            self.lost_contact+=1;self.move([.28,0,.085],.025)
            if self.lost_contact>15:self.fail('翻面期间机械夹具接触丢失。')
            return
        self.lost_contact=0
        if self.phase=='fixture_turn':
            self.message='机械夹具旋转；靠接触保持零件'
            self.move([.28,0,.085],.025)
            if self.phase_steps>=80:self.transition('fixture_inspect')
        elif self.phase=='fixture_inspect':
            self.message='用训练后的 RGB 模型检查凸点面是否朝上'
            if not self.move(self.inspection_views[self.view_index],.025):
                if self.phase_steps>650:self.fail('正反面观察姿态不可达。')
                return
            self.last_rgb=self.sensor.capture()
            from PIL import Image
            Image.fromarray(self.last_rgb).save(ROOT/f'outputs/clutter/inspect_{self.session.seed}_{self.color}_{self.index}_{len(self.checks)}.png')
            evidence=self.verifier.predict(self.last_rgb,camera_pose(self.task.kin,self.task.q),self.color)
            self.checks.append({'actuator_orientation':self.ORIENTATIONS[self.index],'view_index':self.view_index,**evidence})
            self.confirmations=self.confirmations+1 if evidence['upright'] else 0
            if self.confirmations>=2:
                self.done=True;self.phase='fixture_top_face_verified';self.result_evidence={'color':self.color,
                    'upright_visual_checks':self.checks,'training_source':'synthetic isolated-station wrist RGB',
                    'brick_attachment_used':False,'face_decision_source':'RGB classifier only'}
            elif not evidence['upright']:
                # Scores are not calibrated confidence. A low score under jaw
                # occlusion still merits another measured wrist viewpoint.
                if self.view_index<2:
                    self.view_index+=1;self.stable=0;self.phase_steps=0;return
                self.index+=1
                if self.index>=len(self.ORIENTATIONS):self.fail('六个机械姿态均未通过 RGB 正面检查，停止整理。');return
                roll,pitch=self.ORIENTATIONS[self.index];self.fixture.command(roll_deg=roll,pitch_deg=pitch)
                self.view_index=0
                self.transition('fixture_turn')

class FixtureUnload(HeapExtraction):
    def __init__(self,session,color,goal):
        piece={'color':color,'position_m':CENTER.tolist(),'yaw_deg':0.,'face_hypothesis':'up'}
        super().__init__(session,piece,goal)
        self.fixture=session.regripper;self.opening_steps=0
        self.allow_heap_recovery=False
    def refine_source(self):
        self.last_rgb=self.sensor.capture();pose=camera_pose(self.task.kin,self.task.q)
        seen=station_observation(self.last_rgb,pose,self.color)
        if seen is None:return False
        ray=pose[:3,:3]@(np.linalg.inv(intrinsics())@np.r_[seen['center_uv'],1.]*[1,-1,-1])
        estimated=pose[:3,3]+ray*((CENTER[2]-pose[2,3])/ray[2])
        if np.linalg.norm(estimated[:2]-CENTER[:2])>.025:return False
        self.source[:2]=estimated[:2]
        axis=seen['principal_axis_uv'];direction=pose[:3,0]*axis[0]-pose[:3,1]*axis[1]
        self.hold_yaw=float((np.rad2deg(np.arctan2(direction[1],direction[0]))+90)%180-90)
        return True
    def choose_grasp_rotation(self):
        accepted=super().choose_grasp_rotation()
        if accepted:self.grasp_opening=.025  # isolated fixture: allow either horizontal long-axis orientation
        return accepted
    def step(self):
        if self.phase=='close':
            self.steps+=1;self.phase_steps+=1;self.message='机械臂重新抓取已确认正面朝上的零件'
            self.move(self.source+[0,0,self.grasp_z_offset],max(.002,.025-self.phase_steps*.00035))
            self.contact_streak=self.contact_streak+1 if self.contacts() else 0
            if self.contact_streak>=10:
                self.fixture.command(closed=False);self.opening_steps+=1
                if self.opening_steps>=15:
                    self.escape_start_tcp=self.task.tcp[:2].copy();self.transition('fixture_escape')
            elif self.phase_steps>150:self.fail('从翻面夹具重新抓取失败。')
            return
        if self.phase=='fixture_escape':
            self.steps+=1;self.phase_steps+=1;self.message='保持夹持，水平离开翻面夹具后再抬高'
            if not self.contacts():self.lost_contact+=1
            else:self.lost_contact=0
            if self.lost_contact>15:self.fail('离开翻面夹具时夹持丢失。');return
            if self.move(np.r_[self.source[:2]+[0,-.035],self.source[2]+self.grasp_z_offset],.002):
                self.source[:2]+=self.task.tcp[:2]-self.escape_start_tcp;self.transition('lift')
            elif self.phase_steps>650:self.fail('无法水平离开翻面夹具。')
            return
        super().step()
