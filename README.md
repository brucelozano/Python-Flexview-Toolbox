Flexview Python Reader (MATLAB Engine)

Overview
- This project provides a Python-based workflow for Kongsberg Mesotech Flexview/M3 data using MATLAB Engine to parse proprietary files (`.imb`, `.mmb`, `.pmb`).
- Python handles visualization, artifact export, and parity summaries for comparison against MATLAB example outputs.

Structure
- `flexview_py/`
  - `__init__.py`
  - `matlab_bridge.py` — MATLAB Engine session and wrappers for `load_image_data`, `load_raw_data`, `load_profile_data`.
  - `imb_reader.py` — High-level IMB reader returning NumPy arrays.
  - `geometry.py` — Range calculation, polar-to-cartesian mapping, display utilities.
  - `display.py` — OpenCV routines to render frames and simple polar grid.
  - `reporting.py` — JSON-safe summary helpers and parity stats utilities.
- `matlab_helpers/`
  - `load_raw_data_py.m` — MATLAB helper to expose raw-data header metadata in a Python-safe format.
  - `beamform_ping_py.m` — MATLAB helper that mirrors `test_beamformer` workflow and returns Python-safe outputs.
  - `generate_xyz_point_cloud_py.m` — MATLAB helper for georeferenced PMB export with Python-safe summary metadata.
  - `split_beam_ping_py.m` — MATLAB helper that mirrors `test_split_beam` workflow for parity outputs.
  - `export_google_map_py.m` — MATLAB helper for google-map track export summary.
- `flexview_player/`
  - Milestone 1 desktop player scaffold (`py -m flexview_player`) with PySide6 UI, MATLAB session controls, and IMB file-open flow.
- `examples/`
  - `play_imb.py` — Load one `.imb` ping and save raw/cartesian figures plus summary JSON.
  - `play_mmb.py` — Load one `.mmb` raw ping and save diagnostics plus summary JSON.
  - `play_beamformer.py` — Beamform one `.mmb` ping and save polar/fan views plus summary JSON.
  - `play_split_beam.py` — Run split-beam AOA workflow and save array/phase/magnitude artifacts plus summary JSON.
  - `export_pmb_xyz.py` — Export `.pmb` profile points to XYZ with preview image and summary JSON.
  - `export_pmb_xyz_georef.py` — Run full georeferenced PMB point-cloud workflow and export `.xyz` plus summary JSON.
  - `export_google_map.py` — Generate Google map tracks HTML and summary JSON from `.mmb` files.

Prerequisites
- MATLAB installed with MATLAB Engine for Python. Install the engine from MATLAB:
  - Launch the MATLAB version you plan to use.
  - In MATLAB Command Window:
    - `cd(fullfile(matlabroot,'extern','engines','python')); system('py -3 -m pip install .');`
- Python 3.9+ recommended.

Install
```bash
py -3 -m venv .venv
.venv\\Scripts\\activate
py -3 -m pip install -r requirements.txt
```

Usage

Desktop player (Milestone 1 scaffold)
```bash
py -3 -m flexview_player
```
This currently includes MATLAB connect/disconnect, IMB file-open, single-frame rendering
(polar + cartesian), ping seek/step controls, and timer-based play/pause playback.

IMB playback (single ping/frame)
```bash
py -3 examples\\play_imb.py --file "path\\to\\Intakes.imb" --ping-index 3 --save-dir outputs --no-show
```

MMB raw diagnostics (single ping)
```bash
py -3 examples\\play_mmb.py --file "path\\to\\Im30,LFM,fewpings.mmb" --ping-index 1 --image-index 0 --save-dir outputs --no-show
```

MMB beamforming parity (single ping)
```bash
py -3 examples\\play_beamformer.py --file "path\\to\\Im30,LFM,fewpings.mmb" --ping-index 1 --image-index 0 --save-dir outputs --no-show
```

PMB profile export (ping range)
```bash
py -3 examples\\export_pmb_xyz.py --file "path\\to\\Log_Profile.pmb" --ping-start 0 --ping-end 3 --save-dir outputs --no-show
```

Split-beam AOA parity workflow
```bash
py -3 examples\\play_split_beam.py --file "path\\to\\2014,Dec,16,10-53-25snip.mmb" --ping-index 1 --save-dir outputs --no-show
```

Georeferenced PMB point-cloud parity workflow
```bash
py -3 examples\\export_pmb_xyz_georef.py --file "path\\to\\Log_Profile.pmb" --ping-start 0 --ping-end 300 --save-dir outputs --no-show
```
By default this saves Python-generated diagnostic figures (position track, heading/course, pitch/roll).
To additionally save MATLAB-generated figures, pass `--save-matlab-figures`.

Google map track export parity workflow
```bash
py -3 examples\\export_google_map.py --folder "path\\to\\data" --html-filename "google_tracks_phase3.html" --ping-step 10 --save-dir outputs
```

Sample commands using bundled toolbox data
```bash
py -3 examples\\play_imb.py --file "M3_MATLAB_Toolbox_1.2\\data\\Intakes.imb" --ping-index 3 --save-dir outputs --no-show
py -3 examples\\play_mmb.py --file "M3_MATLAB_Toolbox_1.2\\data\\Im30,LFM,fewpings.mmb" --ping-index 1 --save-dir outputs --no-show
py -3 examples\\play_beamformer.py --file "M3_MATLAB_Toolbox_1.2\\data\\Im30,LFM,fewpings.mmb" --ping-index 1 --save-dir outputs --no-show
py -3 examples\\export_pmb_xyz.py --file "M3_MATLAB_Toolbox_1.2\\data\\Log_Profile.pmb" --ping-start 0 --ping-end 3 --save-dir outputs --no-show
py -3 examples\\play_split_beam.py --file "M3_MATLAB_Toolbox_1.2\\data\\2014,Dec,16,10-53-25snip.mmb" --ping-index 1 --save-dir outputs --no-show
py -3 examples\\export_pmb_xyz_georef.py --file "M3_MATLAB_Toolbox_1.2\\data\\Log_Profile.pmb" --ping-start 0 --ping-end 300 --save-dir outputs --no-show
py -3 examples\\export_google_map.py --folder "M3_MATLAB_Toolbox_1.2\\data" --html-filename "google_tracks_phase3.html" --ping-step 10 --save-dir outputs
```

Saved artifacts and parity summaries
- IMB:
  - `*_raw_polar_linear.png`
  - `*_cartesian_fan_log.png`
  - `*_image_summary.json`
- MMB:
  - `*_raw_magnitude.png`
  - `*_ref_pulse.png`
  - `*_raw_summary.json`
- MMB Beamformer:
  - `*_beamformed_polar_linear.png`
  - `*_beamformed_cartesian_log.png`
  - `*_beamformer_summary.json`
- MMB Split Beam:
  - `*_split_full_array.png`
  - `*_split_sub_array_1.png`
  - `*_split_sub_array_2.png`
  - `*_split_phase_diff.png`
  - `*_split_magnitude_fit.png`
  - `*_split_beam_summary.json`
- PMB:
  - `*_profile.xyz`
  - `*_profile_preview.png`
  - `*_profile_summary.json`
- PMB Georeferenced:
  - `*_georef_*.xyz`
  - `*_georef_*_preview.png`
  - `*_georef_*_summary.json`
  - `*_python_nav_latlon.png`
  - `*_python_nav_xy.png`
  - `*_python_heading_course.png`
  - `*_python_pitch_roll.png`
  - optional: `*_matlab_fig_*.png` when `--save-matlab-figures` is used
- Google Map:
  - `google_tracks*.html`
  - `markerwithlabel.js`
  - `*_google_map_summary.json`

The summary JSON files are intended for parity checks against MATLAB examples and include:
- key header fields (ping identifiers, beam/sample counts, timing parameters)
- array dimensions
- basic intensity/range statistics

MATLAB and Python parity command pairs

Split-beam parity (MATLAB)
```matlab
toolbox_root = 'C:\Users\bruce\Documents\Research\Python Flexview Reader\M3_MATLAB_Toolbox_1.2';
addpath(genpath(toolbox_root));
cd(fullfile(toolbox_root,'examples'));
test_split_beam
```

Split-beam parity (Python)
```bash
py -3 examples\\play_split_beam.py --file "M3_MATLAB_Toolbox_1.2\\data\\2014,Dec,16,10-53-25snip.mmb" --ping-index 1 --save-dir outputs --no-show
```

Compare key fields:
- AOA (`AOA_degrees`)
- beam offset (`beam_offset_degrees`)
- strength (`strength_dB`)
- range at target (`range_meters`)

Georeferenced PMB parity (MATLAB)
```matlab
toolbox_root = 'C:\Users\bruce\Documents\Research\Python Flexview Reader\M3_MATLAB_Toolbox_1.2';
addpath(genpath(toolbox_root));
settings.filename_pmb = fullfile(toolbox_root,'data','Log_Profile.pmb');
settings.filename_xyz = fullfile(toolbox_root,'data','Log_Profile_from_matlab.xyz');
options.ping_start = 0;
options.ping_end = 300;
options.z_max = 0;
options.pitch_sensor_offset = 1;
generate_xyz_point_cloud(settings, options);
```

Georeferenced PMB parity (Python)
```bash
py -3 examples\\export_pmb_xyz_georef.py --file "M3_MATLAB_Toolbox_1.2\\data\\Log_Profile.pmb" --ping-start 0 --ping-end 300 --z-max 0 --pitch-sensor-offset 1 --save-dir outputs --no-show
```

Compare key fields:
- total point count
- XYZ bounds (`x_min/max`, `y_min/max`, `z_min/max`)

Google map export parity (MATLAB)
```matlab
toolbox_root = 'C:\Users\bruce\Documents\Research\Python Flexview Reader\M3_MATLAB_Toolbox_1.2';
addpath(genpath(toolbox_root));
cd(fullfile(toolbox_root,'examples'));
test_google_map
```

Google map export parity (Python)
```bash
py -3 examples\\export_google_map.py --folder "M3_MATLAB_Toolbox_1.2\\data" --html-filename "google_tracks_phase3.html" --ping-step 10 --save-dir outputs
```

Compare key fields:
- number of source files
- track count and marker count
- SW/NE map bounds

Design Notes
- Data access flows through MATLAB Engine to leverage vendor readers.
- IMB/MMB/PMB decode paths all use MATLAB readers as source of truth.
- Geometry formulas in Python mirror MATLAB formulas used in toolbox examples.


