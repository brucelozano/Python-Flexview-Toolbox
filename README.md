# Flexview Player (Python + Optional MATLAB Engine)

This project is focused on a Python player and annotation tool for Flexview IMB/MMB data.
Python-native decoding is the default path; MATLAB Engine is optional for cross-checking and parity workflows.

If you only need one command to get started:

```bash
py -3 -m flexview_player
```

Current player scope: `.imb` and `.mmb` files (`.mmb` uses default `image_index=0` in MVP mode).

## Quick Start

### 1) Prerequisites

- Python 3.9+ recommended.

Optional (only if you want MATLAB decoder / parity checks):

- MATLAB installed locally.
- MATLAB Engine for Python installed from the same MATLAB version:

```matlab
cd(fullfile(matlabroot,'extern','engines','python'));
system('py -3 -m pip install .');
```

### 2) Install dependencies

```bash
py -3 -m venv .venv
.venv\Scripts\activate
py -3 -m pip install -r requirements.txt
```

### 3) Launch player

```bash
py -3 -m flexview_player
```

## Build Windows EXE

Create a Windows GUI build with PyInstaller:

```powershell
.\scripts\build_windows_exe.ps1 -Clean
```

Output is written to `dist\FlexviewPlayer\`.

Notes:

- The build includes `matlab_helpers` and `M3_MATLAB_Toolbox_1.2`.
- `.mmb` / `.00x` workflows require MATLAB Engine availability at runtime (the app auto-switches to MATLAB decoder for those files).
- `.imb` can run on the native Python decoder without MATLAB.

### Package a Shareable ZIP

After building, create a portable release archive:

```powershell
.\scripts\package_windows_release.ps1
```

Output is written to `releases\` as a versioned zip containing the full `FlexviewPlayer` app folder.

## Player Workflow

1. Click `Open` and choose an `.imb`/`.mmb` file (split MMB segments like `.001` are also supported).
   - For `.mmb`/`.00x`, the player auto-connects MATLAB decoder before load.
   - For `.mmb`/`.00x`, the player asks whether to enable pre-render and how many frames to decode per chunk.
2. Playback uses the Python decoder by default.
3. Optional: click `Connect MATLAB (Use MATLAB Decoder)` to switch decoding to MATLAB for verification.
3. Navigate pings with play/pause, step buttons, timeline, and ping index spinner. The info panel shows `Index: N / last (total pings)`; the total is counted in the background when a file is opened (header scan, cached) and also caps the timeline and spinner. Ping indices are per file: each split segment (`.mmb`, `.001`, ...) is its own 0-based file, so the total covers only the segment you opened.
4. Toggle `Grid` and `Fan Focus` as needed while reviewing the fan view.
5. Use measurement mode to stage and save line/box/polygon annotations on the fan view.

## Player Controls

### Playback

- `Play/Pause [Space]`: start/stop timed playback.
- `Previous [Left]`: load previous ping.
- `Next [Right]`: load next ping.
- `Prefetch Ahead`: manually queue prefetch from current ping forward (works even when initial pre-render was disabled).
- `Ping` spinner and `Timeline` slider: jump to any ping index.
- `Speed`: `0.25x`, `0.5x`, `1.0x`, `2.0x`.
- `Auto Intensity`: automatic per-ping display windowing for quick visual review.
- `Low dB` / `High dB`: manual display window controls (`-120 dB` to `0 dB`) when auto intensity is off.
- `Palette`: choose `Hot`, `Inferno`, `Viridis`, `Cividis`, or `Gray` for fan and polar display.
- `TVG`: optional range-dependent gain shaping with controls for log slope (`-20` to `60` dB/dec),
  linear slope (`-5.0` to `5.0` dB/m), and offset (`-40` to `40` dB).

### View

- `Grid: On/Off [G]`: toggle fan-view grid overlay.
- `Fan Focus: On/Off [F]`: hide/show the polar panel to give the fan view more space.
- `Flip: On/Off [V]`: vertically flip the fan view (narrow apex on top, widening downward). Annotations stay in world coordinates; saved records include `view_flipped`.
- `No Targets [N]`: mark the current ping as reviewed with nothing to annotate (writes an empty ping file); press again to clear. Refused if the ping already has saved or staged annotations.
- `Saved Annotations: On/Off [H]`: show/hide already-saved annotations (and the "no targets" text) on the fan; staged annotations always stay visible. Persisted per dataset.
- `Export CSV` (top right): write one CSV of every saved annotation for the dataset (all annotators), ordered by ping index. See *CSV Report* below.
- `Zoom: On/Off [Z]`: toggle cartesian zoom mode.
- `Reset Zoom [R]`: reset zoom quickly when zoom mode is enabled.
- Polar and cartesian fan views are shown side-by-side.

### Measurement

- `Measure: On/Off [A]`: enable/disable annotation mode.
- `Type`: choose `Line`, `Box`, or `Polygon`.
- `Line`: click point A, then point B in the cartesian fan view to stage one annotation.
- `Box`: click and drag a region in the cartesian fan view, then release to stage one annotation.
- `Polygon`: click vertices point-by-point, then double-click or press `Enter` to close and stage.
- `Ctrl+Z`: undo last click (or last staged annotation if no active click).
- `S`: save all staged measurements. A dialog asks for a class per numbered annotation (habitat, shark, fish, school, diver, unknown; prefilled with the last class used). Staged annotations show a numbered badge that continues from the annotations already saved on that ping.
- Saved annotations for the current ping are redrawn automatically (numbered badge, class label, class colour: habitat green, shark red, fish blue, school purple, diver yellow, unknown gray). Staged, not-yet-saved annotations are teal. A ping marked with `No Targets` shows "Reviewed - no targets".
- `Annotator` button: set the annotator name used in saved measurement files.

## Features

- Python decoder is default for `.imb` / `.mmb`.
- Optional MATLAB connect/disconnect from the UI for decoder switching/parity checks.
- `.imb` / `.mmb` file open + ping-by-ping playback.
- `.mmb` MVP path uses MATLAB beamforming per ping with default `image_index=0`.
- Optional rolling `.mmb` prefetch with chunk-size prompt.
- Manual `Prefetch Ahead` queue for on-demand background decode while annotating.
- Bottom-right status-bar progress for prefetch jobs (non-blocking for normal prefetch).
- Decoded-frame disk cache is enabled for playback/pre-render reuse across rewinds and sessions (LRU eviction, 10 GB budget).
- MMB split sequences (`.mmb`, `.001`, `.002`, ...) are read in canonical order.
- End-of-file handling while stepping/playing.
- Polar and cartesian fan rendering per frame.
- Fan Focus mode (`F`) to prioritize cartesian fan inspection.
- Dynamic cartesian render target synced to panel size and display scale (DPI-aware).
- Aspect-aware cartesian rendering to avoid unnecessary fan-view upscaling.
- Display controls: auto intensity, manual dB window (`Low dB`/`High dB`), and palette selection.
- Optional TVG gain stage applied before display windowing for far-range compensation.
- Cursor readout in fan view (`x`, `z`, `range`, `angle`).
- Per-frame `Ping Time` readout from decoded header metadata (when available in the source header).
- Staged line/box/polygon annotation workflow with JSON export.

## Measurement Output Files

Saved under:

- `outputs/<dataset_name>_project/measurements/<annotator_slug>/ping_<ping_index>_measurements_<annotator_slug>.json`
- Split files: ping indices restart at 0 in every segment, so each segment gets its own project: `.mmb`/`.imb` -> `<stem>_project`, `.001` -> `<stem>.001_project`, and so on. Annotations, project state, and CSV reports are never shared between segments.

One file per ping per annotator, holding every annotation (all types) saved on that ping. An empty file (`[]`) means the ping was reviewed with no targets. Each save appends to it with an atomic write-then-swap. Older `all_measurements_*` and `*_<annotation_type>.json` copies are no longer written; they can be deleted, and a CSV report should be built by reading the `ping_*` files.

Each measurement includes:

- `measurement_id` (`P<ping_index>-<n>`) and `ping_measurement_index` (n, the number shown on the badge)
- ping/frame metadata (including `ping_timestamp_utc`, absent on older records)
- `annotation_type` (`line`, `box`, `polygon`)
- `class_name` (`habitat`, `shark`, `fish`, `school`, `diver`, `unknown`; absent on older records)
- `view_flipped` (whether the fan view was flipped when saved)
- `geometry.points` with pixel/world coordinates for all points
- `metrics` (type-specific values):
  - line: `length_m` (plus `point_a`, `point_b`, `distance_m`, which are written for lines only)
  - box/polygon: size and position (`area_m2`, `perimeter_m`, centroid `x/z`, `centroid_range_m`, `centroid_angle_deg`; boxes also width/height/diagonal/aspect ratio (box centroid is the corner mean); polygons `vertex_count`)
  - box/polygon intensity inside the region, from raw magnitude dB (no display TVG/windowing, -120 dB floor): `intensity_samples`, `intensity_mean_db`, `intensity_max_db`, `intensity_std_db` (`null` if no samples fall inside)
  - older records lack the centroid range/angle and intensity keys, so readers should treat them as optional
- annotator identity and save timestamp

The player reads legacy measurement JSON from `outputs/<dataset_name>/measurements/...` when the new `_project` location does not exist yet, then continues saving to `_project`.

## CSV Report

`Export CSV` writes `outputs/<dataset_name>_project/reports/annotations_<dataset_name>.csv` (overwritten each time; regenerate any time from the saved `ping_*` JSON files).

- One row per annotation, sorted by `ping_index` (numeric), then annotator, then `annotation_number`.
- Only pings that were annotated or marked `No Targets` appear. Pings you never touched (for example 0-9 and 21-50 when only 10-20 were reviewed) are simply absent.
- A ping marked `No Targets` is one row with `status = no_targets` and the annotation columns empty; annotated rows have `status = annotated`.
- Columns: `dataset, annotator, ping_index, ping_number, ping_timestamp_utc, annotation_number, measurement_id, status, annotation_type, class_name`, then centroid (`centroid_x_m, centroid_z_m, centroid_range_m, centroid_angle_deg`; for lines the midpoint), size (`length_m, width_m, height_m, area_m2, perimeter_m, vertex_count`), intensity (`intensity_samples, intensity_mean_db, intensity_max_db, intensity_std_db`), and `saved_at_utc`.
- Metrics that do not apply to a type, or that older records lack (including `ping_timestamp_utc` on records saved before it was added), are left empty.
- Saved as UTF-8 with BOM so Excel opens it directly. If the file is open in Excel when you export, close it first.

## Dataset Project State

Per-dataset GUI/session state is saved in:

- `outputs/<dataset_name>_project/project_state.json`

When reopening a dataset, the player restores the saved state (display options, view toggles, playback rate, and last ping index).  
If no state file exists yet, defaults are applied:

- TVG log slope: `-5 dB/dec`
- TVG linear slope: `-0.5 dB/m`
- TVG offset: `-1 dB`
- palette: `inferno`
- fan focus: on
- grid: on

## Script Commands (Non-Player Workflows)

These scripts are for parity checks and data exports beyond interactive player use.

```bash
py -3 examples\play_imb.py --file "path\to\Intakes.imb" --ping-index 3 --save-dir outputs --no-show
py -3 examples\play_mmb.py --file "path\to\Im30,LFM,fewpings.mmb" --ping-index 1 --image-index 0 --save-dir outputs --no-show
py -3 examples\play_beamformer.py --file "path\to\Im30,LFM,fewpings.mmb" --ping-index 1 --image-index 0 --save-dir outputs --no-show
py -3 examples\play_split_beam.py --file "path\to\2014,Dec,16,10-53-25snip.mmb" --ping-index 1 --save-dir outputs --no-show
py -3 examples\export_pmb_xyz.py --file "path\to\Log_Profile.pmb" --ping-start 0 --ping-end 3 --save-dir outputs --no-show
py -3 examples\export_pmb_xyz_georef.py --file "path\to\Log_Profile.pmb" --ping-start 0 --ping-end 300 --save-dir outputs --no-show
py -3 examples\export_google_map.py --folder "path\to\data" --html-filename "google_tracks_phase3.html" --ping-step 10 --save-dir outputs
```

## Project Layout

- `flexview_player/`: desktop player (PySide6 UI + playback controller).
- `flexview_py/`: MATLAB bridge, readers, geometry, rendering, reporting helpers.
- `matlab_helpers/`: MATLAB helper functions used by Python tooling.
- `examples/`: script-based parity and export workflows.
