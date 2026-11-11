"""Isolated camera/action loop. Simulator access stays outside the policy.

Scene writes occur ONLY before the first observation. The actuator integrates
commands, never measured joints. No contact, object pose or success signal is
returned to the agent. This is a simulation entry point, not hardware control.
"""
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image
from camera_policy import CONTRACT, MANUAL_CONTRACT, CameraPolicy, SIZE

ROOT = Path(__file__).resolve().parents[1]


class CommandIntegrator:
    def __init__(self, initial, limits):
        self.target = np.asarray(initial, dtype=np.float64).copy()
        self.limits = np.asarray(limits, dtype=np.float64)
        if self.target.shape != (7,) or self.limits.shape != (7, 2):
            raise ValueError('Expected six arm joints and one gripper opening')

    def step(self, action):
        action = np.asarray(action)
        if action.shape != (7,) or not np.isfinite(action).all() or np.abs(action).max() > 1:
            raise ValueError('Invalid command; actuator target unchanged')
        self.target = np.clip(self.target + action*np.array([.01]*6+[.001]),
                              self.limits[:, 0], self.limits[:, 1])
        return self.target.copy()


def save_episode(path, frames, goal, actions, group, *, manual=False):
    if not frames or not group:
        raise ValueError('Empty episode or missing layout/task group')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation preserves previous demonstrations.
    with path.open('xb') as handle:
        np.savez_compressed(handle, contract=np.array(MANUAL_CONTRACT if manual else CONTRACT), rgb=np.stack(frames),
                            goal_rgb=goal, actions=np.asarray(actions, dtype=np.float32),
                            split_group=np.array(group))


def run(app, world, robot, parts, stage, args, initial):
    from pxr import UsdGeom, Gf, PhysxSchema
    from scipy.spatial.transform import Rotation
    from isaacsim.core.utils.types import ArticulationAction
    from wrist_vision import WristRGB
    out=Path(args.camera_output).resolve() if getattr(args,'camera_output',None) else ROOT/'outputs/camera_only'
    out.mkdir(parents=True,exist_ok=True)
    # Setup is independent of policy/checkpoint and cannot be accessed by it.
    rng = np.random.default_rng(args.seed)
    for part in parts.values():
        part.set_world_pose(position=np.array([rng.uniform(.23, .36), rng.uniform(-.18, -.04), rng.uniform(.05, .13)]),
                            orientation=Rotation.random(random_state=rng).as_quat()[[3, 0, 1, 2]])
        part.set_linear_velocity(np.zeros(3))
        part.set_angular_velocity(np.zeros(3))
    if args.camera_mode=='grasp' and args.grasp_flat:
        # Explicit basic-grasp curriculum, not a runtime correction or oracle.
        for part in parts.values():
            yaw=rng.uniform(-np.pi,np.pi)
            part.set_world_pose(position=np.array([rng.uniform(.27,.34),rng.uniform(-.14,-.06),.018]),
                                orientation=np.array([np.cos(yaw/2),0,0,np.sin(yaw/2)]))
    # Identical material across all parts removes identity-by-colour, including
    # brightness labels. Geometry and occlusion are the available visual cues.
    shade = float(rng.uniform(.35, .8))
    for prim in stage.Traverse():
        path = str(prim.GetPath())
        if path.startswith('/World/Brick/') or path.startswith('/World/AssemblyParts/') or path.startswith('/World/TrainingParts/'):
            if prim.IsA(UsdGeom.Gprim):
                UsdGeom.Gprim(prim).CreateDisplayColorAttr([Gf.Vec3f(shade, shade, shade)])
    # Enable robot self collision for this path, including previously cached USD.
    root = stage.GetPrimAtPath(robot.prim_path)
    PhysxSchema.PhysxArticulationAPI.Apply(root).CreateEnabledSelfCollisionsAttr(True)
    robot.get_articulation_controller().apply_action(ArticulationAction(joint_positions=initial.copy()))
    for _ in range(500):
        world.step(render=False)
    world.render()
    manual=bool(getattr(args,'camera_task',None))
    if manual:
        from bricklab_task import load_manual
        goal=load_manual(args.camera_task)
    else:
        goal = np.asarray(Image.open(args.camera_goal).convert('RGB')) if args.camera_mode!='inspect' else None
    policy = CameraPolicy(args.policy, goal,manual=manual) if args.camera_mode == 'evaluate' else None
    sensor = WristRGB(world)
    names = list(robot.dof_names)
    arm = [names.index(f'joint{i}') for i in range(1, 7)]
    fingers = [names.index('joint7'), names.index('joint8')]
    urdf = ET.parse(ROOT/'generated/piper_basic.urdf').getroot()
    limits = []
    for i in range(1, 8):
        limit = urdf.find(f'joint[@name="joint{i}"]/limit')
        limits.append([float(limit.get('lower')), float(limit.get('upper'))])
    limits[-1] = [max(0., limits[-1][0]), min(.025, limits[-1][1])]
    actuator = CommandIntegrator(np.r_[initial[arm], initial[fingers[0]]], limits)
    control = robot.get_articulation_controller()
    if args.camera_mode=='grasp':
        from camera_grasp_runtime import run as run_grasp
        def apply_grasp(command):
            full=np.zeros(8,dtype=np.float32)
            full[arm]=command[:6];full[fingers]=[command[6],-command[6]]
            control.apply_action(ArticulationAction(joint_positions=full))
        return run_grasp(app,world,stage,parts,sensor,actuator,apply_grasp,out,args)
    if args.camera_mode=='explore':
        from camera_explore import run as run_explore
        def apply_exploration(command):
            full=np.zeros(8,dtype=np.float32)
            full[arm]=command[:6];full[fingers]=[command[6],-command[6]]
            control.apply_action(ArticulationAction(joint_positions=full))
        return run_explore(app,world,sensor,actuator,apply_exploration,out,args)
    if args.camera_mode=='live':
        from camera_live import run as run_live
        def apply_live(command):
            full=np.zeros(8,dtype=np.float32)
            full[arm]=command[:6];full[fingers]=[command[6],-command[6]]
            control.apply_action(ArticulationAction(joint_positions=full))
        return run_live(app,world,stage,sensor,goal,actuator,apply_live,out,args,len(parts))
    frames, actions = [], []
    if args.camera_mode=='collect':
        import msvcrt
        print('Focus this terminal. Joint +/-: q/a w/s e/d r/f t/g y/h; gripper: u/j. Space: hold; Esc: save and exit.', flush=True)
        keys = {key: (i, sign) for i, pair in enumerate(['qa', 'ws', 'ed', 'rf', 'tg', 'yh', 'uj'])
                for key, sign in zip(pair, [1., -1.])}
    try:
        for _ in range(args.frames):
            if not app.is_running():
                break
            rgb = sensor.capture()
            if args.camera_mode=='inspect':
                Image.fromarray(rgb).save(out/f'inspect_{args.seed}.png')
                frames.append(rgb.copy())
                world.step(render=True)
                continue
            elif policy is not None:
                action = policy(rgb)
            else:
                action = np.zeros(7, dtype=np.float32)
                key = msvcrt.getwch().lower()  # One operator decision per camera observation.
                if key == '\x1b':
                    break
                if key in keys:
                    axis, sign = keys[key]
                    action[axis] = sign
            command = actuator.step(action)
            full = np.zeros(8, dtype=np.float32)
            full[arm] = command[:6]
            full[fingers] = [command[6], -command[6]]
            control.apply_action(ArticulationAction(joint_positions=full))
            frames.append(rgb.copy())
            actions.append(action.copy())
            for _ in range(20):
                world.step(render=False)
            world.render()
    finally:
        if args.camera_mode=='collect' and frames:
            # Store every page at a common size; no source IDs, page map or
            # externally selected current step enter the demonstration.
            saved_goal=np.stack([np.asarray(Image.fromarray(page).resize((512,512))) for page in goal]) if manual else goal
            save_episode(args.camera_episode, frames, saved_goal, actions, args.camera_group,manual=manual)
    report = {'contract': MANUAL_CONTRACT if manual else CONTRACT, 'mode': args.camera_mode, 'steps': len(actions), 'captured_frames':len(frames),
              'environment_part_count':len(parts),'manual_page_count':len(goal) if manual else 0,
              'observations': ['single_wrist_RGB_history', 'manual_page_images' if manual else 'operator_goal_image'],
              'encoder_feedback_to_policy': False, 'camera_pose_to_policy': False,
              'scene_state_to_policy': False, 'scene_writes_after_setup': 0,
              'human_pose_assistance': False, 'physical_success_evaluated': False,
              'limits': ['rigid LEGO approximation; no verified snap-fit',
                         'joint limits do not establish collision-free or real-hardware safety',
                         'image-conditioned imitation requires new demonstrations and closed-loop validation']}
    (out/f'run_{args.seed}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)
