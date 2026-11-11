"""Simulation motor babbling, NOT successful assembly demonstrations.

Only executed commands and consecutive single-camera RGB enter the dataset.
No state teacher, FK/IK, object labels, success rewards or encoder readings.
"""
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image

EXPLORATION_CONTRACT = 'camera_only_exploration_v1'


class Explorer:
    """Bounded command-history random walk independent of scene/layout seed.

The displacement bound is relative to issued initial commands, not measured
positions. It is a simulation collection limit, NOT a hardware safety proof.
"""
    def __init__(self, seed):
        self.rng = np.random.default_rng(seed)
        self.offset = np.zeros(7)
        self.direction = np.zeros(7)
        self.remaining = 0

    def action(self):
        if not self.remaining:
            self.direction = self.rng.uniform(-1., 1., 7)
            self.direction *= self.rng.random(7) < .5
            self.remaining = int(self.rng.integers(3, 13))
        self.remaining -= 1
        # .18 rad arm displacement and full 25 mm gripper travel; no state read.
        low = np.array([-18.]*6+[-25.])
        high = np.array([18.]*6+[0.])
        action = np.clip(self.direction, low-self.offset, high-self.offset)
        self.offset += action
        return action.astype(np.float32)


def run(app, world, sensor, actuator, apply_action, out, args):
    import secrets
    from bricklab_task import task_document
    _, task = task_document(args.camera_task)
    target = out/'transitions.npz'
    if target.exists():raise ValueError('Refusing to replace exploration data')
    # Independent action RNG prevents layout seed from encoding action labels.
    action_seed = secrets.randbits(32)
    explorer = Explorer(action_seed)
    frames = [sensor.capture()]
    actions = []
    started = time.monotonic()
    for step in range(args.frames):
        if not app.is_running() or (out/'STOP').exists():break
        action = explorer.action()
        # Store the actual clipped command increment, never requested motion
        # that was discarded by actuator saturation. Only command history read.
        before = actuator.target.copy()
        command = actuator.step(action)
        executed = (command-before)/np.array([.01]*6+[.001])
        apply_action(command)
        for _ in range(20):world.step(render=False)
        world.render()
        frames.append(sensor.capture())
        actions.append(executed.astype(np.float32))
        if step % 32 == 0:
            Image.fromarray(frames[-1]).save(out/'latest.png')
            print(json.dumps({'event':'exploration','steps':len(actions),
                              'elapsed_seconds':time.monotonic()-started}),flush=True)
    if not actions:raise RuntimeError('No exploration transitions collected')
    with target.open('xb') as handle:
        np.savez_compressed(handle,contract=np.array(EXPLORATION_CONTRACT),
            rgb=np.stack(frames),actions=np.asarray(actions,dtype=np.float32),
            split_group=np.array(task['source_sha256']+':'+str(args.seed)))
    delta = np.diff(np.asarray(frames,dtype=np.float32),axis=0)
    report = {'contract':EXPLORATION_CONTRACT,'transitions':len(actions),
        'action_seed':action_seed,'layout_seed':args.seed,'source_sha256':task['source_sha256'],
        'mean_pixel_change':float(np.abs(delta).mean()),
        'elapsed_seconds':time.monotonic()-started,'scene_state_to_model':False,
        'demonstration':False,'physical_success_evaluated':False,
        'purpose':'self-supervised visual/motor pretraining only'}
    (out/'collection.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report),flush=True)
