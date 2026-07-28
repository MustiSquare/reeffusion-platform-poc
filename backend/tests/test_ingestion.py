import json

import pytest

from app.processing.bathymetry import parse_xyz_csv
from app.services.scientific_quality import depth_outlier_report, survey_coverage_metrics
from app.services.ingestion import UploadedSurveyFile, validate_survey_upload


def test_validate_upload_extracts_bathymetry_geojson_and_metadata():
    result = validate_survey_upload(
        [
            UploadedSurveyFile(
                filename="reef_bathymetry.csv",
                content_type="text/csv",
                data=b"x,y,z\n0,0,-1\n1,0,-2\n0,1,-3\n1,1,-4\n",
            ),
            UploadedSurveyFile(
                filename="track.geojson",
                content_type="application/geo+json",
                data=json.dumps(
                    {
                        "type": "FeatureCollection",
                        "features": [
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "LineString",
                                    "coordinates": [[10.0, 52.0], [10.2, 52.2]],
                                },
                                "properties": {},
                            }
                        ],
                    }
                ).encode("utf-8"),
            ),
            UploadedSurveyFile(
                filename="metadata.json",
                content_type="application/json",
                data=b'{"survey_name":"North Reef Transect","site":"North Reef","survey_date":"2026-06-18T10:30:00+00:00","camera":{"model":"Cam A"},"sonar":{"model":"Sonar B"}}',
            ),
        ]
    )

    assert result.dataset_name == "North Reef Transect"
    assert result.dataset_metadata["asset_counts"] == {"bathymetry": 1, "gps": 1, "metadata": 1}
    assert result.assets[0].metadata["grid_shape"] == [2, 2]
    assert result.location == {
        "name": "Uploaded survey location",
        "latitude": 52.1,
        "longitude": 10.1,
        "source": "track.geojson",
    }
    assert result.acquisition.started_at.isoformat() == "2026-06-18T10:30:00+00:00"
    assert result.sensor_metadata.camera["model"] == "Cam A"
    assert result.sensor_metadata.sonar["model"] == "Sonar B"
    assert result.coordinate_system.crs == "LOCAL_GRID"
    assert result.quality_report.validation_status == "valid"
    assert result.quality_report.checks["missing_gps"] is False
    assert result.quality_report.checks["depth_outliers"][0]["outlier_count"] == 0
    assert result.quality_report.checks["survey_coverage"][0]["coverage_area"] == 1.0
    assert result.quality_report.scientific_validity["status"] == "workflow_validation_only"
    assert result.quality_report.scientific_validity["is_scientifically_valid"] is False
    assert result.quality_report.uncertainty["qualitative_level"] == "moderate"


def test_validate_upload_rejects_duplicate_names():
    with pytest.raises(ValueError, match="duplicate file name"):
        validate_survey_upload(
            [
                UploadedSurveyFile("a.xyz", "text/plain", b"0 0 -1\n1 0 -2\n0 1 -3\n1 1 -4\n"),
                UploadedSurveyFile("a.xyz", "text/plain", b"0 0 -1\n1 0 -2\n0 1 -3\n1 1 -4\n"),
            ]
        )


def test_validate_upload_requires_survey_data_file():
    with pytest.raises(ValueError, match="bathymetry, imagery or video"):
        validate_survey_upload(
            [UploadedSurveyFile("metadata.json", "application/json", b'{"survey_name":"Only Metadata"}')]
        )


def test_parse_headerless_xyz():
    grid = parse_xyz_csv(b"0 0 -1\n1 0 -2\n0 1 -3\n1 1 -4\n", source="headerless.xyz")

    assert grid.z.shape == (2, 2)
    assert grid.z[0, 0] == -1


def test_depth_outlier_and_coverage_quality_helpers():
    grid = parse_xyz_csv(
        b"x,y,z\n0,0,-1\n1,0,-1\n2,0,-1\n0,1,-1\n1,1,-60\n2,1,-1\n0,2,-1\n1,2,-1\n2,2,-1\n",
        source="outlier.csv",
    )

    outliers = depth_outlier_report(grid.z)
    coverage = survey_coverage_metrics(grid.metadata)

    assert outliers["point_count"] == 9
    assert outliers["outlier_count"] >= 1
    assert outliers["warnings"]
    assert coverage["coverage_area"] == 4.0
    assert coverage["point_density"] == 2.25
