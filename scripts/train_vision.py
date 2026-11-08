"""Supervised wrist RGB localization from Isaac-generated projection labels."""
import argparse,json,time
from pathlib import Path
import numpy as np
import torch
from torch.nn import functional as F
from vision_model import Localizer,decode

ROOT=Path(__file__).resolve().parents[1]
p=argparse.ArgumentParser();p.add_argument('--epochs',type=int,default=80)
p.add_argument('--directory',default='vision')
args=p.parse_args();torch.manual_seed(42);torch.set_num_threads(4)
device='cuda' if torch.cuda.is_available() else 'cpu'
out=ROOT/'outputs'/args.directory
data=np.load(out/'localization.npz')
images=torch.from_numpy(data['images']).permute(0,3,1,2).float()/255
images=F.interpolate(images,(120,160),mode='area').to(device)
uv=torch.tensor((data['pixels']-.5)/2,dtype=torch.float32,device=device)
ids=np.random.default_rng(42).permutation(len(images));nv=max(8,len(ids)//5)
val=torch.tensor(ids[:nv],device=device);train=torch.tensor(ids[nv:],device=device)
if len(train)<8:raise ValueError('Collect at least 32 images before training')
yy,xx=torch.meshgrid(torch.arange(120,device=device),torch.arange(160,device=device),indexing='ij')
heat=torch.exp(-((xx[None]-uv[:,0,None,None])**2+(yy[None]-uv[:,1,None,None])**2)/(2*1.7**2))[:,None]
model=Localizer().to(device);optimizer=torch.optim.Adam(model.parameters(),lr=.001)
best=float('inf');start=time.perf_counter()
for epoch in range(args.epochs):
    model.train()
    for batch in train[torch.randperm(len(train),device=device)].split(24):
        x=images[batch];gain=torch.empty((len(batch),3,1,1),device=device).uniform_(.8,1.2)
        x=(x*gain+torch.randn_like(x)*.015).clamp(0,1)
        logits=model(x)
        loss=F.binary_cross_entropy_with_logits(logits,heat[batch],pos_weight=torch.tensor(40.,device=device))
        optimizer.zero_grad();loss.backward();optimizer.step()
    model.eval()
    with torch.no_grad():
        pred=decode(model(images[val]));error=(pred-torch.tensor(data['pixels'][ids[:nv]],device=device)).norm(dim=1)
        mean=error.mean().item()
    if mean<best:
        best=mean;torch.save(model.cpu().state_dict(),out/'localizer.pt');model.to(device)
    if epoch%10==0:print(json.dumps({'epoch':epoch+1,'validation_mean_pixel_error':mean,'best':best}),flush=True)
report={'method':'RGB keypoint heatmap CNN','device':device,'samples':len(images),
        'train_images':len(train),'validation_images':len(val),'validation_mean_pixel_error':best,
        'epochs':args.epochs,'seconds':time.perf_counter()-start,
        'labels':'simulation top-center projections; no ground-truth object pose at inference',
        'limits':['fixed red brick and orientation','synthetic RGB only','provisional camera calibration']}
(out/'training.json').write_text(json.dumps(report,indent=2));print(json.dumps(report),flush=True)
