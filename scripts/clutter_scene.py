"""Reset-only physical heap generation and independent scene auditing.

No heap layout or body pose is exported to the robot observation interface.
The old assembly connection surrogate is not used to hold loose heap pieces.
"""
import numpy as np
from scipy.spatial.transform import Rotation

HEAP_CENTER=np.array([.275,-.125])
HEAP_BOUNDS=np.array([[.19,-.23],[.37,-.025]])
BUFFER_POINTS=np.array([[.19,.0],[.36,.0],[.19,-.25],[.245,-.25],[.30,-.25],[.36,-.10]])

def add_hollow_geometry(stage,cube,parts):
    """Compound rigid-shell approximation, not plastic interference validation."""
    from pxr import UsdGeom,UsdPhysics,PhysxSchema,Gf
    from assembly_perception import COLORS
    for color,part in parts.items():
        root=part.prim_path;body=stage.GetPrimAtPath(root+'/Body')
        scale=next(op.Get() for op in UsdGeom.Xformable(body).GetOrderedXformOps()
                   if op.GetOpType()==UsdGeom.XformOp.TypeScale)
        length,width=float(scale[0]),float(scale[1]);rgb=COLORS.get(color,[.02,.75,.8] if color.startswith('cyan') else [.025]*3)
        UsdGeom.Imageable(body).MakeInvisible()
        UsdPhysics.CollisionAPI(body).CreateCollisionEnabledAttr(False)
        proxy=stage.GetPrimAtPath(root+'/ConceptContactBody')
        if proxy.IsValid():UsdPhysics.CollisionAPI(proxy).CreateCollisionEnabledAttr(False)
        t=.0012
        cube(root+'/Shell/Roof',[0,0,.0048-t/2],[length,width,t],rgb)
        for sign in [-1,1]:
            suffix='negative' if sign<0 else 'positive'
            cube(root+f'/Shell/End_{suffix}',[sign*(length-t)/2,0,-t/2],[t,width,.0096-t],rgb)
            cube(root+f'/Shell/Side_{suffix}',[0,sign*(width-t)/2,-t/2],[length-2*t,t,.0096-t],rgb)
        # Polygonal annular underside tubes retain an open bore (not a solid cylinder).
        for index,x in enumerate(np.arange(-length/2+.008,length/2-.003,.008)):
            for segment in range(12):
                a=(segment+.5)*2*np.pi/12
                ring=cube(root+f'/Shell/Tube_{index}_{segment}',
                    [float(x+.0027*np.cos(a)),float(.0027*np.sin(a)),-.0006],
                    [.001,2*.0027*np.tan(np.pi/12),.0084],rgb)
                ring.AddRotateZOp().Set(float(np.rad2deg(a)))
        for prim in stage.Traverse():
            if not str(prim.GetPath()).startswith(root+'/'):continue
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                if '/Stud_' in str(prim.GetPath()):UsdPhysics.CollisionAPI(prim).CreateCollisionEnabledAttr(True)
                contact=PhysxSchema.PhysxCollisionAPI.Apply(prim)
                contact.CreateContactOffsetAttr(.00015);contact.CreateRestOffsetAttr(0.)

def drop_heap(session,rng):
    """Release a dense sequence of random stable-face/tilted parts under gravity."""
    parts=session.parts;task=session.task
    # During reset only, park all objects off the drop volume before releasing them.
    for index,part in enumerate(parts.values()):
        part.set_world_pose(position=np.array([.55,.30,.03+index*.025]),orientation=np.array([1.,0,0,0]))
        part.set_linear_velocity(np.zeros(3));part.set_angular_velocity(np.zeros(3))
    colors=list(parts);rng.shuffle(colors)
    # At least one required brick begins upside down and one sideways; final
    # categories are measured after settling rather than assumed from sampling.
    faces={'red':'down','blue':'side'}
    for index,color in enumerate(colors):
        xy=HEAP_CENTER+rng.normal(0,.017,2)
        xy=np.clip(xy,HEAP_BOUNDS[0]+.022,HEAP_BOUNDS[1]-.022)
        face=faces.get(color,str(rng.choice(['up','down','side'],p=[.5,.3,.2])))
        roll={'up':0.,'down':180.,'side':90.}[face]
        rotation=Rotation.from_euler('z',rng.uniform(-180,180),degrees=True)*Rotation.from_euler('x',roll,degrees=True)
        quat=rotation.as_quat();part=parts[color]
        part.set_world_pose(position=np.r_[xy,.09],orientation=np.r_[quat[3],quat[:3]])
        part.set_linear_velocity(np.r_[rng.uniform(-.025,.025,2),-.04])
        part.set_angular_velocity(rng.uniform(-.12,.12,3))
        for _ in range(24):task.advance(task.q,.025)
    for _ in range(100):task.advance(task.q,.025)

def audit_heap(parts):
    """Privileged evaluation only; never input to grasp/pose perception."""
    records={};half=np.array([.0159,.0079,.0048])
    corners=np.array([[x,y,z] for x in [-1,1] for y in [-1,1] for z in [-1,1]])*half
    for color,part in parts.items():
        p,q=part.get_world_pose();r=Rotation.from_quat(np.r_[q[1:],q[0]]).as_matrix()
        local=corners.copy()
        if color=='cyan_distractor':local[:,0]*=.0079/.0159
        world=local@r.T+p;up=float(r[2,2])
        records[color]={'position_m':p.tolist(),'quaternion_wxyz':q.tolist(),
            'normal_world':r[:,2].tolist(),'face':'up' if up>.85 else ('down' if up<-.85 else 'side_or_tilted'),
            'aabb_min_m':world.min(0).tolist(),'aabb_max_m':world.max(0).tolist(),
            'speed_m_s':float(np.linalg.norm(part.get_linear_velocity()))}
    overlaps=[]
    for i,a in enumerate(records):
        for b in list(records)[i+1:]:
            aa,bb=records[a],records[b]
            overlap=np.minimum(aa['aabb_max_m'][:2],bb['aabb_max_m'][:2])-np.maximum(aa['aabb_min_m'][:2],bb['aabb_min_m'][:2])
            if np.all(overlap>.001):overlaps.append([a,b])
    return {'parts':records,'part_count':len(records),
        'up_count':sum(x['face']=='up' for x in records.values()),
        'down_count':sum(x['face']=='down' for x in records.values()),
        'side_or_tilted_count':sum(x['face']=='side_or_tilted' for x in records.values()),
        'elevated_piece_count':sum(x['aabb_min_m'][2]>.0025 for x in records.values()),
        'overlapping_xy_aabb_pairs':overlaps,
        'maximum_top_height_m':max(x['aabb_max_m'][2] for x in records.values()),
        'source':'independent physics evaluation; not robot observation',
        'snapfit_validated':False}

def activate_assembly_surrogate(stage,parts,colors):
    """Explicit handoff to the existing conceptual assembly collision model.

    Heap extraction/turning use hollow shells and stud contacts. Assembly uses
    the already-labelled flat-support approximation; no body transform changes.
    """
    from pxr import Usd,UsdPhysics
    for color in colors:
        root=parts[color].prim_path
        for prim in Usd.PrimRange(stage.GetPrimAtPath(root)):
            path=str(prim.GetPath())
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                UsdPhysics.CollisionAPI(prim).CreateCollisionEnabledAttr(path.endswith('/ConceptContactBody'))

def restore_heap_collision_model(stage,parts):
    """Reset-only inverse of the explicitly labelled assembly handoff."""
    from pxr import Usd,UsdPhysics
    for part in parts.values():
        for prim in Usd.PrimRange(stage.GetPrimAtPath(part.prim_path)):
            if prim.HasAPI(UsdPhysics.CollisionAPI):
                path=str(prim.GetPath())
                UsdPhysics.CollisionAPI(prim).CreateCollisionEnabledAttr('/Shell/' in path or '/Stud_' in path)
