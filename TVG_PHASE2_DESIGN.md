# Phase 2 TVG Design (Follow-up)

## Goal

Add optional range-dependent gain shaping to the cartesian fan render path without breaking
the new auto/manual intensity window controls.

## Proposed TVG Model

Use a transparent parameterization in dB over range, not opaque vendor coefficients:

- `tvg_enabled: bool`
- `tvg_ref_range_m: float` (default `1.0`)
- `tvg_log_slope_db_per_decade: float` (default `20.0`)
- `tvg_linear_slope_db_per_m: float` (default `0.0`)
- `tvg_offset_db: float` (default `0.0`)

For each sample range `r_m`, gain is:

`gain_db(r) = tvg_offset_db + tvg_log_slope_db_per_decade * log10(max(r_m, tvg_ref_range_m) / tvg_ref_range_m) + tvg_linear_slope_db_per_m * (r_m - tvg_ref_range_m)`

Then:

`db_tvg = db_raw + gain_db(r)`

This keeps units explicit and maps naturally to sonar workflows.

## Insertion Point

Apply TVG in `flexview_py/display.py` inside `render_cartesian_image()` before display windowing:

1. input `src_db`
2. **apply optional TVG gain by range**
3. auto/manual display window mapping
4. geometry remap
5. palette application

This keeps remap cache geometry-only and avoids cache churn from control changes.

## Data/State Changes

Phase 2 should extend `PlayerState` in `flexview_player/playback_controller.py` with:

- `tvg_enabled`
- `tvg_ref_range_m`
- `tvg_log_slope_db_per_decade`
- `tvg_linear_slope_db_per_m`
- `tvg_offset_db`

Add matching controller setters and pass-through in `MatlabDataWorker.load_imb_frame()`.

## UI Controls (Phase 2)

Add a compact `TVG` panel in `flexview_player/ui_main_window.py`:

- toggle: `TVG On/Off`
- sliders/spin boxes:
  - `Log Slope (dB/decade)`
  - `Linear Slope (dB/m)`
  - `Offset (dB)`
- optional advanced field: `Ref Range (m)`

Defaults should preserve current behavior when TVG is off.

## Persistence

Persist TVG fields in `QSettings` under `display/tvg/*` keys, loaded at startup like other display controls.

## Validation Plan

- Unit/smoke checks:
  - TVG off => output unchanged from phase 1 baseline.
  - Increasing log slope brightens farther ranges relative to near-field.
  - No NaN/inf propagation.
- UI behavior:
  - TVG changes refresh paused frame immediately.
  - Playback remains stable with no FPS regressions.

