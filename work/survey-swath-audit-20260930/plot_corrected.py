import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from pyproj import Transformer

root=Path(__file__).parent
before=np.load(root/'coverage.npz')
coverage=json.loads((root/'corrected-coverage.json').read_text(encoding='utf-8-sig'))
project=Transformer.from_crs(4326,32605,always_xy=True)
corrected=[]
for polygon in coverage['polygons']:
    x0,y=project.transform(*polygon[0]);x1,_=project.transform(*polygon[1])
    corrected.extend((x,int(round(y))) for x in range(int(round(x0)),int(round(x1))))
corrected=np.array(corrected,dtype=np.int64)
def unpack(keys):return np.column_stack([(keys>>32).astype(np.int64),(keys&np.uint64(0xffffffff)).astype(np.int64)])
old,sv=unpack(before['app_all']),unpack(before['sonarview_all'])
new_keys={(int(x)<<32)|int(y) for x,y in corrected};sv_keys=set(before['sonarview_all'].tolist());old_keys=set(before['app_all'].tolist())
stats={'corrected_occupied_1m_squares':len(new_keys),'previous_occupied_1m_squares':len(old_keys),
       'sonarview_occupied_1m_squares':len(sv_keys),'corrected_intersection_with_sonarview':len(new_keys&sv_keys),
       'corrected_footprint_iou':len(new_keys&sv_keys)/len(new_keys|sv_keys),
       'previous_footprint_iou':len(old_keys&sv_keys)/len(old_keys|sv_keys)}
(root/'corrected-coverage-comparison.json').write_text(json.dumps(stats,indent=2))
origin=np.array([202900,2217400]);clouds=[old,corrected,sv]
fig,axes=plt.subplots(1,3,figsize=(15,6),sharex=True,sharey=True)
for ax,points,title in zip(axes,clouds,['Application before correction','Application after correction','SonarView export']):
    shifted=points-origin
    ax.scatter(shifted[:,0]+.5,shifted[:,1]+.5,s=1,marker='s',linewidths=0,color='#087f8c',rasterized=True)
    ax.set_title(f'{title}\n{len(points):,} occupied 1 m squares',fontsize=11)
    ax.set_aspect('equal');ax.grid(alpha=.15);ax.set_xlabel('Easting relative to 202,900 m (m)')
axes[0].set_ylabel('Northing relative to 2,217,400 m (m)')
fig.suptitle('Survey 2026-08-21-23-13: full-recording footprint',fontsize=16)
fig.text(.5,.03,'Application retains the same 26,680,028 detections. SonarView exports 29,368,782 with different filtering.\nOccupied squares describe point coverage, not independently measured seafloor area. EPSG:32605.',ha='center',fontsize=10)
fig.tight_layout(rect=[0,.09,1,.93]);fig.savefig(root/'corrected-swath-comparison.png',dpi=180)
print(json.dumps(stats,indent=2))
