# Live Survey playback

Open **Live Survey**, then load a `.svlz` or `.svlog` recording (maximum 100 MB).
The supplied `test_data/2026-07-10-20-00.svlz` works, recovering approximately
63 minutes before a damaged gzip section. The UI reports recovered-prefix playback.

Use Play & process/Pause, 1–60× speed, and the timeline. Playback and processing
continue while another tab is visible. Grid defaults to 50 × 50 metres, aligned to the survey's WGS84 UTM zone;
25, 100 and 200 metre sizes are also available. Navigation outside UTM latitude
limits is rejected. A replay is intended for a local, single-zone survey.

Play & process enables automatic processing: during playback, 60% occupied 5 m
cells and ten seconds without new samples make a block ready. At end-of-recording,
every usable partial block is processed, regardless of coverage, and even small
revisions to earlier results are flushed. One job runs at a time. Failed jobs
require a manual retry or Reset processing run followed by Play & process.
Reset rewinds the feed and clears this run's job tracking without deleting saved
datasets/files. Identical snapshots may reuse existing successful results.
Scrubbing disables automatic processing; Play enables it again.

Click a completed map cell to open its latest processed dataset. Incomplete cells
show their measurements and manual processing controls. Saved cells are restored
from the server (without the recent-files list's 100-result limit), even after
refreshing the page. Fit all received cells shows the complete received footprint.
Coverage denotes occupied cells, not verified complete swath coverage. Cells with
fewer than four spread-out points remain visible but cannot form a surface.

For a combined area, choose **Select multiple cells**, click up to **20** completed
cells (pink outlines indicate selection), then **Open selected area** to open the combined view in the **Processed Data Viewer** tab. Clicking a
selected cell deselects it; Clear selection removes the selection. The viewer
captures the latest available processed result per chosen cell at opening time.
Grid/recording changes clear the selection. Existing files are unchanged.

Selected cells are assembled into a normal processed dataset using their stored
projected origins and existing mesh faces. The full ProfessionalViewer handles
single and combined datasets, including annotations, measurement, point clouds,
wireframe, camera presets, and depth exaggeration. Gaps remain empty. Existing
annotations are copied into the shared coordinates; new annotations belong to
the combined dataset. Reopening an identical selection reuses that dataset.
Combined assets are exported under the survey's dated processed folder, with
source IDs recorded in metadata. Mesh area metrics cover supported triangles;
classification remains provisional. The limit remains 20 cells per selection.

Repeated ingestion uses existing entries. Recordings match by SHA-256 content;
manually uploaded packages match file contents/types and supplied metadata,
independent of file order and filenames. Changed content is a different survey.
Each replay/grid/cell keeps one raw dataset, with successive snapshots replacing
its XYZ input. Processing reuses the processed dataset and asset IDs, publishes
new outputs after successful generation, and refreshes the same dated export
folder. Existing annotations remain attached; failed processing keeps the last
good assets. Unchanged replay snapshots reuse completed jobs. Combined areas
refresh in place on reopening when their source revisions change. This policy
applies going forward and reuses matching legacy entries; it does not purge
older duplicate archive entries created before the change.

The Data Archive groups datasets and all asset links beneath expandable survey
headers. Only one survey opens at a time. Delete removes the chosen dataset,
its registered object-store files and dated local exports; deleting a raw entry
also removes its processed results and dependent combined views. The recording
copy is removed when its last raw cell is deleted. Files originally selected on
the user's computer are not removed. Active processing blocks deletion.
Live Survey has an optional survey-name field; recording filenames are the
fallback. Duplicate detection uses content checksums plus the acquisition date,
independently of display names. Matching previously processed surveys require a
Yes/No confirmation showing the previous processing date, before ingestion or
processing proceeds. No leaves existing records and files unchanged. Missing
acquisition dates match only other undated uploads; enter the date in Raw Data
Upload when it is not present in the files.


### Browsing previous surveys

Use **Access previous surveys** on Live Survey to open the Data Archive. Each survey header shows a bundled world-map thumbnail (Natural Earth public-domain land outlines), a red location marker when coordinates are available, recorded acquisition date/duration, and unique received/processed cell counts with a breakdown by grid size. Combined views do not inflate cell counts. Historical wave-height and wind-speed ranges cover the recorded acquisition interval; prevailing wind direction is speed-weighted and circular. Partial or unavailable model coverage is labelled. These estimates are separate from onboard IMU motion.

**Open survey map** displays archived cell footprints directly from database metadata; it does not load sonar recordings, start playback, or request reprocessing. Click a processed cell to open the existing Processed Data Viewer. Enable multiple selection to open at most 20 cells together using the same viewer and its measurement/annotation tools. Pink overlays show selected cells above other map drawings. The viewer's compact map opens individual cells; its full-map button returns to the entire survey for multi-cell selection. Surveys without georeferenced cell metadata retain file access without invented map grids.

The lightweight API is `GET /api/survey/archive`, `GET /api/survey/archive/{survey_id}`, and `GET /api/survey/archive/{survey_id}/conditions`. Weather requests are deferred until summary cards enter the viewport. Basemap tiles and historical weather require network access; the world thumbnails are bundled locally. Natural Earth source: https://github.com/nvkelso/natural-earth-vector/blob/master/geojson/ne_110m_land.geojson (https://www.naturalearthdata.com/about/terms-of-use/).


Opening processed reefs now requires a completed processed result; raw selection cannot populate the processed viewer. Archive maps remain unavailable until the survey has at least one processed cell. **Delete entire survey** requires the explicit Yes/No warning and removes archived raw/processed members, dependent combined views, annotations, stored recording copies and local processed exports. Active processing blocks deletion before files are removed. Unrelated surveys and original files outside application storage are preserved. The delete endpoint is `DELETE /api/survey/archive/{survey_id}?confirmed=true` and uses the same admin authorization as individual dataset deletion.


### Sea-level and MSL display convention

The viewer uses the approved display reference: blue sea level is fixed at **Z = 0 m**. Yellow MSL is at `Z = -offset`, with a user-set default offset of **3 m**. Thus a seabed point at Z = -18 m is 18 m below blue and 15 m below yellow at Z = -3 m. The offset remains editable under **MSL below sea level (m)** and persists per survey in this browser. It is a display setting, not a measured tide correction. Stored XYZ heights and exports are unchanged.

The obsolete absolute-height and sonar-to-waterline browser settings are not used in this convention. Both overlays follow Z exaggeration, span the selected area as continuous flat references, including gaps between cells, and leave reef picking available. Readouts show original metres, the reference Z, and each reference's height above the selected sounding. Recorded sonar altitude is retained separately for inspection; it no longer shifts the blue sea-level reference away from zero.

Processing preserves beam-angle/attitude-corrected vertical sonar distances in `sounding_references.json`, copied to results and dated exports. Combined cells translate XY without changing Z or sonar altitude. `GET /api/survey/processed/{dataset_id}/sounding-references` recovers positions for older processed cells from retained recordings and the saved processing snapshot, without rebuilding or overwriting mesh assets.

Cell hover tooltips are removed from live and archived survey maps; colours and selection controls still indicate cell state. Only the sea-level/MSL references bridge gaps. Seabed geometry is unchanged.
