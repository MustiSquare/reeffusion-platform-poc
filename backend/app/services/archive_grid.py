"""Stable 10 km UTM area memberships from stored geographic footprints."""
import math
from functools import lru_cache
from pyproj import Transformer


def clip(poly, axis, bound, greater):
    if not poly: return []
    result=[]
    for a,b in zip(poly,poly[1:]+poly[:1]):
        ia=(a[axis]>=bound) if greater else (a[axis]<=bound)
        ib=(b[axis]>=bound) if greater else (b[axis]<=bound)
        if ia: result.append(a)
        if ia!=ib:
            f=(bound-a[axis])/(b[axis]-a[axis])
            result.append([a[0]+f*(b[0]-a[0]),a[1]+f*(b[1]-a[1])])
    return result


def rectangle(poly,x0,y0,x1,y1):
    for axis,bound,greater in ((0,x0,True),(0,x1,False),(1,y0,True),(1,y1,False)):
        poly=clip(poly,axis,bound,greater)
    return poly


def area(poly):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1])))/2 if poly else 0


@lru_cache(maxsize=8192)
def footprint_memberships(vertices):
    poly=[list(p) for p in vertices]
    if len(poly)<3 or not all(math.isfinite(v) for p in poly for v in p):return ()
    # Unwrap across the date line before clipping to longitudinal UTM zones.
    anchor=poly[0][0]
    for p in poly:
        p[0]=anchor+(p[0]-anchor+180)%360-180
    result=set()
    for zi in range(math.floor((min(p[0] for p in poly)+180)/6),math.floor((max(p[0] for p in poly)+180)/6)+1):
        west=zi*6-180;zone=zi%60+1
        for north,south_limit,north_limit in ((True,0,84),(False,-80,0)):
            piece=rectangle(poly,west,south_limit,west+6,north_limit)
            if area(piece)<1e-14:continue
            crs=f"EPSG:{32600+zone if north else 32700+zone}"
            transform=Transformer.from_crs(4326,crs,always_xy=True)
            projected=[list(transform.transform((p[0]+180)%360-180,p[1])) for p in piece]
            for col in range(math.floor(min(p[0] for p in projected)/10000),math.floor(max(p[0] for p in projected)/10000)+1):
                for row in range(math.floor(min(p[1] for p in projected)/10000),math.floor(max(p[1] for p in projected)/10000)+1):
                    if area(rectangle(projected,col*10000,row*10000,(col+1)*10000,(row+1)*10000))>.001:
                        result.add((zone,'N' if north else 'S',col,row))
    return tuple(sorted(result))


def memberships(cells):
    members=set()
    for cell in cells:
        if cell.get('footprint'):
            members.update(footprint_memberships(tuple(tuple(p) for p in cell['footprint'])))
    return [{'id':f'{zone}{hemisphere}:{col}:{row}','zone':zone,'hemisphere':hemisphere,
             'column':col,'row':row,'crs':f"EPSG:{32600+zone if hemisphere=='N' else 32700+zone}",
             'block_column':col//10,'block_row':row//10} for zone,hemisphere,col,row in sorted(members)]
