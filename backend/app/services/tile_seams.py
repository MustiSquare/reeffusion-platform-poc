"""Add narrow boundary strips without changing any existing mesh geometry."""
import math
from collections import defaultdict
import numpy as np
import trimesh

SEAM_VERSION = 1
RADIUS = 2.0
EPS = 1e-7


def boundary_edges(mesh):
    edges, counts = np.unique(np.sort(mesh.edges, axis=1), axis=0, return_counts=True)
    return mesh.vertices[edges[counts == 1]]


def at(edge, axis, t):
    if abs(t-edge[0,axis]) < EPS: return edge[0].copy()
    if abs(t-edge[1,axis]) < EPS: return edge[1].copy()
    return edge[0] + (edge[1]-edge[0]) * ((t-edge[0,axis])/(edge[1,axis]-edge[0,axis]))


def cross(a,b,c):
    u,v=b[:2]-a[:2],c[:2]-a[:2]
    return u[0]*v[1]-u[1]*v[0]


def triangulate_polygon(points):
    """Ear clipping for the small, possibly concave four-tile corner hole."""
    clean=[]
    for p in points:
        if not clean or np.linalg.norm(p-clean[-1])>EPS: clean.append(p)
    if len(clean)>1 and np.linalg.norm(clean[0]-clean[-1])<EPS: clean.pop()
    if len(clean)<3: return []
    area=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(clean,clean[1:]+clean[:1]))
    if area<0: clean.reverse()
    indices=list(range(len(clean)));triangles=[]
    while len(indices)>3:
        found=False
        for pos in range(len(indices)):
            a,b,c=(clean[indices[k%len(indices)]] for k in (pos-1,pos,pos+1))
            if cross(a,b,c)<=EPS: continue
            others=[clean[indices[k]] for k in range(len(indices)) if k not in ((pos-1)%len(indices),pos,(pos+1)%len(indices))]
            if any(min(cross(a,b,p),cross(b,c,p),cross(c,a,p))>=-EPS for p in others): continue
            triangles.append([a,b,c]);indices.pop(pos);found=True;break
        if not found:
            # Remove a redundant collinear boundary point, never invent a fan.
            for pos in range(len(indices)):
                a,b,c=(clean[indices[k%len(indices)]] for k in (pos-1,pos,pos+1))
                if abs(cross(a,b,c))<=EPS:
                    indices.pop(pos);found=True;break
            if not found: return []
    if len(indices)==3: triangles.append([clean[i] for i in indices])
    return triangles


def join_tile_edges(meshes, tiles, soundings):
    """All inputs share XY coordinates. tiles contains (x,y,size) or None.

    Only adjacent selected tiles with measured support are connected. The output
    starts with the exact concatenation of all input vertices and faces.
    """
    original=trimesh.util.concatenate(meshes)
    vertices=original.vertices.tolist();faces=original.faces.tolist()
    vertex_index={tuple(np.round(p,9)):i for i,p in enumerate(original.vertices)}
    buckets=defaultdict(list)
    for points in soundings:
        for p in points:
            if len(p)>=3 and np.isfinite(p[:3]).all(): buckets[(math.floor(p[0]),math.floor(p[1]))].append(p[:2])
    supported_cache={}
    def supported(p):
        key=tuple(np.round(p[:2],7))
        if key not in supported_cache:
            x,y=p[:2];i,j=math.floor(x),math.floor(y)
            supported_cache[key]=any((q[0]-x)**2+(q[1]-y)**2<=RADIUS**2+EPS
                for dx in range(-2,3) for dy in range(-2,3) for q in buckets.get((i+dx,j+dy),()))
        return supported_cache[key]
    def triangle_supported(triangle):
        a,b,c=triangle
        longest=max(np.linalg.norm(a[:2]-b[:2]),np.linalg.norm(a[:2]-c[:2]),np.linalg.norm(b[:2]-c[:2]))
        steps=max(1,math.ceil(longest/.5))
        return all(supported(a+(b-a)*(i/steps)+(c-a)*(j/steps)) for i in range(steps+1) for j in range(steps+1-i))
    orientation=np.sign(np.median([cross(*t) for t in original.triangles[:100]])) or 1
    def append_triangle(triangle):
        if abs(cross(*triangle))<EPS: return
        indices=[]
        for p in triangle:
            key=tuple(np.round(p,9))
            if key not in vertex_index: vertex_index[key]=len(vertices);vertices.append(p.tolist())
            indices.append(vertex_index[key])
        if cross(*triangle)*orientation<0: indices[1],indices[2]=indices[2],indices[1]
        faces.append(indices)
    edges=[boundary_edges(m) for m in meshes]
    lookup={tile:i for i,tile in enumerate(tiles) if tile is not None}
    connections={}
    for tile,left in lookup.items():
        x,y,size=tile
        for axis,other,border in ((0,(x+size,y,size),x+size),(1,(x,y+size,size),y+size)):
            right=lookup.get(other)
            if right is None or not soundings[left] or not soundings[right]: continue
            tangent=1-axis
            def candidates(index,sign):
                result=[]
                for edge in edges[index]:
                    distance=sign*(edge[:,axis]-border)
                    if np.all(distance>=-EPS) and np.all(distance<=RADIUS+EPS) and abs(edge[1,tangent]-edge[0,tangent])>EPS:
                        result.append(edge)
                return result
            first,second=candidates(left,-1),candidates(right,1)
            cuts=sorted({float(p[tangent]) for edge in first+second for p in edge})
            strips=[]
            for low,high in zip(cuts,cuts[1:]):
                if high-low<EPS: continue
                mid=(low+high)/2
                def facing(candidates,largest):
                    active=[e for e in candidates if min(e[:,tangent])-EPS<=mid<=max(e[:,tangent])+EPS]
                    return (max if largest else min)(active,key=lambda e:at(e,tangent,mid)[axis]) if active else None
                a,b=facing(first,True),facing(second,False)
                if a is None or b is None: continue
                p,q,r,s=at(a,tangent,low),at(b,tangent,low),at(a,tangent,high),at(b,tangent,high)
                if min(q[axis]-p[axis],s[axis]-r[axis])<-EPS: continue
                triangles=([p,q,r],[q,s,r])
                if not all(triangle_supported(t) for t in triangles): continue
                for triangle in triangles: append_triangle(triangle)
                strips.append((low,high,p,q,r,s))
            connections[(left,right,axis)]=strips
    # Close only tiny corner holes with all four neighbouring measured surfaces.
    def boundary_segment(index,a,b):
        for alpha in np.linspace(0,1,max(2,math.ceil(np.linalg.norm(a[:2]-b[:2])/.2)+1)):
            p=a+(b-a)*alpha
            valid=False
            for edge in edges[index]:
                d=edge[1]-edge[0];length=np.dot(d,d)
                if length<EPS: continue
                t=np.clip(np.dot(p-edge[0],d)/length,0,1)
                if np.linalg.norm(p-edge[0]-t*d)<1e-5: valid=True;break
            if not valid:return False
        return True
    for (x,y,size),sw in lookup.items():
        ids=[sw,lookup.get((x+size,y,size)),lookup.get((x+size,y+size,size)),lookup.get((x,y+size,size))]
        if any(i is None for i in ids):continue
        sw,se,ne,nw=ids;center=np.array([x+size,y+size])
        ends=[]
        for key,last in (((sw,se,0),True),((se,ne,1),False),((nw,ne,0),False),((sw,nw,1),True)):
            strips=connections.get(key,[])
            if not strips:break
            strip=(max(strips,key=lambda s:s[1]) if last else min(strips,key=lambda s:s[0]))
            ends.append(strip[4:6] if last else strip[2:4])
        if len(ends)!=4 or any(np.max(np.abs(p[:2]-center))>RADIUS+EPS for end in ends for p in end): continue
        bottom,right,top,left=ends
        corners=[]
        for index,signs in zip(ids,((1,1),(-1,1),(-1,-1),(1,-1))):
            bound=meshes[index].bounds
            xy=np.array([bound[1 if sign>0 else 0,axis] for axis,sign in enumerate(signs)])
            matches=meshes[index].vertices[np.all(np.isclose(meshes[index].vertices[:,:2],xy,atol=EPS,rtol=0),axis=1)]
            if not len(matches) or np.max(np.abs(xy-center))>RADIUS+EPS:break
            corners.append(matches[0])
        if len(corners)!=4:continue
        paths=((sw,left[0],corners[0],bottom[0]),(se,bottom[1],corners[1],right[0]),(ne,right[1],corners[2],top[1]),(nw,top[0],corners[3],left[1]))
        if not all(boundary_segment(i,a,c) and boundary_segment(i,c,b) for i,a,c,b in paths):continue
        polygon=[bottom[0],bottom[1],corners[1],right[0],right[1],corners[2],top[1],top[0],corners[3],left[1],left[0],corners[0]]
        triangles=triangulate_polygon(polygon)
        if triangles and all(triangle_supported(t) for t in triangles):
            for triangle in triangles: append_triangle(triangle)
    if len(faces)==len(original.faces): return original,0
    result=trimesh.Trimesh(vertices=vertices,faces=faces,process=False)
    # Keep all pre-existing colour/UV attributes. Only new strip attributes are
    # given a neutral average; the source high-resolution material is retained.
    if original.visual.kind == "vertex":
        colors=original.visual.vertex_colors
        extra=np.tile(np.mean(colors,axis=0).astype(colors.dtype),(len(vertices)-len(colors),1))
        result.visual.vertex_colors=np.vstack([colors,extra])
    elif original.visual.kind == "face":
        colors=original.visual.face_colors
        extra=np.tile(np.mean(colors,axis=0).astype(colors.dtype),(len(faces)-len(colors),1))
        result.visual.face_colors=np.vstack([colors,extra])
    elif original.visual.kind == "texture":
        visual=original.visual.copy()
        if visual.uv is not None:
            uv=visual.uv
            visual.uv=np.vstack([uv,np.tile(np.mean(uv,axis=0),(len(vertices)-len(uv),1))])
        result.visual=visual
    # These are the central guarantees of this edge-only repair.
    assert np.array_equal(result.vertices[:len(original.vertices)],original.vertices)
    assert np.array_equal(result.faces[:len(original.faces)],original.faces)
    return result, len(faces)-len(original.faces)
