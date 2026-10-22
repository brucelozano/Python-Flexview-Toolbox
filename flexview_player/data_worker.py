from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import numpy as np

from flexview_py.display import apply_palette, draw_polar_grid, render_cartesian_image
from flexview_py.geometry import compute_rangelist_from_header, magnitude_db, polar_to_cartesian
from flexview_py.imb_reader import IMBReader
from flexview_py.matlab_bridge import MatlabSession


@dataclass
class RenderedFrame:
	polar_bgr: np.ndarray
	cartesian_bgr: np.ndarray
	ping_number: int
	ping_index: int
	shape: tuple[int, int]
	beam_min_deg: float
	beam_max_deg: float
	range_min_m: float
	range_max_m: float
	cart_x_min_m: float
	cart_x_max_m: float
	cart_z_min_m: float
	cart_z_max_m: float


class MatlabDataWorker:
	"""Thin sync worker for MATLAB session lifecycle (Milestone 1).

	Threaded decoding/prefetch will be added in later milestones.
	"""

	def __init__(self) -> None:
		self._session: Optional[MatlabSession] = None
		self._reader: Optional[IMBReader] = None

	@property
	def connected(self) -> bool:
		return self._session is not None

	def connect(self) -> None:
		if self._session is None:
			self._session = MatlabSession()
			self._session.start()
			self._reader = IMBReader(self._session)

	def disconnect(self) -> None:
		if self._session is not None:
			self._session.stop()
			self._session = None
			self._reader = None

	def load_imb_frame(
		self,
		file_path: str,
		ping_index: int,
		cart_width_px: int = 900,
		cart_height_px: int = 700,
		show_grid: bool = True,
		auto_intensity_enabled: bool = True,
		display_low_db: float = -90.0,
		display_high_db: float = -30.0,
		palette_name: str = "hot",
		tvg_enabled: bool = False,
		tvg_ref_range_m: float = 1.0,
		tvg_log_slope_db_per_decade: float = 20.0,
		tvg_linear_slope_db_per_m: float = 0.0,
		tvg_offset_db: float = 0.0,
	) -> RenderedFrame:
		if self._session is None or self._reader is None:
			raise RuntimeError("MATLAB is not connected.")

		header, beam_angles, image = self._reader.load_frame(file_path, ping_index)
		ranges = compute_rangelist_from_header(header)

		# Polar image rendering (range x beam).
		polar_mag = np.abs(image).astype(np.float32)
		polar_norm = polar_mag - np.min(polar_mag)
		if np.max(polar_norm) > 0:
			polar_norm = polar_norm / np.max(polar_norm)
		polar_u8 = (polar_norm * 255.0).astype(np.uint8)
		polar_bgr = apply_palette(polar_u8, palette_name)

		# Cartesian fan rendering.
		x_coords, z_coords = polar_to_cartesian(ranges, beam_angles)
		cart_target_width = max(1, int(cart_width_px))
		cart_target_height = max(1, int(cart_height_px))
		cart_width_m = max(1e-6, float(np.max(x_coords) - np.min(x_coords)))
		cart_height_m = max(1e-6, float(np.max(z_coords)))
		# Use whichever panel dimension is limiting so we avoid upscaling in the UI.
		cart_aspect = cart_width_m / cart_height_m
		cart_render_width_px = max(
			cart_target_width,
			int(round(cart_target_height * cart_aspect)),
		)
		cart_bgr = render_cartesian_image(
			magnitude_db(image),
			x_coords,
			z_coords,
			output_width_px=cart_render_width_px,
			auto_intensity_enabled=bool(auto_intensity_enabled),
			display_low_db=float(display_low_db),
			display_high_db=float(display_high_db),
			palette_name=palette_name,
			tvg_enabled=bool(tvg_enabled),
			tvg_ref_range_m=float(tvg_ref_range_m),
			tvg_log_slope_db_per_decade=float(tvg_log_slope_db_per_decade),
			tvg_linear_slope_db_per_m=float(tvg_linear_slope_db_per_m),
			tvg_offset_db=float(tvg_offset_db),
		)
		if show_grid:
			draw_polar_grid(cart_bgr, ranges, beam_angles)
		cart_x_min = float(np.min(x_coords))
		cart_x_max = float(np.max(x_coords))
		cart_z_min = 0.0
		cart_z_max = float(np.max(z_coords))

		ping_number = int(float(header.get("Ping_Number", ping_index)))
		return RenderedFrame(
			polar_bgr=polar_bgr,
			cartesian_bgr=cart_bgr,
			ping_number=ping_number,
			ping_index=int(ping_index),
			shape=(int(image.shape[0]), int(image.shape[1])),
			beam_min_deg=float(np.min(beam_angles)),
			beam_max_deg=float(np.max(beam_angles)),
			range_min_m=float(np.min(ranges)),
			range_max_m=float(np.max(ranges)),
			cart_x_min_m=cart_x_min,
			cart_x_max_m=cart_x_max,
			cart_z_min_m=cart_z_min,
			cart_z_max_m=cart_z_max,
		)
