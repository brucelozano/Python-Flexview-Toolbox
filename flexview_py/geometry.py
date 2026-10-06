from __future__ import annotations

from typing import Dict, Tuple

import numpy as np


def compute_rangelist_from_header(header: Dict, num_samples_key: str = "Num_Samples") -> np.ndarray:
	"""Compute range (meters) for each image sample per MATLAB formula.

	Requires header fields: SWST, TXWST, Image_Sample_Interval, Velocity_Sound, Num_Samples.
	"""
	num = int(header[num_samples_key])
	range_samples = np.arange(1, num + 1, dtype=np.float32)
	swst = float(header["SWST"])  # sampling window start (s)
	txwst = float(header["TXWST"])  # tx window start (s)
	dt = float(header["Image_Sample_Interval"])  # (s)
	vs = float(header["Velocity_Sound"])  # (m/s)
	rangelist = (swst - txwst + dt * range_samples) * vs / 2.0
	return rangelist.astype(np.float32)


def polar_to_cartesian(rangelist: np.ndarray, beam_angles_deg: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
	"""Map polar grid (M,N) to Cartesian X,Z matrices for plotting.

	Returns (X[M,N], Z[M,N]) matching data layout.
	"""
	m = int(rangelist.shape[0])
	n = int(beam_angles_deg.shape[0])
	x = np.zeros((m, n), dtype=np.float32)
	z = np.zeros((m, n), dtype=np.float32)
	sin_a = np.sin(np.deg2rad(beam_angles_deg))
	cos_a = np.cos(np.deg2rad(beam_angles_deg))
	for i in range(m):
		r = float(rangelist[i])
		x[i, :] = r * sin_a
		z[i, :] = r * cos_a
	return x, z


def magnitude_log10(image_complex: np.ndarray) -> np.ndarray:
	mag = np.abs(image_complex)
	return np.log10(mag + 1.0).astype(np.float32)


