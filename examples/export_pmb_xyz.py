import argparse
import os
import sys
from typing import Any

import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is importable when running from examples/ or root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flexview_py.matlab_bridge import MatlabSession
from flexview_py.reporting import array_stats, matlab_struct_to_dict, write_json


def _header_subset(header: dict[str, Any], keys: list[str]) -> dict[str, Any]:
	return {key: header.get(key) for key in keys}


def _profile_points_to_xyz(points: np.ndarray, header: dict[str, Any], sound_speed_override: float) -> np.ndarray:
	"""Convert PMB points to local sonar-frame XYZ, matching toolbox formulas."""
	if points.size == 0:
		return np.zeros((0, 3), dtype=np.float64)
	if points.ndim == 1:
		points = points.reshape(1, -1)

	sound_speed = sound_speed_override if sound_speed_override > 0 else float(header["Velocity_Sound"])
	swst = float(header["SWST"])
	txwst = float(header["TXWST"])
	dt = float(header["Image_Sample_Interval"])

	theta_deg = points[:, 1] + points[:, 2]
	range_samples = points[:, 3]
	ranges = (swst - txwst + dt * range_samples) * sound_speed / 2.0

	x = -ranges * np.sin(np.deg2rad(theta_deg))
	y = ranges * np.cos(np.deg2rad(theta_deg))
	z = np.zeros_like(x)
	return np.column_stack((x, y, z))


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Export PMB profile points to XYZ and save parity artifacts."
	)
	parser.add_argument("--file", required=True, help="Path to .pmb file")
	parser.add_argument(
		"--ping-start",
		type=int,
		default=0,
		help="Start ping index (default: 0).",
	)
	parser.add_argument(
		"--ping-end",
		type=int,
		default=None,
		help="End ping index inclusive (default: only ping-start).",
	)
	parser.add_argument(
		"--sound-speed",
		type=float,
		default=0.0,
		help="Override sound speed m/s (default: 0 = use header value).",
	)
	parser.add_argument(
		"--save-dir",
		default="outputs",
		help="Directory to save output artifacts (default: outputs).",
	)
	parser.add_argument(
		"--xyz-out",
		default=None,
		help="Optional explicit path for XYZ output file.",
	)
	parser.add_argument(
		"--no-show",
		action="store_true",
		help="Save artifacts without opening display windows.",
	)
	args = parser.parse_args()

	if args.ping_end is not None and args.ping_end < args.ping_start:
		raise ValueError("--ping-end must be >= --ping-start")

	sess = MatlabSession()
	sess.start()
	try:
		abs_filepath = os.path.abspath(args.file)
		save_dir = os.path.abspath(args.save_dir)
		os.makedirs(save_dir, exist_ok=True)

		ping_end = args.ping_start if args.ping_end is None else args.ping_end
		file_stem = os.path.splitext(os.path.basename(abs_filepath))[0]

		all_xyz_blocks: list[np.ndarray] = []
		per_ping: list[dict[str, Any]] = []
		header_keys = [
			"Ping_Number",
			"Num_Beams",
			"Num_Samples",
			"SWST",
			"TXWST",
			"Image_Sample_Interval",
			"Velocity_Sound",
			"Reference_Latitude",
			"Reference_Longitude",
			"Reference_Depth",
			"Reference_Heading",
			"Reference_Pitch",
			"Reference_Roll",
		]

		print(
			f"Loading PMB profile points from ping {args.ping_start} to {ping_end} "
			f"from {abs_filepath}..."
		)
		for ping_idx in range(args.ping_start, ping_end + 1):
			try:
				header_ml, beamlist_ml, points_ml = sess.load_profile_data(abs_filepath, ping_idx)
			except Exception as exc:
				print(f"Stopped at ping index {ping_idx}: {exc}")
				break

			header = matlab_struct_to_dict(header_ml)
			points = np.asarray(points_ml, dtype=np.float64)
			beamlist = np.asarray(beamlist_ml, dtype=np.float64).ravel()
			xyz = _profile_points_to_xyz(points, header, args.sound_speed)

			all_xyz_blocks.append(xyz)
			per_ping.append(
				{
					"ping_index": ping_idx,
					"header_subset": _header_subset(header, header_keys),
					"point_count": int(points.shape[0]) if points.ndim > 1 else int(points.size > 0),
					"beam_count": int(beamlist.size),
					"beam_angle_span_deg": {
						"min": float(np.min(beamlist)) if beamlist.size else 0.0,
						"max": float(np.max(beamlist)) if beamlist.size else 0.0,
					},
					"range_stats_m": array_stats(np.linalg.norm(xyz[:, :2], axis=1))
					if xyz.size
					else array_stats(np.asarray([], dtype=np.float64)),
				}
			)

		if not per_ping:
			raise RuntimeError("No profile pings were loaded. Check ping range and file path.")

		xyz_all = np.vstack(all_xyz_blocks) if all_xyz_blocks else np.zeros((0, 3), dtype=np.float64)

		if args.xyz_out:
			xyz_path = os.path.abspath(args.xyz_out)
		else:
			last_ping = per_ping[-1]["ping_index"]
			xyz_path = os.path.join(
				save_dir,
				f"{file_stem}_pings{args.ping_start}-{last_ping}_profile.xyz",
			)
		preview_path = xyz_path.replace(".xyz", "_preview.png")
		summary_path = xyz_path.replace(".xyz", "_summary.json")

		np.savetxt(xyz_path, xyz_all, fmt="%.6f")

		fig, ax = plt.subplots(figsize=(8, 6))
		fig.canvas.manager.set_window_title("Flexview - PMB XYZ Preview")
		if xyz_all.size:
			ax.scatter(xyz_all[:, 0], xyz_all[:, 1], s=2, c=xyz_all[:, 2], cmap="viridis")
		ax.set_title("PMB Point Cloud Preview (Local XY)")
		ax.set_xlabel("X (m)")
		ax.set_ylabel("Y (m)")
		ax.set_aspect("equal")
		ax.grid(True, alpha=0.3)
		fig.savefig(preview_path, dpi=200, bbox_inches="tight")

		summary = {
			"script": "examples/export_pmb_xyz.py",
			"source_file": abs_filepath,
			"ping_start_requested": args.ping_start,
			"ping_end_requested": ping_end,
			"sound_speed_override_mps": args.sound_speed,
			"pings_loaded": len(per_ping),
			"ping_indices_loaded": [item["ping_index"] for item in per_ping],
			"total_points": int(xyz_all.shape[0]),
			"xyz_bounds_m": {
				"x_min": float(np.min(xyz_all[:, 0])) if xyz_all.size else 0.0,
				"x_max": float(np.max(xyz_all[:, 0])) if xyz_all.size else 0.0,
				"y_min": float(np.min(xyz_all[:, 1])) if xyz_all.size else 0.0,
				"y_max": float(np.max(xyz_all[:, 1])) if xyz_all.size else 0.0,
				"z_min": float(np.min(xyz_all[:, 2])) if xyz_all.size else 0.0,
				"z_max": float(np.max(xyz_all[:, 2])) if xyz_all.size else 0.0,
			},
			"xyz_norm_stats_m": array_stats(np.linalg.norm(xyz_all[:, :2], axis=1))
			if xyz_all.size
			else array_stats(np.asarray([], dtype=np.float64)),
			"per_ping": per_ping,
		}
		write_json(summary_path, summary)

		print(f"Saved XYZ point cloud: {xyz_path}")
		print(f"Saved XYZ preview plot: {preview_path}")
		print(f"Saved PMB parity summary: {summary_path}")

		if args.no_show:
			plt.close(fig)
		else:
			print("\nDisplaying plot. Close the plot window to exit.")
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
