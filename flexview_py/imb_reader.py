from typing import Any, Dict, Iterator, Tuple

import numpy as np

from .matlab_bridge import MatlabSession
from .reporting import matlab_struct_to_dict


class IMBReader:
	"""High-level IMB reader using MATLAB Engine.

	Usage:
		with MatlabSession() as sess:  # if context mgmt added later
			... = IMBReader(sess).load_frame(path, offset)
	"""

	def __init__(self, matlab_session: MatlabSession) -> None:
		self._ml = matlab_session

	def load_frame(self, filename: str, image_offset: int = 0) -> Tuple[Dict[str, Any], np.ndarray, np.ndarray]:
		"""Load a single frame from an IMB file.
		Returns (header_dict, beam_angles_deg[N], image_complex[M,N]).
		"""
		header_ml, beamlist_ml, image_ml = self._ml.load_image_data(filename, image_offset)
		header = matlab_struct_to_dict(header_ml)
		beam_angles = _beamlist_to_numpy(beamlist_ml)
		image = _complex_matrix_to_numpy(image_ml)
		return header, beam_angles, image

	def iter_frames(self, filename: str, start: int = 0, stop: int | None = None) -> Iterator[Tuple[int, Dict[str, Any], np.ndarray, np.ndarray]]:
		"""Iterate frames from IMB file, yielding (offset, header, beam_angles, image)."""
		offset = start
		while True:
			try:
				header, beam_angles, image = self.load_frame(filename, offset)
				yield offset, header, beam_angles, image
				offset += 1
				if stop is not None and offset >= stop:
					break
			except Exception as e:
				print(f"ERROR: Failed to load frame at offset {offset}. MATLAB engine might have stopped.")
				print(f"DETAILS: {e}")
				break

def _beamlist_to_numpy(beamlist_ml: Any) -> np.ndarray:
	"""Convert MATLAB beamlist (struct array or numeric vector) to 1D float array of angles."""
	try:
		# If struct array with field Angle
		angles = []
		for k in range(len(beamlist_ml)):
			angles.append(float(beamlist_ml[k]['Angle']))
		return np.asarray(angles, dtype=np.float32)
	except Exception:
		# Otherwise assume numeric vector
		return np.asarray(beamlist_ml).astype(np.float32).ravel()


def _complex_matrix_to_numpy(m: Any) -> np.ndarray:
	"""Convert MATLAB complex matrix to NumPy complex64 array."""
	arr = np.asarray(m)
	if not np.iscomplexobj(arr):
		arr = arr.astype(np.complex64)
	return arr


