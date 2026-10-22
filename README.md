# Flexview Player (Python + MATLAB Engine)

This project is focused on a Python player and annotation tool for Flexview IMB/MMB data.
MATLAB Engine is used for data decoding, and Python handles playback UI, rendering, and exports.

If you only need one command to get started:

```bash
py -3 -m flexview_player
```

Current player scope: `.imb` and `.mmb` files (`.mmb` uses default `image_index=0` in MVP mode).

## Quick Start

### 1) Prerequisites

- MATLAB installed locally.
- MATLAB Engine for Python installed from the same MATLAB version:

```matlab
cd(fullfile(matlabroot,'extern','engines','python'));
system('py -3 -m pip install .');
```

- Python 3.9+ recommended.

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

## Player Workflow

1. Click `Connect MATLAB`.
2. Click `Open` and choose an `.imb` or `.mmb` file.
3. Navigate pings with play/pause, step buttons, timeline, and ping index spinner.
4. Toggle `Grid` and `Fan Focus` as needed while reviewing the fan view.
5. Use measurement mode to stage and save distances on the fan view.

## Player Controls

### Playback

- `Play/Pause [Space]`: start/stop timed playback.
- `Previous [Left]`: load previous ping.
- `Next [Right]`: load next ping.
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
- Polar and cartesian fan views are shown side-by-side.

### Measurement

- `Measure: On/Off [A]`: enable/disable distance measurement mode.
- Click point A, then point B in the cartesian fan view to stage one measurement.
- `Z`: undo last click (or last staged measurement if no active click).
- `S`: save all staged measurements.
- `Annotator` button: set the annotator name used in saved measurement files.

## Features

- MATLAB connect/disconnect from the UI.
- `.imb` / `.mmb` file open + ping-by-ping playback.
- `.mmb` MVP path uses MATLAB beamforming per ping with default `image_index=0`.
- End-of-file handling while stepping/playing.
- Polar and cartesian fan rendering per frame.
- Fan Focus mode (`F`) to prioritize cartesian fan inspection.
- Dynamic cartesian render target synced to panel size and display scale (DPI-aware).
- Aspect-aware cartesian rendering to avoid unnecessary fan-view upscaling.
- Display controls: auto intensity, manual dB window (`Low dB`/`High dB`), and palette selection.
- Optional TVG gain stage applied before display windowing for far-range compensation.
- Cursor readout in fan view (`x`, `z`, `range`, `angle`).
- Staged measurement workflow with JSON export.

## Measurement Output Files

Saved under:

- `outputs/<dataset_name>/measurements/<annotator_slug>/all_measurements_<annotator_slug>.json`
- `outputs/<dataset_name>/measurements/<annotator_slug>/ping_<ping_index>_measurements_<annotator_slug>.json`

Each measurement includes:

- ping/frame metadata
- point A and point B in pixel/world coordinates
- distance in meters
- annotator identity and save timestamp

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
