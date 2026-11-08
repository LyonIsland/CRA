"""Isolated-station RGB upright verification; no simulator state inputs."""
import numpy as np
from scipy.ndimage import zoom
from scipy.ndimage import label
from clutter_perception import color_masks
from wrist_vision import project
from rotary_regripper import CENTER

def station_observation(rgb,camera_to_world,color=None):
    """Locate the isolated colored piece around the calibrated fixture volume."""
    uv=np.rint(project(CENTER,camera_to_world)[0]).astype(int);radius=int(round(50*rgb.shape[1]/320))
    x0,y0=uv-radius;x1,y1=uv+radius
    if x0<0 or y0<0 or x1>rgb.shape[1] or y1>rgb.shape[0]:return None
    masks=color_masks(rgb)
    full_mask=masks[color] if color in masks else np.logical_or.reduce([m for name,m in masks.items() if name!='black_distractor'])
    mask=full_mask[y0:y1,x0:x1]
    components,count=label(mask);kept=np.zeros_like(mask)
    for index in range(1,count+1):
        yy,xx=np.where(components==index)
        if len(xx)>=20 and np.linalg.norm(np.array([xx.mean(),yy.mean()])-radius)<radius*.65:kept[yy,xx]=True
    yy,xx=np.where(kept)
    if len(xx)<100:return None
    centre=np.array([(xx.min()+xx.max())/2+x0,(yy.min()+yy.max())/2+y0])
    axis=np.linalg.eigh(np.cov(np.vstack([xx,yy])))[1][:,-1]
    return {'center_uv':centre,'principal_axis_uv':axis,'visible_pixels':len(xx),
        'bbox':np.array([xx.min()+x0-.5,xx.max()+x0+.5,yy.min()+y0-.5,yy.max()+y0+.5])}

def patch(rgb,camera_to_world,color):
    uv=np.rint(project(CENTER,camera_to_world)[0]).astype(int);radius=int(round(50*rgb.shape[1]/320))
    x0,y0=uv-radius;x1,y1=uv+radius
    if x0<0 or y0<0 or x1>rgb.shape[1] or y1>rgb.shape[0]:raise ValueError('Inspection station lies outside wrist RGB crop')
    # One isolated colored part in a calibrated neutral-gray fixture. Union
    # segmentation avoids treating a lighting-induced orange/yellow shift as
    # missing geometry; this is not used for identity selection in the heap.
    masks=color_masks(rgb)
    mask=np.logical_or.reduce([m for name,m in masks.items() if name!='black_distractor'])[y0:y1,x0:x1].astype(float)
    components,count=label(mask);kept=np.zeros_like(mask)
    for index in range(1,count+1):
        yy,xx=np.where(components==index)
        if len(xx)>=20 and np.linalg.norm(np.array([xx.mean(),yy.mean()])-radius)<radius*.65:kept[yy,xx]=1
    mask=kept
    if mask.sum()<100:return np.zeros((3,96,96),dtype=np.float32)
    gray=rgb[y0:y1,x0:x1].astype(float).mean(2)/255.
    values=gray[mask>.5]
    scale=float(np.median(values)) if len(values)>15 else .5
    gray=np.clip(gray/max(.08,scale),0,2)*mask*.5
    dy,dx=np.gradient(gray);edge=np.clip(np.sqrt(dx*dx+dy*dy)*3,0,1)
    channels=np.stack([mask,gray,edge])
    yy,xx=np.where(mask>.5);side=int(np.ceil(max(xx.max()-xx.min()+1,yy.max()-yy.min()+1)*1.25))
    cx,cy=(xx.min()+xx.max())/2,(yy.min()+yy.max())/2
    sx,sy=int(round(cx-side/2)),int(round(cy-side/2));padded=np.zeros((3,side,side))
    ax,ay=max(0,sx),max(0,sy);bx,by=min(mask.shape[1],sx+side),min(mask.shape[0],sy+side)
    padded[:,ay-sy:by-sy,ax-sx:bx-sx]=channels[:,ay:by,ax:bx]
    return np.clip(zoom(padded,(1,96/side,96/side),order=1),0,1).astype(np.float32)

def build_model():
    import torch.nn as nn
    return nn.Sequential(nn.Conv2d(3,24,3,padding=1),nn.ReLU(),
        nn.Conv2d(24,32,3,stride=2,padding=1),nn.ReLU(),
        nn.Conv2d(32,48,3,stride=2,padding=1),nn.ReLU(),
        nn.Conv2d(48,64,3,stride=2,padding=1),nn.ReLU(),
        nn.Conv2d(64,96,3,stride=2,padding=1),nn.ReLU(),
        nn.AdaptiveAvgPool2d((4,4)),nn.Flatten(),nn.Linear(1536,96),nn.ReLU(),nn.Linear(96,2))

class UprightVerifier:
    def __init__(self,weights):
        import torch
        self.torch=torch;torch.set_num_threads(2);self.model=build_model().cpu()
        self.model.load_state_dict(torch.load(weights,map_location='cpu',weights_only=True));self.model.eval()
    def predict(self,rgb,camera_to_world,color):
        features=patch(rgb,camera_to_world,color)
        if features[0].sum()<60:return {'upright_score':0.,'upright':False,'insufficient_visibility':True,
            'source':'trained isolated-station wrist RGB classifier','score_is_calibrated_probability':False}
        x=self.torch.from_numpy(features)[None]
        with self.torch.no_grad():p=float(self.model(x).softmax(-1)[0,1])
        return {'upright_score':p,'upright':p>=.98,'source':'trained isolated-station wrist RGB classifier',
            'score_is_calibrated_probability':False}
