"""Isolated real-contact gripper commissioning, not a heap assembly result."""
import json
import numpy as np
from scipy.spatial.transform import Rotation
from live_assembly import LiveAssemblySession
from clutter_extract import HeapExtraction
from clutter_perception import released_table_piece
from wrist_vision import camera_pose
from tabletop import solve_checked
from assembly_agent import ROOT

def commission(app,world,robot,brick,stage,args):
    session=LiveAssemblySession(app,world,robot,brick,stage,args)
    session.heap_estimates=[];session.heap_views=[]
    setup_xy=np.array([.28,-.12]);goal=np.array([.19,-.25,.0048])
    placeholder={'color':'red','position_m':np.r_[setup_xy,.0048].tolist(),'yaw_deg':0.,'face_hypothesis':'up'}
    control=HeapExtraction(session,placeholder,goal)
    world.step(render=True)  # flush newly enabled contact-report schemas before loading
    # Setup only: initialize contact views before loading the isolated specimen.
    for i,part in enumerate(session.parts.values()):
        part.set_world_pose(position=np.array([.55,.30,.03+i*.025]),orientation=np.array([1.,0,0,0]))
        part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
    target=session.parts['red']
    target.set_world_pose(position=np.r_[setup_xy,.006],orientation=np.array([1.,0,0,0]))
    world.render()
    q=solve_checked(session.task.kin,np.r_[setup_xy,.08],session.task.q)
    if q is None:raise RuntimeError('Commissioning view unreachable')
    for _ in range(120):session.task.advance(q,.025)
    world.render();rgb=session.sensor.capture()
    from PIL import Image
    Image.fromarray(rgb).save(ROOT/'outputs/clutter/gripper-commission-source.png')
    observed=released_table_piece(rgb,camera_pose(session.task.kin,session.task.q),'red',setup_xy)
    if observed is None:
        print(json.dumps({'commission_RGB_missing':True,'rgb_shape':rgb.shape,'tcp':session.task.tcp.tolist(),
            'evaluation_only_part_pose':target.get_world_pose()[0].tolist()}),flush=True)
        raise RuntimeError('Isolated RGB specimen not found')
    control.piece=observed;control.source=np.array(observed['position_m']);control.reference_source=control.source.copy()
    control.hold_yaw=observed['yaw_deg'];control.command=session.task.tcp.copy()
    peak=0.;bilateral=0;max_error=0.
    while not control.done and control.steps<5000:
        control.step()
        if control.steps%5==0:world.render()
        fingers=robot.get_joint_positions()[session.task.fingers]
        max_error=max(max_error,abs(float(fingers.sum())))
        p,_=target.get_world_pose();peak=max(peak,float(p[2]))
        if p[2]>.055 and control.contacts():bilateral+=1
    position,quat=target.get_world_pose();up=float(Rotation.from_quat(np.r_[quat[1:],quat[0]]).as_matrix()[2,2])
    error=float(np.linalg.norm(position[:2]-goal[:2]));passed=not control.failed and control.done and error<.004 and up>.98 and max_error<.0005 and bilateral>=5
    report={'scope':'one isolated RGB tabletop grasp, transfer and release; not heap assembly',
        'passed':passed,'phase':control.phase,'message':control.message,'max_jaw_mimic_error_m':max_error,
        'peak_height_m':peak,'bilateral_lift_ticks':bilateral,'placement_error_xy_m':error,
        'final_up_z':up,'grasp_attachments':False,'pose_writes_after_setup':0,
        'source_RGB':observed,'control_steps':control.steps}
    (ROOT/'outputs/clutter/gripper-commission.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
    if not passed:raise RuntimeError('Coupled Piper gripper commissioning failed')
