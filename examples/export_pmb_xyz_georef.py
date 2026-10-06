import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is importable when running from examples/ or root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flexview_py.matlab_bridge import MatlabSession
from flexview_py.reporting import matlab_struct_to_dict, write_json


def _load_xyz(path: str) -> np.ndarray:
	if not os.path.isfile(path):
		return np.zeros((0, 3), dtype=np.float64)
	arr = np.loadtxt(path, dtype=np.float64)
	if arr.size == 0:
		return np.zeros((0, 3), dtype=np.float64)
	if arr.ndim == 1:
		arr = arr.reshape(1, -1)
	return arr


def _to_float(value, default: float = 0.0) -> float:
	if value is None:
		return default
	try:
		return float(value)
	except Exception:
		return default


def _interp_sparse_linear(time_s: np.ndarray, y_raw: np.ndarray, change_mask: np.ndarray) -> np.ndarray:
	"""Replicate MATLAB sparse linear interpolation/extrapolation behavior."""
	n = y_raw.size
	if n == 0:
		return np.asarray([], dtype=np.float64)
	if n == 1:
		return y_raw.copy()

	change_idx = np.flatnonzero(change_mask) + 1
	index = np.concatenate(([0], change_idx))
	y_smooth = np.full(n, np.nan, dtype=np.float64)

	if index.size == 1:
		y_smooth[:] = y_raw[0]
		return y_smooth

	last_i1 = 0
	last_t1 = time_s[0]
	last_slope = 0.0
	last_i2 = 0
	for idx_pos in range(1, index.size):
		i1 = int(index[idx_pos - 1])
		i2 = int(index[idx_pos])
		t1 = float(time_s[i1])
		t2 = float(time_s[i2])
		y1 = float(y_raw[i1])
		y2 = float(y_raw[i2])
		slope = 0.0 if abs(t2 - t1) < 1e-12 else (y2 - y1) / (t2 - t1)
		for k in range(i1, i2 + 1):
			y_smooth[k] = y1 + slope * (float(time_s[k]) - t1)
		last_i1 = i1
		last_i2 = i2
		last_t1 = t1
		last_slope = slope

	for k in range(last_i2 + 1, n):
		y_smooth[k] = float(y_raw[last_i1]) + last_slope * (float(time_s[k]) - last_t1)

	return y_smooth


def _collect_profile_navigation(
	sess: MatlabSession,
	filename_pmb: str,
	ping_start: int,
	ping_end: int,
	pitch_sensor_offset: float = 0.0,
	roll_sensor_offset: float = 0.0,
	hdg_sensor_offset: float = 0.0,
) -> dict:
	"""Load profile headers across ping range for Python-side diagnostics."""
	ping_indices: list[int] = []
	latitudes: list[float] = []
	longitudes: list[float] = []
	headings: list[float] = []
	pitches: list[float] = []
	rolls: list[float] = []
	times_s: list[float] = []

	for ping_idx in range(ping_start, ping_end + 1):
		try:
			header_ml, _, _ = sess.load_profile_data(filename_pmb, ping_idx)
		except Exception:
			break
		header = matlab_struct_to_dict(header_ml)
		ping_indices.append(ping_idx)
		latitudes.append(_to_float(header.get("Reference_Latitude")))
		longitudes.append(_to_float(header.get("Reference_Longitude")))
		headings.append(_to_float(header.get("Reference_Heading")))
		pitches.append(_to_float(header.get("Reference_Pitch")))
		rolls.append(_to_float(header.get("Reference_Roll")))
		t_s = _to_float(header.get("Time_Seconds", header.get("Time_s", 0.0)))
		t_ms = _to_float(header.get("Time_Milliseconds", header.get("Time_ms", 0.0)))
		times_s.append(t_s + t_ms * 1e-3)

	lat = np.asarray(latitudes, dtype=np.float64)
	lon = np.asarray(longitudes, dtype=np.float64)
	hdg_raw = np.asarray(headings, dtype=np.float64) + float(hdg_sensor_offset)
	pitch = np.asarray(pitches, dtype=np.float64) + float(pitch_sensor_offset)
	roll = np.asarray(rolls, dtype=np.float64) + float(roll_sensor_offset)
	time_abs = np.asarray(times_s, dtype=np.float64)
	if time_abs.size:
		time_rel = time_abs - time_abs[0]
	else:
		time_rel = np.asarray([], dtype=np.float64)

	if lat.size:
		proj_lat = float(np.mean(lat))
		proj_lon = float(np.mean(lon))
		northing = (lat - proj_lat) * 60.0 * 1852.0
		easting = (lon - proj_lon) * np.cos(np.deg2rad(proj_lat)) * 60.0 * 1852.0
	else:
		proj_lat = 0.0
		proj_lon = 0.0
		northing = np.asarray([], dtype=np.float64)
		easting = np.asarray([], dtype=np.float64)

	if easting.size > 1 and time_rel.size == easting.size:
		d_posn = np.sqrt(np.diff(northing) ** 2 + np.diff(easting) ** 2)
		northing_smooth = _interp_sparse_linear(time_rel, northing, d_posn != 0.0)
		easting_smooth = _interp_sparse_linear(time_rel, easting, d_posn != 0.0)

		hdg_n = np.cos(np.deg2rad(hdg_raw))
		hdg_e = np.sin(np.deg2rad(hdg_raw))
		d_heading = np.diff(hdg_raw)
		hdg_n_smooth = _interp_sparse_linear(time_rel, hdg_n, np.abs(d_heading) > 0.0)
		hdg_e_smooth = _interp_sparse_linear(time_rel, hdg_e, np.abs(d_heading) > 0.0)
		heading_smooth = (np.rad2deg(np.arctan2(hdg_e_smooth, hdg_n_smooth)) + 360.0) % 360.0

		# Match MATLAB cmg computation exactly (using swapped diff labels from source).
		d_easting_m = np.diff(northing_smooth)
		d_northing_m = np.diff(easting_smooth)
		course = (90.0 - np.rad2deg(np.arctan2(d_easting_m, d_northing_m)) + 360.0) % 360.0
		course_time = time_rel[1:]
	else:
		northing_smooth = northing
		easting_smooth = easting
		heading_smooth = hdg_raw
		course = np.asarray([], dtype=np.float64)
		course_time = np.asarray([], dtype=np.float64)

	return {
		"ping_indices": ping_indices,
		"lat": lat,
		"lon": lon,
		"heading_raw": hdg_raw,
		"heading_smooth": heading_smooth,
		"pitch": pitch,
		"roll": roll,
		"time_rel": time_rel,
		"course": course,
		"course_time": course_time,
		"easting": easting,
		"northing": northing,
		"easting_smooth": easting_smooth.copy(),
		"northing_smooth": northing_smooth.copy(),
		"proj_lat": proj_lat,
		"proj_lon": proj_lon,
	}


def _save_python_diagnostic_figures(nav: dict, file_stem: str, save_dir: str) -> list[str]:
	"""Create Python-native georeference diagnostics mirroring MATLAB outputs."""
	output_paths: list[str] = []

	lat = nav["lat"]
	lon = nav["lon"]
	easting = nav["easting"]
	northing = nav["northing"]
	easting_smooth = nav["easting_smooth"]
	northing_smooth = nav["northing_smooth"]
	time_rel = nav["time_rel"]
	heading_raw = nav["heading_raw"]
	heading_smooth = nav["heading_smooth"]
	course = nav["course"]
	course_time = nav["course_time"]
	pitch = nav["pitch"]
	roll = nav["roll"]
	proj_lat = nav["proj_lat"]
	proj_lon = nav["proj_lon"]

	# 1) Longitude/Latitude track.
	fig1, ax1 = plt.subplots(figsize=(7, 5))
	if lat.size:
		ax1.plot(lon, lat, "b.-")
		ax1.plot(lon[0], lat[0], "rx")
	ax1.grid(True, alpha=0.3)
	ax1.set_xlabel("Longitude (deg)")
	ax1.set_ylabel("Latitude (deg)")
	ax1.set_title("Profile Position (Lon/Lat)")
	path1 = os.path.join(save_dir, f"{file_stem}_python_nav_latlon.png")
	fig1.savefig(path1, dpi=200, bbox_inches="tight")
	plt.close(fig1)
	output_paths.append(path1)

	# 2) Easting/Northing track.
	fig2, ax2 = plt.subplots(figsize=(7, 5))
	if easting.size:
		ax2.plot(easting, northing, "ko-", label="Raw")
		if easting_smooth.size:
			ax2.plot(easting_smooth, northing_smooth, "b.-", label="Smoothed")
		ax2.plot(easting[0], northing[0], "rx")
	ax2.grid(True, alpha=0.3)
	ax2.set_aspect("equal")
	ax2.set_xlabel("Easting (m)")
	ax2.set_ylabel("Northing (m)")
	ax2.set_title(f"Projected Track (Lat0={proj_lat:.6f}, Lon0={proj_lon:.6f})")
	ax2.legend(loc="best")
	path2 = os.path.join(save_dir, f"{file_stem}_python_nav_xy.png")
	fig2.savefig(path2, dpi=200, bbox_inches="tight")
	plt.close(fig2)
	output_paths.append(path2)

	# 3) Heading/Course.
	fig3, ax3 = plt.subplots(figsize=(8, 4))
	if time_rel.size:
		ax3.plot(time_rel, heading_raw, "ko-", label="Raw Heading")
		ax3.plot(time_rel, heading_smooth, "b.-", label="Smoothed Heading")
	if course_time.size:
		ax3.plot(course_time, course, "g.-", label="CMG")
	ax3.grid(True, alpha=0.3)
	ax3.set_xlabel("Time (s)")
	ax3.set_ylabel("Angle (deg)")
	ax3.set_title("Heading and Course")
	ax3.legend(loc="best")
	path3 = os.path.join(save_dir, f"{file_stem}_python_heading_course.png")
	fig3.savefig(path3, dpi=200, bbox_inches="tight")
	plt.close(fig3)
	output_paths.append(path3)

	# 4) Pitch/Roll.
	fig4, (ax4a, ax4b) = plt.subplots(2, 1, figsize=(8, 6), sharex=True)
	if time_rel.size:
		ax4a.plot(time_rel, pitch, "b.-")
		ax4b.plot(time_rel, roll, "r.-")
	ax4a.grid(True, alpha=0.3)
	ax4b.grid(True, alpha=0.3)
	ax4a.set_ylabel("Pitch (deg)")
	ax4b.set_ylabel("Roll (deg)")
	ax4b.set_xlabel("Time (s)")
	ax4a.set_title("Pitch Sensor")
	ax4b.set_title("Roll Sensor")
	path4 = os.path.join(save_dir, f"{file_stem}_python_pitch_roll.png")
	fig4.savefig(path4, dpi=200, bbox_inches="tight")
	plt.close(fig4)
	output_paths.append(path4)

	return output_paths


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Run MATLAB georeferenced PMB point-cloud workflow and export parity artifacts."
	)
	parser.add_argument("--file", required=True, help="Path to .pmb file")
	parser.add_argument("--ping-start", type=int, default=0, help="Start ping index (default: 0).")
	parser.add_argument("--ping-end", type=int, default=9999, help="End ping index inclusive (default: 9999).")
	parser.add_argument("--z-max", type=float, default=0.0, help="Maximum Z trim in meters (default: 0.0).")
	parser.add_argument(
		"--pitch-sensor-offset",
		type=float,
		default=1.0,
		help="Pitch sensor offset in degrees (default: 1.0 to mirror MATLAB test).",
	)
	parser.add_argument("--roll-sensor-offset", type=float, default=0.0, help="Roll sensor offset in degrees.")
	parser.add_argument("--hdg-sensor-offset", type=float, default=0.0, help="Heading sensor offset in degrees.")
	parser.add_argument("--xyz-out", default=None, help="Optional explicit output path for georeferenced XYZ.")
	parser.add_argument("--save-dir", default="outputs", help="Directory to save outputs (default: outputs).")
	parser.add_argument(
		"--save-matlab-figures",
		action="store_true",
		help="Also save MATLAB-generated diagnostic figures (default: off).",
	)
	parser.add_argument(
		"--no-show",
		action="store_true",
		help="Save artifacts without opening display windows for Python preview only.",
	)
	args = parser.parse_args()

	if args.ping_end < args.ping_start:
		raise ValueError("--ping-end must be >= --ping-start")

	abs_pmb = os.path.abspath(args.file)
	save_dir = os.path.abspath(args.save_dir)
	os.makedirs(save_dir, exist_ok=True)
	file_stem = os.path.splitext(os.path.basename(abs_pmb))[0]
	if args.xyz_out:
		xyz_path = os.path.abspath(args.xyz_out)
	else:
		xyz_path = os.path.join(
			save_dir,
			f"{file_stem}_georef_pings{args.ping_start}-{args.ping_end}.xyz",
		)
	preview_path = xyz_path.replace(".xyz", "_preview.png")
	summary_path = xyz_path.replace(".xyz", "_summary.json")
	figure_prefix = os.path.splitext(os.path.basename(xyz_path))[0]
	figure_output_dir = save_dir if args.save_matlab_figures else ""

	sess = MatlabSession()
	sess.start()
	try:
		print(
			f"Running georeferenced PMB export from {abs_pmb} "
			f"(pings {args.ping_start}..{args.ping_end})..."
		)
		matlab_summary = sess.generate_xyz_point_cloud(
			abs_pmb,
			xyz_path,
			ping_start=args.ping_start,
			ping_end=args.ping_end,
			z_max=args.z_max,
			pitch_sensor_offset=args.pitch_sensor_offset,
			roll_sensor_offset=args.roll_sensor_offset,
			hdg_sensor_offset=args.hdg_sensor_offset,
			figure_output_dir=figure_output_dir,
			figure_prefix=figure_prefix,
		)
		print("MATLAB georeferenced workflow completed.")
		nav = _collect_profile_navigation(
			sess,
			abs_pmb,
			args.ping_start,
			args.ping_end,
			pitch_sensor_offset=args.pitch_sensor_offset,
			roll_sensor_offset=args.roll_sensor_offset,
			hdg_sensor_offset=args.hdg_sensor_offset,
		)
		python_diag_files = _save_python_diagnostic_figures(nav, figure_prefix, save_dir)

		xyz = _load_xyz(xyz_path)
		fig, ax = plt.subplots(figsize=(8, 6))
		fig.canvas.manager.set_window_title("Flexview - Georeferenced PMB Preview")
		if xyz.size > 0:
			sc = ax.scatter(xyz[:, 0], xyz[:, 1], s=1.5, c=xyz[:, 2], cmap="viridis")
			plt.colorbar(sc, ax=ax, label="Z (m)")
		ax.set_title("Georeferenced PMB Point Cloud (Plan View)")
		ax.set_xlabel("Easting X (m)")
		ax.set_ylabel("Northing Y (m)")
		ax.set_aspect("equal")
		ax.grid(True, alpha=0.3)
		fig.savefig(preview_path, dpi=200, bbox_inches="tight")

		summary = {
			"script": "examples/export_pmb_xyz_georef.py",
			"source_file": abs_pmb,
			"xyz_output": xyz_path,
			"ping_start_requested": args.ping_start,
			"ping_end_requested": args.ping_end,
			"z_max_requested": args.z_max,
			"pitch_sensor_offset_requested": args.pitch_sensor_offset,
			"roll_sensor_offset_requested": args.roll_sensor_offset,
			"hdg_sensor_offset_requested": args.hdg_sensor_offset,
			"matlab_summary": matlab_summary,
			"python_diagnostic_figures": python_diag_files,
			"navigation_samples_loaded": len(nav["ping_indices"]),
			"total_points": int(xyz.shape[0]),
			"xyz_bounds_m": {
				"x_min": float(np.min(xyz[:, 0])) if xyz.size else 0.0,
				"x_max": float(np.max(xyz[:, 0])) if xyz.size else 0.0,
				"y_min": float(np.min(xyz[:, 1])) if xyz.size else 0.0,
				"y_max": float(np.max(xyz[:, 1])) if xyz.size else 0.0,
				"z_min": float(np.min(xyz[:, 2])) if xyz.size else 0.0,
				"z_max": float(np.max(xyz[:, 2])) if xyz.size else 0.0,
			},
		}
		write_json(summary_path, summary)

		print(f"Saved georeferenced XYZ:    {xyz_path}")
		print(f"Saved georef preview plot:  {preview_path}")
		print(f"Saved georef parity summary:{summary_path}")
		print(f"Saved Python diagnostic figures: {len(python_diag_files)}")
		for fig_path in python_diag_files:
			print(f"  - {fig_path}")
		figure_files = matlab_summary.get("figure_files", [])
		if figure_files:
			print(f"Saved MATLAB diagnostic figures: {len(figure_files)}")
			for fig_path in figure_files:
				print(f"  - {fig_path}")

		if args.no_show:
			plt.close(fig)
		else:
			print("\nDisplaying plot. Close plot window to exit.")
			plt.show()

	except Exception as exc:
		print(f"\nAn error occurred: {exc}")
		import traceback

		traceback.print_exc()
	finally:
		sess.stop()
		print("Cleanup complete. Exiting.")


if __name__ == "__main__":
	main()
