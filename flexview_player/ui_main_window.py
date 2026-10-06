from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEvent, QSettings, Qt, Signal
from PySide6.QtGui import QColor, QImage, QKeySequence, QPainter, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (
	QApplication,
	QComboBox,
	QFileDialog,
	QHBoxLayout,
	QInputDialog,
	QLabel,
	QLineEdit,
	QMainWindow,
	QMessageBox,
	QPushButton,
	QSizePolicy,
	QSlider,
	QSpinBox,
	QStatusBar,
	QVBoxLayout,
	QWidget,
)

from .data_worker import RenderedFrame
from .playback_controller import PlaybackController, PlayerState


WorldPoint = tuple[float, float, float, float]


@dataclass
class StagedMeasurement:
	point_a_px: tuple[float, float]
	point_b_px: tuple[float, float]
	world_a: WorldPoint
	world_b: WorldPoint
	distance_m: float


class ImageViewLabel(QLabel):
	"""Fixed-behavior image view that will not resize the parent window."""

	mouse_moved = Signal(object)
	mouse_pressed = Signal(object)
	mouse_left = Signal()

	def __init__(self, text: str) -> None:
		super().__init__(text)
		self.setAlignment(Qt.AlignmentFlag.AlignCenter)
		self.setMinimumSize(320, 240)
		self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
		self.setMouseTracking(True)
		self.setStyleSheet(
			"QLabel { border: 1px solid #777; background: #000; color: #ddd; font-size: 14px; }"
		)

	def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
		self.mouse_moved.emit(event.position())
		super().mouseMoveEvent(event)

	def mousePressEvent(self, event) -> None:  # type: ignore[override]
		self.mouse_pressed.emit(event.position())
		super().mousePressEvent(event)

	def leaveEvent(self, event) -> None:  # type: ignore[override]
		self.mouse_left.emit()
		super().leaveEvent(event)


class MainWindow(QMainWindow):
	"""Flexview Player main window (Milestone 1 scaffold)."""

	def __init__(self, controller: PlaybackController) -> None:
		super().__init__()
		self._controller = controller
		self.setWindowTitle("Flexview Player (Milestone 3)")
		self.resize(1200, 760)

		self._status_label = QLabel("Status: Ready")
		self._connected_label = QLabel("MATLAB: Disconnected")
		self._file_label = QLabel("File: (none)")
		self._meta_label = QLabel("Frame: (none)")
		self._meta_label.setWordWrap(True)
		self._cursor_label = QLabel("Cursor (fan view): -")
		self._measurement_label = QLabel("Measurement: mode off. Click 'Measure' or press A.")
		self._measurement_label.setWordWrap(True)

		self._open_btn = QPushButton("Open .imb")
		self._connect_btn = QPushButton("Connect MATLAB")
		self._disconnect_btn = QPushButton("Disconnect")

		self._play_btn = QPushButton("Play/Pause [Space]")
		self._step_back_btn = QPushButton("Previous [Left]")
		self._step_fwd_btn = QPushButton("Next [Right]")
		self._ping_spin = QSpinBox()
		self._ping_spin.setRange(0, 10_000_000)
		self._speed_combo = QComboBox()
		self._speed_combo.addItems(["0.25x", "0.5x", "1.0x", "2.0x"])
		self._speed_combo.setCurrentText("1.0x")
		self._timeline = QSlider(Qt.Orientation.Horizontal)
		self._timeline.setRange(0, 1000)
		self._timeline.setSingleStep(1)
		self._grid_toggle_btn = QPushButton("Grid: On [G]")
		self._grid_toggle_btn.setCheckable(True)
		self._grid_toggle_btn.setChecked(True)
		self._annotator_btn = QPushButton("Annotator: (set)")
		self._measure_mode_btn = QPushButton("Measure: Off [A]")
		self._measure_mode_btn.setCheckable(True)
		self._clear_measure_btn = QPushButton("Clear Measure")

		self._polar_view = ImageViewLabel("Polar View (no frame loaded)")
		self._cart_view = ImageViewLabel("Cartesian Fan View (no frame loaded)")
		self._polar_pixmap: QPixmap | None = None
		self._cart_pixmap: QPixmap | None = None
		self._current_frame: RenderedFrame | None = None
		self._measure_current_points_px: list[tuple[float, float]] = []
		self._staged_measurements: list[StagedMeasurement] = []
		self._measurement_mode_enabled = False
		self._annotator_name = ""
		self._annotator_slug = ""
		self._settings = QSettings("Flexview", "FlexviewPlayer")
		self._load_saved_annotator()
		self._shortcut_toggle_measure = QShortcut(QKeySequence("A"), self)
		self._shortcut_toggle_grid = QShortcut(QKeySequence("G"), self)
		self._shortcut_toggle_play = QShortcut(QKeySequence("Space"), self)
		self._shortcut_step_back = QShortcut(QKeySequence("Left"), self)
		self._shortcut_step_fwd = QShortcut(QKeySequence("Right"), self)
		self._shortcut_toggle_measure.setContext(Qt.ShortcutContext.WindowShortcut)
		self._shortcut_toggle_grid.setContext(Qt.ShortcutContext.WindowShortcut)
		self._shortcut_toggle_play.setContext(Qt.ShortcutContext.WindowShortcut)
		self._shortcut_step_back.setContext(Qt.ShortcutContext.WindowShortcut)
		self._shortcut_step_fwd.setContext(Qt.ShortcutContext.WindowShortcut)
		self._shortcut_toggle_measure.setAutoRepeat(False)
		self._shortcut_toggle_grid.setAutoRepeat(False)
		self._shortcut_toggle_play.setAutoRepeat(False)
		app = QApplication.instance()
		if app is not None:
			app.installEventFilter(self)

		self._build_layout()
		self._wire_signals()
		self._controller.state_changed.emit(self._controller.state())

	def _build_layout(self) -> None:
		root = QWidget(self)
		self.setCentralWidget(root)
		root_layout = QVBoxLayout(root)
		root_layout.setContentsMargins(10, 10, 10, 10)
		root_layout.setSpacing(8)

		top_bar = QHBoxLayout()
		top_bar.addWidget(self._open_btn)
		top_bar.addWidget(self._connect_btn)
		top_bar.addWidget(self._disconnect_btn)
		top_bar.addSpacing(20)
		top_bar.addWidget(self._connected_label)
		top_bar.addStretch(1)
		root_layout.addLayout(top_bar)
		root_layout.addWidget(self._file_label)
		root_layout.addWidget(self._meta_label)
		root_layout.addWidget(self._cursor_label)
		root_layout.addWidget(self._measurement_label)

		views_layout = QHBoxLayout()
		views_layout.setSpacing(8)
		views_layout.addWidget(self._polar_view, stretch=1)
		views_layout.addWidget(self._cart_view, stretch=1)
		root_layout.addLayout(views_layout, stretch=1)

		transport = QHBoxLayout()
		transport.addWidget(self._step_back_btn)
		transport.addWidget(self._play_btn)
		transport.addWidget(self._step_fwd_btn)
		transport.addSpacing(8)
		transport.addWidget(QLabel("Ping:"))
		transport.addWidget(self._ping_spin)
		transport.addSpacing(8)
		transport.addWidget(QLabel("Speed:"))
		transport.addWidget(self._speed_combo)
		transport.addSpacing(8)
		transport.addWidget(QLabel("Timeline:"))
		transport.addWidget(self._timeline, stretch=1)
		transport.addWidget(self._grid_toggle_btn)
		transport.addWidget(self._annotator_btn)
		transport.addWidget(self._measure_mode_btn)
		transport.addWidget(self._clear_measure_btn)
		root_layout.addLayout(transport)

		status_bar = QStatusBar(self)
		status_bar.addWidget(self._status_label, stretch=1)
		self.setStatusBar(status_bar)

	def _wire_signals(self) -> None:
		self._open_btn.clicked.connect(self._on_open_file)
		self._connect_btn.clicked.connect(self._controller.connect_matlab)
		self._disconnect_btn.clicked.connect(self._controller.disconnect_matlab)

		self._play_btn.clicked.connect(self._controller.toggle_play)
		self._step_fwd_btn.clicked.connect(self._controller.step_forward)
		self._step_back_btn.clicked.connect(self._controller.step_back)
		self._ping_spin.valueChanged.connect(self._controller.set_ping_index)
		self._speed_combo.currentTextChanged.connect(self._on_speed_changed)
		self._timeline.valueChanged.connect(self._controller.set_ping_index)
		self._grid_toggle_btn.toggled.connect(self._on_grid_toggled)
		self._annotator_btn.clicked.connect(self._on_annotator_clicked)
		self._measure_mode_btn.toggled.connect(self._on_measure_mode_toggled)
		self._clear_measure_btn.clicked.connect(self._clear_measurement)

		self._controller.status_message.connect(self._set_status)
		self._controller.state_changed.connect(self._apply_state)
		self._controller.frame_ready.connect(self._on_frame_ready)
		self._cart_view.mouse_moved.connect(self._on_cart_mouse_moved)
		self._cart_view.mouse_pressed.connect(self._on_cart_mouse_pressed)
		self._cart_view.mouse_left.connect(self._on_cart_mouse_left)
		self._shortcut_toggle_measure.activated.connect(self._toggle_measure_mode)
		self._shortcut_toggle_measure.activatedAmbiguously.connect(self._toggle_measure_mode)
		self._shortcut_toggle_grid.activated.connect(self._toggle_grid_mode)
		self._shortcut_toggle_grid.activatedAmbiguously.connect(self._toggle_grid_mode)
		self._shortcut_toggle_play.activated.connect(self._controller.toggle_play)
		self._shortcut_toggle_play.activatedAmbiguously.connect(self._controller.toggle_play)
		self._shortcut_step_back.activated.connect(self._controller.step_back)
		self._shortcut_step_back.activatedAmbiguously.connect(self._controller.step_back)
		self._shortcut_step_fwd.activated.connect(self._controller.step_forward)
		self._shortcut_step_fwd.activatedAmbiguously.connect(self._controller.step_forward)

	def eventFilter(self, watched, event) -> bool:  # type: ignore[override]
		if event.type() != QEvent.Type.KeyPress:
			return super().eventFilter(watched, event)
		if not self.isVisible() or not self.isActiveWindow():
			return super().eventFilter(watched, event)
		modal = QApplication.activeModalWidget()
		if modal is not None and modal is not self:
			return super().eventFilter(watched, event)
		if not hasattr(event, "key") or not hasattr(event, "modifiers"):
			return super().eventFilter(watched, event)
		if event.isAutoRepeat():
			return super().eventFilter(watched, event)

		modifiers = event.modifiers()
		if modifiers not in (Qt.KeyboardModifier.NoModifier, Qt.KeyboardModifier.KeypadModifier):
			return super().eventFilter(watched, event)

		key = event.key()
		if key == Qt.Key.Key_S:
			self._save_measurement()
			return True
		if key == Qt.Key.Key_Z:
			self._undo_measurement_click()
			return True
		return super().eventFilter(watched, event)

	def _on_open_file(self) -> None:
		start_dir = str(Path.cwd())
		path, _ = QFileDialog.getOpenFileName(
			self,
			"Select IMB File",
			start_dir,
			"Flexview IMB Files (*.imb *.IMB);;All Files (*.*)",
		)
		if path:
			self._controller.open_imb_file(path)

	def _on_speed_changed(self, value: str) -> None:
		try:
			rate = float(value.lower().replace("x", ""))
		except ValueError:
			rate = 1.0
		self._controller.set_playback_rate(rate)

	def _on_grid_toggled(self, checked: bool) -> None:
		enabled = bool(checked)
		self._grid_toggle_btn.setText("Grid: On [G]" if enabled else "Grid: Off [G]")
		self._controller.set_show_grid(enabled)
		state = self._controller.state()
		if state.connected and state.file_path and not state.is_playing:
			# Refresh current frame immediately when paused.
			self._controller.set_ping_index(state.current_ping_index)
		self._set_status("Fan grid enabled." if enabled else "Fan grid disabled.")

	def _toggle_grid_mode(self) -> None:
		self._grid_toggle_btn.toggle()

	def _toggle_measure_mode(self) -> None:
		self._measure_mode_btn.toggle()

	def _on_annotator_clicked(self) -> None:
		if self._prompt_for_annotator(required=False):
			self._set_status(f"Annotator set to '{self._annotator_name}'.")
			self._update_measurement_label()

	def _on_measure_mode_toggled(self, checked: bool) -> None:
		self._measurement_mode_enabled = bool(checked)
		self._measure_mode_btn.setText(
			"Measure: On [A]" if self._measurement_mode_enabled else "Measure: Off [A]"
		)
		if not self._measurement_mode_enabled:
			self._set_status("Measurement mode disabled.")
		else:
			if not self._ensure_annotator():
				self._measurement_mode_enabled = False
				self._measure_mode_btn.blockSignals(True)
				self._measure_mode_btn.setChecked(False)
				self._measure_mode_btn.blockSignals(False)
				self._measure_mode_btn.setText("Measure: Off [A]")
				self._set_status("Measurement mode remains disabled: annotator name is required.")
				self._update_measurement_label()
				return
			self._set_status(
				f"Measurement mode enabled for annotator '{self._annotator_name}'. "
				"Click point pairs to stage annotations."
			)
		self._update_measurement_label()

	def _apply_state(self, state_obj: object) -> None:
		state = state_obj if isinstance(state_obj, PlayerState) else self._controller.state()
		self._connected_label.setText("MATLAB: Connected" if state.connected else "MATLAB: Disconnected")
		self._file_label.setText(f"File: {state.file_path or '(none)'}")
		self._ping_spin.blockSignals(True)
		self._ping_spin.setValue(state.current_ping_index)
		self._ping_spin.blockSignals(False)
		self._timeline.blockSignals(True)
		self._timeline.setMaximum(max(1, state.discovered_max_ping_index))
		self._timeline.setValue(state.current_ping_index)
		self._timeline.blockSignals(False)
		self._play_btn.setText("Pause [Space]" if state.is_playing else "Play [Space]")

	def _set_status(self, text: str) -> None:
		self._status_label.setText(f"Status: {text}")

	def _on_frame_ready(self, frame_obj: object) -> None:
		if not isinstance(frame_obj, RenderedFrame):
			return
		frame = frame_obj
		self._current_frame = frame
		self._polar_pixmap = self._pixmap_from_bgr(frame.polar_bgr)
		self._cart_pixmap = self._pixmap_from_bgr(frame.cartesian_bgr)
		self._reset_measurement_state()
		self._update_measurement_label()
		self._refresh_pixmaps()
		self._meta_label.setText(
			"Frame: "
			f"ping_index={frame.ping_index}, ping_number={frame.ping_number}, "
			f"shape={frame.shape[0]}x{frame.shape[1]}, "
			f"beam=[{frame.beam_min_deg:.2f},{frame.beam_max_deg:.2f}] deg, "
			f"range=[{frame.range_min_m:.2f},{frame.range_max_m:.2f}] m"
		)

	def resizeEvent(self, event) -> None:  # type: ignore[override]
		super().resizeEvent(event)
		self._refresh_pixmaps()

	def _refresh_pixmaps(self) -> None:
		if self._polar_pixmap is not None:
			self._polar_view.setPixmap(
				self._polar_pixmap.scaled(
					self._polar_view.size(),
					# Echogram-style view should fill the panel even when
					# source dimensions are extremely tall/narrow.
					Qt.AspectRatioMode.IgnoreAspectRatio,
					Qt.TransformationMode.SmoothTransformation,
				)
			)
		if self._cart_pixmap is not None:
			scaled = self._cart_pixmap.scaled(
				self._cart_view.size(),
				Qt.AspectRatioMode.KeepAspectRatio,
				Qt.TransformationMode.SmoothTransformation,
			)
			if self._measure_current_points_px or self._staged_measurements:
				scaled = self._draw_measurement_overlay(scaled)
			self._cart_view.setPixmap(scaled)

	def _clear_measurement(self) -> None:
		self._reset_measurement_state()
		self._update_measurement_label()
		self._set_status("Measurement selections cleared.")
		self._refresh_pixmaps()

	def _reset_measurement_state(self) -> None:
		self._measure_current_points_px.clear()
		self._staged_measurements.clear()

	def _load_saved_annotator(self) -> None:
		saved_name = self._settings.value("measurement/annotator_name", "", type=str)
		if saved_name:
			self._set_annotator(saved_name, persist=False)
		else:
			self._update_annotator_button()

	def _update_annotator_button(self) -> None:
		if self._annotator_name:
			self._annotator_btn.setText(f"Annotator: {self._annotator_name}")
		else:
			self._annotator_btn.setText("Annotator: (set)")

	def _sanitize_annotator_slug(self, annotator_name: str) -> str:
		slug = re.sub(r"[^A-Za-z0-9._-]+", "_", annotator_name.strip().lower()).strip("._-")
		return slug

	def _set_annotator(self, annotator_name: str, *, persist: bool = True) -> bool:
		clean_name = " ".join(annotator_name.strip().split())
		slug = self._sanitize_annotator_slug(clean_name)
		if not clean_name or not slug:
			return False

		self._annotator_name = clean_name
		self._annotator_slug = slug
		self._update_annotator_button()
		if persist:
			self._settings.setValue("measurement/annotator_name", clean_name)
		return True

	def _prompt_for_annotator(self, *, required: bool) -> bool:
		initial_text = self._annotator_name
		while True:
			input_name, ok = QInputDialog.getText(
				self,
				"Annotator Name",
				"Enter annotator name:",
				QLineEdit.EchoMode.Normal,
				initial_text,
			)
			if not ok:
				return False
			if self._set_annotator(input_name, persist=True):
				return True
			if not required:
				return False
			QMessageBox.warning(
				self,
				"Invalid Annotator Name",
				"Annotator name cannot be empty.",
			)
			initial_text = input_name

	def _ensure_annotator(self) -> bool:
		if self._annotator_slug:
			return True
		return self._prompt_for_annotator(required=True)

	def _update_measurement_label(self, *, last_distance_m: float | None = None) -> None:
		if not self._measurement_mode_enabled:
			self._measurement_label.setText("Measurement: mode off. Click 'Measure' or press A.")
			return

		annotator_hint = (
			f"Annotator={self._annotator_name}. "
			if self._annotator_name
			else "Annotator not set. "
		)
		staged_count = len(self._staged_measurements)
		if len(self._measure_current_points_px) == 1:
			point_a = self._measure_current_points_px[0]
			world_a = self._cart_pixel_to_world(point_a[0], point_a[1])
			if world_a is not None:
				self._measurement_label.setText(
					f"{annotator_hint}Measurement: point A set at x={world_a[0]:.2f} m, z={world_a[1]:.2f} m. "
					f"Staged={staged_count}. Click point B. Press Z to undo."
				)
			else:
				self._measurement_label.setText(
					f"{annotator_hint}Measurement: point A set. Staged={staged_count}. Click point B. Press Z to undo."
				)
			return

		if staged_count > 0:
			prefix = f"Measurement: {staged_count} staged annotation(s)."
			if last_distance_m is not None:
				prefix = (
					f"Measurement: staged {staged_count} annotation(s); "
					f"last distance {last_distance_m:.2f} m."
				)
			self._measurement_label.setText(
				f"{annotator_hint}{prefix} Click point A then point B for next. "
				"Press Z to undo last, S to save all."
			)
			return

		self._measurement_label.setText(
			f"{annotator_hint}Measurement: mode on. Click point A then point B. "
			"Press Z to undo, S to save staged annotations."
		)

	def _on_cart_mouse_left(self) -> None:
		self._cursor_label.setText("Cursor (fan view): -")

	def _on_cart_mouse_moved(self, pos_obj: object) -> None:
		if self._cart_pixmap is None:
			self._cursor_label.setText("Cursor (fan view): -")
			return
		pixel = self._view_pos_to_source_pixel(self._cart_view, self._cart_pixmap, pos_obj)
		if pixel is None:
			self._cursor_label.setText("Cursor (fan view): -")
			return
		world = self._cart_pixel_to_world(pixel[0], pixel[1])
		if world is None:
			self._cursor_label.setText("Cursor (fan view): -")
			return
		x_m, z_m, range_m, angle_deg = world
		self._cursor_label.setText(
			f"Cursor (fan view): x={x_m:.2f} m, z={z_m:.2f} m, range={range_m:.2f} m, angle={angle_deg:.2f} deg"
		)

	def _on_cart_mouse_pressed(self, pos_obj: object) -> None:
		if not self._measurement_mode_enabled:
			return
		if self._cart_pixmap is None:
			return
		pixel = self._view_pos_to_source_pixel(self._cart_view, self._cart_pixmap, pos_obj)
		if pixel is None:
			return
		world = self._cart_pixel_to_world(pixel[0], pixel[1])
		if world is None:
			return

		self._measure_current_points_px.append(pixel)
		if len(self._measure_current_points_px) == 1:
			self._measurement_label.setText(
				f"Measurement: point A set at x={world[0]:.2f} m, z={world[1]:.2f} m. "
				f"Staged={len(self._staged_measurements)}. Click point B. Press Z to undo."
			)
		else:
			world_a = self._cart_pixel_to_world(
				self._measure_current_points_px[0][0], self._measure_current_points_px[0][1]
			)
			world_b = self._cart_pixel_to_world(
				self._measure_current_points_px[1][0], self._measure_current_points_px[1][1]
			)
			if world_a is not None and world_b is not None:
				dx_m = world_b[0] - world_a[0]
				dz_m = world_b[1] - world_a[1]
				distance_m = float(np.hypot(dx_m, dz_m))
				self._staged_measurements.append(
					StagedMeasurement(
						point_a_px=self._measure_current_points_px[0],
						point_b_px=self._measure_current_points_px[1],
						world_a=world_a,
						world_b=world_b,
						distance_m=distance_m,
					)
				)
				self._measure_current_points_px.clear()
				self._set_status(
					f"Staged annotation {len(self._staged_measurements)} ({distance_m:.2f} m). Press S to save all."
				)
				self._update_measurement_label(last_distance_m=distance_m)
			else:
				self._measure_current_points_px.clear()
				self._set_status("Measurement failed: could not map selected points to world coordinates.")
				self._update_measurement_label()
		self._refresh_pixmaps()

	def _undo_measurement_click(self) -> None:
		if not self._measurement_mode_enabled:
			return
		if self._measure_current_points_px:
			self._measure_current_points_px.pop()
			self._set_status("Removed last measurement click.")
		elif self._staged_measurements:
			removed = self._staged_measurements.pop()
			self._set_status(
				f"Removed last staged annotation ({removed.distance_m:.2f} m)."
			)
		else:
			self._set_status("Nothing to undo: no points or staged annotations.")
			return
		self._update_measurement_label()
		self._refresh_pixmaps()

	def _save_measurement(self) -> None:
		if self._current_frame is None:
			self._set_status("Cannot save measurement: no frame loaded.")
			return
		if not self._ensure_annotator():
			self._set_status("Cannot save measurement: annotator name is required.")
			return
		if len(self._measure_current_points_px) == 1:
			self._set_status(
				"Cannot save measurement: current annotation is incomplete. Set point B or press Z to undo."
			)
			return
		if not self._staged_measurements:
			if self._measure_current_points_px:
				self._set_status("Cannot save measurement: complete point B before saving.")
			else:
				self._set_status("Cannot save measurement: no staged annotations.")
			return

		state = self._controller.state()
		frame = self._current_frame
		save_dir, all_measurements_path, ping_measurements_path = self._measurement_paths(
			state.file_path,
			frame.ping_index,
			self._annotator_slug,
		)
		save_dir.mkdir(parents=True, exist_ok=True)

		try:
			all_measurements = self._read_measurements_array(all_measurements_path)
			ping_measurements = self._read_measurements_array(ping_measurements_path)
		except ValueError as exc:
			self._set_status(f"Cannot save measurement: {exc}")
			return

		replaced_existing = False
		existing_ping_count = len(ping_measurements)
		if existing_ping_count > 0:
			should_replace = self._confirm_replace_existing_frame_measurements(
				ping_index=frame.ping_index,
				ping_measurements_path=ping_measurements_path,
				existing_count=existing_ping_count,
				annotator_name=self._annotator_name,
			)
			if not should_replace:
				self._set_status("Save cancelled: kept existing frame measurements.")
				return
			all_measurements = self._remove_measurements_for_frame(
				all_measurements=all_measurements,
				source_file=state.file_path,
				ping_index=frame.ping_index,
				annotator_slug=self._annotator_slug,
			)
			ping_measurements = []
			replaced_existing = True

		measurement_seq = self._next_measurement_sequence(all_measurements)
		ping_measurement_seq = len(ping_measurements) + 1
		staged_count = len(self._staged_measurements)
		for idx, staged in enumerate(self._staged_measurements):
			payload = {
				"measurement_id": f"M{measurement_seq + idx:06d}",
				"ping_measurement_index": ping_measurement_seq + idx,
				"saved_at_utc": datetime.now(timezone.utc).isoformat(),
				"source_file": state.file_path,
				"annotator_name": self._annotator_name,
				"annotator_slug": self._annotator_slug,
				"ping_index": frame.ping_index,
				"ping_number": frame.ping_number,
				"frame_shape": {"rows": frame.shape[0], "cols": frame.shape[1]},
				"beam_deg": {"min": frame.beam_min_deg, "max": frame.beam_max_deg},
				"range_m": {"min": frame.range_min_m, "max": frame.range_max_m},
				"point_a": {
					"pixel_u": staged.point_a_px[0],
					"pixel_v": staged.point_a_px[1],
					"x_m": staged.world_a[0],
					"z_m": staged.world_a[1],
					"range_m": staged.world_a[2],
					"angle_deg": staged.world_a[3],
				},
				"point_b": {
					"pixel_u": staged.point_b_px[0],
					"pixel_v": staged.point_b_px[1],
					"x_m": staged.world_b[0],
					"z_m": staged.world_b[1],
					"range_m": staged.world_b[2],
					"angle_deg": staged.world_b[3],
				},
				"distance_m": staged.distance_m,
			}
			all_measurements.append(payload)
			ping_measurements.append(payload)

		try:
			self._write_measurements_array(all_measurements_path, all_measurements)
			self._write_measurements_array(ping_measurements_path, ping_measurements)
		except OSError as exc:
			self._set_status(f"Failed to save measurement: {exc}")
			return

		action_verb = "Replaced" if replaced_existing else "Saved"
		self._set_status(
			f"{action_verb} {staged_count} annotation(s): {all_measurements_path.name} and {ping_measurements_path.name}"
		)
		self._reset_measurement_state()
		self._update_measurement_label()
		if self._measurement_mode_enabled:
			action_word = "replaced" if replaced_existing else "saved"
			self._measurement_label.setText(
				f"Annotator={self._annotator_name}. Measurement: {action_word} {staged_count} annotation(s). "
				"Click point A then point B to stage more, press Z to undo, then S to save all."
			)
		self._refresh_pixmaps()

	def _measurement_paths(self, source_file: str, ping_index: int, annotator_slug: str) -> tuple[Path, Path, Path]:
		output_root = Path(__file__).resolve().parents[1] / "outputs"
		dataset_name = self._dataset_folder_name(source_file)
		measurements_dir = output_root / dataset_name / "measurements" / annotator_slug
		all_measurements_path = measurements_dir / f"all_measurements_{annotator_slug}.json"
		ping_measurements_path = (
			measurements_dir / f"ping_{int(ping_index):06d}_measurements_{annotator_slug}.json"
		)
		return measurements_dir, all_measurements_path, ping_measurements_path

	def _dataset_folder_name(self, source_file: str) -> str:
		name = Path(source_file).stem.strip() if source_file else ""
		if not name:
			return "unknown_dataset"
		# Keep dataset folder names readable and cross-platform safe.
		safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
		return safe_name or "unknown_dataset"

	def _confirm_replace_existing_frame_measurements(
		self,
		*,
		ping_index: int,
		ping_measurements_path: Path,
		existing_count: int,
		annotator_name: str,
	) -> bool:
		reply = QMessageBox.question(
			self,
			"Replace Existing Frame Measurements?",
			(
				f"Annotator '{annotator_name}' already has {existing_count} saved measurement(s)\n"
				f"for frame {ping_index}\n"
				f"in {ping_measurements_path.name}.\n\n"
				"Do you want to replace them with the current staged annotations?"
			),
			QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
			QMessageBox.StandardButton.Cancel,
		)
		return reply == QMessageBox.StandardButton.Yes

	def _remove_measurements_for_frame(
		self,
		*,
		all_measurements: list[dict],
		source_file: str,
		ping_index: int,
		annotator_slug: str,
	) -> list[dict]:
		filtered: list[dict] = []
		for entry in all_measurements:
			if not isinstance(entry, dict):
				filtered.append(entry)
				continue

			entry_ping = entry.get("ping_index")
			try:
				same_ping = int(float(entry_ping)) == int(ping_index)
			except (TypeError, ValueError):
				same_ping = False

			same_source = True if not source_file else entry.get("source_file") == source_file
			entry_slug = str(entry.get("annotator_slug", "")).strip().lower()
			same_annotator = (entry_slug == annotator_slug) if entry_slug else True
			if same_ping and same_source and same_annotator:
				continue
			filtered.append(entry)
		return filtered

	def _next_measurement_sequence(self, all_measurements: list[dict]) -> int:
		max_seq = 0
		for entry in all_measurements:
			if not isinstance(entry, dict):
				continue
			measurement_id = str(entry.get("measurement_id", "")).strip()
			match = re.fullmatch(r"M(\d+)", measurement_id)
			if match is None:
				continue
			max_seq = max(max_seq, int(match.group(1)))
		return (max_seq + 1) if max_seq > 0 else (len(all_measurements) + 1)

	def _read_measurements_array(self, path: Path) -> list[dict]:
		if not path.exists():
			return []
		try:
			data = json.loads(path.read_text(encoding="utf-8"))
		except json.JSONDecodeError as exc:
			raise ValueError(f"existing file is not valid JSON: {path.name} ({exc})") from exc
		if not isinstance(data, list):
			raise ValueError(f"existing file is not a JSON list: {path.name}")
		return data

	def _write_measurements_array(self, path: Path, measurements: list[dict]) -> None:
		path.write_text(json.dumps(measurements, indent=2), encoding="utf-8")

	def _view_pos_to_source_pixel(
		self,
		view: QLabel,
		source_pixmap: QPixmap,
		pos_obj: object,
	) -> tuple[float, float] | None:
		if source_pixmap.width() <= 0 or source_pixmap.height() <= 0:
			return None
		if not hasattr(pos_obj, "x") or not hasattr(pos_obj, "y"):
			return None

		view_w = float(view.width())
		view_h = float(view.height())
		src_w = float(source_pixmap.width())
		src_h = float(source_pixmap.height())
		if view_w <= 0 or view_h <= 0:
			return None

		scale = min(view_w / src_w, view_h / src_h)
		display_w = src_w * scale
		display_h = src_h * scale
		offset_x = (view_w - display_w) / 2.0
		offset_y = (view_h - display_h) / 2.0

		mouse_x = float(pos_obj.x())
		mouse_y = float(pos_obj.y())
		if mouse_x < offset_x or mouse_y < offset_y:
			return None
		if mouse_x >= (offset_x + display_w) or mouse_y >= (offset_y + display_h):
			return None

		pixel_u = (mouse_x - offset_x) / scale
		pixel_v = (mouse_y - offset_y) / scale
		pixel_u = float(np.clip(pixel_u, 0.0, src_w - 1.0))
		pixel_v = float(np.clip(pixel_v, 0.0, src_h - 1.0))
		return pixel_u, pixel_v

	def _cart_pixel_to_world(self, pixel_u: float, pixel_v: float) -> tuple[float, float, float, float] | None:
		frame = self._current_frame
		if frame is None:
			return None

		img_h, img_w = frame.cartesian_bgr.shape[:2]
		width_m = frame.cart_x_max_m - frame.cart_x_min_m
		if img_w <= 0 or width_m <= 0:
			return None

		scale = img_w / width_m
		x_m = frame.cart_x_max_m - (pixel_u / scale)
		z_m = frame.cart_z_min_m + ((img_h - 1 - pixel_v) / scale)
		range_m = float(np.hypot(x_m, z_m))
		angle_deg = float(np.degrees(np.arctan2(x_m, z_m)))
		return x_m, z_m, range_m, angle_deg

	def _draw_measurement_overlay(self, scaled_pixmap: QPixmap) -> QPixmap:
		if self._cart_pixmap is None:
			return scaled_pixmap

		out = scaled_pixmap.copy()
		painter = QPainter(out)
		painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

		scale_x = out.width() / self._cart_pixmap.width()
		scale_y = out.height() / self._cart_pixmap.height()

		def _to_display(point_u: float, point_v: float) -> tuple[int, int]:
			return int(round(point_u * scale_x)), int(round(point_v * scale_y))

		staged_pen = QPen(QColor(0, 128, 128))
		staged_pen.setWidth(2)
		painter.setPen(staged_pen)
		for staged in self._staged_measurements:
			a_x, a_y = _to_display(staged.point_a_px[0], staged.point_a_px[1])
			b_x, b_y = _to_display(staged.point_b_px[0], staged.point_b_px[1])
			painter.drawEllipse(a_x - 4, a_y - 4, 8, 8)
			painter.drawEllipse(b_x - 4, b_y - 4, 8, 8)
			painter.drawLine(a_x, a_y, b_x, b_y)

		active_pen = QPen(QColor(0, 255, 255))
		active_pen.setWidth(2)
		painter.setPen(active_pen)
		display_points: list[tuple[int, int]] = []
		for point_u, point_v in self._measure_current_points_px:
			disp_x, disp_y = _to_display(point_u, point_v)
			display_points.append((disp_x, disp_y))
			painter.drawEllipse(disp_x - 4, disp_y - 4, 8, 8)

		if len(display_points) == 2:
			painter.drawLine(display_points[0][0], display_points[0][1], display_points[1][0], display_points[1][1])

		painter.end()
		return out

	@staticmethod
	def _pixmap_from_bgr(image_bgr) -> QPixmap:
		rgb = image_bgr[:, :, ::-1].copy()
		h, w, _ = rgb.shape
		qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
		return QPixmap.fromImage(qimg)
