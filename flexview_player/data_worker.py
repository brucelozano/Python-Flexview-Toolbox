from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from flexview_py.display import (
	apply_palette,
	compute_cartesian_view_bounds,
	render_cartesian_image,
)
from flexview_py.geometry import compute_rangelist_from_header, magnitude_db, polar_to_cartesian
from flexview_py.imb_reader import IMBReader
from flexview_py.mmb_reader import MMBReader
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
		self._imb_reader: Optional[IMBReader] = None
		self._mmb_reader: Optional[MMBReader] = None
		self._decoded_cache: dict[tuple[str, int], tuple[dict, np.ndarray, np.ndarray, np.ndarray, int]] = {}
		self._decoded_cache_order: list[tuple[str, int]] = []
		self._decoded_cache_max = 8

	@property
	def connected(self) -> bool:
		return self._session is not None

	def connect(self) -> None:
		if self._session is None:
			self._session = MatlabSession()
			self._session.start()
			self._imb_reader = IMBReader(self._session)
			self._mmb_reader = MMBReader(self._session, default_image_index=0)

	def disconnect(self) -> None:
		if self._session is not None:
			self._session.stop()
			self._session = None
			self._imb_reader = None
			self._mmb_reader = None
			self._decoded_cache.clear()
			self._decoded_cache_order.clear()

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
		zoom_enabled: bool = False,
		zoom_scale: float = 1.0,
		zoom_center_x_m: float = float("nan"),
		zoom_center_z_m: float = float("nan"),
	) -> RenderedFrame:
		if self._session is None or self._imb_reader is None or self._mmb_reader is None:
			raise RuntimeError("MATLAB is not connected.")

		header, beam_angles, image, ranges, effective_ping_index = self._load_decoded_frame(
			file_path=file_path,
			ping_index=ping_index,
		)

		# Polar image rendering (range x beam).
		polar_mag = np.abs(image).astype(np.float32)
		polar_norm = polar_mag - np.min(polar_mag)
		if np.max(polar_norm) > 0:
			polar_norm = polar_norm / np.max(polar_norm)
		polar_u8 = (polar_norm * 255.0).astype(np.uint8)
		polar_bgr = apply_palette(polar_u8, palette_name)

		# Cartesian fan rendering.
		x_coords, z_coords = polar_to_cartesian(ranges, beam_angles)
		cart_x_min, cart_x_max, cart_z_min, cart_z_max = compute_cartesian_view_bounds(
			x_coords,
			z_coords,
			zoom_enabled=bool(zoom_enabled),
			zoom_scale=float(zoom_scale),
			zoom_center_x_m=float(zoom_center_x_m),
			zoom_center_z_m=float(zoom_center_z_m),
		)
		cart_target_width = max(1, int(cart_width_px))
		cart_target_height = max(1, int(cart_height_px))
		cart_width_m = max(1e-6, float(cart_x_max - cart_x_min))
		cart_height_m = max(1e-6, float(cart_z_max - cart_z_min))
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
			zoom_enabled=bool(zoom_enabled),
			zoom_scale=float(zoom_scale),
			zoom_center_x_m=float(zoom_center_x_m),
			zoom_center_z_m=float(zoom_center_z_m),
		)
		_ = show_grid  # Grid is drawn as a high-quality UI overlay in the main window.

		default_ping_number = effective_ping_index
		ping_number = int(float(header.get("Ping_Number", default_ping_number)))
		return RenderedFrame(
			polar_bgr=polar_bgr,
			cartesian_bgr=cart_bgr,
			ping_number=ping_number,
			ping_index=int(effective_ping_index),
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

	def _load_decoded_frame(
		self,
		*,
		file_path: str,
		ping_index: int,
	) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, int]:
		cache_key = (str(file_path), int(ping_index))
		cached = self._decoded_cache_get(cache_key)
		if cached is not None:
			header, beam_angles, image, ranges, effective_ping_index = cached
			return (
				dict(header),
				beam_angles.copy(),
				image.copy(),
				ranges.copy(),
				int(effective_ping_index),
			)

		ext = Path(file_path).suffix.lower()
		if ext == ".imb":
			header, beam_angles, image = self._imb_reader.load_frame(file_path, ping_index)
			ranges = compute_rangelist_from_header(header)
			effective_ping_index = int(ping_index)
		elif ext == ".mmb":
			header, beam_angles, image = self._mmb_reader.load_frame(file_path, ping_index)
			ranges = self._mmb_reader.last_range_list_m
			if ranges is None or ranges.size == 0:
				raise RuntimeError("MMB beamforming returned an empty range list.")
			effective_ping_index = (
				int(self._mmb_reader.last_actual_ping_index)
				if self._mmb_reader.last_actual_ping_index is not None
				else int(ping_index)
			)
		else:
			raise RuntimeError(f"Unsupported file type: {ext}")

		header_dict = dict(header) if isinstance(header, dict) else {}
		beam_angles_arr = np.asarray(beam_angles, dtype=np.float32).ravel()
		image_arr = np.asarray(image)
		ranges_arr = np.asarray(ranges, dtype=np.float32).ravel()
		self._decoded_cache_put(
			cache_key,
			(header_dict, beam_angles_arr, image_arr, ranges_arr, int(effective_ping_index)),
		)
		return header_dict, beam_angles_arr, image_arr, ranges_arr, int(effective_ping_index)

	def _decoded_cache_get(
		self,
		key: tuple[str, int],
	) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, int] | None:
		value = self._decoded_cache.get(key)
		if value is None:
			return None
		try:
			self._decoded_cache_order.remove(key)
		except ValueError:
			pass
		self._decoded_cache_order.append(key)
		return value

	def _decoded_cache_put(
		self,
		key: tuple[str, int],
		value: tuple[dict, np.ndarray, np.ndarray, np.ndarray, int],
	) -> None:
		if key not in self._decoded_cache:
			self._decoded_cache_order.append(key)
		self._decoded_cache[key] = value
		while len(self._decoded_cache_order) > self._decoded_cache_max:
			evict_key = self._decoded_cache_order.pop(0)
			self._decoded_cache.pop(evict_key, None)
