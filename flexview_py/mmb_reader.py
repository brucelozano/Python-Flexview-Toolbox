from __future__ import annotations

from typing import Any, Dict, Tuple

import numpy as np

from .matlab_bridge import MatlabSession


class MMBReader:
	"""High-level MMB reader using MATLAB Engine beamforming helpers."""

	def __init__(self, matlab_session: MatlabSession, *, default_image_index: int = 0) -> None:
		self._ml = matlab_session
		self._default_image_index = int(default_image_index)
		self._last_range_list_m: np.ndarray | None = None
		self._last_actual_ping_index: int | None = None

	@property
	def last_range_list_m(self) -> np.ndarray | None:
		return self._last_range_list_m

	@property
	def last_actual_ping_index(self) -> int | None:
		return self._last_actual_ping_index

	def load_frame(
		self,
		filename: str,
		ping_index: int = 0,
		*,
		image_index: int | None = None,
	) -> Tuple[Dict[str, Any], np.ndarray, np.ndarray]:
		"""Load one beamformed frame from an MMB file.

		Returns (header_dict, beam_angles_deg[N], image_data[M,N]).
		"""
		use_image_index = self._default_image_index if image_index is None else int(image_index)
		header, beam_angles_ml, image_data_ml, range_list_ml, actual_ping = self._ml.beamform_ping(
			filename, int(ping_index), use_image_index
		)
		beam_angles = np.asarray(beam_angles_ml, dtype=np.float32).ravel()
		image_data = np.asarray(image_data_ml)
		range_list = np.asarray(range_list_ml, dtype=np.float32).ravel()

		self._last_range_list_m = range_list
		self._last_actual_ping_index = int(actual_ping)

		header_dict = dict(header) if isinstance(header, dict) else {}
		header_dict.setdefault("Ping_Number", int(actual_ping))
		return header_dict, beam_angles, image_data

