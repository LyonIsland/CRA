"""Actual Isaac RGB scan of scattered pieces. Assembly execution is gated."""
import json
from pathlib import Path
import numpy as np
from assembly_agent import InstructionAgent,ROOT
from assembly_perception import Inventory,detect,COLORS
from wrist_vision import WristRGB,camera_pose
from tabletop import workspace_points,solve_checked,SETTINGS
from tabletop import TabletopController

OUT=ROOT/'outputs/assembly'
CAPABILITIES={'visual_pick':False,'oriented_transport':False,'force_limited_insertion':False,
              'connection_verification':False,'fixture_registration':False}

class InstructionPickPrefix(TabletopController):
    """Reuse grasp feedback, select the manual's part using multi-color RGB."""
    def __init__(self,task,sensor,part):
        self.required_part=part
        super().__init__(task,sensor,SETTINGS['default_goal'])
    def detect(self,held=False):
        if held:raise RuntimeError('Prefix preview stops after lift')
        rgb=self.sensor.capture();self.last_rgb=rgb
        candidates=[p for p in detect(rgb,camera_pose(self.task.kin,self.task.q))
            if p['color']==self.required_part['color'] and p['catalog_id']==self.required_part['catalog_id'] and p['confidence']>=.85]
        if not candidates:return None
        piece=max(candidates,key=lambda p:p['confidence']);self.confidence=piece['confidence']
        self.last_uv=np.array(piece['pixel_center'])
        return np.array(piece['pose']['position_m'])

def test_pick_prefix(task,sensor,agent,seed):
    from PIL import Image
    # Only S1/red is physically verified here. No source pose is copied from the
    # scene or from the old snapshot; the controller reacquires current RGB.
    part=agent.recipe['steps'][0]['part']
    if part['color']!='red':raise RuntimeError('This first skill adapter verifies the red S1 prefix only')
    task.contacts.initialize(task.world.physics_sim_view)
    controller=InstructionPickPrefix(task,sensor,part)
    peak=.0048;bilateral=0
    for _ in range(3000):
        controller.step()
        z=float(task.object[2]);peak=max(peak,z)  # evaluator only
        if z>.04 and controller.contacts():bilateral+=1
        if controller.phase=='via_source' or controller.done:break
    success=not controller.failed and controller.phase=='via_source' and peak>.055 and bilateral>=5
    rgb=sensor.capture();Image.fromarray(rgb).save(OUT/f'prefix_pick_{seed}.png')
    report={'seed':seed,'step_id':'S1','requested_part_from_instruction':part,
        'skill_prefix':'RGB select, grasp and lift only','success':bool(success),'peak_height_m':peak,
        'bilateral_lift_steps':bilateral,'grasp_retries':controller.retries,'message':controller.message,
        'instruction_step_completed':False,'physical_connection_attempted':False,
        'source_pose_from_current_RGB':True}
    (OUT/f'prefix_pick_{seed}.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
    return report

def add_parts(world,stage,cube,red):
    from pxr import UsdGeom,UsdPhysics,Gf
    from isaacsim.core.prims import SingleRigidPrim
    parts={'red':red}
    specs={color:(rgb,[4,2],.0023) for color,rgb in COLORS.items()}
    specs.update({'cyan_distractor':([.02,.75,.8],[2,2],.0013),'black_distractor':([.025,.025,.025],[4,2],.0023)})
    for color,(rgb,studs,mass) in specs.items():
        if color=='red':continue
        path=f'/World/AssemblyParts/{color}'
        prim=UsdGeom.Xform.Define(stage,path);prim.AddTranslateOp().Set(Gf.Vec3d(.25,0,.04))
        UsdPhysics.RigidBodyAPI.Apply(prim.GetPrim())
        UsdPhysics.MassAPI.Apply(prim.GetPrim()).CreateMassAttr(mass)
        cube(path+'/Body',[0,0,0],[studs[0]*.008-.0002,studs[1]*.008-.0002,.0096],rgb)
        for i in range(studs[0]):
            for j in range(studs[1]):
                x=(i-(studs[0]-1)/2)*.008;y=(j-(studs[1]-1)/2)*.008
                stud=UsdGeom.Cylinder.Define(stage,f'{path}/Stud_{i}_{j}')
                stud.CreateRadiusAttr(.0024);stud.CreateHeightAttr(.0018);stud.CreateAxisAttr('Z')
                stud.AddTranslateOp().Set(Gf.Vec3d(x,y,.0057));stud.CreateDisplayColorAttr([Gf.Vec3f(*rgb)])
                UsdPhysics.CollisionAPI.Apply(stud.GetPrim())
        parts[color]=world.scene.add(SingleRigidPrim(prim_path=path,name=f'assembly_{color}'))
    UsdGeom.Imageable(stage.GetPrimAtPath('/World/Goal')).MakeInvisible()
    return parts

def run(app,world,robot,brick,stage,args,parts):
    from pick_place import Task
    from PIL import Image,ImageDraw
    OUT.mkdir(exist_ok=True)
    task=Task(app,world,robot,brick,stage);task.reset(0)
    sensor=WristRGB(world);points=np.array(workspace_points(task.kin))
    home=solve_checked(task.kin,SETTINGS['home'])
    trials=[]
    for trial in range(args.episodes):
        seed=args.seed+trial;rng=np.random.default_rng(seed);world.reset();inventory=Inventory()
        selected=[]
        for color,part in parts.items():
            for _ in range(2000):
                xy=points[rng.integers(len(points))]+rng.uniform(-.002,.002,2)
                if .21<xy[0]<.34 and .035<xy[1]<.125:continue
                if all(np.linalg.norm(xy-p)>.055 for p in selected):break
            else:raise RuntimeError('Could not generate separated inventory')
            selected.append(xy);part.set_world_pose(position=np.r_[xy,.007],orientation=np.array([1.,0,0,0]))
            part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
        full=robot.get_joint_positions();full[task.arm]=home;full[task.fingers]=[.025,-.025]
        robot.set_joint_positions(full);robot.set_joint_velocities(np.zeros(8))
        for _ in range(15):task.advance(home,.025)
        errors=[];frames=[]
        for view,point in enumerate(SETTINGS['scan_poses']):
            # Scan waypoints are independent of scattered source locations.
            command=task.tcp.copy()
            for _ in range(350):
                delta=np.array(point)-command
                command+=delta*min(1.,.003/(np.linalg.norm(delta)+1e-9))
                q,error=task.kin.solve(command,task.q)
                if error>.002:break
                task.advance(q,.025)
                if np.linalg.norm(task.tcp-point)<.0015:break
            rgb=sensor.capture();detections=detect(rgb,camera_pose(task.kin,task.q));inventory.update(detections)
            for d in detections:
                truth=parts[d['color']].get_world_pose()[0]  # evaluation only
                errors.append(float(np.linalg.norm(np.array(d['pose']['position_m'])[:2]-truth[:2])))
            image=Image.fromarray(rgb);draw=ImageDraw.Draw(image)
            for d in detections:
                draw.rectangle(d['pixel_bbox'],outline='cyan',width=1);draw.text(d['pixel_bbox'][:2],d['color'],fill='white')
            image.save(OUT/f'seed_{seed}_view_{view}.png')
            frames.append({'view':view,'detections':len(detections)})
            print(json.dumps({'seed':seed,'view':view,'colors':sorted({p['color'] for p in inventory.tracks.values()})}),flush=True)
        observation=inventory.observation();agent=InstructionAgent();agent.observe(observation)
        plan=agent.next_plan(CAPABILITIES)
        (OUT/f'observation_{seed}.json').write_text(json.dumps(observation,indent=2))
        (OUT/f'plan_{seed}.json').write_text(json.dumps(plan,indent=2))
        item={'seed':seed,'observed_colors':sorted({p['color'] for p in observation['pieces']}),
            'scene_piece_count':len(parts),'recipe_piece_count':6,'distractor_count':len(parts)-6,
            'visual_tracks':len(observation['pieces']),'mean_detection_error_m':float(np.mean(errors)) if errors else None,
            'next_step':plan,'views':frames,'physical_assembly_completed':False}
        trials.append(item)
        if args.assembly_pick_prefix:item['pick_prefix_test']=test_pick_prefix(task,sensor,agent,seed)
        (OUT/'live-observation.json').write_text(json.dumps(observation,indent=2))
        (OUT/'live-status.json').write_text(json.dumps({'agent':agent.snapshot(),'capabilities':CAPABILITIES,
            'stage':'RGB inventory and instruction planning; physical assembly blocked',
            'physical_assembly_completed':False,'last_seed':seed},indent=2))
        (OUT/'rgb-scan-check.json').write_text(json.dumps({'trials':trials,'source':'actual Isaac wrist RGB',
            'source_poses_read_by_detector_or_agent':False,'physical_assembly_tested':False},indent=2))
