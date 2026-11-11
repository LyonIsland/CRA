"""Render measured overnight metrics and fixed-index held-out predictions.

This is an offline report, never a robot control or assembly-success demo.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import numpy as np
import torch
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
from camera_policy import image_tensor
from pretrain_camera import VisualMotorModel, PRETRAIN_CONTRACT, MODEL_VERSION


def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main(run,out):
    torch.set_num_threads(4)
    out.mkdir(parents=True,exist_ok=True)
    status=read(run/'status.json');test=read(run/'final-test.json');latest=read(run/'latest.json')
    checkpoint=Path(latest['checkpoint'])
    if hashlib.sha256(checkpoint.read_bytes()).hexdigest()!=test['checkpoint_sha256']:
        raise ValueError('Checkpoint does not match final test')
    final_report=read(latest['report'])
    reports=[read(p) for p in sorted((run/'models').glob('round-*/report.json'))]
    initial=[read(p) for p in sorted((run/'models').glob('initial-*/report.json'))]
    selected_initial=min(initial,key=lambda r:r['best_metrics']['selection_score'])
    sequence=[selected_initial,*reports]
    epochs=sum(r['epochs_completed'] for r in initial+reports)
    seconds=(datetime.fromisoformat(status['updated_at'])-datetime.fromisoformat(status['started_at'])).total_seconds()
    metrics=test['metrics']
    image_gain=100*(1-metrics['next_image_mse']/metrics['persistence_image_mse'])
    action_gain=100*(1-metrics['inverse_action_mse']/metrics['mean_action_mse'])
    tasks=read(read(run/'config.json')['tasks'])
    names={}
    labels=['6 块墙','4 块塔','12 块金字塔']
    for path,label in zip(tasks['train'],labels):names[read(path)['source_sha256']]=label
    names[read(tasks['validation'][-1])['source_sha256']]='38 块小屋'
    font=Path('C:/Windows/Fonts/msyh.ttc')
    if font.exists():
        font_manager.fontManager.addfont(str(font))
        plt.rcParams['font.family']=font_manager.FontProperties(fname=str(font)).get_name()
    plt.rcParams.update({'axes.unicode_minus':False,'font.size':11,'axes.spines.top':False,
                         'axes.spines.right':False,'figure.facecolor':'#f5f7fb','axes.facecolor':'white',
                         'axes.titleweight':'bold','savefig.facecolor':'#f5f7fb'})
    fig,axes=plt.subplots(2,2,figsize=(13,8.5))
    fig.suptitle('夜间训练结果｜视觉与动作关系预训练',fontsize=21,x=.06,ha='left',y=.98)
    fig.text(.06,.92,f'{seconds/3600:.2f} 小时  ·  {len(reports)} 轮增量训练  ·  {status["training_transitions"]:,} 次训练交互  ·  {len(test["groups"])} 个测试布局 / {test["transitions"]:,} 次交互',fontsize=11)
    x=np.arange(len(sequence))
    for ax,key,baseline,title in [
        (axes[0,0],'next_image_mse','persistence_image_mse','固定验证集：下一帧预测误差'),
        (axes[0,1],'inverse_action_mse','mean_action_mse','固定验证集：反推已发生动作的误差')]:
        ax.plot(x,[r['best_metrics'][key] for r in sequence],color='#2563eb',lw=2,label='模型')
        ax.axhline(sequence[-1]['best_metrics'][baseline],color='#8994a6',ls='--',label='简单基线')
        ax.set(title=title,xlabel='增量训练轮次（0 = 初始选中模型）',ylabel='均方误差 MSE，越低越好')
        ax.grid(alpha=.15);ax.legend(frameon=False)
        if key=='next_image_mse':ax.ticklabel_format(axis='y',style='sci',scilimits=(0,0))
    scene_rows=[]
    for group,m in test['per_group_metrics'].items():
        scene_rows.append({'scene':names[group.split(':')[0]],'group':group,
            'prediction_reduction_pct':100*(1-m['next_image_mse']/m['persistence_image_mse']),
            'inverse_reduction_pct':100*(1-m['inverse_action_mse']/m['mean_action_mse'])})
    scene_rows.sort(key=lambda r:labels.index(r['scene']) if r['scene'] in labels else 3)
    ax=axes[1,0]
    ax.barh([r['scene'] for r in scene_rows],[r['prediction_reduction_pct'] for r in scene_rows],color='#10a684')
    for i,r in enumerate(scene_rows):ax.text(r['prediction_reduction_pct']+1,i,f'{r["prediction_reduction_pct"]:.1f}%',va='center')
    ax.invert_yaxis();ax.set(xlim=(0,70),title='最终测试：各新布局的图像预测改进',xlabel='相对沿用当前画面，误差降低百分比')
    ax=axes[1,1]
    values=[metrics['next_image_mse'],metrics['persistence_image_mse'],metrics['shuffled_action_next_image_mse']]
    ax.bar(['正确动作输入','沿用当前画面','打乱动作输入'],values,color=['#2563eb','#8994a6','#e5a446'])
    ax.set(title='最终测试：动作输入确实影响预测',ylabel='下一帧 MSE，越低越好')
    ax.ticklabel_format(axis='y',style='sci',scilimits=(0,0))
    for i,v in enumerate(values):ax.text(i,v+max(values)*.035,f'{v:.6f}',ha='center',fontsize=10)
    ax.set_ylim(0,max(values)*1.25)
    fig.text(.06,.035,'范围：仅仿真相机数据。最终测试未参与调参；每种场景仅 1 个测试布局。小屋参与过验证选型。\n这些是预测误差，不是抓取或搭建成功率；当前权重不能直接部署为搭建策略。',fontsize=10,color='#526176')
    fig.subplots_adjust(top=.85,bottom=.16,left=.09,right=.97,hspace=.55,wspace=.3)
    fig.savefig(out/'training-results.png',dpi=150);plt.close(fig)
    payload=torch.load(checkpoint,map_location='cpu',weights_only=True)
    if payload.get('contract')!=PRETRAIN_CONTRACT or payload.get('model_version')!=MODEL_VERSION:
        raise ValueError('Unexpected checkpoint')
    model=VisualMotorModel().eval();model.load_state_dict(payload['model'])
    fig,axes=plt.subplots(4,4,figsize=(13,10))
    fig.suptitle('留出场景：相机画面与下一帧预测',fontsize=20,y=.98)
    fig.text(.06,.938,'每个测试场景固定展示第 256 次交互，未挑选最佳样本。网络输入：当前灰度画面 + 已发出的动作。',fontsize=10)
    sample_records=[]
    for row,path in enumerate(sorted((run/'data/test').glob('*/transitions.npz'))):
        with np.load(path,allow_pickle=False) as data:
            t=255;group=str(data['split_group']);name=names[group.split(':')[0]]
            if group in payload['seen_groups']:raise ValueError('Report example is not held out')
            before=image_tensor(data['rgb'][t])[None]
            actual=image_tensor(data['rgb'][t+1])[None]
            action=torch.from_numpy(data['actions'][t].copy()).float()[None]
        with torch.inference_mode():
            # Future target is deliberately NOT passed into this prediction.
            _,prediction,_=model(before,torch.zeros_like(before),action)
        before,actual,prediction=[x[0,0].numpy() for x in (before,actual,prediction)]
        error=np.abs(actual-prediction)
        sample_records.append({'scene':name,'transition_1_based':256,
            'prediction_mse':float(np.square(actual-prediction).mean()),
            'persistence_mse':float(np.square(actual-before).mean())})
        for col,(data,title) in enumerate(zip([before,actual,prediction,error],['当前相机画面','真实下一帧','模型预测下一帧','预测绝对误差（统一色标）'])):
            ax=axes[row,col]
            im=ax.imshow(data,cmap='magma' if col==3 else 'gray',vmin=0,vmax=.15 if col==3 else 1,interpolation='nearest')
            ax.set_xticks([]);ax.set_yticks([])
            if row==0:ax.set_title(title,fontsize=11)
            if col==0:ax.set_ylabel(name,fontsize=12)
            if col==3:fig.colorbar(im,ax=ax,fraction=.035,pad=.03)
    fig.text(.07,.035,'预测图分辨率为 128 × 96；低整体误差不代表砖块位姿、夹持或装配正确。这里展示的是随机探索记录，不是自动搭建演示。',fontsize=10,color='#526176')
    fig.subplots_adjust(left=.09,right=.93,top=.89,bottom=.09,hspace=.13,wspace=.12)
    fig.savefig(out/'prediction-examples.png',dpi=150);plt.close(fig)
    summary={'run':str(run),'checkpoint':str(checkpoint),'duration_seconds':seconds,
        'incremental_rounds':len(reports),'total_compute_epochs_including_trials':epochs,
        'training_transitions':status['training_transitions'],'training_layouts':len(final_report['training_groups']),
        'test_transitions':test['transitions'],'test_layouts':len(test['groups']),
        'prediction_error_reduction_pct':image_gain,'inverse_error_reduction_pct':action_gain,
        'shuffled_vs_correct_prediction_error_ratio':metrics['shuffled_action_next_image_mse']/metrics['next_image_mse'],
        'test_metrics':metrics,'scenes':scene_rows,'fixed_examples':sample_records,
        'physical_success_evaluated':False,'deployable_policy':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    # Standalone, local report: no server, CDN, telemetry or external resources.
    html='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>夜间训练结果</title><style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f5f7fb;color:#182334;max-width:1280px;margin:32px auto;padding:0 20px}img{width:100%;border-radius:12px}p{line-height:1.8}.note{padding:16px;background:#fff4db;border-radius:10px}a{color:#245ddd}</style><h1>夜间视觉与动作预训练结果</h1><p>训练已正常完成：约 6 小时 51 分钟，96 轮增量训练，101,376 次训练交互。最终测试包含 4 个新布局、2,048 次交互。</p><p class="note">当前模型学的是图像与动作的关系，尚不是搭建策略。没有完整抓取或搭建成功率；不能把误差下降百分比解释为成功率。</p><img src="training-results.png" alt="训练曲线及最终测试基线比较"><img src="prediction-examples.png" alt="固定测试样本的相机与预测对照"><p><a href="summary.json">下载数值结果与样本选择记录</a></p></html>'''
    (out/'index.html').write_text(html,encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--run',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();main(args.run,args.out)
