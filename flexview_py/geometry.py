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


def magnitude_db(
	image_complex: np.ndarray,
	*,
	ref_amplitude: float = 1.0,
	floor_db: float = -120.0,
) -> np.ndarray:
	"""Return amplitude in decibels using a fixed floor to avoid -inf."""
	ref = max(1e-12, float(ref_amplitude))
	floor = float(floor_db)
	eps = ref * (10.0 ** (floor / 20.0))
	mag = np.abs(image_complex).astype(np.float32)
	db = 20.0 * np.log10(np.maximum(mag, eps) / ref)
	return db.astype(np.float32)


def polygon_db_stats(
	db: np.ndarray,
	ranges_m: np.ndarray,
	beam_angles_deg: np.ndarray,
	polygon_xz: list[tuple[float, float]],
) -> dict:
	"""Mean/max/std of dB samples whose (x, z) lies inside the polygon.

	`db` is (ranges, beams); sample (i, j) sits at x=r_i*sin(a_j), z=r_i*cos(a_j).
	"""
	poly = np.asarray(polygon_xz, dtype=np.float64)
	# Only scan range rows the polygon's bounding box can touch.
	x_lo, z_lo = poly.min(axis=0)
	x_hi, z_hi = poly.max(axis=0)
	r_lo = float(np.hypot(min(max(0.0, x_lo), x_hi), min(max(0.0, z_lo), z_hi)))  # nearest bbox point to origin
	r_hi = float(max(np.hypot(x, z) for x in (x_lo, x_hi) for z in (z_lo, z_hi)))
	rows = np.nonzero((ranges_m >= r_lo) & (ranges_m <= r_hi))[0]
	empty = {"samples": 0, "mean_db": None, "max_db": None, "std_db": None}
	if rows.size == 0:
		return empty

	ang = np.deg2rad(np.asarray(beam_angles_deg, dtype=np.float64))
	r = np.asarray(ranges_m, dtype=np.float64)[rows][:, None]
	x = r * np.sin(ang)[None, :]
	z = r * np.cos(ang)[None, :]
	inside = np.zeros(x.shape, dtype=bool)
	for i in range(len(poly)):  # even-odd ray casting
		(x1, z1), (x2, z2) = poly[i], poly[(i + 1) % len(poly)]
		crosses = (z1 > z) != (z2 > z)
		with np.errstate(divide="ignore", invalid="ignore"):
			x_at_z = x1 + (x2 - x1) * (z - z1) / (z2 - z1)
		inside ^= crosses & (x < x_at_z)

	vals = np.asarray(db)[rows][inside]
	vals = vals[np.isfinite(vals)]
	if vals.size == 0:
		return empty
	return {
		"samples": int(vals.size),
		"mean_db": float(vals.mean()),
		"max_db": float(vals.max()),
		"std_db": float(vals.std()),
	}
