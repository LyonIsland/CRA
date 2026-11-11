"""Uncalibrated image-based grasp baseline. Input: single wrist RGB only.

Inspired by Yoshimi & Allen (ICRA 1994) active uncalibrated alignment.
Joint probes estimate image derivatives; no FK/IK, depth, encoders, scene pose,
inventory parser, or simulator import is used here.
"""
import cv2
import numpy as np
from collections import deque


def gray(rgb):
    if not isinstance(rgb,np.ndarray) or rgb.dtype!=np.uint8 or rgb.ndim!=3 or rgb.shape[2]!=3:
        raise ValueError('Single uint8 camera RGB required')
    return np.rint(rgb.astype(np.float32).mean(2)).astype(np.uint8)


def detect(rgb,near=None,exclusion=None):
    g=gray(rgb)
    edges=cv2.Canny(cv2.GaussianBlur(g,(3,3),0),20,45)
    edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    # Local grayscale contrast also recovers weak/open edges. Both polarities
    # are considered: brightness is not a part identity or a required color.
    radius=int(g.shape[1]/10)|1
    kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(radius,radius))
    for op in (cv2.MORPH_TOPHAT,cv2.MORPH_BLACKHAT):
        contrast=cv2.morphologyEx(g,op,kernel)
        binary=(contrast>12).astype(np.uint8)*255
        # Do not close this mask: a narrow contact edge can otherwise join the
        # brick to the robot's cast shadow and move its centre by tens of pixels.
        more,_=cv2.findContours(binary,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        contours=tuple(contours)+tuple(more)
    found=[]
    for contour in contours:
        area=cv2.contourArea(cv2.convexHull(contour))
        (u,v),(w,h),angle=cv2.minAreaRect(contour)
        if exclusion is not None and exclusion[int(np.clip(v,0,g.shape[0]-1)),int(np.clip(u,0,g.shape[1]-1))]:continue
        scale=g.shape[1]/320
        max_length=50*scale if near is None else min(115*scale,near[2]*1.6)
        if (near is None and max(w,h)<20*scale) or min(w,h)<5*scale or max(w,h)>max_length or area<55*scale*scale:continue
        if not 1.25<max(w,h)/min(w,h)<3.:continue
        if not 15<u<g.shape[1]-15 or not 15<v<g.shape[0]-15:continue
        x,y,bw,bh=cv2.boundingRect(contour)
        if x<2 or y<2 or x+bw>g.shape[1]-2 or y+bh>g.shape[0]-2:continue
        rectangularity=area/(w*h)
        if rectangularity<(.79 if near is None else .6):continue
        if w<h:angle+=90
        angle=(angle+90)%180-90
        feature=np.array([u,v,max(w,h),angle],dtype=float)
        score=np.linalg.norm(feature[:2]-near[:2]) if near is not None else abs(u-g.shape[1]*.5)+abs(v-g.shape[0]*.5)+100*scale*(1-rectangularity)
        found.append((score,feature))
    if not found:return None
    score,feature=min(found,key=lambda p:p[0])
    if near is not None and score>40*scale:return None
    return feature


class ObjectTracker:
    """Subpixel Lucas-Kanade tracking, refreshed using image contours only."""
    def __init__(self,exclusion=None):
        self.previous=None;self.points=None;self.feature=None;self.missing=0;self.lost=False;self.exclusion=exclusion

    def observe(self,rgb):
        if self.lost:return None
        previous_feature=self.feature
        g=gray(rgb);found=detect(rgb,self.feature,self.exclusion if self.previous is None else None);prediction=None
        if found is not None and self.feature is not None and np.linalg.norm(found[:2]-self.feature[:2])>8:
            found=None
        if self.points is not None and self.previous is not None and len(self.points)>=3:
            moved,ok,_=cv2.calcOpticalFlowPyrLK(self.previous,g,self.points,None,winSize=(21,21),maxLevel=3,
                criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.001))
            if moved is not None:
                backwards,back_ok,_=cv2.calcOpticalFlowPyrLK(g,self.previous,moved,None,winSize=(21,21),maxLevel=3)
                valid=ok.ravel().astype(bool)&back_ok.ravel().astype(bool)&(np.linalg.norm(backwards-self.points,axis=2).ravel()<.5)
                if valid.sum()>=3:
                    transform,inliers=cv2.estimateAffinePartial2D(self.points[valid],moved[valid],method=cv2.RANSAC,ransacReprojThreshold=1.)
                    if transform is not None:
                        scale=float(np.linalg.norm(transform[0,:2]))
                        if .97<scale<1.03 and inliers.mean()>.65:
                            prediction=self.feature.copy()
                            prediction[:2]=transform@np.r_[prediction[:2],1.]
                            prediction[2]*=scale
                            prediction[3]=(prediction[3]+np.degrees(np.arctan2(transform[1,0],transform[0,0]))+90)%180-90
                            if np.linalg.norm(prediction[:2]-self.feature[:2])>8:prediction=None
        if prediction is not None:
            if found is not None and np.linalg.norm(found[:2]-prediction[:2])<8:
                prediction[:2]=.5*prediction[:2]+.5*found[:2]
                prediction[2:]=found[2:]
            self.feature=prediction
        elif found is not None:self.feature=found
        else:self.feature=None
        # A contour can disappear in the gripper's cast shadow while consistent
        # forward/backward optical flow still tracks the same physical corners.
        self.missing=self.missing+1 if self.feature is None else 0
        if self.missing>5 or (self.feature is None and previous_feature is not None):
            self.feature=None;self.lost=True
        self.previous=g
        if self.feature is not None:
            mask=np.zeros_like(g)
            u,v,length,angle=self.feature
            box=cv2.boxPoints(((float(u),float(v)),(float(length+8),float(length*.65+8)),float(angle)))
            cv2.fillConvexPoly(mask,np.rint(box).astype(np.int32),255)
            self.points=cv2.goodFeaturesToTrack(g,30,.01,3,mask=mask,blockSize=3)
        else:self.points=None
        return self.feature


class VisualGrasp:
    # Command synergies; these are own joint commands, not Cartesian targets.
    # At the fixed observation posture, coordinated wrist commands reduce image
    # rotation while shoulder/elbow probes translate the camera.
    basis=np.array([[1,0,0],[0,1,0],[0,0,1],[0,0,0],[0,-1,-1],[1,0,0],[0,0,0]],float)

    def __init__(self):
        self.phase='calibrate_tool';self.done=False;self.diagnostic={}
        self.last=None;self.generator=self.sequence();self.request=None
        self.latest=None;self.feature=None;self.history=[]
        self.approach=[]
        self.misses=0
        self.servo_diagnostic={}
        self.tracker=ObjectTracker()
        self.feature_window=deque(maxlen=5)

    def __call__(self,rgb):
        self.latest=rgb.copy()
        self.feature=self.tracker.observe(rgb)
        if self.feature is not None:self.last=self.feature;self.misses=0
        else:
            self.misses+=1
            if self.misses<=2:self.feature=self.last
        if self.feature is not None:self.feature_window.append(self.feature.copy())
        if self.feature is None and self.misses>2 and self.phase in ('visual_servo','align_angle','clear_view'):
            raise RuntimeError('Visual target tracking lost; reacquisition requires a new attempt')
        self.diagnostic={**self.servo_diagnostic,'target_pixels':self.feature.tolist() if self.feature is not None else None}
        try:return np.asarray(next(self.generator),dtype=float)
        except StopIteration:self.done=True;return np.zeros(7)

    def move(self,delta):
        delta=np.asarray(delta,float)
        count=max(1,int(np.ceil(np.max(np.abs(delta)))))
        for _ in range(count):yield delta/count
        # Settle command dynamics, observing at every step.
        for _ in range(12):yield np.zeros(7)

    def measurement(self):
        if self.feature is None:raise RuntimeError('Target lost; stop instead of using scene truth')
        centre=self.feature.copy()
        yield from self.move([0,0,0,0,0,15,0])
        if self.feature is None:raise RuntimeError('Target lost during visual rotation probe')
        plus=np.median(np.stack(self.feature_window),axis=0)
        yield from self.move([0,0,0,0,0,-30,0])
        if self.feature is None:raise RuntimeError('Target lost during visual rotation probe')
        minus=np.median(np.stack(self.feature_window),axis=0)
        yield from self.move([0,0,0,0,0,15,0])
        if self.feature is None:raise RuntimeError('Target lost after probe')
        # Rotation derivative is observed in images, not computed from camera
        # extrinsics. Vanishing motion aligns the target with the wrist axis.
        settled=np.median(np.stack(self.feature_window),axis=0)
        return np.array([settled[0],settled[1],(plus[1]-minus[1])/.30])

    def sequence(self):
        # Empty close/open detects tool contact-point pixels from visible pads.
        open_gray=gray(self.latest)
        yield from self.move([0,0,0,0,0,0,-25])
        g=gray(self.latest)
        # Visible dark gripper tips, bounded by the image left half. Hardware
        # appearance prior only; no target position or camera geometry supplied.
        mask=((g<60)&(cv2.absdiff(g,open_gray)>15)).astype(np.uint8)
        mask[:,g.shape[1]//2:]=0
        mask[:g.shape[0]//3]=0;mask[2*g.shape[0]//3:]=0
        ys,xs=np.where(mask)
        if len(xs)<5:raise RuntimeError('Cannot visually locate gripper contact point')
        right=xs.max();tip_y=float(np.median(ys[xs>=right-3]))
        self.goal=np.array([float(right-.032*g.shape[1]),tip_y,0.])
        exclusion=cv2.dilate((cv2.absdiff(g,open_gray)>15).astype(np.uint8),np.ones((5,5),np.uint8))
        yield from self.move([0,0,0,0,0,0,25])
        self.tracker=ObjectTracker()
        self.feature=self.tracker.observe(self.latest)
        self.feature_window.clear()
        if self.feature is not None:self.feature_window.append(self.feature.copy())
        if self.feature is None:raise RuntimeError('No isolated visible rectangular brick')
        # A target between the open fingers will disappear during wrist rotation.
        # Move it into free image space using an observed 2D Jacobian first.
        if self.feature[0]<right+20:
            self.phase='clear_view'
            view_goal=np.array([right+65.,tip_y+75.])
            for view_iteration in range(12):
                centre=self.feature[:2].copy()
                error=view_goal-centre
                if np.linalg.norm(error)<8:break
                columns=[]
                for axis in range(3):
                    delta=self.basis[:,axis]*2
                    yield from self.move(delta)
                    columns.append((self.feature[:2]-centre)/2)
                    yield from self.move(-delta)
                    centre=self.feature[:2].copy()
                jac=np.array(columns).T
                change=jac.T@np.linalg.solve(jac@jac.T+.2*np.eye(2),error)
                change*=min(1,4/max(1e-6,float(np.abs(change).max())))
                delta=self.basis@change
                self.approach.append(delta.copy())
                yield from self.move(delta)
            else:raise RuntimeError('Could not move target to an unobstructed view')
        self.phase='align_angle' 
        # Determine sign from actual image changes instead of assuming mapping.
        angle=self.feature[3]
        yield from self.move([0,0,0,0,0,5,0])
        derivative=((self.feature[3]-angle+90)%180-90)/5
        if abs(derivative)<.05:raise RuntimeError('Insufficient visual rotation signal')
        turn=np.clip(-self.feature[3]/derivative,-100,100)
        yield from self.move([0,0,0,0,0,turn,0])
        self.phase='visual_servo'
        jac=None;previous=None;previous_change=None
        for iteration in range(24):
            features=yield from self.measurement()
            error=self.goal-features
            self.servo_diagnostic.update(goal_pixels=self.goal.tolist(),servo_error=error.tolist(),iteration=iteration)
            self.history.append({'features':features.tolist(),'goal':self.goal.tolist()})
            if np.linalg.norm(error[:2])<2 and abs(error[2])<4:break
            if jac is not None and previous is not None:
                observed=features-previous
                residual=observed-jac@previous_change
                jac+=.6*np.outer(residual,previous_change)/(previous_change@previous_change+1e-5)
            if jac is None or iteration%4==0:
                columns=[]
                for axis in range(3):
                    delta=self.basis[:,axis]*5
                    yield from self.move(delta)
                    perturbed=yield from self.measurement()
                    columns.append((perturbed-features)/5)
                    yield from self.move(-delta)
                jac=np.array(columns).T
            self.history[-1]['jacobian']=jac.tolist()
            change=jac.T@np.linalg.solve(jac@jac.T+.2*np.eye(3),error)
            max_change=8
            change*=min(1,max_change/max(1e-6,float(np.abs(change).max())))
            delta=self.basis@change*.7
            self.history[-1]['command']=delta.tolist()
            self.approach.append(delta.copy())
            previous=features.copy();previous_change=change*.7
            yield from self.move(delta)
        else:
            raise RuntimeError('Visual alignment did not converge; no blind close')
        self.phase='close'
        yield from self.move([0,0,0,0,0,0,-25])
        self.phase='lift'
        for delta in reversed(self.approach):yield from self.move(-delta)
        self.phase='hold'
        for _ in range(120):yield np.zeros(7)
        self.phase='finished_unverified'
