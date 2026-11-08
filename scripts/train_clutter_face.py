"""Train the narrow RGB verification skill on the authorized local GPU."""
import hashlib,json,sys
from pathlib import Path
import numpy as np
import torch
from clutter_face_model import build_model

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'outputs/clutter_face'
torch.manual_seed(71);torch.set_num_threads(4)
device='cuda' if torch.cuda.is_available() else 'cpu'
data=np.load(OUT/'dataset.npz');x=torch.from_numpy(data['images'].astype(np.float32)/255);y=torch.from_numpy(data['labels'])
rng=np.random.default_rng(71);order=rng.permutation(len(x));cut=int(len(x)*.8)
train=torch.utils.data.TensorDataset(x[order[:cut]],y[order[:cut]])
val_x=x[order[cut:]].to(device);val_y=y[order[cut:]].to(device)
loader=torch.utils.data.DataLoader(train,batch_size=96,shuffle=True)
model=build_model().to(device)
# Flatten has no weights: training-only dropout preserves inference checkpoint
# keys and is disabled in evaluation, while reducing crop memorization.
model[11]=torch.nn.Sequential(torch.nn.Flatten(),torch.nn.Dropout(.25))
optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.001)
scheduler=torch.optim.lr_scheduler.MultiStepLR(optimizer,milestones=[70,110,140],gamma=.25)
best=None;best_state=None;history=[]
for epoch in range(160):
    model.train();losses=[]
    for bx,by in loader:
        bx,by=bx.to(device),by.to(device);optimizer.zero_grad()
        bx=bx.clone()
        bx[:,1:]*=torch.empty((len(bx),1,1,1),device=device).uniform_(.85,1.15)
        bx[:,1:]=bx[:,1:].clamp(0,1)
        loss=torch.nn.functional.cross_entropy(model(bx),by);loss.backward();optimizer.step();losses.append(loss.item())
    model.eval()
    with torch.no_grad():
        score=model(val_x).softmax(-1)[:,1];pred=score>=.98
        accuracy=float(((score>.5)==val_y.bool()).float().mean())
        fp=int((pred&~val_y.bool()).sum());fn=int((~pred&val_y.bool()).sum())
    metric=(fp==0,-fp,-fn,accuracy)
    if best is None or metric>best:
        best=metric;best_state={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    history.append({'epoch':epoch,'loss':float(np.mean(losses)),'validation_accuracy':accuracy,'false_upright':fp,'missed_upright_at_098':fn})
    scheduler.step()
    if epoch%10==0:print(json.dumps(history[-1]),flush=True)
model.load_state_dict(best_state);model.eval()
with torch.no_grad():
    score=model(val_x).softmax(-1)[:,1];pred=score>=.98
    accuracy=float(((score>.5)==val_y.bool()).float().mean());fp=int((pred&~val_y.bool()).sum());fn=int((~pred&val_y.bool()).sum())
torch.save(best_state,OUT/'upright.pt')
report={'device':device,'training_samples':len(train),'validation_samples':len(val_y),
    'dataset_seed':json.loads((OUT/'dataset.json').read_text())['seed'],
    'dataset_sha256':hashlib.sha256((OUT/'dataset.npz').read_bytes()).hexdigest(),
    'validation_accuracy':accuracy,'false_upright_at_098':fp,'missed_upright_at_098':fn,
    'threshold':.98,'approved_for_simulated_station_trial':fp==0 and fn<=max(2,int(len(val_y)*.03)),
    'training_augmentation':'normalized intensity/edge gain 0.85..1.15; feature dropout 0.25; no image rotations altering lighting cues',
    'scope':'simulated isolated-station wrist RGB only; not general clutter grasp or real hardware validation',
    'history':history}
(OUT/'training.json').write_text(json.dumps(report,indent=2));print(json.dumps({k:v for k,v in report.items() if k!='history'}),flush=True)
