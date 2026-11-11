"""Visual representation learning from actual RGB/action transitions.

Exploration actions are inverse-dynamics targets, NEVER imitation targets.
Outputs cannot be loaded as an assembly policy. No simulator imports.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.data import Dataset, DataLoader
from camera_policy import CameraNetwork, image_tensor
from camera_explore import EXPLORATION_CONTRACT

PRETRAIN_CONTRACT = 'camera_visual_motor_pretrain_v1'
MODEL_VERSION = 'image_warp_v3'


def atomic_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')
    tmp.replace(path)


def atomic_checkpoint(path, value):
    path=Path(path);tmp=path.with_suffix('.tmp')
    torch.save(value,tmp);tmp.replace(path)


class Transitions(Dataset):
    def __init__(self, paths):
        self.episodes=[];self.episode_groups=[];self.index=[];self.groups=set();self.hashes={};self.fingerprints=set()
        for path in paths:
            with np.load(path,allow_pickle=False) as data:
                if set(data.files)!={'contract','rgb','actions','split_group'}:
                    raise ValueError(f'{path}: forbidden or missing fields')
                if str(data['contract'])!=EXPLORATION_CONTRACT:
                    raise ValueError(f'{path}: not self-supervised exploration')
                rgb,actions=data['rgb'],data['actions']
                group=str(data['split_group'])
                if not group or rgb.dtype!=np.uint8 or rgb.ndim!=4 or rgb.shape[-1]!=3:
                    raise ValueError('Expected grouped uint8 RGB sequence')
                if len(rgb)<3 or actions.shape!=(len(rgb)-1,7):
                    raise ValueError('Need aligned before/action/after transitions')
                if not np.isfinite(actions).all() or np.abs(actions).max()>1.00001:
                    raise ValueError('Nonfinite or unbounded action')
                digest=hashlib.sha256(rgb.tobytes());digest.update(actions.astype(np.float32).tobytes())
                self.fingerprints.add(digest.hexdigest())
                # uint8 grayscale cache keeps overnight dataset RAM bounded.
                frames=torch.stack([(image_tensor(frame)*255).round().byte() for frame in rgb])
                ep=len(self.episodes)
                self.episodes.append((frames,torch.from_numpy(actions.copy()).float()))
                self.episode_groups.append(group)
                self.index.extend((ep,t) for t in range(len(actions)))
                self.groups.add(group)
                self.hashes[str(path)]=hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if not self.index:raise ValueError('No exploration data')

    def __len__(self):return len(self.index)

    def __getitem__(self,index):
        ep,t=self.index[index];frames,actions=self.episodes[ep]
        return frames[t].float()/255,frames[t+1].float()/255,actions[t]


class VisualMotorModel(nn.Module):
    def __init__(self):
        super().__init__()
        self.encoder=CameraNetwork().encoder
        self.decoder=nn.Sequential(nn.Linear(128,64*6*8),nn.ReLU(),nn.Unflatten(1,(64,6,8)),
            nn.ConvTranspose2d(64,32,4,2,1),nn.ReLU(),
            nn.ConvTranspose2d(32,16,4,2,1),nn.ReLU(),
            nn.ConvTranspose2d(16,8,4,2,1),nn.ReLU(),
            nn.ConvTranspose2d(8,1,4,2,1),nn.Sigmoid())
        self.inverse=nn.Sequential(nn.Linear(256,128),nn.ReLU(),nn.Linear(128,7),nn.Tanh())
        self.forward_model=nn.Sequential(nn.LayerNorm(135),nn.Linear(135,256),nn.ReLU(),nn.Linear(256,128))
        # Predict image motion rather than repainting a nearly unchanged frame.
        # A zero flow starts exactly at the persistence baseline. The only
        # conditioning is the RGB encoding and issued action, no camera pose.
        self.flow=nn.Sequential(nn.Linear(128,64*6*8),nn.ReLU(),nn.Unflatten(1,(64,6,8)),
            nn.ConvTranspose2d(64,32,4,2,1),nn.ReLU(),
            nn.ConvTranspose2d(32,16,4,2,1),nn.ReLU(),nn.Conv2d(16,2,3,padding=1))
        nn.init.zeros_(self.flow[-1].weight);nn.init.zeros_(self.flow[-1].bias)

    def forward(self,before,after,action,warp_source=None):
        z=self.encoder(before);next_z=self.encoder(after)
        predicted=z+self.forward_model(torch.cat([z,action],1))
        displacement=F.interpolate(self.flow(predicted),size=before.shape[-2:],mode='bilinear',align_corners=False).tanh()*.15
        h,w=before.shape[-2:]
        y=(torch.arange(h,device=before.device,dtype=before.dtype)+.5)*2/h-1
        x=(torch.arange(w,device=before.device,dtype=before.dtype)+.5)*2/w-1
        yy,xx=torch.meshgrid(y,x,indexing='ij')
        grid=torch.stack([xx,yy],-1)[None]+displacement.permute(0,2,3,1)
        future=F.grid_sample(before if warp_source is None else warp_source,grid,mode='bilinear',padding_mode='border',align_corners=False)
        return self.decoder(z),future,self.inverse(torch.cat([z,10*(next_z-z)],1))


def evaluate(model,loader,device,action_mean):
    sums=dict(reconstruction_mse=0.,next_image_mse=0.,inverse_action_mse=0.,
              persistence_image_mse=0.,zero_action_mse=0.,mean_action_mse=0.,
              shuffled_action_next_image_mse=0.)
    count=0
    model.eval()
    permutation_rng=torch.Generator().manual_seed(876)
    with torch.inference_mode():
        for before,after,action in loader:
            before,after,action=[x.to(device) for x in (before,after,action)]
            rec,pred,inv=model(before,after,action)
            permutation=torch.randperm(len(action),generator=permutation_rng).to(device)
            _,shuffled,_=model(before,after,action[permutation])
            pairs=[(rec,before),(pred,after),(inv,action),(before,after),
                   (torch.zeros_like(action),action),(action_mean.expand_as(action),action),(shuffled,after)]
            for key,(a,b) in zip(sums,pairs):sums[key]+=float(F.mse_loss(a,b))*len(before)
            count+=len(before)
    metrics={key:value/count for key,value in sums.items()}
    metrics['selection_score']=metrics['reconstruction_mse']+20*metrics['next_image_mse']+.25*metrics['inverse_action_mse']
    if not all(math.isfinite(v) for v in metrics.values()):raise RuntimeError('Nonfinite validation')
    return metrics


def train(train_paths,val_paths,out,*,epochs=20,lr=3e-4,batch_size=64,seed=42,
          resume=None,require_cuda=False,manual_task=None,deadline=None,stop_file=None):
    torch.set_num_threads(4);torch.manual_seed(seed);np.random.seed(seed)
    if require_cuda and not torch.cuda.is_available():raise RuntimeError('CUDA required; no silent CPU fallback')
    device='cuda' if torch.cuda.is_available() else 'cpu'
    training,validation=Transitions(train_paths),Transitions(val_paths)
    if training.groups & validation.groups:raise ValueError('Layout/task group leakage')
    # Also reject identical shards mislabeled with different group names.
    if training.fingerprints & validation.fingerprints:raise ValueError('Duplicate shard leakage')
    loader=DataLoader(training,batch_size=batch_size,shuffle=True,num_workers=0)
    val_loader=DataLoader(validation,batch_size=batch_size,num_workers=0)
    model=VisualMotorModel().to(device)
    optimizer=torch.optim.AdamW(model.parameters(),lr=lr,weight_decay=1e-4)
    if resume:
        payload=torch.load(resume,map_location='cpu',weights_only=True)
        if payload.get('contract')!=PRETRAIN_CONTRACT or payload.get('model_version')!=MODEL_VERSION:
            raise ValueError('Wrong pretraining checkpoint or architecture')
        model.load_state_dict(payload['model'])
        optimizer.load_state_dict(payload['optimizer'])
        for state in optimizer.state.values():
            for key,value in state.items():
                if isinstance(value,torch.Tensor):state[key]=value.to(device)
        for group in optimizer.param_groups:group['lr']=lr
    pages=None
    if manual_task:
        from bricklab_task import load_manual
        manuals=manual_task if isinstance(manual_task,(list,tuple)) else [manual_task]
        pages=torch.stack([image_tensor(page) for task in manuals for page in load_manual(task)]).to(device)
    action_mean=torch.cat([a for _,a in training.episodes]).mean(0).to(device)
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,patience=2,factor=.5)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    baseline=evaluate(model,val_loader,device,action_mean)
    best=baseline['selection_score'];stale=0;history=[]
    def save_best(epoch,metrics):
        state={key:value.detach().cpu() for key,value in model.state_dict().items()}
        atomic_checkpoint(out/'best.pt',{'contract':PRETRAIN_CONTRACT,'model_version':MODEL_VERSION,'model':state,
            'optimizer':optimizer.state_dict(),'epoch':epoch,'metrics':metrics,
            'action_mean':action_mean.detach().cpu(),
            'seen_groups':sorted(training.groups|validation.groups),
            'seen_fingerprints':sorted(training.fingerprints|validation.fingerprints),
            'deployable_policy':False})
        atomic_checkpoint(out/'encoder.pt',{'contract':PRETRAIN_CONTRACT,
            'encoder':{k:v.detach().cpu() for k,v in model.encoder.state_dict().items()},
            'deployable_policy':False})
    save_best(0,baseline)
    for epoch in range(1,epochs+1):
        if (deadline and time.time()>=deadline) or (stop_file and Path(stop_file).exists()):break
        model.train();total=0.;seen=0
        for before,after,action in loader:
            if (deadline and time.time()>=deadline) or (stop_file and Path(stop_file).exists()):break
            before,after,action=[x.to(device) for x in (before,after,action)]
            # Same exposure perturbation on a pair preserves motion correspondence.
            gain=torch.empty(len(before),1,1,1,device=device).uniform_(.7,1.3)
            before=(before*gain).clamp(0,1);after=(after*gain).clamp(0,1)
            # Corrupt input only; learn denoising, not arbitrary image copying.
            noisy=(before+.025*torch.randn_like(before)).clamp(0,1)
            rec,pred,inv=model(noisy,after,action,warp_source=before)
            loss=F.mse_loss(rec,before)+20*F.mse_loss(pred,after)+.25*F.mse_loss(inv,action)
            if pages is not None:
                goal=pages[torch.randint(len(pages),(min(8,len(pages)),),device=device)]
                goal_noisy=(goal+.025*torch.randn_like(goal)).clamp(0,1)
                loss=loss+.1*F.mse_loss(model.decoder(model.encoder(goal_noisy)),goal)
            if not torch.isfinite(loss):raise RuntimeError('Nonfinite training loss')
            optimizer.zero_grad(set_to_none=True);loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(),1.);optimizer.step()
            total+=float(loss.detach())*len(before);seen+=len(before)
        if not seen:break
        metrics=evaluate(model,val_loader,device,action_mean)
        record={'epoch':epoch,'train_loss':total/seen,'lr':optimizer.param_groups[0]['lr'],**metrics}
        history.append(record);print(json.dumps(record),flush=True)
        with (out/'metrics.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(record)+'\n')
        scheduler.step(metrics['selection_score'])
        if metrics['selection_score']<best-1e-6:
            best=metrics['selection_score'];stale=0;save_best(epoch,metrics)
        else:stale+=1
        if stale>=5:break
    payload=torch.load(out/'best.pt',map_location='cpu',weights_only=True)
    measured=payload['metrics']
    report={'contract':PRETRAIN_CONTRACT,'model_version':MODEL_VERSION,'device':device,'gpu':torch.cuda.get_device_name(0) if device=='cuda' else None,
        'training_transitions':len(training),'validation_transitions':len(validation),
        'training_groups':sorted(training.groups),'validation_groups':sorted(validation.groups),
        'dataset_sha256':{**training.hashes,**validation.hashes},'initial_metrics':baseline,
        'best_metrics':payload['metrics'],'epochs_completed':len(history),'seed':seed,
        'physical_success_evaluated':False,'deployable_policy':False,
        'manual_objective':'image reconstruction only; not instruction/action alignment',
        'selection_weights':{'reconstruction_mse':1.,'next_image_mse':20.,'inverse_action_mse':.25},
        'beats_persistence':measured['next_image_mse']<measured['persistence_image_mse'],
        'beats_zero_and_mean_actions':measured['inverse_action_mse']<min(measured['zero_action_mse'],measured['mean_action_mse']),
        'correct_actions_better_than_shuffled':measured['next_image_mse']<measured['shuffled_action_next_image_mse'],
        'limitations':['motor babbling is not successful assembly demonstration',
                      'validation reused for model selection; not an independent final test',
                      'predictive metrics do not establish grasping or assembly ability']}
    atomic_json(out/'report.json',report)
    return report


def test_checkpoint(checkpoint,paths,out):
    torch.set_num_threads(4)
    device='cuda' if torch.cuda.is_available() else 'cpu'
    payload=torch.load(checkpoint,map_location='cpu',weights_only=True)
    if payload.get('contract')!=PRETRAIN_CONTRACT or payload.get('model_version')!=MODEL_VERSION:raise ValueError('Wrong checkpoint')
    dataset=Transitions(paths)
    if dataset.groups & set(payload['seen_groups']):raise ValueError('Test overlaps model-selection data')
    if dataset.fingerprints & set(payload['seen_fingerprints']):raise ValueError('Test contains duplicate model-selection content')
    model=VisualMotorModel().to(device);model.load_state_dict(payload['model'])
    per_group={}
    for group in sorted(dataset.groups):
        indices=[i for i,(ep,_) in enumerate(dataset.index) if dataset.episode_groups[ep]==group]
        subset=torch.utils.data.Subset(dataset,indices)
        per_group[group]=evaluate(model,DataLoader(subset,batch_size=64),device,payload['action_mean'].to(device))
    report={'metrics':evaluate(model,DataLoader(dataset,batch_size=64),device,payload['action_mean'].to(device)),
            'groups':sorted(dataset.groups),'per_group_metrics':per_group,'transitions':len(dataset),
            'checkpoint_sha256':hashlib.sha256(Path(checkpoint).read_bytes()).hexdigest(),
            'physical_success_evaluated':False,'deployable_policy':False}
    atomic_json(out,report)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--epochs',type=int,default=20)
    parser.add_argument('--lr',type=float,default=3e-4)
    parser.add_argument('--batch-size',type=int,default=64)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--resume',type=Path)
    parser.add_argument('--require-cuda',action='store_true')
    parser.add_argument('--manual-task',type=Path,action='append')
    parser.add_argument('--deadline',type=float)
    parser.add_argument('--stop-file',type=Path)
    parser.add_argument('--test-checkpoint',type=Path)
    args=parser.parse_args()
    if args.test_checkpoint:
        test_checkpoint(args.test_checkpoint,sorted(args.data.glob('*/transitions.npz')),args.out)
        raise SystemExit(0)
    if args.epochs<1 or args.batch_size<1 or args.lr<=0:parser.error('Positive training arguments required')
    train(sorted((args.data/'train').glob('*/transitions.npz')),
          sorted((args.data/'validation').glob('*/transitions.npz')),args.out,
          epochs=args.epochs,lr=args.lr,batch_size=args.batch_size,seed=args.seed,
          resume=args.resume,require_cuda=args.require_cuda,manual_task=args.manual_task,deadline=args.deadline,stop_file=args.stop_file)
