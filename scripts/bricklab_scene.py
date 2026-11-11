"""Instantiate nominal BRICKLAB inventory in the local PhysX workcell.

Only environment setup calls this module. No assembly targets are loaded.
"""
import numpy as np
from bricklab_task import load_scene


def add_parts(world, stage, cube, first, task_path, seed):
    from pxr import Gf, UsdGeom, UsdPhysics, UsdShade
    from isaacsim.core.prims import SingleRigidPrim
    inventory = load_scene(task_path)
    rng=np.random.default_rng(seed)
    descriptions=[inventory['parts'][i] for i in rng.permutation(len(inventory['parts']))]
    material=UsdShade.Material.Define(stage,'/World/TrainingMaterial')
    physics=UsdPhysics.MaterialAPI.Apply(material.GetPrim())
    physics.CreateStaticFrictionAttr(1.)
    physics.CreateDynamicFrictionAttr(.8)
    physics.CreateRestitutionAttr(0.)
    shade=float(rng.uniform(.35,.8))
    parts={}
    for index,description in enumerate(descriptions):
        path='/World/Brick' if index==0 else f'/World/TrainingParts/Part_{index:03d}'
        if index==0:
            for child in list(stage.GetPrimAtPath(path).GetChildren()):stage.RemovePrim(child.GetPath())
            part=first
        else:
            body=UsdGeom.Xform.Define(stage,path)
            body.AddTranslateOp().Set(Gf.Vec3d(0,0,.1))
            UsdPhysics.RigidBodyAPI.Apply(body.GetPrim())
            part=world.scene.add(SingleRigidPrim(prim_path=path,name=f'training_part_{index}'))
        UsdPhysics.MassAPI.Apply(stage.GetPrimAtPath(path)).CreateMassAttr(float(description['nominal_mass_kg']))
        for number,item in enumerate(description['shapes']):
            shape_path=f'{path}/Shape_{number:03d}'
            if item['kind']=='box':
                shape=cube(shape_path,item['center_m'],item['size_m'],[shade]*3)
            elif item['kind']=='cylinder':
                shape=UsdGeom.Cylinder.Define(stage,shape_path)
                shape.CreateAxisAttr('Z')
                shape.CreateRadiusAttr(item['radius_m'])
                shape.CreateHeightAttr(item['height_m'])
                shape.AddTranslateOp().Set(Gf.Vec3d(*item['center_m']))
            elif item['kind']=='prism':
                polygon=item['polygon_m']
                if len(polygon)!=4:raise ValueError('Expected reviewed convex quadrilateral shell segment')
                shape=UsdGeom.Mesh.Define(stage,shape_path)
                shape.CreatePointsAttr([Gf.Vec3f(x,y,z) for z in [item['z_min_m'],item['z_max_m']] for x,y in polygon])
                shape.CreateFaceVertexCountsAttr([4]*6)
                shape.CreateFaceVertexIndicesAttr([3,2,1,0,4,5,6,7,0,1,5,4,1,2,6,5,2,3,7,6,3,0,4,7])
                shape.CreateSubdivisionSchemeAttr('none')
                UsdPhysics.MeshCollisionAPI.Apply(shape.GetPrim()).CreateApproximationAttr('convexHull')
            else:raise ValueError('Unsupported geometry; no bounding-box substitutions')
            shape.CreateDisplayColorAttr([Gf.Vec3f(shade,shade,shade)])
            UsdPhysics.CollisionAPI.Apply(shape.GetPrim())
            UsdShade.MaterialBindingAPI.Apply(shape.GetPrim()).Bind(material,materialPurpose='physics')
        parts[f'part_{index}']=part
    UsdGeom.Imageable(stage.GetPrimAtPath('/World/Goal')).MakeInvisible()
    if inventory['baseplate_studs'] is not None:
        # Fixed workcell fixture. Its pose is not returned to the controller.
        nx,ny=inventory['baseplate_studs']
        if [nx,ny]!=[20,20]:raise ValueError('Only the reviewed BRICKLAB 20x20 board is supported')
        centre=[.28,.10]
        cube('/World/TrainingBaseplate/Body',[*centre,.0016],[nx*.008,ny*.008,.0032],[.45]*3)
        for i in range(nx):
            for j in range(ny):
                stud=UsdGeom.Cylinder.Define(stage,f'/World/TrainingBaseplate/Stud_{i}_{j}')
                stud.CreateAxisAttr('Z');stud.CreateRadiusAttr(.0024);stud.CreateHeightAttr(.0016)
                stud.AddTranslateOp().Set(Gf.Vec3d(centre[0]+(i-(nx-1)/2)*.008,centre[1]+(j-(ny-1)/2)*.008,.004))
                stud.CreateDisplayColorAttr([Gf.Vec3f(.45,.45,.45)])
                UsdPhysics.CollisionAPI.Apply(stud.GetPrim())
    return parts
