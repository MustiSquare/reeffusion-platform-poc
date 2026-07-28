from dataclasses import dataclass, field

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.models import tables  # noqa: F401
from app.models.tables import RawAsset, RawDataset


SAMPLE_BATHYMETRY_XYZ = b"0 0 -1\n1 0 -2\n0 1 -3\n1 1 -4\n"
SAMPLE_METADATA_JSON = (
    b'{"survey_name":"Fixture Reef","site":"Fixture Site",'
    b'"survey_date":"2026-06-18T10:30:00+00:00"}'
)
SAMPLE_GEOJSON = (
    b'{"type":"FeatureCollection","features":[{"type":"Feature","geometry":'
    b'{"type":"LineString","coordinates":[[10.0,52.0],[10.2,52.2]]},"properties":{}}]}'
)


@dataclass
class FakeObjectStore:
    objects: dict[str, bytes] = field(default_factory=dict)
    content_types: dict[str, str | None] = field(default_factory=dict)
    deleted_keys: list[str] = field(default_factory=list)
    deleted_prefixes: list[str] = field(default_factory=list)

    def get_bytes(self, key):
        return self.objects[key]

    def put_bytes(self, key, data: bytes, content_type=None):
        self.objects[key] = data
        self.content_types[key] = content_type
        return key

    def delete_key(self, key):
        self.deleted_keys.append(key)
        self.objects.pop(key, None)

    def delete_prefix(self, prefix):
        self.deleted_prefixes.append(prefix)
        for key in list(self.objects):
            if key.startswith(prefix):
                self.objects.pop(key, None)


def in_memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def create_raw_fixture_dataset(db, object_store: FakeObjectStore) -> RawDataset:
    raw = RawDataset(
        name="Fixture Uploaded Reef",
        source="upload",
        sensor_metadata_json={"sonar": {"model": "fixture sonar"}},
        coordinate_system_json={"crs": "LOCAL_GRID", "vertical_units": "meters"},
        quality_report_json={"validation_status": "valid"},
        metadata_json={
            "validation_status": "valid",
            "asset_counts": {"bathymetry": 1, "metadata": 1},
            "warnings": [],
        },
    )
    db.add(raw)
    db.commit()
    object_key = f"raw/{raw.id}/bathymetry.xyz"
    object_store.put_bytes(object_key, SAMPLE_BATHYMETRY_XYZ, "text/plain")
    db.add(
        RawAsset(
            dataset_id=raw.id,
            file_name="bathymetry.xyz",
            media_type="text/plain",
            asset_type="bathymetry",
            object_key=object_key,
            size_bytes=len(SAMPLE_BATHYMETRY_XYZ),
            metadata_json={"source": "fixture"},
        )
    )
    db.commit()
    return raw
