"""RGB grasp execution with a separate, read-only physical evaluator.

Controller receives ONLY camera arrays. Evaluation never determines actions,
phase transitions, retries, or episode termination.
"""
import json
from pathlib import Path
import time
import hashlib
import numpy as np
from PIL import Image


def run(app,world,stage,parts,sensor,actuator,apply_action,out,args):
    from isaacsim.core.api.sensors import RigidContactView
    from camera_live import write_state,atomic_bytes
    if (out/'result.json').exists():raise ValueError('Refusing to overwrite a grasp run')
    policy_source=Path(__file__).with_name('camera_grasp_policy.py').read_bytes()
    (out/'policy-source.py').write_bytes(policy_source)
    contacts=RigidContactView(prim_paths_expr=['/World/Piper/link7','/World/Piper/link8'],
        filter_paths_expr=[[p.prim_path for p in parts.values()]]*2,max_contact_count=256)
    contacts.initialize(world.physics_sim_view)
    initial_z=np.array([p.get_world_pose()[0][2] for p in parts.values()])
    initial_positions=np.array([p.get_world_pose()[0] for p in parts.values()])
    stable=np.zeros(len(parts),dtype=int);longest=stable.copy();peaks=np.zeros(len(parts))
    trace=[];evaluation=[];started=time.monotonic();step=0
    if args.grasp_plan:
        if args.grasp_negative_open:
            raise ValueError('Negative-open requires the visual controller, not a commissioning replay')
        plan=json.loads(Path(args.grasp_plan).read_text(encoding='utf-8'))
        if not isinstance(plan,list) or not plan:raise ValueError('Expected a nonempty commissioning action list')
        for item in plan:
            if not isinstance(item,dict) or set(item)-{'action','repeat','label'}:
                raise ValueError('Unexpected commissioning fields')
            action=np.asarray(item.get('action'),dtype=float)
            repeat=item.get('repeat',1);label=item.get('label','probe')
            if action.shape!=(7,) or not np.isfinite(action).all() or np.abs(action).max()>1:
                raise ValueError('Expected seven bounded commissioning increments')
            if type(repeat) is not int or repeat<1 or not isinstance(label,str) or not label.replace('-','').isalnum():
                raise ValueError('Invalid commissioning repeat or filename label')
        if sum(item.get('repeat',1) for item in plan)>args.frames:raise ValueError('Commissioning plan exceeds frame limit')
        controller=None
    else:
        from camera_grasp_policy import VisualGrasp
        controller=VisualGrasp();plan=None
    def capture(label):
        rgb=sensor.capture()
        Image.fromarray(rgb).save(out/(label+'.png'))
        Image.fromarray(rgb).save(out/'wrist.png')
        return rgb
    def execute(action):
        nonlocal step
        action=np.asarray(action,dtype=float).copy()
        before=actuator.target.copy()
        command=actuator.step(action)
        actual=(command-before)/np.array([.01]*6+[.001])
        if controller is not None and np.max(np.abs(actual[:6]-np.asarray(action)[:6]))>1e-5:
            raise RuntimeError('Arm command hit limit; stop, do not estimate a false image Jacobian')
        apply_action(command)
        for _ in range(20):world.step(render=False)
        world.render();step+=1
        # Evaluation-only channel: never passed to controller/capture/plan.
        positions=np.array([p.get_world_pose()[0] for p in parts.values()])
        lift=positions[:,2]-initial_z;np.maximum(peaks,lift,out=peaks)
        forces=np.asarray(contacts.get_contact_force_matrix(dt=.001))
        magnitudes=np.linalg.norm(forces,axis=-1).reshape(2,len(parts))
        bilateral=np.all(magnitudes>.001,axis=0)
        holding=(lift>.03)&bilateral
        stable[:]=np.where(holding,stable+1,0);np.maximum(longest,stable,out=longest)
        evaluation.append({'step':step,'positions':positions.tolist(),'bilateral':bilateral.tolist(),
                           'contact_forces':magnitudes.tolist(),'lift_m':lift.tolist()})
    rgb=capture('0000-start')
    if plan is not None:
        for i,item in enumerate(plan):
            action=np.asarray(item['action'],dtype=float)
            for _ in range(item.get('repeat',1)):
                execute(action)
            rgb=capture(f'{i+1:04d}-{item.get("label","probe")}')
            print(json.dumps({'probe':i,'steps':step,'image':str(out/'wrist.png')}),flush=True)
    else:
        for i in range(args.frames):
            if not app.is_running() or (out/'STOP').exists() or controller.done:break
            rgb=sensor.capture()
            try:action=controller(rgb)
            except (RuntimeError,ValueError) as error:
                controller.phase='failed_visual';controller.diagnostic['error']=str(error)
                trace.append({'step':step,'phase':controller.phase,'visual':controller.diagnostic})
                break
            # Negative control deliberately prevents physical closure; retain
            # the effective command in the trace, not the overridden request.
            if args.grasp_negative_open and controller.phase in ('close','lift','hold'):
                action=np.asarray(action,dtype=float).copy();action[-1]=1.
            trace.append({'step':step,'phase':controller.phase,'action':np.asarray(action).tolist(),
                          'visual':controller.diagnostic})
            try:execute(action)
            except RuntimeError as error:
                controller.phase='failed_actuator';controller.diagnostic['error']=str(error)
                trace.append({'step':step,'phase':controller.phase,'visual':controller.diagnostic})
                break
            if i%10==0:
                rgb=capture(f'frame-{i:05d}')
                write_state(out/'status.json',{'step':step,'phase':controller.phase,'visual':controller.diagnostic})
                write_state(out/'visual-servo.json',controller.history)
                print(json.dumps(trace[-1]),flush=True)
    capture('final')
    success=bool(np.any(longest>=100))
    report={'success':success,'criterion':'same part lifted >= 30 mm with bilateral physical finger contact continuously >= 2 s',
        'peak_lift_m':peaks.tolist(),'longest_bilateral_hold_seconds':(longest*.02).tolist(),
        'steps':step,'elapsed_seconds':time.monotonic()-started,'seed':args.seed,
        'policy_sha256':hashlib.sha256(policy_source).hexdigest(),
        'negative_open':bool(args.grasp_negative_open),
        'curriculum':'upright randomized XY/yaw' if args.grasp_flat else 'random dropped orientations',
        'control_inputs':['single wrist RGB','own command memory'],
        'scene_truth_to_controller':False,'encoder_feedback_to_controller':False,
        'attachments':False,'pose_writes_after_setup':0,'simulation_only':True,
        'controller_result':controller.phase if controller else 'commissioning_plan'}
    if controller and controller.diagnostic.get('error'):report['failure_reason']=controller.diagnostic['error']
    write_state(out/'result.json',report);write_state(out/'trace.json',trace)
    if controller:write_state(out/'visual-servo.json',controller.history)
    write_state(out/'evaluation-only.json',{'initial_positions':initial_positions.tolist(),'frames':evaluation})
    write_state(out/'status.json',{'step':step,'phase':report['controller_result'],'closed':True,'result':report})
    print(json.dumps(report),flush=True)
