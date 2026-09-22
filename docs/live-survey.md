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
