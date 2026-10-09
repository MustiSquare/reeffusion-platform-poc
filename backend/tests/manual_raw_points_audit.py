"""Explicit live-data audit (not collected by pytest). Outputs a compact JSON report."""
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import numpy as np


def audit():
    base='http://127.0.0.1:8000/api/survey/archive/f409f591-e87d-5974-81a7-6d1918a1ae98'
    def get(path):
        with urllib.request.urlopen(base+path,timeout=120) as response:return response.read()
    manifest=json.loads(get('/raw-points/manifest'))
    exported=json.loads(get('/xyz-export'))
    def chunk(c):
        payload=get('/raw-points/chunks/'+c['id'])
        assert len(payload)==c['bytes']==c['count']*12
        points=np.frombuffer(payload,dtype='<f4').reshape(-1,3).astype(float)+c['origin']
        assert np.isfinite(points).all()
        assert np.all(points[:,2]<=.00001)
        squares=np.unique(np.floor(points[:,:2]).astype(np.int64),axis=0)
        return len(points),len(payload),points.min(axis=0),points.max(axis=0),set(map(tuple,squares))
    started=time.monotonic();count=byte_count=0;minimum=np.full(3,np.inf);maximum=-minimum;coverage=set()
    with ThreadPoolExecutor(max_workers=4) as executor:
        for n,size,lo,hi,squares in executor.map(chunk,manifest['chunks']):
            count+=n;byte_count+=size;minimum=np.minimum(minimum,lo);maximum=np.maximum(maximum,hi);coverage.update(squares)
    assert count==manifest['point_count']==exported['point_count']==26680028
    assert np.allclose(minimum,manifest['min'],rtol=0,atol=.001)
    assert np.allclose(maximum,manifest['max'],rtol=0,atol=.001)
    return {'detections':count,'chunks':len(manifest['chunks']),'bytes':byte_count,
            'overview_points':manifest['overview_count'],'overview_chunks':len(manifest['overview']),
            'download_and_decode_seconds':round(time.monotonic()-started,2),
            'occupied_1m_squares':len(coverage),'min':minimum.tolist(),'max':maximum.tolist(),
            'matches_xyz_count':True,'bounds_within_1mm':True,'partial':manifest['partial']}


if __name__=='__main__':print(json.dumps(audit()))
