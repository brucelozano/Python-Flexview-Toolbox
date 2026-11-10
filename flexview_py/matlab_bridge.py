import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

_MATLAB_MODULE: Optional[Any] = None
_MATLAB_IMPORT_ERROR: Optional[Exception] = None


def _try_import_matlab_engine() -> tuple[Optional[Any], Optional[Exception]]:
	"""Try importing matlab + matlab.engine and return (module, error)."""
	try:
		import importlib

		matlab_mod = importlib.import_module("matlab")
		importlib.import_module("matlab.engine")
		return matlab_mod, None
	except Exception as exc:  # pragma: no cover - environment specific
		return None, exc


def _prepend_sys_path(path: Path) -> None:
	path_str = str(path)
	if path_str and path_str not in sys.path:
		sys.path.insert(0, path_str)


def _candidate_matlab_roots() -> list[Path]:
	roots: list[Path] = []
	env_root = os.environ.get("MATLABROOT")
	if env_root:
		roots.append(Path(env_root))

	if sys.platform.startswith("win"):
		base = Path("C:/Program Files/MATLAB")
		if base.is_dir():
			# Prefer newest release first (e.g. R2025b > R2025a).
			roots.extend(sorted(base.glob("R*"), reverse=True))

	seen: set[str] = set()
	unique: list[Path] = []
	for root in roots:
		try:
			resolved = str(root.resolve())
		except Exception:
			continue
		if resolved in seen:
			continue
		seen.add(resolved)
		unique.append(root)
	return unique


def _configure_runtime_paths_for_root(root: Path) -> bool:
	"""Add MATLAB engine runtime paths for a given MATLAB installation root."""
	dist_root = root / "extern" / "engines" / "python" / "dist"
	matlab_pkg_root = dist_root / "matlab"
	engine_win64 = matlab_pkg_root / "engine" / "win64"
	extern_bin = root / "extern" / "bin" / "win64"
	bin_win64 = root / "bin" / "win64"

	required = (dist_root, matlab_pkg_root, engine_win64, extern_bin, bin_win64)
	if not all(p.is_dir() for p in required):
		return False

	_prepend_sys_path(dist_root)
	_prepend_sys_path(matlab_pkg_root)
	_prepend_sys_path(engine_win64)
	_prepend_sys_path(extern_bin)

	if sys.platform.startswith("win"):
		path_entries = [str(bin_win64), str(extern_bin)]
		existing_path = os.environ.get("PATH", "")
		for entry in reversed(path_entries):
			if entry and entry not in existing_path:
				existing_path = f"{entry}{os.pathsep}{existing_path}" if existing_path else entry
		os.environ["PATH"] = existing_path
		if hasattr(os, "add_dll_directory"):
			for dll_dir in (bin_win64, extern_bin):
				try:
					os.add_dll_directory(str(dll_dir))
				except Exception:
					pass
	return True


def _ensure_matlab_engine_available() -> Optional[Any]:
	"""Import MATLAB engine, with runtime-path fallback for frozen EXE builds."""
	global _MATLAB_MODULE, _MATLAB_IMPORT_ERROR
	if _MATLAB_MODULE is not None:
		return _MATLAB_MODULE

	matlab_mod, import_err = _try_import_matlab_engine()
	if matlab_mod is not None:
		_MATLAB_MODULE = matlab_mod
		_MATLAB_IMPORT_ERROR = None
		return _MATLAB_MODULE

	last_error: Optional[Exception] = import_err
	for root in _candidate_matlab_roots():
		if not _configure_runtime_paths_for_root(root):
			continue
		matlab_mod, import_err = _try_import_matlab_engine()
		if matlab_mod is not None:
			_MATLAB_MODULE = matlab_mod
			_MATLAB_IMPORT_ERROR = None
			return _MATLAB_MODULE
		last_error = import_err

	_MATLAB_IMPORT_ERROR = last_error
	return None


class MatlabSession:
	"""Manage MATLAB Engine and provide typed wrappers for M3 readers."""

	def __init__(self) -> None:
		self._eng: Optional[Any] = None

	def start(self) -> None:
		if self._eng is None:
			matlab_mod = _ensure_matlab_engine_available()
			if matlab_mod is None:
				detail = f" (import error: {_MATLAB_IMPORT_ERROR})" if _MATLAB_IMPORT_ERROR else ""
				raise RuntimeError(
					"MATLAB Engine is not available. Install from MATLAB: "
					"cd(fullfile(matlabroot,'extern','engines','python')); system('py -3 -m pip install .')"
					f"{detail}"
				)
			self._eng = matlab_mod.engine.start_matlab()
			# Change the CWD and add helper paths (supports source + frozen builds).
			toolbox_root, helpers_root = self._resolve_matlab_resource_paths()
			if toolbox_root is not None:
				self.eng.cd(str(toolbox_root), nargout=0)
				gp = self.eng.genpath(str(toolbox_root))
				self.eng.addpath(gp, nargout=0)
			if helpers_root is not None:
				self.eng.addpath(str(helpers_root), nargout=0)

	@staticmethod
	def _resolve_matlab_resource_paths() -> tuple[Path | None, Path | None]:
		def _candidates() -> list[Path]:
			source_root = Path(__file__).resolve().parents[1]
			cands = [source_root]
			if getattr(sys, "frozen", False):
				meipass = getattr(sys, "_MEIPASS", None)
				if meipass:
					cands.insert(0, Path(meipass))
				cands.insert(0, Path(sys.executable).resolve().parent)
			return cands

		for root in _candidates():
			toolbox_root = root / "M3_MATLAB_Toolbox_1.2"
			helpers_root = root / "matlab_helpers"
			if toolbox_root.is_dir() and helpers_root.is_dir():
				return toolbox_root, helpers_root
		return None, None

	def stop(self) -> None:
		if self._eng is not None:
			self._eng.quit()
			self._eng = None

	@property
	def eng(self) -> Any:
		if self._eng is None:
			raise RuntimeError("MATLAB Engine not started. Call start().")
		return self._eng

	def load_image_data(self, filename: str, image_offset: int = 0) -> Tuple[Dict[str, Any], Any, Any]:
		"""Call MATLAB load_image_data.
		Returns (header_struct, beamlist, image_data).
		"""
		ok, header, beamlist, image_data, err_msg = self.eng.load_image_data_quiet_py(
			filename, float(image_offset), nargout=5
		)
		if not bool(ok):
			raise RuntimeError(err_msg)
		return header, beamlist, image_data

	def load_raw_data(self, filename: str, ping_index: int, image_index: int = 0):
		"""Call MATLAB load_raw_data through a Python-safe wrapper.
		Returns (header_dict, beam_angles, ref_pulse, raw_data).
		"""
		header_json, beam_angles, ref_pulse, raw_data = self.eng.load_raw_data_py(
			filename, float(ping_index), float(image_index), nargout=4
		)
		header = json.loads(header_json)
		return header, beam_angles, ref_pulse, raw_data

	def load_profile_data(self, filename: str, ping_index: int):
		return self.eng.load_profile_data(filename, float(ping_index), nargout=3)

	def beamform_ping(self, filename: str, ping_index: int, image_index: int = 0):
		"""Run one-ping beamforming via MATLAB helper.
		Returns (header_dict, beam_angles, image_data, range_list, actual_ping_num).
		"""
		ok, header_json, beam_angles, image_data, range_list, actual_ping_num, err_msg = (
			self.eng.beamform_ping_quiet_py(
				filename,
				float(ping_index),
				float(image_index),
				nargout=7,
			)
		)
		if not bool(ok):
			raise RuntimeError(str(err_msg))
		header = json.loads(header_json)
		return header, beam_angles, image_data, range_list, int(actual_ping_num)

	def split_beam_ping(self, filename: str, ping_index: int, image_index: int = 0):
		"""Run split-beam parity workflow via MATLAB helper.
		Returns dict-safe metadata and arrays for plotting/reporting.
		"""
		(
			header_json,
			beam_angles,
			range_list,
			image_full,
			image_sub_1,
			image_sub_2,
			phase_angles,
			phase_values,
			mag_angles,
			mag_values,
			fit_angles,
			fit_values,
			aoa_json,
		) = self.eng.split_beam_ping_py(filename, float(ping_index), float(image_index), nargout=13)
		return (
			json.loads(header_json),
			beam_angles,
			range_list,
			image_full,
			image_sub_1,
			image_sub_2,
			phase_angles,
			phase_values,
			mag_angles,
			mag_values,
			fit_angles,
			fit_values,
			json.loads(aoa_json),
		)

	def generate_xyz_point_cloud(
		self,
		filename_pmb: str,
		filename_xyz: str,
		ping_start: int = 0,
		ping_end: int = 9999,
		z_max: float = float("inf"),
		pitch_sensor_offset: float = 0.0,
		roll_sensor_offset: float = 0.0,
		hdg_sensor_offset: float = 0.0,
		figure_output_dir: str = "",
		figure_prefix: str = "georef",
	):
		"""Run full MATLAB georeferenced PMB point-cloud export helper."""
		summary_json = self.eng.generate_xyz_point_cloud_py(
			filename_pmb,
			filename_xyz,
			float(ping_start),
			float(ping_end),
			float(z_max),
			float(pitch_sensor_offset),
			float(roll_sensor_offset),
			float(hdg_sensor_offset),
			figure_output_dir,
			figure_prefix,
			nargout=1,
		)
		return json.loads(summary_json)

	def export_google_map(self, data_folder: str, html_filename: str = "google_tracks.html", ping_step: int = 10):
		"""Run MATLAB google-map export helper and return summary metadata."""
		summary_json = self.eng.export_google_map_py(data_folder, html_filename, float(ping_step), nargout=1)
		return json.loads(summary_json)


