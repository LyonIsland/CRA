"""Instruction-conditioned assembly planning. No simulator object access.

The recipe describes the finished structure, never scattered source poses.
Observed tracks and verified connection evidence are supplied by adapters.
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RECIPE=ROOT/'assets/manuals/step_wall6/recipe.json'

def target_pose(recipe,step):
    pitch=recipe['geometry']['stud_pitch_m'];height=recipe['geometry']['brick_height_m']
    x,y,layer=step['anchor_stud'];nx,ny=step['part']['studs_xy']
    if step['yaw_deg']%180==90:nx,ny=ny,nx
    return {'position_m':[(x+(nx-1)/2)*pitch,(y+(ny-1)/2)*pitch,(layer+.5)*height],
            'yaw_deg':step['yaw_deg'],'frame':'assembly_fixture'}

def occupied(step):
    x,y,z=step['anchor_stud'];nx,ny=step['part']['studs_xy']
    if step['yaw_deg']%180==90:nx,ny=ny,nx
    return {(x+i,y+j,z) for i in range(nx) for j in range(ny)}

def validate_recipe(recipe):
    if recipe['schema_version']!='1.0':raise ValueError('Unknown recipe version')
    known={};cells=set()
    for step in recipe['steps']:
        sid=step['id']
        if sid in known:raise ValueError('Duplicate step id')
        if len(step['anchor_stud'])!=3 or any(not isinstance(v,int) or v<0 for v in step['anchor_stud']):raise ValueError('Invalid stud-grid anchor')
        if len(step['part']['studs_xy'])!=2 or any(not isinstance(v,int) or v<1 for v in step['part']['studs_xy']):raise ValueError('Invalid brick dimensions')
        if step['yaw_deg'] not in [0,90,180,270]:raise ValueError('Invalid stud-grid orientation')
        shape=occupied(step)
        if cells&shape:raise ValueError('Overlapping brick volumes')
        layer=step['anchor_stud'][2]
        connections=step['connections']
        if not connections:raise ValueError('Every brick needs declared support')
        actual=set()
        for connection in connections:
            support=connection['support_step']
            if support=='fixture':
                if layer!=0:raise ValueError('Only bottom layer can attach to fixture')
                contact={(x,y) for x,y,z in shape}
            else:
                if support not in known:raise ValueError('Dependency must precede this step')
                if known[support]['anchor_stud'][2]!=layer-1:raise ValueError('Support on wrong layer')
                contact={(x,y) for x,y,z in shape}&{(x,y) for x,y,z in occupied(known[support])}
            if len(contact)!=connection['stud_count']:raise ValueError('Stud overlap differs from instruction')
            actual|=contact
        if len(actual)!=len(shape):raise ValueError('This baseline requires every stud position supported')
        cells|=shape;known[sid]=step
    key=lambda p:(p['catalog_id'],tuple(p['studs_xy']),p['color'])
    actual_bom=Counter(key(s['part']) for s in recipe['steps'])
    declared=Counter()
    for part in recipe['bom']:
        if not isinstance(part['quantity'],int) or part['quantity']<1:raise ValueError('Invalid BOM quantity')
        declared[key(part)]+=part['quantity']
    if actual_bom!=declared:raise ValueError('BOM differs from instruction steps')
    if any(key in json.dumps(recipe) for key in ['source_position','loose_pose','spawn_seed']):
        raise ValueError('Recipe must not contain scattered source information')
    return True

class InstructionAgent:
    def __init__(self,recipe=None,allow_test_evidence=False,execution_mode='physical'):
        self.recipe=recipe or json.loads(RECIPE.read_text(encoding='utf-8'))
        validate_recipe(self.recipe)
        self.recipe_hash=hashlib.sha256(json.dumps(self.recipe,sort_keys=True).encode()).hexdigest()
        self.completed=[];self.reserved={};self.last_observation=None
        self.allow_test_evidence=allow_test_evidence
        if execution_mode not in ['physical','concept']:raise ValueError('Unknown execution mode')
        self.execution_mode=execution_mode
        self.state='waiting_for_observation';self.reason=None;self.last_plan=None

    def observe(self,observation):
        if observation.get('source') not in ['wrist_rgb','recorded_rgb','planning_test_fixture']:
            raise ValueError('Observation adapter must declare provenance')
        if observation['source']=='planning_test_fixture' and not self.allow_test_evidence:raise ValueError('Test observations are disabled')
        if not observation.get('calibration_id'):raise ValueError('Missing calibrated observation frame')
        if observation.get('frame')!='robot_base':raise ValueError('Observation frame must be robot_base')
        ids=set()
        for item in observation.get('pieces',[]):
            if not isinstance(item['track_id'],str) or not item['track_id']:raise ValueError('Invalid track id')
            if item['track_id'] in ids:raise ValueError('Duplicate track id')
            ids.add(item['track_id'])
            pose=item['pose'];values=pose['position_m']+[pose['yaw_deg'],item['confidence']]
            if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):raise ValueError('Invalid observation values')
            if len(pose['position_m'])!=3 or not 0<=item['confidence']<=1:raise ValueError('Invalid pose/confidence')
        fixture=observation.get('fixture',{})
        if fixture.get('registered'):
            pose=fixture['pose'];values=pose['position_m']+[pose['yaw_deg'],fixture['confidence']]
            if len(pose['position_m'])!=3 or not all(isinstance(v,(int,float)) and math.isfinite(v) for v in values):raise ValueError('Invalid fixture registration')
        self.last_observation=observation;self.state='observed';self.reason=None

    def next_plan(self,capabilities=None):
        if len(self.completed)==len(self.recipe['steps']):
            self.state='complete';return {'status':'complete','completed_steps':list(self.completed)}
        if not self.last_observation:
            self.state='search';return {'status':'need_observation','action':'scan_workspace'}
        step=self.recipe['steps'][len(self.completed)]
        candidates=[]
        for piece in self.last_observation['pieces']:
            part=step['part']
            if piece['track_id'] in self.reserved:continue
            if piece.get('region','loose')!='loose' or piece.get('occluded',False):continue
            if piece.get('catalog_id')!=part['catalog_id'] or piece.get('color')!=part['color']:continue
            if piece.get('studs_xy')!=part['studs_xy'] or piece['confidence']<.85:continue
            if piece.get('xy_sigma_m',1.)>.003:continue
            candidates.append(piece)
        if not candidates:
            self.state='search';self.reason='所需积木尚未可靠识别，继续扫描或请求人工补料。'
            return {'status':'need_piece','step_id':step['id'],'required_part':step['part'],'action':'scan_workspace','reason':self.reason}
        piece=max(candidates,key=lambda p:(p.get('observed_frame',0),p['confidence']))
        target=target_pose(self.recipe,step)
        required=['visual_pick','oriented_transport','force_limited_insertion','connection_verification','fixture_registration']
        if self.execution_mode=='concept':
            required=['visual_pick','concept_transport','concept_connection_model','placement_verification','fixture_registration']
        capabilities=capabilities or {}
        missing=[name for name in required if not capabilities.get(name,False)]
        fixture=self.last_observation.get('fixture',{})
        registered=fixture.get('registered') is True and fixture.get('confidence',0.)>=.95
        if not registered and 'fixture_registration' not in missing:missing.append('fixture_registration')
        world_target=None
        if registered:
            origin=fixture['pose']['position_m'];angle=math.radians(fixture['pose']['yaw_deg'])
            x,y,z=target['position_m']
            world_target={'position_m':[origin[0]+math.cos(angle)*x-math.sin(angle)*y,
                origin[1]+math.sin(angle)*x+math.cos(angle)*y,origin[2]+z],
                'yaw_deg':fixture['pose']['yaw_deg']+target['yaw_deg'],'frame':'robot_base'}
        plan={'status':'blocked_execution' if missing else 'ready','step_id':step['id'],
              'recipe_sha256':self.recipe_hash,'selected_track_id':piece['track_id'],
              'selected_part':step['part'],'source_pose_observed':piece['pose'],'target_pose':target,
              'target_pose_robot_base':world_target,'fixture_observed':fixture,
              'connections':step['connections'],'actions':['reobserve_selected_piece','grasp','verify_grasp','orient',
                'move_above_target','align_studs','press_with_force_limit','release','verify_pose_and_connections'],
              'missing_capabilities':missing,'completed_steps':list(self.completed),
              'source_of_target':'instruction','source_of_pick_pose':'current_observation'}
        plan['execution_mode']=self.execution_mode
        if self.execution_mode=='concept':plan['actions']=['reobserve_selected_piece','grasp','verify_grasp','orient','move_above_target','seat_on_support','engage_simulated_connector','release','verify_concept_placement']
        self.last_plan=plan;self.state=plan['status'];return plan

    def confirm(self,evidence):
        if not self.last_plan or self.last_plan['status']!='ready':raise ValueError('No executable instruction awaiting confirmation')
        step=self.recipe['steps'][len(self.completed)]
        required={c['support_step']:c['stud_count'] for c in step['connections']}
        if evidence.get('step_id')!=step['id'] or evidence.get('track_id')!=self.last_plan['selected_track_id']:
            raise ValueError('Evidence does not match planned piece/step')
        errors=[evidence.get('position_error_m',1.),evidence.get('yaw_error_deg',180.)]
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>=0 for v in errors):raise ValueError('Invalid verification error')
        tolerance=.003 if self.execution_mode=='concept' else .001
        yaw_tolerance=6 if self.execution_mode=='concept' else 2
        if errors[0]>tolerance or errors[1]>yaw_tolerance:
            self.state='verify_failed';return False
        if evidence.get('connections')!=required or evidence.get('connection_verified') is not True:
            self.state='verify_failed';return False
        allowed=['measured_connection','validated_snapfit_backend','planning_test_fixture']
        if self.execution_mode=='concept':allowed.append('simulated_connector_surrogate')
        if evidence.get('verification_source') not in allowed:
            raise ValueError('Visual proximity is not connection verification')
        if evidence['verification_source']=='planning_test_fixture' and not self.allow_test_evidence:raise ValueError('Test evidence is disabled')
        self.completed.append(step['id']);self.reserved[self.last_plan['selected_track_id']]=step['id']
        self.last_plan=None;self.state='complete' if len(self.completed)==len(self.recipe['steps']) else 'waiting_for_observation'
        return True

    def conditional_overview(self):
        """Lookahead only: never changes completion or fabricates connections."""
        observation=self.last_observation or {'pieces':[]};used=set(self.reserved);plans=[]
        for step in self.recipe['steps'][len(self.completed):]:
            part=step['part']
            candidates=[p for p in observation['pieces'] if p['track_id'] not in used
                and p.get('region','loose')=='loose' and not p.get('occluded',False)
                and p.get('catalog_id')==part['catalog_id'] and p.get('color')==part['color']
                and p.get('studs_xy')==part['studs_xy'] and p['confidence']>=.85 and p.get('xy_sigma_m',1.)<=.003]
            piece=max(candidates,key=lambda p:(p.get('observed_frame',0),p['confidence'])) if candidates else None
            if piece:used.add(piece['track_id'])
            plans.append({'step_id':step['id'],'part':part,'selected_track_id':piece['track_id'] if piece else None,
                'source_pose_observed':piece['pose'] if piece else None,'target_pose':target_pose(self.recipe,step),
                'requires_verified_supports':[c['support_step'] for c in step['connections']],
                'status':'conditional_plan' if piece else 'need_piece','executable_now':False})
        return {'planning_only':True,'completed_steps_unchanged':list(self.completed),'steps':plans}

    def snapshot(self):
        return {'recipe_id':self.recipe['id'],'state':self.state,'completed_steps':list(self.completed),
                'reason':self.reason,'last_plan':self.last_plan,'observation':self.last_observation}
