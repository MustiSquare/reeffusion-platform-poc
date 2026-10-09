# Live Survey playback

### Full-survey XYZ CSV export

Each survey row in **Data Archive** has **Export XYZ CSV**. This reads the stored
original SonarView recording independently of the playback cursor and processed
cells. The export preserves each valid, supported sonar detection, including
repeated positions. It bypasses the playback 500,000-point limit, 1 m averaging
and 6,000-point map preview cap; those playback limits remain unchanged.

The CSV contains `x,y,z` in WGS84 UTM metres with negative vehicle-relative Z.
Comment headers identify the EPSG code, source recording, point count, units,
vertical datum, format version and partial status. No viewer MSL offset, tide
correction or vertical exaggeration is applied. Geometry uses the same decoder,
navigation synchronization, mounting, power and validity checks as playback.
Downloads use the current survey name and recording acquisition date.

Preparation runs in the existing Celery worker. The archive shows progress and
then **Download XYZ CSV**, or **Download partial CSV** with warnings and the
recovered count. Damaged compression, truncated/malformed packets, unsupported
point packets, unpaired pings, missing mounts, additional sessions and the
configured decompression limit produce an explicitly partial result. Partial
filenames contain `_partial`. Empty results fail with an explanation and can be
retried. Surveys without an available original recording explain why export is
unavailable; generated reef points are never substituted.

The worker hashes the original while streaming it to temporary disk, streams
detections to another temporary file, then adds the final metadata headers.
Memory does not grow with the point count. Temporary disk must accommodate the
recording plus roughly two copies of its XYZ output. Temporary files close on
success or failure. CSVs and manifests are retained under
`replays/<id>/xyz-v1/`, keyed by source SHA-256 and format version; a change to the
configured decompression limit also invalidates the cache. Survey deletion
removes these outputs with the recording. No database migration is needed.

Requests for the same recording share a leased job. A heartbeat renews the lease
while the worker runs; an interrupted or never-started job becomes retryable
after at most five minutes. Duplicate task delivery cannot start another writer.
Retry removes abandoned CSV attempts and incomplete multipart uploads while
preserving the last published export. Deletion also aborts unfinished uploads.
Deletion is blocked during preparation. Database row locks serialize export
startup/publication with deletion. Redis must be available to check deletion
safety for surveys that have requested exports.

Survey-scoped endpoints:

- `POST /api/survey/archive/{survey_id}/xyz-export`: prepare or reuse an export
  (same editor authorization as processing).
- `GET /api/survey/archive/{survey_id}/xyz-export`: availability, state, progress,
  errors, warnings and recovered point count.
- `GET /api/survey/archive/{survey_id}/xyz-export/download`: stream the completed
  CSV through the backend without loading it into browser/backend memory.

Restart the backend and worker after installing this change so the new routes
and Celery task are registered.

Validation on 2026-09-30: the stored 500,028,324-byte recording
`2026-08-21-20-15.svlz` exported 25,951,295 individual detections into a
1,273,439,389-byte CSV. Streaming the download through the backend confirmed
every row and the byte count; another prepare request reused the same object.
The result was explicitly partial because one point packet lacked its matching
ping. Worker peak resident memory was 241,208 KiB (about 236 MiB), including
multipart upload buffers; decoding stayed near 131 MiB. The smaller damaged
recording also completed, exporting 3,283,621 recovered detections with its
compression warning. Tests cover coordinates, repeated detections beyond the
preview limit, invalid/empty inputs, cache invalidation, duplicate requests,
interruption, retry, deletion protection, metadata and archive controls.

### Playback controls

Open **Live Survey**, then load a `.svlz` or `.svlog` recording (default maximum 2 GiB).
Uploads are decoded and stored as streams. `SURVEY_UPLOAD_LIMIT_MB` (default 2048)
and `SURVEY_DECOMPRESSED_LIMIT_MB` (default 16384) configure the limits in MiB.
The existing 500,000 retained-point limit and one-day recording limit still apply;
decoder warnings indicate partial recovery or point truncation.
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


Loading shows an estimated overall percentage beside the recording selector. The
configured upload limit is displayed there and checked before transfer. Saved
replay upgrades and onboard motion summaries are retained in object storage.
Identical recordings can reuse versioned decoding results; overwrite confirmation
still applies. Playback responses omit backend-only reference arrays without
changing stored XYZ or processed-viewer data. Progress uses short-lived Redis
records and loading continues if progress reporting is unavailable.


Combined views retain the original high-resolution tile meshes without resampling.
The shared 1 m surface reconstruction has been rolled back. Any combined view
created using it is restored from original tile meshes when reopened, retaining
its ID and annotations. Artificial tile seams are repaired with added boundary strips only: original
vertices and faces remain unchanged. Connections require adjacent selected cells
from the same survey, edges within 2 m of the shared boundary and supporting
soundings within 2 m. Unsupported gaps remain open. Small four-tile corner holes
are closed only when all four measured boundary chains are present. Existing
combined views upgrade in place on reopening; original cell meshes are untouched.

## Coordinate correction and full-recording recovery (coordinate version 2)

The September 2026 comparison with SonarView identified a horizontal frame error
in individual detections, upstream of the mesh and viewer. The decoder now applies
the RX array-to-forward yaw conversion before vehicle heading and projects true
north/east offsets geodesically into UTM. A global rotation of a finished mesh is
not a substitute. Medium power, range, classification and navigation filters are
unchanged, as are negative vehicle-origin depths. Rejection counters are included
in XYZ metadata and rebuild results.

Coordinate version is independent of CSV format version. It is recorded in replay,
export, raw-cell and processed metadata. Legacy replay geometry is fully decoded
again from its original source when opened; old XYZ caches cannot be reused.
Legacy surfaces never receive newly corrected sounding overlays.

`GET/POST /api/survey/archive/{survey_id}/repair` reports or starts a background
rebuild. This streams all recoverable supported detections into temporary SQLite
storage with an 8192-detection input buffer and an 8 MiB SQLite cache. Weighted
1 m bins retain detection counts and vertical references. Every occupied cell is
reconsidered, including new outer cells; playback's 500,000-point cap is not used.
Cells too sparse for a surface retain their raw measurements and coverage.

Each attempt creates a separate generation. All replacements are staged before a
single database transaction activates the survey. Old raw cells, surfaces,
combined views and annotations remain available as **legacy** archive entries;
annotations are not transferred to different coordinates. Default maps, results
and dataset lists use active generations. Mixed-version and legacy combinations
are rejected. No database migration or source re-upload is required.

Repair shares a renewable lease with XYZ export and uses raw-row locks when
starting and activating. Deletion and cell processing are blocked during repair.
An interrupted or failed attempt releases its lease (or expires after 300 seconds)
and can be retried; stale deliveries cannot activate a newer generation. Previous
results remain active on failure. Retried attempts use distinct IDs so an old
worker cannot overwrite the new attempt. Partial recovery is labelled with its
warnings and point count. Missing originals have an explicit unavailable reason.

The archive map's optional full-detection footprint uses every occupied 1 m
square, compressed as horizontal runs, rather than sampled points. It is served
by `GET /api/survey/archive/{survey_id}/detection-coverage` after rebuild. This is
recorded coverage, not interpolated seafloor area. The 3D viewer still shows
processed surfaces for selected cells, with its existing support rules.

Georeferenced reef renders open facing true north, with east to the right and
free rotation around the reef centre. **Fit dataset** restores that starting
view. **Lock north-up** optionally restricts navigation to tilt, pan and zoom;
**Unlock rotation** restores free orbit and the side view. Opening another
dataset restores free rotation. Rectangle selection temporarily disables orbit
while dragging and does not change the chosen rotation lock.
The display accounts for UTM meridian convergence; measurements and stored
coordinates are unchanged. Datasets without geographic coordinates retain free
rotation. This viewer change requires no survey reprocessing.

### Raw sonar detections

The viewer's **Surface points** layer contains processed surface samples. The
separate **Raw sonar detections** option prepares a reusable index directly from
the original recording. Enable it and choose **Prepare / retry raw points** once.
It opens in a reduced overview clipped to the selected cell or cells, preserving
gaps between separate cells. The overview uses up to two million actual detections; it does
not use averaged or generated points. Full-detail modes preserve every valid
supported detection, including repeated positions.

Use **Select inspection rectangle** to drag an area in north-up top view, then
choose **Full detail in selected area**, or choose **Full detail in selected cells**.
Every mode stays within the selected cells. Counts,
chunk progress, partial-recording warnings and buffer estimates distinguish a
complete load from a reduced or interrupted one. Full-detail loading can be
slower and depends on available browser/GPU memory. Cancel and return to the
overview if needed. Combined views from multiple recordings offer a source-survey
selector; raw viewing loads one named recording at a time.

Raw mode initially hides the processed surface and surface points. They can be
enabled independently for comparison. Blue Z=0 and user-set yellow MSL reference
planes span the displayed raw footprint, and the depth ruler remains available.
These are display references, not a tide/datum correction to the recording.
Annotation and measurement tools still operate on the processed surface.

With **Matte surface (trial)** enabled, **Surface colour** switches between
blue-grey and **Depth — Turbo spectrum**. The full-spectrum depth palette matches raw detections
and retains matte lighting to reveal slopes. An available raw index supplies the
shared full-survey depth range without loading point chunks. Otherwise the
labelled selected-surface range is used. Colours use original Z values and are
unaffected by display exaggeration or MSL offset. The choice persists in this
browser; choosing blue-grey restores the muted appearance.

The API uses `GET/POST /api/survey/archive/{survey_id}/raw-points`, plus
`/manifest` and `/chunks/{chunk_id}` downloads. Index preparation shares the
export/rebuild lease and deletion protection. Cached binary chunks live under
the recording prefix, keyed by source hash, coordinate and format versions;
source recordings, existing CSV exports and surfaces are not replaced.

The August 23:13 recording was validated with 26,680,028 detections in 445 chunks
(320,160,336 binary bytes), matching its full XYZ export and 127,291 occupied
metre squares. Preparation took 194.65 seconds and the worker process peaked at
151,140 KiB RSS. The four-request HTTP audit, including coordinate/coverage
calculations, took 109.49 seconds. Browser GPU frame-rate and whole-survey visual
validation remain unmeasured because browser automation was unavailable.

Independent regression fixtures in `tests/fixtures/sonarview_coordinates.json`
cover both channels and multiple headings from the supplied August recording.
Reference association uses recorded power and consistent within-ping depth
differences, with no XY fitting. The depth difference is used only to identify
detections; output Z is unchanged. One of 20 sampled pings had no confident
association and is excluded. The 19 matched pings pass the 10 cm horizontal
95th-percentile requirement. See the local swath audit for full matching evidence.
