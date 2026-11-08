"""Multi-color RGB/geometry baseline. No simulator scene or object-pose API."""
import time
import numpy as np
from scipy.ndimage import label
from scipy.optimize import least_squares
from scipy.spatial.transform import Rotation
from wrist_vision import project,unproject,intrinsics,CONFIG

COLORS={'red':[.85,.05,.035],'blue':[.03,.15,.85],'green':[.05,.65,.18],
        'yellow':[.95,.82,.02],'orange':[.95,.28,.02],'purple':[.50,.03,.65]}
# Calibrated from actual Isaac LDR RGB color patches, not nominal linear USD
# material values. Orange/yellow in this tone mapper are only ~12 degrees apart.
HUES={'red':8.,'orange':45.,'yellow':58.,'green':154.,'blue':205.,'purple':296.}

def detect(rgb,camera_to_world,center_z_m=.0048,free_height=False,held_color=None):
    pixel_scale=320/rgb.shape[1];area_scale=1/(pixel_scale*pixel_scale)
    image=rgb.astype(float)/255.;hi=image.max(2);lo=image.min(2);delta=hi-lo
    saturation=delta/np.maximum(hi,1e-6);hue=np.zeros_like(hi);r,g,b=np.moveaxis(image,2,0)
    index=image.argmax(2);valid=delta>1e-6
    for channel,formula in [(0,(g-b)/np.maximum(delta,1e-6)%6),
                            (1,(b-r)/np.maximum(delta,1e-6)+2),
                            (2,(r-g)/np.maximum(delta,1e-6)+4)]:
        take=(index==channel)&valid;hue[take]=formula[take]*60
    names=list(HUES);centers=np.array([HUES[n] for n in names])
    # A piece already identified on the table can shift hue under the gripper.
    # Only the held-object view uses this calibrated shadow prototype; inventory
    # classification of ungrasped pieces retains all ordinary prototypes.
    if held_color=='orange':centers[names.index('orange')]=28.
    distance=abs(hue[:,:,None]-centers);distance=np.minimum(distance,360-distance)
    winner=distance.argmin(2);minimum=distance.min(2)
    detections=[]
    corners=np.array([[x,y,z] for x in [-.0159,.0159] for y in [-.0079,.0079] for z in [-.0048,.0048]])
    for color_id,color in enumerate(names):
        # Blue shifts toward violet in the gripper's shadow in Isaac LDR.
        # Nearest-prototype classification still separates it from purple.
        hue_tolerance=38 if color=='blue' else 22
        mask=(winner==color_id)&(minimum<hue_tolerance)&(saturation>.38)&(hi>.2)
        components,count=label(mask)
        for component in range(1,count+1):
            yy,xx=np.where(components==component)
            if len(xx)<24*area_scale or len(xx)>6000*area_scale:continue
            if xx.min()<5 or yy.min()<5 or xx.max()>rgb.shape[1]-6 or yy.max()>rgb.shape[0]-6:continue
            uv=np.array([xx.mean(),yy.mean()])
            try:initial=unproject(uv,camera_to_world)
            except ValueError:continue
            if center_z_m!=.0048:
                top=initial.copy();top[2]=.0096
                ray=top-camera_to_world[:3,3]
                initial=camera_to_world[:3,3]+ray*((center_z_m+.0048-camera_to_world[2,3])/ray[2])
                initial[2]=center_z_m
            if not (.08<initial[0]<.42 and -.33<initial[1]<.33):continue
            axis=np.linalg.eigh(np.cov(np.vstack([xx,yy])))[1][:,-1]
            direction=camera_to_world[:3,0]*axis[0]-camera_to_world[:3,1]*axis[1]
            yaw=float((np.arctan2(direction[1],direction[0])+np.pi/2)%np.pi-np.pi/2)
            observed=np.array([xx.min()-.5,xx.max()+.5,yy.min()-.5,yy.max()+.5])
            def residual(values):
                center=np.array(values[:3]) if free_height else np.r_[values[:2],center_z_m]
                rotation=Rotation.from_euler('z',values[-1]).as_matrix()
                pixels=np.array([project(center+rotation@corner,camera_to_world)[0] for corner in corners])
                return np.r_[(np.array([pixels[:,0].min(),pixels[:,0].max(),pixels[:,1].min(),pixels[:,1].max()])-observed)*pixel_scale,
                             2*np.sin(values[-1]-yaw)]
            if free_height:
                fit=least_squares(residual,np.r_[initial[:2],center_z_m,yaw],bounds=([.05,-.4,.005,yaw-.4],[.45,.4,.22,yaw+.4]),max_nfev=60)
            else:
                fit=least_squares(residual,np.r_[initial[:2],yaw],bounds=([.05,-.4,yaw-.4],[.45,.4,yaw+.4]),max_nfev=45)
            error=float(np.linalg.norm(fit.fun))
            if error>4:continue
            center=fit.x[:3] if free_height else np.r_[fit.x[:2],center_z_m]
            # Area gate rejects a merged component or the large green goal marker.
            depth=project(center+[0,0,.0048],camera_to_world)[1]
            calibration=intrinsics()
            area_expected=(calibration[0,0]*.0318/depth)*(calibration[1,1]*.0158/depth)
            ratio=len(xx)/max(1.,area_expected)
            if not .55<ratio<1.75:continue
            confidence=float(max(0.,min(.99,.99-.025*error-.04*abs(np.log(ratio)))))
            detections.append({'catalog_id':'3001','studs_xy':[4,2],'color':color,
                'pose':{'position_m':center.tolist(),'yaw_deg':float(np.rad2deg(fit.x[-1]))},
                'confidence':confidence,'confidence_type':'heuristic_not_calibrated_probability',
                'xy_sigma_m':.002,'region':'loose','pixel_center':uv.tolist(),
                'pixel_bbox':[int(xx.min()),int(yy.min()),int(xx.max()),int(yy.max())],
                'geometry_fit_error_px':error,'geometry_fit_error_reference_width':320,'occluded':False})
    return detections

class Inventory:
    def __init__(self):self.tracks={};self.counter=0;self.frames=0
    def update(self,detections):
        self.frames+=1;now=time.time()
        for detection in detections:
            position=np.array(detection['pose']['position_m'])
            matches=[(np.linalg.norm(position-np.array(t['pose']['position_m'])),key)
                     for key,t in self.tracks.items() if t['color']==detection['color']]
            distance,key=min(matches) if matches else (1.,None)
            if distance>.025:
                key=f'visual_track_{self.counter:03}';self.counter+=1
            self.tracks[key]={**detection,'track_id':key,'last_seen_s':now,'observed_frame':self.frames}
    def observation(self):
        return {'source':'wrist_rgb','frame':'robot_base','calibration_id':'simulated_wrist_config_v1',
            'captured_at_s':time.time(),'views':self.frames,'pieces':list(self.tracks.values()),
            'fixture':{'registered':False,'confidence':0.,'registration_source':'proposed_fixture_not_registered',
                       'pose':{'position_m':[.23,.08,0.],'yaw_deg':0}},
            'limits':['HSV plus known-geometry baseline; not a trained multi-object detector',
                      'color prototypes calibrated to this Isaac tone mapper; real RGB needs new calibration',
                      'only 3001-shaped bricks on known table plane','multi-view tracks require reobservation before grasp',
                      'real camera calibration and real fixture registration not validated']}
