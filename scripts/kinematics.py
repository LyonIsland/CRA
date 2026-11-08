"""Piper FK/IK from the pinned URDF; no secondary physics engine."""
from pathlib import Path
import xml.etree.ElementTree as ET
import numpy as np
from scipy.spatial.transform import Rotation
from scipy.optimize import least_squares

class PiperKinematics:
    def __init__(self,urdf):
        root=ET.parse(urdf).getroot()
        self.joints=[root.find(f'joint[@name="joint{i}"]') for i in range(1,7)]
        self.origins=[]; self.axes=[]; self.bounds=[]
        for j in self.joints:
            origin=j.find('origin'); transform=np.eye(4)
            transform[:3,:3]=Rotation.from_euler('xyz',np.fromstring(origin.get('rpy'),sep=' ')).as_matrix()
            transform[:3,3]=np.fromstring(origin.get('xyz'),sep=' ')
            self.origins.append(transform)
            self.axes.append(np.fromstring(j.find('axis').get('xyz'),sep=' '))
            limit=j.find('limit'); self.bounds.append([float(limit.get('lower')),float(limit.get('upper'))])
        self.bounds=np.array(self.bounds)
        self.desired_rotation=np.diag([-1.,1.,-1.])

    def forward(self,q):
        pose=np.eye(4)
        for angle,origin,axis in zip(q,self.origins,self.axes):
            rotation=np.eye(4); rotation[:3,:3]=Rotation.from_rotvec(axis*angle).as_matrix()
            pose=pose@origin@rotation
        tcp=pose[:3,3]+pose[:3,:3]@np.array([0,0,.1308])
        return tcp,pose[:3,:3]

    def solve(self,target,q0):
        def residual(q):
            pos,rot=self.forward(q)
            return np.r_[pos-target,.12*Rotation.from_matrix(self.desired_rotation@rot.T).as_rotvec()]
        result=least_squares(residual,np.clip(q0,self.bounds[:,0]+1e-7,self.bounds[:,1]-1e-7),
                             bounds=(self.bounds[:,0],self.bounds[:,1]),max_nfev=35,
                             ftol=1e-7,xtol=1e-7,gtol=1e-7)
        return result.x,float(np.linalg.norm(residual(result.x)[:3]))
