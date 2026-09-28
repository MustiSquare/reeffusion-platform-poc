import numpy as np
import trimesh
from app.processing.mesh import _grid_faces
from app.services.tile_seams import join_tile_edges


def surface(x0,x1,y0,y1,step=1):
    x,y=np.meshgrid(np.linspace(x0,x1,int(round((x1-x0)/step))+1),np.linspace(y0,y1,int(round((y1-y0)/step))+1))
    z=-10+.3*np.sin(x)*np.cos(y)
    return trimesh.Trimesh(vertices=np.column_stack([x.ravel(),y.ravel(),z.ravel()]),faces=_grid_faces(*x.shape),process=False)


def assert_original_untouched(original,result):
    np.testing.assert_array_equal(result.vertices[:len(original.vertices)],original.vertices)
    np.testing.assert_array_equal(result.faces[:len(original.faces)],original.faces)


def test_high_resolution_meshes_remain_exact_and_only_seam_faces_are_added():
    a,b=surface(0,9.7,0,10,.25),surface(10.2,20,0,10,.3)
    original=trimesh.util.concatenate([a,b])
    mesh,added=join_tile_edges([a,b],[(0,0,10),(10,0,10)],[a.vertices.tolist(),b.vertices.tolist()])
    assert_original_untouched(original,mesh)
    assert added>0
    triangles=mesh.triangles[len(original.faces):]
    assert triangles[:,:,0].min()>=9.7-1e-6
    assert triangles[:,:,0].max()<=10.2+1e-6
    # The connecting strip spans the full join, at the original edge heights.
    u,v=triangles[:,1,:2]-triangles[:,0,:2],triangles[:,2,:2]-triangles[:,0,:2]
    area=np.abs(u[:,0]*v[:,1]-u[:,1]*v[:,0]).sum()/2
    assert abs(area-5)<1e-6


def test_wide_gap_and_unsupported_seam_are_not_filled():
    a,b=surface(0,7,0,10),surface(13,20,0,10)
    mesh,added=join_tile_edges([a,b],[(0,0,10),(10,0,10)],[a.vertices.tolist(),b.vertices.tolist()])
    assert added==0
    a,b=surface(0,9.7,0,10),surface(10.2,20,0,10)
    mesh,added=join_tile_edges([a,b],[(0,0,10),(10,0,10)],[[],[]])
    assert added==0


def test_four_tile_corner_is_closed_without_changing_source_triangles():
    meshes=[surface(0,9.7,0,9.4),surface(10.4,20,0,9.8),surface(10.5,20,10.2,20),surface(0,9.6,10.3,20)]
    tiles=[(0,0,10),(10,0,10),(10,10,10),(0,10,10)]
    original=trimesh.util.concatenate(meshes)
    mesh,added=join_tile_edges(meshes,tiles,[m.vertices.tolist() for m in meshes])
    assert_original_untouched(original,mesh)
    triangles=mesh.triangles
    u,v=triangles[:,1,:2]-triangles[:,0,:2],triangles[:,2,:2]-triangles[:,0,:2]
    area=np.abs(u[:,0]*v[:,1]-u[:,1]*v[:,0]).sum()/2
    assert abs(area-400)<1e-6
    assert added>0


def test_gap_along_sonar_pass_is_preserved_at_tile_join():
    a=trimesh.util.concatenate([surface(0,9.7,0,3),surface(0,9.7,7,10)])
    b=trimesh.util.concatenate([surface(10.2,20,0,3),surface(10.2,20,7,10)])
    original=trimesh.util.concatenate([a,b])
    mesh,added=join_tile_edges([a,b],[(0,0,10),(10,0,10)],[a.vertices.tolist(),b.vertices.tolist()])
    assert added>0
    centers=mesh.triangles_center[len(original.faces):]
    assert not np.any((centers[:,1]>3)&(centers[:,1]<7))
    assert_original_untouched(original,mesh)


def test_original_vertex_colours_are_retained():
    a,b=surface(0,9.7,0,10),surface(10.2,20,0,10)
    a.visual.vertex_colors=np.tile([255,0,0,255],(len(a.vertices),1))
    b.visual.vertex_colors=np.tile([0,0,255,255],(len(b.vertices),1))
    original=trimesh.util.concatenate([a,b])
    mesh,added=join_tile_edges([a,b],[(0,0,10),(10,0,10)],[a.vertices.tolist(),b.vertices.tolist()])
    assert added>0
    np.testing.assert_array_equal(mesh.visual.vertex_colors[:len(original.vertices)],original.visual.vertex_colors)
