from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

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
from flexview_py.native_flexview_reader import NativeFlexviewReader

DISK_CACHE_BUDGET_DEFAULT_BYTES = 10 * 1024 * 1024 * 1024
DISK_CACHE_EVICT_EVERY_N_WRITES = 16
FRAME_COUNT_INDEX_FILENAME = "frame_count_index.json"
DECODED_CACHE_KEY_VERSION = "v2"


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
	ping_timestamp_utc: str
	# Raw magnitude dB (ranges x beams, no TVG/windowing) + axes, for annotation statistics.
	polar_db: np.ndarray
	ranges_m: np.ndarray
	beam_angles_deg: np.ndarray


class MatlabDataWorker:
	"""Data worker with Python-native and optional MATLAB decode backends."""

	def __init__(self) -> None:
		self._session: Optional[MatlabSession] = None
		self._imb_reader: Optional[IMBReader] = None
		self._mmb_reader: Optional[MMBReader] = None
		self._native_readers: dict[str, NativeFlexviewReader] = {}
		self._decode_lock = threading.RLock()
		self._cache_lock = threading.RLock()
		self._decoded_cache: dict[
			tuple[str, int, str],
			tuple[dict, np.ndarray, np.ndarray, np.ndarray, int],
		] = {}
		self._decoded_cache_order: list[tuple[str, int, str]] = []
		self._decoded_cache_max = 8
		self._disk_cache_lock = threading.RLock()
		self._disk_cache_root = Path(__file__).resolve().parents[1] / "outputs" / ".decoded_frame_cache"
		self._disk_cache_budget_bytes = DISK_CACHE_BUDGET_DEFAULT_BYTES
		self._disk_cache_enabled = True
		self._disk_cache_write_count = 0
		self._frame_count_index_path: Path | None = None
		self._frame_count_index: dict[str, dict[str, int | str]] = {}
		try:
			self._disk_cache_root.mkdir(parents=True, exist_ok=True)
		except OSError:
			self._disk_cache_enabled = False
		if self._disk_cache_enabled:
			self._frame_count_index_path = self._disk_cache_root / FRAME_COUNT_INDEX_FILENAME
			self._load_frame_count_index_locked()
			self._enforce_disk_cache_budget(force=True)

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
			with self._cache_lock:
				self._decoded_cache.clear()
				self._decoded_cache_order.clear()

	def set_decoded_cache_max(self, size: int) -> None:
		with self._cache_lock:
			self._decoded_cache_max = max(8, int(size))
			while len(self._decoded_cache_order) > self._decoded_cache_max:
				evict_key = self._decoded_cache_order.pop(0)
				self._decoded_cache.pop(evict_key, None)

	def set_disk_cache_budget_bytes(self, size_bytes: int) -> None:
		self._disk_cache_budget_bytes = max(0, int(size_bytes))
		self._enforce_disk_cache_budget(force=True)

	def has_decoded_frame(self, *, file_path: str, ping_index: int, decoder_backend: str) -> bool:
		backend = "matlab" if str(decoder_backend).strip().lower() == "matlab" else "python"
		file_key = str(Path(file_path).resolve())
		cache_key = (file_key, int(ping_index), backend)
		with self._cache_lock:
			if cache_key in self._decoded_cache:
				return True
		if not self._disk_cache_enabled or self._disk_cache_budget_bytes <= 0:
			return False
		cache_path = self._disk_cache_path(cache_key)
		return cache_path.exists()

	def cached_contiguous_count(
		self,
		*,
		file_path: str,
		start_ping_index: int,
		decoder_backend: str,
		max_probe: int,
	) -> int:
		backend = "matlab" if str(decoder_backend).strip().lower() == "matlab" else "python"
		file_key = str(Path(file_path).resolve())
		probe_limit = max(0, int(max_probe))
		if probe_limit <= 0:
			return 0
		with self._cache_lock:
			memory_hits: set[int] = {
				int(key[1]) for key in self._decoded_cache.keys() if key[0] == file_key and key[2] == backend
			}
		signature = self._file_signature(file_key)
		count = 0
		for offset in range(probe_limit):
			ping_index = int(start_ping_index) + offset
			if ping_index in memory_hits:
				count += 1
				continue
			if not self._disk_cache_enabled or self._disk_cache_budget_bytes <= 0:
				break
			disk_path = self._disk_cache_path_for_signature(
				file_key=file_key,
				ping_index=ping_index,
				backend=backend,
				signature=signature,
			)
			if disk_path.exists():
				count += 1
				continue
			break
		return count

	def frame_count(self, file_path: str, *, allow_slow: bool = True) -> int | None:
		file_key = str(Path(file_path).resolve())
		signature = self._file_signature(file_key)
		with self._disk_cache_lock:
			entry = self._frame_count_index.get(file_key)
			if isinstance(entry, dict) and str(entry.get("signature", "")) == signature:
				try:
					cached_count = int(entry.get("count", 0))
				except (TypeError, ValueError):
					cached_count = 0
				if cached_count > 0:
					return cached_count
		if not allow_slow:
			return None
		try:
			with self._decode_lock:
				reader = self._native_readers.get(file_key)
				if reader is None:
					reader = NativeFlexviewReader(file_key)
					self._native_readers[file_key] = reader
				count = int(reader.frame_count)
		except Exception:
			return None
		if count <= 0:
			return None
		with self._disk_cache_lock:
			self._frame_count_index[file_key] = {"signature": signature, "count": int(count)}
			self._save_frame_count_index_locked()
		return count

	def warm_decoded_range(
		self,
		*,
		file_path: str,
		start_ping_index: int,
		frame_count: int,
		decoder_backend: str,
		cancel_event: threading.Event | None = None,
		progress_callback: Callable[[int, int, int, int], None] | None = None,
	) -> tuple[int, bool]:
		loaded = 0
		reached_eof = False
		target_count = max(0, int(frame_count))
		for _ in range(target_count):
			if cancel_event is not None and cancel_event.is_set():
				break
			ping_index = int(start_ping_index) + loaded
			try:
				self._load_decoded_frame(
					file_path=file_path,
					ping_index=ping_index,
					decoder_backend=decoder_backend,
				)
			except Exception:
				reached_eof = True
				break
			loaded += 1
			if progress_callback is not None:
				progress_callback(int(start_ping_index), target_count, loaded, ping_index)
		return loaded, reached_eof

	def load_imb_frame(
		self,
		file_path: str,
		ping_index: int,
		decoder_backend: str = "python",
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
		backend = "matlab" if str(decoder_backend).strip().lower() == "matlab" else "python"
		if backend == "matlab" and (
			self._session is None or self._imb_reader is None or self._mmb_reader is None
		):
			raise RuntimeError("MATLAB decoder requested but MATLAB is not connected.")

		header, beam_angles, image, ranges, effective_ping_index = self._load_decoded_frame(
			file_path=file_path,
			ping_index=ping_index,
			decoder_backend=backend,
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
		polar_db = magnitude_db(image)
		cart_bgr = render_cartesian_image(
			polar_db,
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
		ping_timestamp_utc = self._extract_ping_timestamp_utc(header)
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
			ping_timestamp_utc=ping_timestamp_utc,
			polar_db=polar_db,
			ranges_m=np.asarray(ranges, dtype=np.float32),
			beam_angles_deg=np.asarray(beam_angles, dtype=np.float32),
		)

	@staticmethod
	def _extract_ping_timestamp_utc(header: dict) -> str:
		if not isinstance(header, dict):
			return "-"
		def _to_float_scalar(value: object) -> float | None:
			if value is None:
				return None
			if isinstance(value, np.ndarray):
				if value.size <= 0:
					return None
				value = value.reshape(-1)[0]
			try:
				out = float(value)
			except (TypeError, ValueError):
				return None
			return out if np.isfinite(out) else None

		epoch_seconds = _to_float_scalar(header.get("Time_s", None))
		ms_value_raw = _to_float_scalar(header.get("Time_ms", None))
		if epoch_seconds is None:
			epoch_seconds = _to_float_scalar(header.get("Time_Seconds", None))
			ms_value_raw = _to_float_scalar(header.get("Time_Milliseconds", None))
		if epoch_seconds is None:
			return "-"
		try:
			ms_value = int(round(ms_value_raw)) if ms_value_raw is not None else 0
		except (TypeError, ValueError):
			ms_value = 0
		if 0 <= ms_value < 1000 and abs(epoch_seconds - round(epoch_seconds)) < 1e-6:
			epoch_seconds += (float(ms_value) / 1000.0)
		try:
			dt = datetime.fromtimestamp(epoch_seconds, tz=timezone.utc)
		except (OverflowError, OSError, ValueError):
			return "-"
		return dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] + " UTC"

	def _load_decoded_frame(
		self,
		*,
		file_path: str,
		ping_index: int,
		decoder_backend: str,
	) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, int]:
		backend = "matlab" if str(decoder_backend).strip().lower() == "matlab" else "python"
		file_key = str(Path(file_path).resolve())
		cache_key = (file_key, int(ping_index), backend)
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
		disk_cached = self._decoded_cache_get_disk(cache_key)
		if disk_cached is not None:
			self._decoded_cache_put(cache_key, disk_cached)
			header, beam_angles, image, ranges, effective_ping_index = disk_cached
			return (
				dict(header),
				beam_angles.copy(),
				image.copy(),
				ranges.copy(),
				int(effective_ping_index),
			)

		with self._decode_lock:
			# Foreground playback and prefetch can race to the same frame;
			# re-check cache under decode lock before doing expensive decode work.
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
			disk_cached = self._decoded_cache_get_disk(cache_key)
			if disk_cached is not None:
				self._decoded_cache_put(cache_key, disk_cached)
				header, beam_angles, image, ranges, effective_ping_index = disk_cached
				return (
					dict(header),
					beam_angles.copy(),
					image.copy(),
					ranges.copy(),
					int(effective_ping_index),
				)

			ext = Path(file_path).suffix.lower()
			if backend == "matlab":
				if ext == ".imb":
					header, beam_angles, image = self._imb_reader.load_frame(file_path, ping_index)
					ranges = compute_rangelist_from_header(header)
					effective_ping_index = int(ping_index)
				elif ext == ".mmb" or re.fullmatch(r"\.\d{3}", ext) is not None:
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
			else:
				header, beam_angles, image, ranges, effective_ping_index = self._load_native_frame(
					file_path=file_key,
					ping_index=ping_index,
				)

			header_dict = dict(header) if isinstance(header, dict) else {}
			beam_angles_arr = np.asarray(beam_angles, dtype=np.float32).ravel()
			image_arr = np.asarray(image)
			ranges_arr = np.asarray(ranges, dtype=np.float32).ravel()
			self._decoded_cache_put(
				cache_key,
				(header_dict, beam_angles_arr, image_arr, ranges_arr, int(effective_ping_index)),
			)
			self._decoded_cache_put_disk(
				cache_key,
				(header_dict, beam_angles_arr, image_arr, ranges_arr, int(effective_ping_index)),
			)
			return header_dict, beam_angles_arr, image_arr, ranges_arr, int(effective_ping_index)

	def _load_native_frame(
		self,
		*,
		file_path: str,
		ping_index: int,
	) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, int]:
		native_key = str(Path(file_path).resolve())
		reader = self._native_readers.get(native_key)
		if reader is None:
			reader = NativeFlexviewReader(native_key)
			self._native_readers[native_key] = reader
		frame = reader.load_frame(int(ping_index))
		return (
			dict(frame.header),
			frame.beam_angles_deg,
			frame.image,
			frame.ranges_m,
			int(frame.ping_index),
		)

	def _decoded_cache_get(
		self,
		key: tuple[str, int, str],
	) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, int] | None:
		with self._cache_lock:
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
		key: tuple[str, int, str],
		value: tuple[dict, np.ndarray, np.ndarray, np.ndarray, int],
	) -> None:
		with self._cache_lock:
			if key not in self._decoded_cache:
				self._decoded_cache_order.append(key)
			self._decoded_cache[key] = value
			while len(self._decoded_cache_order) > self._decoded_cache_max:
				evict_key = self._decoded_cache_order.pop(0)
				self._decoded_cache.pop(evict_key, None)

	def _disk_cache_path(self, key: tuple[str, int, str]) -> Path:
		file_key, ping_index, backend = key
		signature = self._file_signature(file_key)
		return self._disk_cache_path_for_signature(
			file_key=file_key,
			ping_index=int(ping_index),
			backend=backend,
			signature=signature,
		)

	def _disk_cache_path_for_signature(
		self,
		*,
		file_key: str,
		ping_index: int,
		backend: str,
		signature: str,
	) -> Path:
		digest = hashlib.sha1(
			f"{DECODED_CACHE_KEY_VERSION}|{file_key}|{backend}|{signature}|{int(ping_index)}".encode("utf-8")
		).hexdigest()
		return self._disk_cache_root / digest[:2] / digest[2:4] / f"{digest}.npz"

	@staticmethod
	def _file_signature(file_path: str) -> str:
		try:
			stat = Path(file_path).stat()
		except OSError:
			return "missing"
		return f"{int(stat.st_size)}:{int(stat.st_mtime_ns)}"

	def _decoded_cache_get_disk(
		self,
		key: tuple[str, int, str],
	) -> tuple[dict, np.ndarray, np.ndarray, np.ndarray, int] | None:
		if not self._disk_cache_enabled or self._disk_cache_budget_bytes <= 0:
			return None
		cache_path = self._disk_cache_path(key)
		if not cache_path.exists():
			return None
		with self._disk_cache_lock:
			try:
				with np.load(cache_path, allow_pickle=False) as bundle:
					header_json = str(bundle["header_json"].item())
					header = json.loads(header_json)
					beam_angles = np.asarray(bundle["beam_angles"]).copy()
					image = np.asarray(bundle["image"]).copy()
					ranges = np.asarray(bundle["ranges"]).copy()
					effective_ping_index = int(np.asarray(bundle["effective_ping_index"]).item())
				os.utime(cache_path, None)
			except Exception:
				try:
					cache_path.unlink(missing_ok=True)
				except OSError:
					pass
				return None
		if not isinstance(header, dict):
			return None
		return header, beam_angles, image, ranges, effective_ping_index

	def _decoded_cache_put_disk(
		self,
		key: tuple[str, int, str],
		value: tuple[dict, np.ndarray, np.ndarray, np.ndarray, int],
	) -> None:
		if not self._disk_cache_enabled or self._disk_cache_budget_bytes <= 0:
			return
		cache_path = self._disk_cache_path(key)
		tmp_path = cache_path.with_name(f"{cache_path.name}.tmp.npz")
		header, beam_angles, image, ranges, effective_ping_index = value
		header_json = json.dumps(header, separators=(",", ":"))
		with self._disk_cache_lock:
			try:
				cache_path.parent.mkdir(parents=True, exist_ok=True)
				np.savez_compressed(
					tmp_path,
					header_json=np.array(header_json),
					beam_angles=np.asarray(beam_angles),
					image=np.asarray(image),
					ranges=np.asarray(ranges),
					effective_ping_index=np.array(int(effective_ping_index), dtype=np.int64),
				)
				tmp_path.replace(cache_path)
				self._disk_cache_write_count += 1
			except Exception:
				try:
					tmp_path.unlink(missing_ok=True)
				except OSError:
					pass
				return
		self._enforce_disk_cache_budget(force=False)

	def _enforce_disk_cache_budget(self, *, force: bool) -> None:
		if not self._disk_cache_enabled or self._disk_cache_budget_bytes <= 0:
			return
		if not force and (self._disk_cache_write_count % DISK_CACHE_EVICT_EVERY_N_WRITES) != 0:
			return
		with self._disk_cache_lock:
			cache_files = [p for p in self._disk_cache_root.rglob("*.npz") if p.is_file()]
			if not cache_files:
				return
			file_rows: list[tuple[float, int, Path]] = []
			total_bytes = 0
			for path in cache_files:
				try:
					stat = path.stat()
				except OSError:
					continue
				file_size = int(stat.st_size)
				total_bytes += file_size
				file_rows.append((float(stat.st_mtime), file_size, path))
			if total_bytes <= self._disk_cache_budget_bytes:
				return
			file_rows.sort(key=lambda row: row[0])
			for _, file_size, path in file_rows:
				try:
					path.unlink(missing_ok=True)
				except OSError:
					continue
				total_bytes -= file_size
				if total_bytes <= self._disk_cache_budget_bytes:
					break

	def _load_frame_count_index_locked(self) -> None:
		if not self._disk_cache_enabled or self._frame_count_index_path is None:
			return
		try:
			payload = json.loads(self._frame_count_index_path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError):
			self._frame_count_index = {}
			return
		if not isinstance(payload, dict):
			self._frame_count_index = {}
			return
		index: dict[str, dict[str, int | str]] = {}
		for key, value in payload.items():
			if not isinstance(key, str) or not isinstance(value, dict):
				continue
			signature = str(value.get("signature", ""))
			try:
				count = int(value.get("count", 0))
			except (TypeError, ValueError):
				continue
			if not signature or count <= 0:
				continue
			index[key] = {"signature": signature, "count": count}
		self._frame_count_index = index

	def _save_frame_count_index_locked(self) -> None:
		if not self._disk_cache_enabled or self._frame_count_index_path is None:
			return
		try:
			self._frame_count_index_path.write_text(
				json.dumps(self._frame_count_index, indent=2),
				encoding="utf-8",
			)
		except OSError:
			return
