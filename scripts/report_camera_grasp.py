"""Render physical grasp evidence; development and frozen evaluation stay separate."""
import argparse
import html
import json
import os
import shutil
from pathlib import Path


def load(path):return json.loads(path.read_text(encoding='utf-8'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--development',type=Path,required=True)
    parser.add_argument('--evaluation',type=Path,required=True)
    parser.add_argument('--negative',type=Path)
    parser.add_argument('--replay-control',type=Path)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
    batch=load(args.evaluation/'summary.json');dev=load(args.development/'result.json')
    experiment_root=Path(__file__).resolve().parents[1]/'outputs/camera_grasp'
    if args.evaluation.resolve().is_relative_to(experiment_root.resolve()):
        (args.out/'progress-source.json').write_text(json.dumps({
            'evaluation':args.evaluation.resolve().relative_to(experiment_root.resolve()).as_posix()}),encoding='utf-8')
    def link(path):
        # Publish only explicitly selected evidence, not the simulator's scene
        # inventory, raw evaluation poses, or arbitrary project files.
        target=args.out/'evidence'/path.parent.name/path.name
        target.parent.mkdir(parents=True,exist_ok=True)
        if path.is_file():shutil.copy2(path,target)
        return html.escape(Path(os.path.relpath(target,args.out)).as_posix(),quote=True)
    def video(run):
        target=run/'wrist-grasp.mp4'
        frames=sorted(run.glob('frame-*.png'))
        if not target.is_file() and frames:
            import imageio.v2 as imageio
            with imageio.get_writer(target,fps=5,codec='libx264',quality=7,macro_block_size=1) as writer:
                for frame in frames:writer.append_data(imageio.imread(frame))
        return target
    successes=sum(bool(r['success']) for r in batch['runs']);count=len(batch['runs'])
    rows=[]
    for r in batch['runs']:
        run=args.evaluation/r['directory']
        reason=r.get('failure_reason',r.get('controller_result',''))
        reason={'finished_unverified':'控制流程完成',
                'No isolated visible rectangular brick':'未检出可见的完整积木',
                'Visual target tracking lost; reacquisition requires a new attempt':'目标跟踪丢失，已停止',
                'Visual alignment did not converge; no blind close':'视觉对准未收敛，已停止'}.get(reason,reason)
        rows.append(f"<tr><td>{r['seed']}</td><td>{'成功' if r['success'] else '失败'}</td>"
                    f"<td>{1000*max(r.get('peak_lift_m',[0])):.1f} mm</td>"
                    f"<td>{max(r.get('longest_bilateral_hold_seconds',[0])):.2f} s</td>"
                    f"<td>{html.escape(reason)}</td>"
                    f'<td><a href="{link(run/"result.json")}">记录</a> · <a href="{link(run/"final.png")}">末帧</a></td></tr>')
    selected=next((args.evaluation/r['directory'] for r in batch['runs'] if r['success']),args.development)
    selected_label='独立测试成功回放' if selected!=args.development else '开发场景成功回放（不计入独立测试成功率）'
    movie=video(selected)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    evidence=load(selected/'evaluation-only.json')['frames']
    times=[f['step']*.02 for f in evidence]
    fig,ax=plt.subplots(2,1,figsize=(10,4.8),sharex=True,layout='constrained')
    for i in range(len(evidence[0]['lift_m'])):
        ax[0].plot(times,[1000*f['lift_m'][i] for f in evidence],label=f'Part {i+1}')
        ax[1].plot(times,[int(f['bilateral'][i]) for f in evidence],label=f'Part {i+1}')
    ax[0].axhline(30,color='gray',linestyle='--');ax[0].set_ylabel('Lift (mm)')
    ax[1].set_ylabel('Both fingers contact');ax[1].set_xlabel('Simulation time (s)')
    for axis in ax:axis.grid(alpha=.2)
    fig.savefig(args.out/'physical-evidence.png',dpi=150);plt.close(fig)
    negative='未提供负对照结果。'
    if args.negative:
        result=load(args.negative/'result.json')
        if not result.get('negative_open') or result.get('policy_sha256')!=batch['sources']['camera_grasp_policy.py']:
            raise ValueError('Negative control must use the same frozen policy with negative-open enabled')
        outcome='异常通过，需检查评价器' if result['success'] else (
            '未通过抓取验收（符合预期）' if result['controller_result']=='finished_unverified' else '流程未完成，不能证明夹爪负对照有效')
        negative=f"同一策略、场景 {result['seed']} 的持续张爪负对照：{outcome}；最大抬升 {1000*max(result['peak_lift_m']):.1f} mm，连续双指接触 {max(result['longest_bilateral_hold_seconds']):.2f} s。"
    replay=''
    if args.replay_control:
        comparison=load(args.replay_control/'comparison.json')
        if comparison.get('kind')!='paired_mechanical_replay_not_online_evaluation' or not comparison.get('complete'):
            raise ValueError('Expected completed paired mechanical control')
        if comparison['source_policy_sha256']!=batch['sources']['camera_grasp_policy.py']:
            raise ValueError('Replay control source differs from the online evaluation policy')
        normal=comparison['runs']['original'];opened=comparison['runs']['open']
        conclusion='支持闭爪动作产生真实物理夹持' if comparison.get('supports_physical_closure') else '未形成有效机械对照'
        replay=f'''<p>补充机械对照：回放成功场景 {comparison['source_seed']} 的相同关节指令，只改变夹爪开合。此回放不是在线视觉策略，不计入上方成功率。</p>
<table><tr><th>回放条件</th><th>抓取验收</th><th>最大抬升</th><th>连续双指接触</th></tr>
<tr><td>原始指令</td><td>{'通过' if normal['success'] else '失败'}</td><td>{1000*max(normal['peak_lift_m']):.1f} mm</td><td>{max(normal['longest_bilateral_hold_seconds']):.2f} s</td></tr>
<tr><td>夹取后持续张爪</td><td>{'通过' if opened['success'] else '失败'}</td><td>{1000*max(opened['peak_lift_m']):.1f} mm</td><td>{max(opened['longest_bilateral_hold_seconds']):.2f} s</td></tr></table><p>{conclusion}。</p>'''
    rate=f'{successes/count:.0%}' if count else '—'
    document=f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>单相机基础抓取 · 实验报告</title><style>
body{{font:16px/1.7 system-ui,sans-serif;margin:0;background:#edf2f5;color:#192c3c}}main{{max-width:1150px;margin:auto;padding:36px 24px}}
h1{{font-size:32px}}h2{{font-size:21px}}section,.cards>div{{background:white;border:1px solid #d9e3e9;border-radius:12px;padding:22px;margin:18px 0}}
.cards{{display:flex;gap:18px}}.cards>div{{flex:1}}strong.metric{{display:block;font-size:36px;color:#086f72}}p{{max-width:950px}}
video{{width:100%;max-width:800px;background:#101b25}}img{{max-width:100%}}table{{width:100%;border-collapse:collapse;font-size:14px}}td,th{{text-align:left;padding:10px;border-bottom:1px solid #d9e3e9}}a{{color:#086f72}}code{{overflow-wrap:anywhere}}.scroll{{overflow:auto}}
</style><main><h1>单相机基础抓取</h1><p>目标：观察 → 对准 → 接近 → 夹取 → 抬升 → 保持。单腕部 RGB 与自身指令历史驱动；这是物理仿真基线，不是实机或完整积木搭建验收。</p>
<section><h2>当前批次监控</h2><p id="live-status">通过平台打开此报告可查看实时进度。下方完整结果截至本报告生成时。</p><img id="live-frame" alt="当前测试的实际腕部相机" style="display:none;max-width:640px"></section>
<div class="cards"><div>已完成独立测试中的成功数<strong class="metric" id="eval-count">{successes} / {count}</strong><span id="eval-rate">{'成功率 '+rate if batch['complete'] else '批次尚未完成'}；计划 {len(batch['planned_seeds'])} 个场景</span></div>
<div>历史开发成功<strong class="metric">{1000*max(dev['peak_lift_m']):.1f} mm</strong>抬升；连续双指接触 {max(dev['longest_bilateral_hold_seconds']):.2f} s</div></div>
<section><h2>{selected_label}</h2><video controls preload="metadata" poster="{link(selected/'final.png')}" src="{link(movie)}"></video><p>视频按仿真时间播放；每 10 个控制步保存一帧。下图来自独立评价器，数据没有反馈给控制器。</p><img src="physical-evidence.png" alt="物理抬升和双指接触曲线"></section>
<section><h2>逐场景结果快照</h2><p>固定策略版本，随机位置、偏航与灰度材质，单块直立 2×4 积木。成功需同一积木抬升至少 30 mm，并连续保持双指接触至少 2 秒。没有焊接、吸附或运行中修改物体位姿。</p>
<div class="scroll"><table><thead><tr><th>种子</th><th>结果</th><th>最大抬升</th><th>连续保持</th><th>终止原因</th><th>证据</th></tr></thead><tbody>{''.join(rows)}</tbody></table></div>
<p>批次{'已完成' if batch['complete'] else '未完成'}；开发调参种子不计入上述成功率。样本较少，结果不能外推为任意摆放、遮挡、堆叠或实机成功率。</p><p>策略 SHA-256：<code>{batch['sources']['camera_grasp_policy.py']}</code></p><a href="{link(args.evaluation/'summary.json')}">批次原始记录</a></section>
<section><h2>负对照与能力边界</h2><p>{negative}</p>{replay}<p>当前使用图像轮廓、光流和主动试探估计图像雅可比，含固定夹爪外观与矩形积木假设。未证明任意物体抓取、自动放置、LEGO 插接或完整说明书搭建；预训练预测误差不作为物理成功率。</p></section>
<section><h2>参考方法</h2><p><a href="https://ieeexplore.ieee.org/abstract/document/4015997">Chaumette &amp; Hutchinson (2006), Visual Servo Control</a> · <a href="https://www.cs.columbia.edu/robotics/projects/visual_control/bill-peginhole.html">Yoshimi &amp; Allen (1994), Active Uncalibrated Visual Servoing</a> · <a href="https://github.com/lagadic/visp">ViSP</a>。本项目自行实现 OpenCV/NumPy 版本，未声称复现论文全部实验。GG-CNN 标准输入为深度图，因此未直接用于本 RGB-only 基线。</p></section></main>
<script>
const phases={{starting:'启动中',calibrate_tool:'识别夹爪',align_angle:'对准方向',visual_servo:'视觉对准',close:'夹取',lift:'抬升',hold:'保持',finished_unverified:'流程结束，结果由独立评价器判定',failed_visual:'视觉失败',failed_actuator:'动作达到限位'}};
let polling=false;
async function poll(){{if(location.protocol==='file:'||polling)return;polling=true;try{{
 const response=await fetch('/grasp-report/progress',{{cache:'no-store'}});if(!response.ok)throw Error('连接不可用');const s=await response.json();
 document.getElementById('live-status').textContent=`${{s.complete?'批次已结束':'测试中'}} · 已完成 ${{s.completed}}/${{s.planned}} · 成功 ${{s.successes}} · 场景 ${{s.seed}} · ${{phases[s.phase]||s.phase}} · ${{s.step}} 步`;
 document.getElementById('eval-count').textContent=`${{s.successes}} / ${{s.completed}}`;
 document.getElementById('eval-rate').textContent=(s.complete?'成功率 '+Math.round(100*s.successes/Math.max(1,s.completed))+'%':'批次尚未完成')+`；计划 ${{s.planned}} 个场景`;
 const im=document.getElementById('live-frame');if(s.step){{im.src=`/grasp-report/wrist.png?seed=${{s.seed}}&step=${{s.step}}`;im.style.display='block';}}else{{im.style.display='none';}}
 }}catch(e){{document.getElementById('live-status').textContent='实时连接暂不可用；下方仍可查看已生成的实验报告。';}}finally{{polling=false;}}}}
poll();setInterval(poll,2000);
</script></html>'''
    (args.out/'index.html').write_text(document,encoding='utf-8')
    print(args.out/'index.html')


if __name__=='__main__':main()
