"""RGB multiview heap observations and model-based height/pose fitting.

Inputs are pixels and encoder-derived camera matrices. No scene/body queries.
Coarse faces remain hypotheses until isolated visual inspection validates them.
"""
import numpy as np
from scipy.ndimage import label
from scipy.optimize import least_squares
from scipy.spatial import ConvexHull
from scipy.spatial.transform import Rotation
from assembly_perception import HUES
from wrist_vision import intrinsics,project,unproject

FACES={'up':[0,0,0],'down':[180,0,0],'side_left':[90,0,0],
       'side_right':[-90,0,0],'end_front':[0,90,0],'end_back':[0,-90,0]}
BODY=np.array([[x,y,z] for x in [-.0159,.0159] for y in [-.0079,.0079] for z in [-.0048,.0048]])
STUDS=np.array([[x+.0024*np.cos(a),y+.0024*np.sin(a),.0066]
    for x in [-.012,-.004,.004,.012] for y in [-.004,.004] for a in np.linspace(0,2*np.pi,8,endpoint=False)])
MODEL=np.vstack([BODY,STUDS])

def model_for(color):
    if color!='cyan_distractor':return MODEL
    body=np.array([[x,y,z] for x in [-.0079,.0079] for y in [-.0079,.0079] for z in [-.0048,.0048]])
    studs=np.array([[x+.0024*np.cos(a),y+.0024*np.sin(a),.0066]
        for x in [-.004,.004] for y in [-.004,.004] for a in np.linspace(0,2*np.pi,8,endpoint=False)])
    return np.vstack([body,studs])

def color_masks(rgb):
    image=rgb.astype(float)/255.;hi=image.max(2);lo=image.min(2);d=hi-lo
    hue=np.zeros_like(hi);r,g,b=np.moveaxis(image,2,0);index=image.argmax(2)
    for channel,formula in [(0,(g-b)/np.maximum(d,1e-6)%6),(1,(b-r)/np.maximum(d,1e-6)+2),(2,(r-g)/np.maximum(d,1e-6)+4)]:
        take=(index==channel)&(d>1e-6);hue[take]=formula[take]*60
    hues={**HUES,'cyan_distractor':183.}
    prototypes=[*hues.items(),('orange',28.),('blue',225.),('green',135.)]
    names=[x[0] for x in prototypes];distance=abs(hue[:,:,None]-np.array([x[1] for x in prototypes]))
    distance=np.minimum(distance,360-distance);win=distance.argmin(2);minimum=distance.min(2)
    masks={name:np.isin(win,[i for i,n in enumerate(names) if n==name])&(minimum<(38 if name=='blue' else 30))&(d/np.maximum(hi,1e-6)>.35)&(hi>.16)
            for name in hues}
    masks['black_distractor']=(hi<.23)&(hi>.025)&(d/np.maximum(hi,1e-6)<.35)
    # Known wrist self-occlusion strip: robot fingers occupy the far left.
    masks['black_distractor'][:,:int(round(rgb.shape[1]*.125))]=False
    return masks

def observe(rgb,pose):
    observations={}
    for color,mask in color_masks(rgb).items():
        components,count=label(mask);groups=[]
        for i in range(1,count+1):
            yy,xx=np.where(components==i)
            if len(xx)>=12:groups.append((xx,yy))
        if not groups:continue
        xx,yy=max(groups,key=lambda g:len(g[0]))
        if xx.min()<4 or yy.min()<4 or xx.max()>rgb.shape[1]-5 or yy.max()>rgb.shape[0]-5:continue
        observations[color]={'bbox':np.array([xx.min()-.5,xx.max()+.5,yy.min()-.5,yy.max()+.5]),
            'pixel_scale':320/rgb.shape[1],
            'pixels':int(len(xx)),'center_uv':np.array([xx.mean(),yy.mean()]),
            'pose':np.asarray(pose),'mask':mask,
            'principal_axis_uv':np.linalg.eigh(np.cov(np.vstack([xx,yy])))[1][:,-1]}
    return observations

def projected_bbox(points,pose):
    p=(points-pose[:3,3])@pose[:3,:3];cv=p*np.array([1,-1,-1])
    uv=cv@intrinsics().T;uv=uv[:,:2]/uv[:,2:3]
    return np.array([uv[:,0].min(),uv[:,0].max(),uv[:,1].min(),uv[:,1].max()])

def projected_area(points,pose):
    p=(points-pose[:3,3])@pose[:3,:3];cv=p*np.array([1,-1,-1])
    uv=cv@intrinsics().T;uv=uv[:,:2]/uv[:,2:3]
    return float(ConvexHull(uv).volume)

def fit_piece(color,views):
    observations=[v[color] for v in views if color in v]
    if len(observations)<2:return None
    # Prefer high-pixel observations; a tiny occluded fragment is not a full bbox.
    observations=sorted(observations,key=lambda o:o['pixels'],reverse=True)[:4]
    model=model_for(color);body=model[:8]
    init=np.median([unproject(o['center_uv'],o['pose'])[:2] for o in observations],axis=0)
    k=intrinsics();view_cache={}
    def prepared(selected):
        key=tuple(id(o) for o in selected)
        if key not in view_cache:
            view_cache[key]=(np.array([o['pose'][:3,3] for o in selected]),
                np.array([o['pose'][:3,:3] for o in selected]),np.array([o['bbox'] for o in selected]),
                np.array([o['pixel_scale'] for o in selected]),np.array([o['principal_axis_uv'] for o in selected]))
        return view_cache[key]
    solutions=[]
    for name,euler in FACES.items():
        face=Rotation.from_euler('xyz',euler,degrees=True).as_matrix()
        # The observed rigid shape cannot extend below the calibrated tabletop.
        # Constrain the optimizer itself, rather than fitting a shrunken/shadowed
        # silhouette below the table and rejecting the result afterwards.
        minimum_z=max(.003,-float((model@face.T)[:,2].min())-.0003)
        use_axis=not name.startswith('end') and color!='cyan_distractor'
        def residual(v,selected=None):
            selected=observations if selected is None else selected
            r=Rotation.from_euler('z',v[3]).as_matrix()@face
            points=model@r.T+v[:3]
            centres,bases,boxes,scales,axes=prepared(selected)
            samples=np.vstack([points,v[:3]+r[:,0]*.012,v[:3]-r[:,0]*.012]) if use_axis else points
            cv=np.matmul(samples[None,:,:]-centres[:,None,:],bases)*np.array([1,-1,-1])
            uv=cv@k.T;uv=uv[:,:,:2]/uv[:,:,2:3]
            model_uv=uv[:,:len(points)]
            predicted=np.column_stack([model_uv[:,:,0].min(1),model_uv[:,:,0].max(1),model_uv[:,:,1].min(1),model_uv[:,:,1].max(1)])
            errors=(predicted-boxes)*scales[:,None]
            if use_axis:
                direction=uv[:,-2]-uv[:,-1];direction/=np.maximum(1e-8,np.linalg.norm(direction,axis=1))[:,None]
                dot=np.sum(direction*axes,axis=1)
                errors=np.column_stack([errors,3*np.sqrt(np.maximum(0.,1-dot*dot))])
            return errors.ravel()
        best=None
        for yaw in [-np.pi/3,0,np.pi/3]:
            start=np.r_[np.clip(init,[.15,-.25],[.40,.02]),max(.015,minimum_z+.002),yaw]
            fit=least_squares(residual,start,bounds=([.15,-.26,minimum_z,-np.pi],[.40,.03,.08,np.pi]),
                loss='soft_l1',f_scale=1.2,max_nfev=55)
            selected=observations
            if len(observations)>2:
                errors=np.sqrt(np.mean(fit.fun.reshape(len(observations),5 if use_axis else 4)**2,axis=1))
                selected=[observations[i] for i in np.argsort(errors)[:max(2,len(observations)-1)]]
                fit=least_squares(lambda v:residual(v,selected),fit.x,
                    bounds=([.15,-.26,minimum_z,-np.pi],[.40,.03,.08,np.pi]),loss='soft_l1',f_scale=1.2,max_nfev=55)
            score=float(np.sqrt(np.mean(fit.fun**2)))
            if best is None or score<best[0]:best=(score,fit.x,selected)
        score,v,selected=best;r=Rotation.from_euler('z',v[3]).as_matrix()@face
        lo=(body@r.T+v[:3]).min(0);hi=(model@r.T+v[:3]).max(0)
        if lo[2]<-.0015:score+=20*abs(lo[2])/.0015
        expected=[];silhouette_fill=[]
        for o in selected:
            bbox=projected_bbox(model@r.T+v[:3],o['pose'])
            expected.append(o['pixels']/max(1.,(bbox[1]-bbox[0])*(bbox[3]-bbox[2])))
            silhouette_fill.append(o['pixels']/max(1.,projected_area(model@r.T+v[:3],o['pose'])))
        solutions.append({'score_px':score,'face_hypothesis':name,'position_m':v[:3].tolist(),
            'yaw_deg':float(np.rad2deg(v[3])),'rotation_matrix':r.tolist(),
            'top_height_m':float(hi[2]),'bottom_height_m':float(lo[2]),
            'visible_bbox_fill':float(np.median(expected)),'views':len(selected),
            'visible_silhouette_fill':float(np.median(silhouette_fill)),
            'rejected_view_count':len(observations)-len(selected)})
    solutions.sort(key=lambda x:x['score_px']);best=solutions[0]
    best.update({'color':color,'face_hypotheses':[{k:v for k,v in s.items() if k in ['face_hypothesis','score_px']} for s in solutions],
        'source':'multiview_wrist_RGB_geometry','orientation_confirmed':False,
        'safe_candidate':bool(best['score_px']<2.0 and best['visible_silhouette_fill']>.50 and best['bottom_height_m']>-.0015)})
    return best

def reconstruct(views):
    return [piece for color in [*HUES,'cyan_distractor','black_distractor'] if (piece:=fit_piece(color,views)) is not None]

def finger_visual_overlap(views,estimates,color,centre,yaw,opening):
    """Project the actual pad boxes into measured RGB masks of neighbouring parts."""
    from PIL import Image,ImageDraw
    rotation=Rotation.from_euler('z',yaw,degrees=True).as_matrix()
    corners=np.array([[x,y,z] for x in [-.010,.010] for y in [-.002,.002] for z in [-.004,.004]])
    by_color={p['color']:p for p in estimates};scores=[]
    for view in views:
        if color not in view:continue
        pose=view[color]['pose'];shape=view[color]['mask'].shape;neighbours=np.zeros(shape,dtype=bool)
        for name,observation in view.items():
            if name==color:continue
            estimate=by_color.get(name)
            if estimate and estimate['score_px']<2. and estimate['top_height_m']<centre[2]-.004:continue
            mask=observation['mask']
            if name=='black_distractor':
                # Restrict achromatic pixels to the detected component bbox;
                # otherwise robot/table shadows masquerade as black obstacles.
                x0,x1,y0,y1=np.rint(observation['bbox']).astype(int)
                neighbours[max(0,y0):y1+1,max(0,x0):x1+1]|=mask[max(0,y0):y1+1,max(0,x0):x1+1]
            else:neighbours|=mask
        for side in [-1,1]:
            middle=centre+rotation[:,1]*side*(opening+.002)
            pixels=np.array([project(p,pose)[0] for p in corners@rotation.T+middle])
            hull=ConvexHull(pixels);canvas=Image.new('1',(shape[1],shape[0]))
            ImageDraw.Draw(canvas).polygon([tuple(p) for p in pixels[hull.vertices]],fill=1)
            footprint=np.asarray(canvas,dtype=bool);area=int(footprint.sum())
            if area>=8:scores.append(float((footprint&neighbours).sum())/area)
    return round(max(scores,default=0.),3)

def released_table_piece(rgb,pose,color,near_xy):
    """Reobserve a previously verified upright part after releasing on the table."""
    seen=observe(rgb,pose).get(color)
    if seen is None:return None
    axis=seen['principal_axis_uv'];direction=pose[:3,0]*axis[0]-pose[:3,1]*axis[1]
    yaw=float(np.arctan2(direction[1],direction[0]));model=model_for(color)
    def residual(v):
        r=Rotation.from_euler('z',v[2]).as_matrix();centre=np.r_[v[:2],.0048]
        box=(projected_bbox(model@r.T+centre,pose)-seen['bbox'])*seen['pixel_scale']
        a=project(centre+r[:,0]*.012,pose)[0];b=project(centre-r[:,0]*.012,pose)[0]
        projected=(a-b)/max(1e-8,np.linalg.norm(a-b))
        return np.r_[box,3*np.sqrt(max(0.,1-float(projected@axis)**2))]
    near=np.asarray(near_xy);fit=least_squares(residual,np.r_[near,yaw],
        bounds=(np.r_[near-.04,yaw-.45],np.r_[near+.04,yaw+.45]),max_nfev=60)
    error=float(np.sqrt(np.mean(fit.fun**2)))
    if error>2. or np.linalg.norm(fit.x[:2]-near)>.03:return None
    return {'color':color,'position_m':np.r_[fit.x[:2],.0048].tolist(),
        'yaw_deg':float(np.rad2deg(fit.x[2])),'face_hypothesis':'up',
        'source':'released wrist RGB, known tabletop and previously verified upright face',
        'score_px':error}
