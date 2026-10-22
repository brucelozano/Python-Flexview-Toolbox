from __future__ import annotations

import math
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

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

	def state(self) -> PlayerState:
		return replace(self._state)

	def connect_matlab(self) -> None:
		try:
			self._worker.connect()
			self._state.connected = True
			self._state.decoder_backend = "matlab"
			self._emit_state("Connected to MATLAB. Decoder switched to MATLAB.")
			if self._state.file_path:
				self._load_frame(self._state.current_ping_index, status=False)
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

	def open_imb_file(self, file_path: str) -> None:
		path = Path(file_path)
		if not path.exists():
			self._emit_state(f"File not found: {file_path}")
			return
		if path.suffix.lower() not in {".imb", ".mmb"}:
			self._emit_state("Please select an .imb or .mmb file for v1 playback.")
			return
		self._state.file_path = str(path.resolve())
		self._state.current_ping_index = 0
		self._state.discovered_max_ping_index = 1000
		# Re-initialize center when the dataset changes so stale coordinates are not reused.
		self._state.zoom_center_x_m = float("nan")
		self._state.zoom_center_z_m = float("nan")
		self._emit_state(f"Loaded file: {self._state.file_path}")
		if self._decoder_ready():
			self._load_frame(0, status=True)

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

		try:
			frame: RenderedFrame = self._worker.load_imb_frame(
				self._state.file_path,
				ping_index,
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
			if ping_index > self._state.current_ping_index:
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
				self._emit_state(f"Failed to load ping {ping_index}: {exc}")
			return False

		self._state.current_ping_index = int(frame.ping_index)
		self._state.last_loaded_ping_number = int(frame.ping_number)
		self._state.discovered_max_ping_index = max(
			self._state.discovered_max_ping_index, self._state.current_ping_index + 1
		)
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
