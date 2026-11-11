"""Persistent camera-only robot session, with a separate human viewer channel.

Only RGB/manual arrays reach CameraPolicy. Scene meshes/transforms below are
viewer outputs and are never passed back into inference or demonstrations.
"""
import io
import json
from pathlib import Path
import time
import numpy as np
from PIL import Image
from camera_policy import CameraPolicy, MANUAL_CONTRACT
from camera_commands import validate_command


def atomic_bytes(path, data):
    path=Path(path)
    temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_bytes(data)
    for attempt in range(5):
        try:temporary.replace(path);break
        except PermissionError:
            if attempt==4:raise
            time.sleep(.01)


def write_state(path, value):
    atomic_bytes(path,json.dumps(value,ensure_ascii=False,allow_nan=False).encode('utf-8'))


def run(app,world,stage,sensor,goal,actuator,apply_action,out,args,part_count):
    from xr_bridge import export_geometry,C4
    from pxr import UsdGeom
    from camera_runtime import save_episode
    from bricklab_task import task_document
    root,task=task_document(args.camera_task)
    model,prims=export_geometry(stage)
    write_state(out/'model.json',model)
    commands=out/'commands'
    commands.mkdir(exist_ok=True)
    policy=None
    recording=False
    frames,actions=[],[]
    mode='ready'
    message='场景已就绪，可以通过腕部相机逐步操作机械臂。'
    last_command=0;sequence=0;steps=0
    last_publish=0.;last_policy=0.;saved=[];error=None
    latest_rgb=None

    def save():
        nonlocal frames,actions,recording
        if not frames:raise ValueError('尚无动作示范，请先开始记录并操作机械臂。')
        # No poses, page map, stage number or viewer transforms are saved.
        # Keep unreviewed live demonstrations with this run; do not silently
        # mix experiments or failed manipulations into the training dataset.
        path=out/'demonstrations'/f'episode-{len(saved)+1:03d}.npz'
        pages=np.stack([np.asarray(Image.fromarray(page).resize((512,512))) for page in goal])
        save_episode(path,frames,pages,actions,task['source_sha256']+':'+str(args.seed),manual=True)
        saved.append(str(path));frames=[];actions=[];recording=False
        return '示范已保存；这不代表已自动确认搭建成功。'

    def step(action):
        nonlocal latest_rgb,steps
        latest_rgb=sensor.capture()
        command=actuator.step(action)
        if recording:
            frames.append(latest_rgb.copy());actions.append(np.asarray(action,dtype=np.float32).copy())
        apply_action(command)
        for _ in range(20):world.step(render=False)
        world.render();steps+=1

    def publish(closed=False):
        nonlocal sequence,latest_rgb
        if latest_rgb is None or not closed:latest_rgb=sensor.capture()
        buffer=io.BytesIO();Image.fromarray(latest_rgb).save(buffer,format='JPEG',quality=85)
        atomic_bytes(out/'wrist.jpg',buffer.getvalue())
        cache=UsdGeom.XformCache()
        matrices=[(C4@np.asarray(cache.GetLocalToWorldTransform(prim)).T@C4.T).T.ravel().tolist() for prim in prims]
        sequence+=1
        write_state(out/'live.json',{'sequence':sequence,'updated_at':time.time(),'closed':closed,
            'mode':mode,'message':message,'error':error,'last_command':last_command,
            'recording':recording,'recorded_steps':len(actions),'executed_steps':steps,
            'saved_demonstrations':saved,'part_count':part_count,'manual_page_count':len(goal),
            'source_sha256':task['source_sha256'],'matrices':matrices,
            'policy_available':bool(args.policy and Path(args.policy).is_file()),
            'policy_inputs':['manual_page_images','single_wrist_RGB_history'],
            'physical_assembly_completed':False,'scene_state_to_policy':False,'scene_writes_after_setup':0})

    publish()
    shutdown=False
    try:
        while app.is_running() and not shutdown:
            for path in sorted(commands.glob('*.json')):
                number=int(path.stem)
                if number<=last_command:continue
                last_command=number
                try:
                    command=validate_command(json.loads(path.read_text(encoding='utf-8')))
                    op=command['op'];error=None
                    if op=='shutdown':
                        if recording and frames:message=save()
                        shutdown=True;mode='closed';break
                    elif op=='pause':mode='paused';message='机械臂已暂停。'
                    elif op=='step':
                        if mode=='policy':raise ValueError('先暂停自动策略，再手动操作。')
                        step(command['action']);mode='manual';message='已执行一次腕部相机反馈下的关节增量。'
                    elif op=='record':
                        if mode=='policy':raise ValueError('先暂停自动策略，再采集人工示范。')
                        recording=True;message='正在记录纯视觉示范；操作时只显示腕部相机与说明书。'
                    elif op=='save':message=save()
                    elif op=='start_policy':
                        if recording:raise ValueError('先保存人工示范，再启动策略。')
                        if not args.policy or not Path(args.policy).is_file():
                            raise ValueError('尚无经过训练的说明书策略，请先采集示范并训练。')
                        policy=CameraPolicy(args.policy,goal,manual=True)
                        mode='policy';message='纯视觉策略正在根据说明书和腕部图像执行；装配结果尚未验收。'
                except (ValueError,RuntimeError,OSError) as exception:
                    mode='paused';error=str(exception);message=error
            now=time.monotonic()
            if mode=='policy' and now-last_policy>=.1:
                try:step(policy(sensor.capture()));last_policy=now
                except Exception as exception:mode='paused';error=str(exception);message='策略已停止：'+error
            if now-last_publish>=.25 or shutdown:
                publish(shutdown);last_publish=now
            time.sleep(.02)
    finally:
        if recording and frames:
            try:message=save()
            except Exception as exception:error=str(exception)
        mode='closed';message='本作品的机械臂场景已关闭。'+('示范已保存在本次运行中。' if saved else '')
        publish(True)
