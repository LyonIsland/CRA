"""General stud-grid latch surrogate, NOT validated LEGO interference physics.

This environment component knows grid geometry and physical body state, not the
instruction or loose-source layout. It never moves a body into position. A latch
is authored at the actually achieved pose after contact and registration checks.
"""
import numpy as np
from scipy.spatial.transform import Rotation

FIXTURE_ORIGIN=np.array([.23,.08,.002])
FIXTURE_PATH='/World/AssemblyFixture'
PITCH=.008;HEIGHT=.0096

class ConceptConnectors:
    def __init__(self,stage,parts,fixture):
        self.stage=stage;self.parts=parts;self.fixture=fixture;self.latched={};self.events=[]
        self.broken=[];self._event_subscription=None
        if stage is not None:
            from omni.physx import get_physx_interface
            self._event_subscription=get_physx_interface().get_simulation_event_stream_v2().create_subscription_to_pop(self._on_event)
    def _on_event(self,event):
        from omni.physx.bindings._physx import SimulationEvent
        if event.type!=int(SimulationEvent.JOINT_BREAK):return
        from pxr import PhysicsSchemaTools
        path=str(PhysicsSchemaTools.decodeSdfPath(*event.payload['jointPath']))
        if path.startswith('/World/AssemblyConnections/') or path=='/World/AssemblyFixtureAnchor':
            self.broken.append(path)
    def reset(self):
        self.stage.RemovePrim('/World/AssemblyConnections');self.latched={};self.events=[];self.broken=[]
    def try_engage(self,color,support_contact,stable_steps):
        if color in self.latched:return self.latched[color]
        if not support_contact or stable_steps<8:return None
        part=self.parts[color];position,quat=part.get_world_pose()
        rotation=Rotation.from_quat(np.r_[quat[1:],quat[0]])
        if np.linalg.norm(rotation.as_matrix()[:,2]-[0,0,1])>.10:return None
        yaw=rotation.as_euler('xyz')[2];quarter=int(round(yaw/(np.pi/2)))
        yaw_error=abs(float(np.arctan2(np.sin(yaw-quarter*np.pi/2),np.cos(yaw-quarter*np.pi/2))))
        if yaw_error>np.deg2rad(6):return None
        nx,ny=(4,2) if quarter%2==0 else (2,4)
        relative=position-FIXTURE_ORIGIN
        anchor_float=relative[:2]/PITCH-np.array([(nx-1)/2,(ny-1)/2])
        anchor=np.rint(anchor_float).astype(int)
        layer=int(round((relative[2]-.0048)/HEIGHT))
        ideal=FIXTURE_ORIGIN+np.r_[(anchor+[(nx-1)/2,(ny-1)/2])*PITCH,layer*HEIGHT+.0048]
        if layer<0 or np.linalg.norm(position[:2]-ideal[:2])>.003 or abs(position[2]-ideal[2])>.0025:return None
        if np.linalg.norm(part.get_linear_velocity())>.025:return None
        cells={(int(anchor[0]+i),int(anchor[1]+j)) for i in range(nx) for j in range(ny)}
        parents={}
        if layer==0:
            if any(x<0 or y<0 or x>=16 or y>=16 for x,y in cells):return None
            parents['fixture']=len(cells)
        else:
            for parent,record in self.latched.items():
                if record['layer']==layer-1:
                    overlap=cells&{tuple(c) for c in record['cells']}
                    if overlap:parents[parent]=len(overlap)
            if sum(parents.values())!=len(cells):return None
        from pxr import UsdPhysics,Gf,Sdf
        paths=[]
        for parent in parents:
            body0=self.fixture if parent=='fixture' else self.parts[parent]
            p0,q0=body0.get_world_pose();r0=Rotation.from_quat(np.r_[q0[1:],q0[0]])
            local_position=r0.inv().apply(position-p0);local_rotation=(r0.inv()*rotation).as_quat()
            path=f'/World/AssemblyConnections/{color}_to_{parent}'
            joint=UsdPhysics.FixedJoint.Define(self.stage,path)
            joint.CreateBody0Rel().SetTargets([Sdf.Path(body0.prim_path)])
            joint.CreateBody1Rel().SetTargets([Sdf.Path(part.prim_path)])
            joint.CreateLocalPos0Attr(Gf.Vec3f(*map(float,local_position)))
            joint.CreateLocalRot0Attr(Gf.Quatf(float(local_rotation[3]),Gf.Vec3f(*map(float,local_rotation[:3]))))
            joint.CreateLocalPos1Attr(Gf.Vec3f(0,0,0));joint.CreateLocalRot1Attr(Gf.Quatf(1.,Gf.Vec3f(0,0,0)))
            joint.CreateBreakForceAttr(20.);joint.CreateBreakTorqueAttr(.2)
            paths.append(path)
        record={'color':color,'anchor_stud':[int(anchor[0]),int(anchor[1]),layer],'layer':layer,
                'cells':[list(c) for c in sorted(cells)],'support_colors':parents,'joint_paths':paths,
                'engaged_position_m':position.tolist(),'engaged_yaw_deg':float(np.rad2deg(yaw)),
                'alignment_error_m':float(np.linalg.norm(position-ideal)),
                'model':'stud-grid fixed-joint surrogate; no teleport; unvalidated physical snap-fit'}
        self.latched[color]=record;self.events.append(record);return record

def add_fixture(world,stage,cube,parts):
    from pxr import UsdPhysics,Usd,UsdGeom,Gf,PhysxSchema
    from isaacsim.core.prims import SingleRigidPrim
    root=UsdGeom.Xform.Define(stage,FIXTURE_PATH);root.AddTranslateOp().Set(Gf.Vec3d(.29,.14,.001))
    cube(FIXTURE_PATH+'/Body',[0,0,0],[.128,.128,.002],[.36,.4,.44])
    body=UsdPhysics.RigidBodyAPI.Apply(root.GetPrim())
    UsdPhysics.MassAPI.Apply(root.GetPrim()).CreateMassAttr(.1)
    anchor=UsdPhysics.FixedJoint.Define(stage,'/World/AssemblyFixtureAnchor')
    anchor.CreateBody1Rel().SetTargets([root.GetPath()])
    anchor.CreateLocalPos0Attr(Gf.Vec3f(.29,.14,.001));anchor.CreateLocalPos1Attr(Gf.Vec3f(0,0,0))
    fixture=world.scene.add(SingleRigidPrim(prim_path=FIXTURE_PATH,name='assembly_fixture'))
    # Studs are visible but non-colliding in this explicitly approximate mode.
    for part in parts.values():
        # Explicit concept collision surrogate: 1.5 mm clearance at each long
        # end accommodates the concept registration tolerance. Visual geometry stays
        # nominal. Y gripping surfaces and Z support height remain unchanged.
        body=stage.GetPrimAtPath(part.prim_path+'/Body')
        scale=next(op.Get() for op in UsdGeom.Xformable(body).GetOrderedXformOps() if op.GetOpType()==UsdGeom.XformOp.TypeScale)
        UsdPhysics.CollisionAPI(body).CreateCollisionEnabledAttr(False)
        proxy=cube(part.prim_path+'/ConceptContactBody',[0,0,0],
            [float(scale[0])-.003,float(scale[1]),float(scale[2])],[.5,.5,.5])
        UsdGeom.Imageable(proxy.GetPrim()).MakeInvisible()
        for prim in [proxy.GetPrim()]:
            contact=PhysxSchema.PhysxCollisionAPI.Apply(prim)
            contact.CreateContactOffsetAttr(.0004);contact.CreateRestOffsetAttr(0.)
        for prim in Usd.PrimRange(stage.GetPrimAtPath(part.prim_path)):
            if '/Stud_' in str(prim.GetPath()) and prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI(prim).CreateCollisionEnabledAttr(False)
    return fixture
