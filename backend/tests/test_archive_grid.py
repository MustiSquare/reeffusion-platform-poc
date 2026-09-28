from pyproj import Transformer
from app.services.archive_grid import memberships


def footprint(crs,x,y,size):
    t=Transformer.from_crs(crs,4326,always_xy=True)
    return {'footprint':[list(t.transform(a,b)) for a,b in ((x,y),(x+size,y),(x+size,y+size),(x,y+size))]}


def test_fixed_grid_and_boundary_crossing():
    inside=memberships([footprint('EPSG:32605',201000,2201000,50)])
    assert [(a['zone'],a['column'],a['row']) for a in inside]==[(5,20,220)]
    crossing=memberships([footprint('EPSG:32605',209975,2201000,50)])
    assert {a['column'] for a in crossing}=={20,21}
    assert len(crossing)==2
    assert memberships([footprint('EPSG:32605',201000,2201000,50)]*2)==inside


def test_100km_boundary_and_missing_coverage():
    areas=memberships([footprint('EPSG:32605',299975,2201000,50)])
    assert {a['block_column'] for a in areas}=={2,3}
    assert memberships([{'footprint':None}])==[]


def test_zone_and_date_line_boundaries():
    areas=memberships([{'footprint':[[-156.001,20],[-155.999,20],[-155.999,20.001],[-156.001,20.001]]}])
    assert {a['zone'] for a in areas}=={4,5}
    areas=memberships([{'footprint':[[179.999,20],[-179.999,20],[-179.999,20.001],[179.999,20.001]]}])
    assert {a['zone'] for a in areas}=={1,60}
