from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from flexview_py.display import normalize_palette_name

from .data_worker import MatlabDataWorker, RenderedFrame

DISPLAY_DB_FLOOR = -120.0
DISPLAY_DB_CEILING = 0.0
DISPLAY_DB_MIN_SPAN = 1.0
TVG_REF_RANGE_MIN_M = 0.1
TVG_REF_RANGE_MAX_M = 100.0
TVG_LOG_SLOPE_MIN = -20.0
TVG_LOG_SLOPE_MAX = 60.0
TVG_LINEAR_SLOPE_MIN = -5.0
TVG_LINEAR_SLOPE_MAX = 5.0
TVG_OFFSET_MIN = -40.0
TVG_OFFSET_MAX = 40.0
ZOOM_SCALE_MIN = 1.0
ZOOM_SCALE_MAX = 8.0
MMB_PREFETCH_CHUNK_SIZE_DEFAULT = 500
MMB_PREFETCH_TRIGGER_RATIO = 0.75


class _PrefetchWorker(QObject):
	"""Background decode-cache warm worker."""

	progress = Signal(int, int, int, int)
	finished = Signal(int, int, int, bool, str)

	def __init__(
		self,
		*,
		data_worker: MatlabDataWorker,
		file_path: str,
		start_ping_index: int,
		frame_count: int,
		decoder_backend: str,
		cancel_event: threading.Event,
	) -> None:
		super().__init__()
		self._data_worker = data_worker
		self._file_path = file_path
		self._start_ping_index = int(start_ping_index)
		self._frame_count = max(0, int(frame_count))
		self._decoder_backend = decoder_backend
		self._cancel_event = cancel_event

	@Slot()
	def run(self) -> None:
		error_message = ""
		try:
			loaded, reached_eof = self._data_worker.warm_decoded_range(
				file_path=self._file_path,
				start_ping_index=self._start_ping_index,
				frame_count=self._frame_count,
				decoder_backend=self._decoder_backend,
				cancel_event=self._cancel_event,
				progress_callback=self._on_progress,
			)
		except Exception as exc:  # pragma: no cover
			loaded = 0
			reached_eof = False
			error_message = str(exc)
		self.finished.emit(
			self._start_ping_index,
			self._frame_count,
			int(loaded),
			bool(reached_eof),
			error_message,
		)

	def _on_progress(self, start: int, count: int, loaded: int, ping_index: int) -> None:
		self.progress.emit(int(start), int(count), int(loaded), int(ping_index))


@dataclass
class PlayerState:
	file_path: str = ""
	connected: bool = False
	decoder_backend: str = "python"
	is_playing: bool = False
	current_ping_index: int = 0
	playback_rate: float = 1.0
	auto_intensity_enabled: bool = True
	display_low_db: float = -90.0
	display_high_db: float = -30.0
	palette_name: str = "hot"
	tvg_enabled: bool = False
	tvg_ref_range_m: float = 1.0
	tvg_log_slope_db_per_decade: float = 20.0
	tvg_linear_slope_db_per_m: float = 0.0
	tvg_offset_db: float = 0.0
	zoom_enabled: bool = False
	zoom_scale: float = 1.0
	zoom_center_x_m: float = float("nan")
	zoom_center_z_m: float = float("nan")
	last_loaded_ping_number: int = 0
	discovered_max_ping_index: int = 1000


class PlaybackController(QObject):
	"""Controller for player state, rendering, and playback loop."""

	status_message = Signal(str)
	state_changed = Signal(object)
	frame_ready = Signal(object)
	prefetch_event = Signal(object)

	def __init__(self) -> None:
		super().__init__()
		self._worker = MatlabDataWorker()
		self._state = PlayerState()
		self._show_grid = True
		self._cart_render_width_px = 900
		self._cart_render_height_px = 700
		self._timer = QTimer(self)
		self._timer.timeout.connect(self._on_timer_tick)
		self._set_timer_interval()
		self._mmb_prefetch_enabled = False
		self._mmb_prefetch_chunk_size = MMB_PREFETCH_CHUNK_SIZE_DEFAULT
		self._prefetch_trigger_ratio = MMB_PREFETCH_TRIGGER_RATIO
		self._prefetch_loaded_until_exclusive = 0
		self._prefetch_initial_end_exclusive = 0
		self._prefetch_reached_eof = False
		self._prefetch_backend = "python"
		self._prefetch_wait_target: int | None = None
		self._prefetch_resume_play = False
		self._prefetch_pending_request: tuple[int, int, bool, str] | None = None
		self._prefetch_active = False
		self._prefetch_thread: QThread | None = None
		self._prefetch_worker: _PrefetchWorker | None = None
		self._prefetch_cancel_event = threading.Event()

	def state(self) -> PlayerState:
		return replace(self._state)

	def configure_mmb_prefetch(self, *, enabled: bool, chunk_size: int) -> None:
		self._mmb_prefetch_enabled = bool(enabled)
		self._mmb_prefetch_chunk_size = max(32, int(chunk_size))
		if self._mmb_prefetch_enabled:
			self._worker.set_decoded_cache_max(max(64, self._mmb_prefetch_chunk_size * 3))
		else:
			self._worker.set_decoded_cache_max(64)
			self._cancel_prefetch()

	def estimate_frame_count(self, file_path: str, *, allow_slow: bool = True) -> int | None:
		return self._worker.frame_count(file_path, allow_slow=allow_slow)

	def estimate_cached_contiguous(
		self,
		*,
		file_path: str,
		start_ping_index: int,
		decoder_backend: str,
		max_probe: int = 5000,
	) -> int:
		return self._worker.cached_contiguous_count(
			file_path=file_path,
			start_ping_index=int(start_ping_index),
			decoder_backend=decoder_backend,
			max_probe=max_probe,
		)

	def refresh_prefetch_window(self) -> None:
		if not self._state.file_path:
			return
		self._configure_prefetch_for_current_file()

	def prefetch_ahead(self, frame_count: int) -> bool:
		if not self._is_prefetch_supported_for_current_file():
			self._emit_state("Manual prefetch is available for MMB/.00x files.")
			return False
		requested = max(1, int(frame_count))
		# Keep a reasonable decode cache window for manual-only workflows.
		self._worker.set_decoded_cache_max(max(64, requested * 3))
		start_idx = int(self._state.current_ping_index) + 1
		self._schedule_prefetch_chunk(
			start_ping_index=start_idx,
			urgent=True,
			reason="manual",
			frame_count_override=requested,
			allow_when_disabled=True,
		)
		self._emit_state(f"Manual prefetch queued for {requested} frame(s) from ping {start_idx}.")
		return True

	def connect_matlab(self) -> None:
		try:
			self._worker.connect()
			self._state.connected = True
			self._state.decoder_backend = "matlab"
			self._emit_state("Connected to MATLAB. Decoder switched to MATLAB.")
			if self._state.file_path:
				self._load_frame(self._state.current_ping_index, status=False)
				self._configure_prefetch_for_current_file()
		except Exception as exc:  # pragma: no cover
			self._emit_state(f"Failed to connect MATLAB: {exc}")

	def disconnect_matlab(self) -> None:
		self._timer.stop()
		self._worker.disconnect()
		self._state.connected = False
		self._state.is_playing = False
		self._state.decoder_backend = "python"
		self._emit_state("Disconnected from MATLAB. Decoder switched to Python.")
		if self._state.file_path:
			self._load_frame(self._state.current_ping_index, status=False)
			self._configure_prefetch_for_current_file()

	def open_imb_file(self, file_path: str) -> None:
		path = Path(file_path)
		if not path.exists():
			self._emit_state(f"File not found: {file_path}")
			return
		if not self._is_supported_source(path):
			self._emit_state("Please select an .imb/.mmb file (or split .001/.002/... segment) for playback.")
			return
		self._cancel_prefetch()
		self._state.file_path = str(path.resolve())
		self._state.current_ping_index = 0
		self._state.discovered_max_ping_index = 1000
		# Re-initialize center when the dataset changes so stale coordinates are not reused.
		self._state.zoom_center_x_m = float("nan")
		self._state.zoom_center_z_m = float("nan")
		self._prefetch_wait_target = None
		self._prefetch_resume_play = False
		if self._is_mmb_like(path) and self._mmb_prefetch_enabled:
			self._worker.set_decoded_cache_max(max(64, self._mmb_prefetch_chunk_size * 3))
		self._emit_state(f"Loaded file: {self._state.file_path}")
		if self._decoder_ready():
			self._load_frame(0, status=True)
			self._configure_prefetch_for_current_file()

	def toggle_play(self) -> None:
		if not self._state.file_path:
			self._emit_state("Load an .imb or .mmb file first.")
			return
		if not self._decoder_ready():
			self._emit_state("Connect MATLAB first or switch back to Python decoder.")
			return
		self._state.is_playing = not self._state.is_playing
		if self._state.is_playing:
			self._set_timer_interval()
			self._timer.start()
			self._emit_state("Playback started.")
		else:
			self._timer.stop()
			self._emit_state("Playback paused.")

	def step_forward(self) -> None:
		self._load_frame(self._state.current_ping_index + 1, status=True)

	def step_back(self) -> None:
		self._load_frame(max(0, self._state.current_ping_index - 1), status=True)

	def set_ping_index(self, ping_index: int) -> None:
		self._load_frame(max(0, int(ping_index)), status=False)

	def set_playback_rate(self, playback_rate: float) -> None:
		self._state.playback_rate = max(0.05, float(playback_rate))
		self._set_timer_interval()
		self._emit_state(f"Playback rate set to {self._state.playback_rate:.2f}x.")

	def set_show_grid(self, show_grid: bool) -> None:
		self._show_grid = bool(show_grid)

	def set_auto_intensity(self, enabled: bool) -> None:
		auto_enabled = bool(enabled)
		if auto_enabled == self._state.auto_intensity_enabled:
			return
		self._state.auto_intensity_enabled = auto_enabled
		self._refresh_display_state()

	def set_display_window_db(
		self,
		*,
		low_db: float | None = None,
		high_db: float | None = None,
	) -> None:
		low = self._state.display_low_db if low_db is None else float(low_db)
		high = self._state.display_high_db if high_db is None else float(high_db)
		low, high = self._clamp_display_window_db(low, high)
		if (
			abs(low - self._state.display_low_db) < 1e-6
			and abs(high - self._state.display_high_db) < 1e-6
		):
			return
		self._state.display_low_db = low
		self._state.display_high_db = high
		self._refresh_display_state()

	def set_palette(self, palette_name: str) -> None:
		normalized = normalize_palette_name(palette_name)
		if normalized == self._state.palette_name:
			return
		self._state.palette_name = normalized
		self._refresh_display_state()

	def set_tvg_enabled(self, enabled: bool) -> None:
		tvg_enabled = bool(enabled)
		if tvg_enabled == self._state.tvg_enabled:
			return
		self._state.tvg_enabled = tvg_enabled
		self._refresh_display_state()

	def set_tvg_parameters(
		self,
		*,
		ref_range_m: float | None = None,
		log_slope_db_per_decade: float | None = None,
		linear_slope_db_per_m: float | None = None,
		offset_db: float | None = None,
	) -> None:
		ref_range = (
			self._state.tvg_ref_range_m if ref_range_m is None else float(ref_range_m)
		)
		log_slope = (
			self._state.tvg_log_slope_db_per_decade
			if log_slope_db_per_decade is None
			else float(log_slope_db_per_decade)
		)
		linear_slope = (
			self._state.tvg_linear_slope_db_per_m
			if linear_slope_db_per_m is None
			else float(linear_slope_db_per_m)
		)
		offset = self._state.tvg_offset_db if offset_db is None else float(offset_db)
		ref_range, log_slope, linear_slope, offset = self._clamp_tvg_parameters(
			ref_range=ref_range,
			log_slope=log_slope,
			linear_slope=linear_slope,
			offset=offset,
		)
		if (
			abs(ref_range - self._state.tvg_ref_range_m) < 1e-6
			and abs(log_slope - self._state.tvg_log_slope_db_per_decade) < 1e-6
			and abs(linear_slope - self._state.tvg_linear_slope_db_per_m) < 1e-6
			and abs(offset - self._state.tvg_offset_db) < 1e-6
		):
			return
		self._state.tvg_ref_range_m = ref_range
		self._state.tvg_log_slope_db_per_decade = log_slope
		self._state.tvg_linear_slope_db_per_m = linear_slope
		self._state.tvg_offset_db = offset
		self._refresh_display_state()

	def set_zoom_enabled(self, enabled: bool) -> None:
		zoom_enabled = bool(enabled)
		if zoom_enabled == self._state.zoom_enabled:
			return
		self._state.zoom_enabled = zoom_enabled
		self._refresh_display_state()

	def set_zoom_scale(self, zoom_scale: float) -> None:
		scale_clamped = self._clamp_zoom_scale(zoom_scale)
		if abs(scale_clamped - self._state.zoom_scale) < 1e-6:
			return
		self._state.zoom_scale = scale_clamped
		self._refresh_display_state()

	def set_zoom_center_world(self, x_m: float, z_m: float) -> None:
		center_x = float(x_m)
		center_z = float(z_m)
		if not (math.isfinite(center_x) and math.isfinite(center_z)):
			return
		if (
			math.isfinite(self._state.zoom_center_x_m)
			and math.isfinite(self._state.zoom_center_z_m)
			and abs(center_x - self._state.zoom_center_x_m) < 1e-6
			and abs(center_z - self._state.zoom_center_z_m) < 1e-6
		):
			return
		self._state.zoom_center_x_m = center_x
		self._state.zoom_center_z_m = center_z
		self._refresh_display_state()

	def reset_zoom(self) -> None:
		changed = False
		if self._state.zoom_enabled:
			self._state.zoom_enabled = False
			changed = True
		if abs(self._state.zoom_scale - 1.0) > 1e-6:
			self._state.zoom_scale = 1.0
			changed = True
		if math.isfinite(self._state.zoom_center_x_m) or math.isfinite(
			self._state.zoom_center_z_m
		):
			self._state.zoom_center_x_m = float("nan")
			self._state.zoom_center_z_m = float("nan")
			changed = True
		if changed:
			self._refresh_display_state()

	def set_cart_render_target(
		self,
		width_px: int,
		height_px: int,
		*,
		refresh_if_paused: bool = False,
	) -> None:
		target_w = max(1, int(width_px))
		target_h = max(1, int(height_px))
		if (
			target_w == self._cart_render_width_px
			and target_h == self._cart_render_height_px
		):
			return
		self._cart_render_width_px = target_w
		self._cart_render_height_px = target_h
		if (
			refresh_if_paused
			and self._decoder_ready()
			and bool(self._state.file_path)
			and not self._state.is_playing
		):
			self._load_frame(self._state.current_ping_index, status=False)

	def _load_frame(self, ping_index: int, status: bool = True) -> bool:
		if not self._state.file_path:
			if status:
				self._emit_state("Load an .imb or .mmb file first.")
			return False
		if not self._decoder_ready():
			if status:
				self._emit_state("Connect MATLAB first or switch back to Python decoder.")
			return False
		requested_ping_index = max(0, int(ping_index))
		if self._should_wait_for_prefetch(requested_ping_index):
			self._begin_prefetch_wait(requested_ping_index)
			if status:
				self._emit_state(f"Waiting for prefetched frame {requested_ping_index}...")
			else:
				self.state_changed.emit(self.state())
			return False

		try:
			frame: RenderedFrame = self._worker.load_imb_frame(
				self._state.file_path,
				requested_ping_index,
				decoder_backend=self._state.decoder_backend,
				cart_width_px=self._cart_render_width_px,
				cart_height_px=self._cart_render_height_px,
				show_grid=self._show_grid,
				auto_intensity_enabled=self._state.auto_intensity_enabled,
				display_low_db=self._state.display_low_db,
				display_high_db=self._state.display_high_db,
				palette_name=self._state.palette_name,
				tvg_enabled=self._state.tvg_enabled,
				tvg_ref_range_m=self._state.tvg_ref_range_m,
				tvg_log_slope_db_per_decade=self._state.tvg_log_slope_db_per_decade,
				tvg_linear_slope_db_per_m=self._state.tvg_linear_slope_db_per_m,
				tvg_offset_db=self._state.tvg_offset_db,
				zoom_enabled=self._state.zoom_enabled,
				zoom_scale=self._state.zoom_scale,
				zoom_center_x_m=self._state.zoom_center_x_m,
				zoom_center_z_m=self._state.zoom_center_z_m,
			)
		except Exception as exc:
			if requested_ping_index > self._state.current_ping_index:
				# Common forward-step failure means EOF.
				self._state.discovered_max_ping_index = max(
					self._state.current_ping_index, self._state.discovered_max_ping_index
				)
				self._state.is_playing = False
				self._timer.stop()
				if status:
					self._emit_state(
						f"Reached end of file near ping index {self._state.current_ping_index}."
					)
				else:
					self.state_changed.emit(self.state())
				return False
			if status:
				self._emit_state(f"Failed to load ping {requested_ping_index}: {exc}")
			return False

		self._state.current_ping_index = int(frame.ping_index)
		self._state.last_loaded_ping_number = int(frame.ping_number)
		self._state.discovered_max_ping_index = max(
			self._state.discovered_max_ping_index, self._state.current_ping_index + 1
		)
		if self._is_prefetch_enabled_for_current_file():
			self._maybe_schedule_next_prefetch(self._state.current_ping_index)
		self.frame_ready.emit(frame)
		if status:
			self._emit_state(
				f"Loaded ping index {frame.ping_index} (Ping_Number {frame.ping_number})."
			)
		else:
			self.state_changed.emit(self.state())
		return True

	def _on_timer_tick(self) -> None:
		ok = self._load_frame(self._state.current_ping_index + 1, status=False)
		if not ok:
			if self._prefetch_wait_target is not None:
				return
			self._emit_state(
				f"Playback stopped at ping index {self._state.current_ping_index} (end/error)."
			)

	def _set_timer_interval(self) -> None:
		# Base target of 10 frames/sec at 1x.
		base_interval_ms = 100.0
		interval = max(10, int(round(base_interval_ms / self._state.playback_rate)))
		self._timer.setInterval(interval)

	def _emit_state(self, message: str) -> None:
		self.status_message.emit(message)
		self.state_changed.emit(self.state())

	def _refresh_display_state(self) -> None:
		self.state_changed.emit(self.state())
		if self._decoder_ready() and bool(self._state.file_path) and not self._state.is_playing:
			self._load_frame(self._state.current_ping_index, status=False)

	def _is_prefetch_enabled_for_current_file(self) -> bool:
		if not self._mmb_prefetch_enabled:
			return False
		return self._is_prefetch_supported_for_current_file()

	def _is_prefetch_supported_for_current_file(self) -> bool:
		if not self._state.file_path:
			return False
		return self._is_mmb_like(Path(self._state.file_path))

	@staticmethod
	def _is_mmb_like(path: Path) -> bool:
		suffix = path.suffix.lower()
		return suffix == ".mmb" or re.fullmatch(r"\.\d{3}", suffix) is not None

	@classmethod
	def _is_supported_source(cls, path: Path) -> bool:
		return path.suffix.lower() == ".imb" or cls._is_mmb_like(path)

	def _configure_prefetch_for_current_file(self) -> None:
		self._cancel_prefetch()
		self._prefetch_pending_request = None
		self._prefetch_wait_target = None
		self._prefetch_resume_play = False
		self._prefetch_loaded_until_exclusive = 0
		self._prefetch_initial_end_exclusive = 0
		self._prefetch_reached_eof = False
		self._prefetch_backend = self._state.decoder_backend
		if not self._is_prefetch_enabled_for_current_file():
			self.prefetch_event.emit({"type": "prefetch_disabled"})
			return
		self._prefetch_loaded_until_exclusive = max(
			0,
			int(self._state.current_ping_index) + 1,
		)
		self._prefetch_initial_end_exclusive = self._prefetch_loaded_until_exclusive + int(
			self._mmb_prefetch_chunk_size
		)
		self.prefetch_event.emit(
			{
				"type": "prefetch_ready",
				"chunk_size": int(self._mmb_prefetch_chunk_size),
				"loaded_until_exclusive": int(self._prefetch_loaded_until_exclusive),
			}
		)
		self._schedule_prefetch_chunk(
			start_ping_index=self._prefetch_loaded_until_exclusive,
			urgent=False,
			reason="initial",
		)

	def _should_wait_for_prefetch(self, ping_index: int) -> bool:
		if not self._is_prefetch_enabled_for_current_file():
			return False
		# After the initial pre-render window, keep classic playback behavior
		# and let cache misses decode inline without blocking dialogs.
		if int(ping_index) >= int(self._prefetch_initial_end_exclusive):
			return False
		# Only block during the initial pre-render warm-up itself.
		# If those early frames were later evicted, fallback to normal decode.
		if int(self._prefetch_loaded_until_exclusive) >= int(self._prefetch_initial_end_exclusive):
			return False
		if self._prefetch_reached_eof and ping_index >= self._prefetch_loaded_until_exclusive:
			return False
		if self._worker.has_decoded_frame(
			file_path=self._state.file_path,
			ping_index=ping_index,
			decoder_backend=self._state.decoder_backend,
		):
			return False
		return True

	def _begin_prefetch_wait(self, target_ping_index: int) -> None:
		self._prefetch_wait_target = int(target_ping_index)
		self.prefetch_event.emit(
			{
				"type": "prefetch_waiting",
				"target_ping_index": int(target_ping_index),
			}
		)
		if self._state.is_playing:
			self._prefetch_resume_play = True
			self._state.is_playing = False
			self._timer.stop()
			self.state_changed.emit(self.state())
		chunk_start = (int(target_ping_index) // int(self._mmb_prefetch_chunk_size)) * int(
			self._mmb_prefetch_chunk_size
		)
		self._schedule_prefetch_chunk(
			start_ping_index=chunk_start,
			urgent=True,
			reason="wait_target",
		)

	def _maybe_schedule_next_prefetch(self, current_ping_index: int) -> None:
		if not self._is_prefetch_enabled_for_current_file():
			return
		if self._prefetch_reached_eof:
			return
		if self._prefetch_loaded_until_exclusive <= 0:
			return
		trigger_margin = max(
			1,
			int(round(float(self._mmb_prefetch_chunk_size) * (1.0 - self._prefetch_trigger_ratio))),
		)
		trigger_index = self._prefetch_loaded_until_exclusive - trigger_margin
		if int(current_ping_index) >= int(trigger_index):
			self._schedule_prefetch_chunk(
				start_ping_index=self._prefetch_loaded_until_exclusive,
				urgent=False,
				reason="rolling",
			)

	def _schedule_prefetch_chunk_with_count(
		self,
		*,
		start_ping_index: int,
		urgent: bool,
		reason: str,
		frame_count: int,
		allow_when_disabled: bool = False,
	) -> None:
		if not self._is_prefetch_supported_for_current_file():
			return
		if not allow_when_disabled and not self._is_prefetch_enabled_for_current_file():
			return
		if self._prefetch_reached_eof and not urgent:
			return
		start_idx = max(0, int(start_ping_index))
		count = max(1, int(frame_count))
		if not urgent and start_idx < self._prefetch_loaded_until_exclusive:
			start_idx = self._prefetch_loaded_until_exclusive
		if self._prefetch_active:
			if self._prefetch_pending_request is None:
				self._prefetch_pending_request = (start_idx, count, urgent, reason)
			else:
				existing_start, existing_count, existing_urgent, _ = self._prefetch_pending_request
				combined_start = min(existing_start, start_idx)
				combined_count = max(existing_count, count)
				self._prefetch_pending_request = (
					combined_start,
					combined_count,
					existing_urgent or urgent,
					"queued",
				)
			return
		self._start_prefetch_chunk(
			start_ping_index=start_idx,
			frame_count=count,
			urgent=urgent,
			reason=reason,
		)

	def _schedule_prefetch_chunk(
		self,
		*,
		start_ping_index: int,
		urgent: bool,
		reason: str,
		frame_count_override: int | None = None,
		allow_when_disabled: bool = False,
	) -> None:
		frame_count = (
			int(self._mmb_prefetch_chunk_size)
			if frame_count_override is None
			else max(1, int(frame_count_override))
		)
		self._schedule_prefetch_chunk_with_count(
			start_ping_index=start_ping_index,
			urgent=urgent,
			reason=reason,
			frame_count=frame_count,
			allow_when_disabled=allow_when_disabled,
		)

	def _start_prefetch_chunk(
		self,
		*,
		start_ping_index: int,
		frame_count: int,
		urgent: bool,
		reason: str,
	) -> None:
		if not self._state.file_path:
			return
		self._prefetch_cancel_event = threading.Event()
		self._prefetch_active = True
		self._prefetch_thread = QThread(self)
		self._prefetch_worker = _PrefetchWorker(
			data_worker=self._worker,
			file_path=self._state.file_path,
			start_ping_index=int(start_ping_index),
			frame_count=max(1, int(frame_count)),
			decoder_backend=self._state.decoder_backend,
			cancel_event=self._prefetch_cancel_event,
		)
		self._prefetch_worker.moveToThread(self._prefetch_thread)
		self._prefetch_thread.started.connect(self._prefetch_worker.run)
		self._prefetch_worker.progress.connect(self._on_prefetch_progress)
		self._prefetch_worker.finished.connect(self._on_prefetch_finished)
		self._prefetch_worker.finished.connect(self._prefetch_thread.quit)
		self._prefetch_worker.finished.connect(self._prefetch_worker.deleteLater)
		self._prefetch_thread.finished.connect(self._prefetch_thread.deleteLater)
		self.prefetch_event.emit(
			{
				"type": "prefetch_started",
				"start_ping_index": int(start_ping_index),
				"frame_count": max(1, int(frame_count)),
				"urgent": bool(urgent),
				"reason": reason,
			}
		)
		self._prefetch_thread.start()

	def _cancel_prefetch(self) -> None:
		self._prefetch_pending_request = None
		self._prefetch_active = False
		if self._prefetch_worker is not None:
			self._prefetch_cancel_event.set()
		if self._prefetch_thread is not None and self._prefetch_thread.isRunning():
			self._prefetch_thread.quit()
			self._prefetch_thread.wait(250)
		self._prefetch_worker = None
		self._prefetch_thread = None

	@Slot(int, int, int, int)
	def _on_prefetch_progress(
		self,
		start_ping_index: int,
		frame_count: int,
		loaded_count: int,
		latest_ping_index: int,
	) -> None:
		self.prefetch_event.emit(
			{
				"type": "prefetch_progress",
				"start_ping_index": int(start_ping_index),
				"frame_count": int(frame_count),
				"loaded_count": int(loaded_count),
				"latest_ping_index": int(latest_ping_index),
				"target_ping_index": self._prefetch_wait_target,
			}
		)
		self._check_prefetch_wait_target_ready()

	@Slot(int, int, int, bool, str)
	def _on_prefetch_finished(
		self,
		start_ping_index: int,
		frame_count: int,
		loaded_count: int,
		reached_eof: bool,
		error_message: str,
	) -> None:
		self._prefetch_active = False
		self._prefetch_worker = None
		self._prefetch_thread = None
		start_idx = int(start_ping_index)
		loaded = max(0, int(loaded_count))
		if loaded > 0:
			chunk_end = start_idx + loaded
			if start_idx <= self._prefetch_loaded_until_exclusive:
				self._prefetch_loaded_until_exclusive = max(self._prefetch_loaded_until_exclusive, chunk_end)
			else:
				self._prefetch_loaded_until_exclusive = chunk_end
			self._state.discovered_max_ping_index = max(
				self._state.discovered_max_ping_index,
				self._prefetch_loaded_until_exclusive,
			)
			self.state_changed.emit(self.state())
		if bool(reached_eof):
			self._prefetch_reached_eof = True
		self.prefetch_event.emit(
			{
				"type": "prefetch_finished",
				"start_ping_index": start_idx,
				"frame_count": int(frame_count),
				"loaded_count": loaded,
				"reached_eof": bool(reached_eof),
				"error_message": str(error_message or ""),
				"loaded_until_exclusive": int(self._prefetch_loaded_until_exclusive),
			}
		)
		self._check_prefetch_wait_target_ready()
		if self._prefetch_pending_request is not None and not self._prefetch_reached_eof:
			next_start, next_count, next_urgent, next_reason = self._prefetch_pending_request
			self._prefetch_pending_request = None
			self._start_prefetch_chunk(
				start_ping_index=int(next_start),
				frame_count=max(1, int(next_count)),
				urgent=bool(next_urgent),
				reason=str(next_reason),
			)

	def _check_prefetch_wait_target_ready(self) -> None:
		target = self._prefetch_wait_target
		if target is None:
			return
		if not self._state.file_path:
			return
		if not self._worker.has_decoded_frame(
			file_path=self._state.file_path,
			ping_index=int(target),
			decoder_backend=self._state.decoder_backend,
		):
			if self._prefetch_reached_eof and not self._prefetch_active:
				self._prefetch_wait_target = None
				self._prefetch_resume_play = False
				self.prefetch_event.emit(
					{
						"type": "prefetch_wait_failed",
						"target_ping_index": int(target),
					}
				)
			return

		self._prefetch_wait_target = None
		loaded = self._load_frame(int(target), status=False)
		self.prefetch_event.emit(
			{
				"type": "prefetch_wait_ready",
				"target_ping_index": int(target),
				"loaded": bool(loaded),
			}
		)
		if loaded and self._prefetch_resume_play:
			self._prefetch_resume_play = False
			self._state.is_playing = True
			self._set_timer_interval()
			self._timer.start()
			self._emit_state("Playback resumed after prefetch catch-up.")
		elif not loaded:
			self._prefetch_resume_play = False

	def _decoder_ready(self) -> bool:
		if self._state.decoder_backend == "python":
			return True
		return bool(self._state.connected)

	@staticmethod
	def _clamp_display_window_db(low: float, high: float) -> tuple[float, float]:
		floor = DISPLAY_DB_FLOOR
		ceiling = DISPLAY_DB_CEILING
		min_span = DISPLAY_DB_MIN_SPAN

		low_clamped = min(ceiling - min_span, max(floor, float(low)))
		high_clamped = min(ceiling, max(floor + min_span, float(high)))
		if high_clamped - low_clamped >= min_span:
			return low_clamped, high_clamped

		center = (low_clamped + high_clamped) * 0.5
		low_clamped = center - (min_span * 0.5)
		high_clamped = center + (min_span * 0.5)
		if low_clamped < floor:
			low_clamped = floor
			high_clamped = floor + min_span
		if high_clamped > ceiling:
			high_clamped = ceiling
			low_clamped = ceiling - min_span
		return low_clamped, high_clamped

	@staticmethod
	def _clamp_tvg_parameters(
		*,
		ref_range: float,
		log_slope: float,
		linear_slope: float,
		offset: float,
	) -> tuple[float, float, float, float]:
		ref_range_clamped = min(TVG_REF_RANGE_MAX_M, max(TVG_REF_RANGE_MIN_M, float(ref_range)))
		log_slope_clamped = min(TVG_LOG_SLOPE_MAX, max(TVG_LOG_SLOPE_MIN, float(log_slope)))
		linear_slope_clamped = min(
			TVG_LINEAR_SLOPE_MAX, max(TVG_LINEAR_SLOPE_MIN, float(linear_slope))
		)
		offset_clamped = min(TVG_OFFSET_MAX, max(TVG_OFFSET_MIN, float(offset)))
		return (
			ref_range_clamped,
			log_slope_clamped,
			linear_slope_clamped,
			offset_clamped,
		)

	@staticmethod
	def _clamp_zoom_scale(zoom_scale: float) -> float:
		return min(ZOOM_SCALE_MAX, max(ZOOM_SCALE_MIN, float(zoom_scale)))
