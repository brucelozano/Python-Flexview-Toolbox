from typing import Any, Dict, Tuple, Optional
import json
import os

try:
	import matlab.engine  # type: ignore
except Exception:  # pragma: no cover
	matlab = None  # type: ignore


class MatlabSession:
	"""Manage MATLAB Engine and provide typed wrappers for M3 readers."""

	def __init__(self) -> None:
		self._eng: Optional[Any] = None

	def start(self) -> None:
		if self._eng is None:
			if matlab is None:
				raise RuntimeError(
					"MATLAB Engine is not available. Install from MATLAB: "
					"cd(fullfile(matlabroot,'extern','engines','python')); system('py -3 -m pip install .')"
				)
			self._eng = matlab.engine.start_matlab()
			# Change the CWD and add path to be robust against .mex file issues.
			project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
			toolbox_root = os.path.join(project_root, "M3_MATLAB_Toolbox_1.2")
			helpers_root = os.path.join(project_root, "matlab_helpers")
			if os.path.isdir(toolbox_root):
				self.eng.cd(toolbox_root, nargout=0)
				gp = self.eng.genpath(toolbox_root)
				self.eng.addpath(gp, nargout=0)
			if os.path.isdir(helpers_root):
				self.eng.addpath(helpers_root, nargout=0)

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
		header_json, beam_angles, image_data, range_list, actual_ping_num = self.eng.beamform_ping_py(
			filename, float(ping_index), float(image_index), nargout=5
		)
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


