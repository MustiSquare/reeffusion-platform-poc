import csv, io, json, math, random, uuid
from datetime import datetime, timedelta, timezone
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
from sqlalchemy.orm import Session
from app.models.tables import SurveyLocation, RawDataset, RawAsset, ProcessedDataset, ProcessedAsset, Annotation
from app.storage.s3 import store
from app.processing.rugosity import rugosity_from_grid
from app.processing.ai_models import run_image_quality_assessment, run_coral_segmentation, run_benthic_cover_classification, run_coral_health_classification, project_ai_layers_to_3d, generate_ai_insights
from app.processing.ml_registry import ensure_ml_registry
from app.processing.mesh import export_mesh_glb, export_mesh_obj, export_mesh_ply, texture_mapping_metadata
from app.processing.photogrammetry import PointCloud
from app.schemas.domain import CoordinateSystemSchema, ProcessingVersionSchema, QualityReportSchema, SensorMetadataSchema

CLASSES=["coral","rock","sand","algae","healthy","bleached","dead","diseased"]
DEMO_COORDINATE_SYSTEM = CoordinateSystemSchema(
    crs="LOCAL_GRID",
    coordinate_system="projected_or_local",
    horizontal_units="meters",
    vertical_units="meters",
    vertical_convention="elevation_positive_up",
)
DEMO_SENSOR_METADATA = SensorMetadataSchema(
    camera={"model": "generated downward camera", "frame_count": 4},
    sonar={"model": "generated bathymetry grid"},
    gps={"track": "synthetic scout usv track"},
    platform={"name": "Scout USV synthetic"},
)
DEMO_PROCESSING_VERSION = ProcessingVersionSchema(
    name="bathymetry-mesh",
    version="v1",
    geometry_engine="generated-grid",
    mesh_formats=["glb", "ply", "obj"],
    ai_assisted=True,
)

def reef_grid(seed=1, time_shift=0.0, n=128):
    """Generate a denser, reef-like terrain grid with bommies, ridges, channels and local coral heads."""
    rng=np.random.default_rng(seed)
    x=np.linspace(-5.5,5.5,n); y=np.linspace(-5.5,5.5,n); X,Y=np.meshgrid(x,y)
    # base seafloor slope and low-frequency reef relief
    Z=-9.5 + 0.12*X - 0.08*Y
    Z += 0.55*np.sin(1.4*X+0.4*np.sin(Y))*np.cos(1.1*Y)
    Z += 0.28*np.sin(3.1*X+1.7*Y) + 0.18*np.cos(4.2*np.hypot(X,Y))
    # large coral bommies and rubble depressions
    centers=[(-2.8,-1.6,1.8,0.85),(0.2,0.1,2.35,1.15),(2.7,1.6,1.55,0.75),(-1.3,2.6,1.25,0.6),(3.1,-2.4,1.05,0.55)]
    for cx,cy,amp,spread in centers:
        Z += amp*np.exp(-((X-cx)**2+(Y-cy)**2)/(2*spread**2))
    channels=[(1.8,-0.7,0.55,0.18),(-2.2,1.2,0.40,0.28)]
    for cx,cy,amp,spread in channels:
        Z -= amp*np.exp(-((X-cx)**2+(Y-cy)**2)/(2*spread**2))
    # many small coral heads / knolls for realistic rugosity
    for _ in range(42):
        cx=float(rng.uniform(-5,5)); cy=float(rng.uniform(-5,5))
        amp=float(rng.uniform(0.12,0.55)); spread=float(rng.uniform(0.10,0.32))
        Z += amp*np.exp(-((X-cx)**2+(Y-cy)**2)/(2*spread**2))
    # local pitting and photogrammetry-like roughness
    Z += 0.045*rng.normal(size=(n,n))
    Z += time_shift*np.exp(-((X-1.2)**2+(Y+.4)**2)/0.9)
    return X,Y,Z

def _xyz_csv(X,Y,Z):
    out=io.StringIO(); wr=csv.writer(out); wr.writerow(["x","y","z"])
    for x,y,z in zip(X.ravel(),Y.ravel(),Z.ravel()): wr.writerow([round(float(x),4),round(float(y),4),round(float(z),4)])
    return out.getvalue().encode()


def _coral_texture(seed=1, size=1024):
    """Create a reef-like texture image for the browser mesh without adding external runtime dependencies."""
    rng=random.Random(seed)
    img=Image.new("RGB",(size,size),(18,72,86)); d=ImageDraw.Draw(img, "RGBA")
    palette=[(230,142,92,230),(251,196,108,220),(113,201,146,210),(172,119,205,215),(73,184,202,205),(214,225,188,210),(136,103,78,220)]
    # soft underwater background gradients
    for y in range(size):
        t=y/size
        d.line((0,y,size,y), fill=(int(10+18*t), int(74+34*t), int(92+30*t), 255))
    # colony patches
    for _ in range(150):
        cx=rng.randint(-60,size+60); cy=rng.randint(-60,size+60); rx=rng.randint(28,110); ry=rng.randint(18,95)
        col=rng.choice(palette)
        d.ellipse((cx-rx,cy-ry,cx+rx,cy+ry), fill=col)
        # polyp / brain-coral pattern
        step=rng.randint(9,18)
        for a in range(0,360,step):
            import math as _m
            x1=cx+_m.cos(_m.radians(a))*rx*0.15; y1=cy+_m.sin(_m.radians(a))*ry*0.15
            x2=cx+_m.cos(_m.radians(a))*rx*0.95; y2=cy+_m.sin(_m.radians(a))*ry*0.95
            d.line((x1,y1,x2,y2), fill=(255,255,255,28), width=1)
        for _p in range(rng.randint(10,26)):
            px=cx+rng.randint(-rx,rx); py=cy+rng.randint(-ry,ry); pr=rng.randint(2,6)
            d.ellipse((px-pr,py-pr,px+pr,py+pr), outline=(255,255,255,45), fill=(255,255,255,18))
    # caustic streaks and blur to make it natural
    for _ in range(34):
        x=rng.randint(0,size); d.line((x,0,x+rng.randint(-180,180),size), fill=(144,230,245,28), width=rng.randint(1,3))
    img=img.filter(ImageFilter.GaussianBlur(radius=0.45))
    b=io.BytesIO(); img.save(b, format="JPEG", quality=88); return b.getvalue()

def _geojson_track():
    coords=[[-155.1+i*0.00003,19.7+math.sin(i/7)*0.00005] for i in range(60)]
    return json.dumps({"type":"FeatureCollection","features":[{"type":"Feature","properties":{"name":"synthetic scout usv track"},"geometry":{"type":"LineString","coordinates":coords}}]}, indent=2).encode()

def _frame(seed, idx):
    rng=random.Random(seed+idx)
    img=Image.new("RGB",(960,540),(10,82,104)); d=ImageDraw.Draw(img, "RGBA")
    for y in range(540):
        t=y/540; d.line((0,y,960,y), fill=(int(8+20*t), int(80+38*t), int(105+26*t), 255))
    for _ in range(95):
        x=rng.randint(0,960); y=rng.randint(120,540); r=rng.randint(8,42)
        col=rng.choice([(238,183,95,230),(46,164,110,225),(199,93,84,225),(180,180,150,215),(139,92,170,225),(232,151,105,225)])
        d.ellipse((x-r,y-r,x+r,y+r), fill=col)
        for _p in range(8):
            px=x+rng.randint(-r,r); py=y+rng.randint(-r,r); pr=max(1,rng.randint(1,4))
            d.ellipse((px-pr,py-pr,px+pr,py+pr), fill=(255,255,255,45))
    for _ in range(18):
        x=rng.randint(0,960); base=rng.randint(260,540); col=rng.choice([(233,168,95,220),(88,201,142,210),(186,122,210,210)])
        for branch in range(rng.randint(5,13)):
            x2=x+rng.randint(-70,70); y2=base-rng.randint(40,160)
            d.line((x,base,x2,y2), fill=col, width=rng.randint(3,7))
    for _ in range(22):
        x=rng.randint(0,960); d.line((x,0,x+rng.randint(-120,120),540), fill=(120,220,235,34), width=1)
    b=io.BytesIO(); img=img.filter(ImageFilter.GaussianBlur(radius=0.25)); img.save(b, format="JPEG", quality=86); return b.getvalue()

def _generated_glb():
    X, Y, Z = reef_grid()
    return _mesh_glb(X, Y, Z)


def _mesh_glb(X, Y, Z):
    return export_mesh_glb(PointCloud(x=X, y=Y, z=Z, source="generated reef grid", metadata={"generated": True}))


def _mesh_exports(X, Y, Z):
    point_cloud = PointCloud(x=X, y=Y, z=Z, source="generated reef grid", metadata={"generated": True})
    texture_metadata = texture_mapping_metadata(point_cloud, "coral_texture.jpg")
    return {
        "mesh.glb": (export_mesh_glb(point_cloud), "model/gltf-binary", "mesh_glb", {}),
        "mesh.ply": (export_mesh_ply(point_cloud), "application/octet-stream", "mesh_ply", {}),
        "mesh.obj": (export_mesh_obj(point_cloud), "text/plain", "mesh_obj", {}),
        "texture_mapping.json": (json.dumps(texture_metadata, indent=2).encode("utf-8"), "application/json", "texture_mapping", texture_metadata),
    }

def generate_demo(db: Session, pair: bool=True):
    s3=store(); ensure_ml_registry(db)
    loc=SurveyLocation(name="Synthetic Kona Reef", latitude=19.70, longitude=-155.10, crs="EPSG:4326", coordinate_system="geographic", geom_geojson={"type":"Point","coordinates":[-155.10,19.70]}, metadata_json={"source":"generated"})
    db.add(loc); db.commit(); created=[]
    for tp,shift in [("A",0.0),("B",-.35)] if pair else [("A",0.0)]:
        seed=42 if tp=="A" else 43; X,Y,Z=reef_grid(seed,shift)
        acquired_at=datetime.now(timezone.utc)+timedelta(days=30 if tp=="B" else 0)
        raw=RawDataset(
            name=f"Reef Survey {tp}",
            location_id=loc.id,
            source="generated",
            acquisition_started_at=acquired_at,
            acquisition_ended_at=acquired_at+timedelta(hours=1),
            sensor_metadata_json=DEMO_SENSOR_METADATA.model_dump(mode="json"),
            coordinate_system_json=DEMO_COORDINATE_SYSTEM.model_dump(mode="json"),
            quality_report_json=QualityReportSchema(validation_status="valid", checks={"generated": True}).model_dump(mode="json"),
            metadata_json={"equipment":"Scout USV, 1080p downward camera, Cerulean-style sonar", "timepoint":tp},
        )
        db.add(raw); db.commit()
        files={
            "bathymetry_xyz.csv":(_xyz_csv(X,Y,Z),"text/csv","bathymetry"),
            "gps_track.geojson":(_geojson_track(),"application/geo+json","gps"),
            "metadata.json":(json.dumps({"timepoint":tp,"format":"reefusion-generated-survey"}, indent=2).encode(),"application/json","metadata"),
        }
        for i in range(4): files[f"frame_{i:03}.jpg"] = (_frame(seed,i),"image/jpeg","image")
        for name,(data,ctype,atype) in files.items():
            key=f"raw/{raw.id}/{name}"; s3.put_bytes(key,data,ctype)
            db.add(RawAsset(dataset_id=raw.id,file_name=name,media_type=ctype,asset_type=atype,object_key=key,size_bytes=len(data)))
        metrics=rugosity_from_grid(Z)
        benthic=run_benthic_cover_classification(raw)
        health=run_coral_health_classification(raw)
        metrics={**metrics,"cover":benthic["classes"],"health":health["classes"]}
        projected=project_ai_layers_to_3d(raw)
        metrics["ai"]={"image_quality":run_image_quality_assessment(raw),"segmentation":run_coral_segmentation(raw),"benthic_classification":benthic,"health_classification":health,"projected_3d_layers":projected,"insights":generate_ai_insights(metrics)}
        proc=ProcessedDataset(raw_dataset_id=raw.id,name=f"Processed Reef Survey {tp}",location_id=loc.id,survey_date=acquired_at,processing_version="bathymetry-mesh-v1",processing_version_json=DEMO_PROCESSING_VERSION.model_dump(mode="json"),coordinate_system_json=DEMO_COORDINATE_SYSTEM.model_dump(mode="json"),quality_report_json=QualityReportSchema(validation_status="valid", checks={"generated": True, "mesh_formats":["glb","ply","obj"]}).model_dump(mode="json"),metrics_json=metrics,viewer_config_json={"primary":"point_cloud_xyz","ai_layers":projected["layers"]})
        db.add(proc); db.commit()
        pfiles={
            "point_cloud.xyz.csv":(_xyz_csv(X,Y,Z),"text/csv","point_cloud_xyz",{}),
            **_mesh_exports(X,Y,Z),
            "coral_texture.jpg":(_coral_texture(seed),"image/jpeg","coral_texture",{}),
            "classes.geojson":(_geojson_track(),"application/geo+json","classes_geojson",{}),
        }
        for name,(data,ctype,atype,metadata) in pfiles.items():
            key=f"processed/{proc.id}/{name}"; s3.put_bytes(key,data,ctype)
            db.add(ProcessedAsset(dataset_id=proc.id,file_name=name,media_type=ctype,asset_type=atype,object_key=key,metadata_json=metadata))
        for i,label in enumerate(CLASSES):
            db.add(Annotation(processed_dataset_id=proc.id,label=label,annotation_type="point",geometry_json={"type":"Point","coordinates":[float(X.ravel()[i*37]),float(Y.ravel()[i*37]),float(Z.ravel()[i*37])]},properties_json={"generated":True}))
        db.commit(); created.append({"raw_dataset_id":raw.id,"processed_dataset_id":proc.id,"timepoint":tp})
    return {"location_id": loc.id, "created": created}
