from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .data_worker import MatlabDataWorker, RenderedFrame


@dataclass
class PlayerState:
	file_path: str = ""
	connected: bool = False
	is_playing: bool = False
	current_ping_index: int = 0
	playback_rate: float = 1.0
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
		self._timer = QTimer(self)
		self._timer.timeout.connect(self._on_timer_tick)
		self._set_timer_interval()

	def state(self) -> PlayerState:
		return replace(self._state)

	def connect_matlab(self) -> None:
		try:
			self._worker.connect()
			self._state.connected = True
			self._emit_state("Connected to MATLAB.")
			if self._state.file_path:
				self._load_frame(self._state.current_ping_index, status=False)
		except Exception as exc:  # pragma: no cover
			self._emit_state(f"Failed to connect MATLAB: {exc}")

	def disconnect_matlab(self) -> None:
		self._timer.stop()
		self._worker.disconnect()
		self._state.connected = False
		self._state.is_playing = False
		self._emit_state("Disconnected from MATLAB.")

	def open_imb_file(self, file_path: str) -> None:
		path = Path(file_path)
		if not path.exists():
			self._emit_state(f"File not found: {file_path}")
			return
		if path.suffix.lower() != ".imb":
			self._emit_state("Please select a .imb file for v1 playback.")
			return
		self._state.file_path = str(path.resolve())
		self._state.current_ping_index = 0
		self._state.discovered_max_ping_index = 1000
		self._emit_state(f"Loaded file: {self._state.file_path}")
		if self._state.connected:
			self._load_frame(0, status=True)

	def toggle_play(self) -> None:
		if not self._state.file_path:
			self._emit_state("Load an .imb file first.")
			return
		if not self._state.connected:
			self._emit_state("Connect MATLAB first.")
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

	def _load_frame(self, ping_index: int, status: bool = True) -> bool:
		if not self._state.file_path:
			if status:
				self._emit_state("Load an .imb file first.")
			return False
		if not self._state.connected:
			if status:
				self._emit_state("Connect MATLAB first.")
			return False

		try:
			frame: RenderedFrame = self._worker.load_imb_frame(
				self._state.file_path,
				ping_index,
				show_grid=self._show_grid,
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
