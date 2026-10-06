import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is importable when running from examples/ or root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flexview_py.geometry import magnitude_log10
from flexview_py.matlab_bridge import MatlabSession
from flexview_py.reporting import array_stats, write_json


def _polar_edge_mesh(ranges: np.ndarray, beam_angles_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
	"""Build pcolormesh-compatible edge grids from center coordinates."""
	range_edges = np.empty(ranges.size + 1, dtype=np.float32)
	range_edges[1:-1] = 0.5 * (ranges[:-1] + ranges[1:])
	range_edges[0] = ranges[0] - 0.5 * (ranges[1] - ranges[0])
	range_edges[-1] = ranges[-1] + 0.5 * (ranges[-1] - ranges[-2])

	beam_edges = np.empty(beam_angles_deg.size + 1, dtype=np.float32)
	beam_edges[1:-1] = 0.5 * (beam_angles_deg[:-1] + beam_angles_deg[1:])
	beam_edges[0] = beam_angles_deg[0] - 0.5 * (beam_angles_deg[1] - beam_angles_deg[0])
	beam_edges[-1] = beam_angles_deg[-1] + 0.5 * (beam_angles_deg[-1] - beam_angles_deg[-2])

	angle_rad, range_m = np.meshgrid(np.deg2rad(beam_edges), range_edges)
	x_edge = range_m * np.sin(angle_rad)
	z_edge = range_m * np.cos(angle_rad)
	return x_edge, z_edge


def add_matplotlib_polar_grid(ax, ranges: np.ndarray, beam_angles_deg: np.ndarray) -> None:
	"""Adds a custom polar grid and labels to a Matplotlib axes object."""
	min_range, max_range = ranges[0], ranges[-1]

	num_range_rings = 5
	for i in range(num_range_rings + 1):
		r = min_range + (i / num_range_rings) * (max_range - min_range)
		if r > 0:
			angle_rad = np.deg2rad(np.linspace(beam_angles_deg[0], beam_angles_deg[-1], 100))
			x_arc = r * np.sin(angle_rad)
			z_arc = r * np.cos(angle_rad)
			ax.plot(x_arc, z_arc, "--", color="gray", linewidth=0.75)
			label_angle_deg = beam_angles_deg[0] + 3
			ax.text(
				r * np.sin(np.deg2rad(label_angle_deg)),
				r * np.cos(np.deg2rad(label_angle_deg)),
				f" {r:.2f} m",
				color="white",
				ha="left",
				va="center",
				fontsize=8,
			)

	if abs(float(beam_angles_deg[0])) <= 70:
		line_angles_deg = [-60, -30, 0, 30, 60]
	elif abs(float(beam_angles_deg[0])) <= 90:
		line_angles_deg = [-90, -60, -30, 0, 30, 60, 90]
	else:
		line_angles_deg = [-120, -90, -60, -30, 0, 30, 60, 90, 120]

	for angle in line_angles_deg:
		if beam_angles_deg[0] <= angle <= beam_angles_deg[-1]:
			ax.plot(
				[0, max_range * np.sin(np.deg2rad(angle))],
				[0, max_range * np.cos(np.deg2rad(angle))],
				"--",
				color="gray",
				linewidth=0.75,
			)
			if angle == 0:
				label = "000"
			elif angle > 0:
				label = f"{360-angle:03d}"
			else:
				label = f"{-angle:03d}"
			r_label = max_range * 1.05
			ax.text(
				r_label * np.sin(np.deg2rad(angle)),
				r_label * np.cos(np.deg2rad(angle)),
				label,
				color="white",
				ha="center",
				va="center",
				fontsize=8,
			)

	ax.axhline(0, color="gray", linestyle="--", linewidth=0.75)
	xlim = ax.get_xlim()
	ax.text(xlim[0] * 0.95, 0, "270", color="white", ha="center", va="bottom", fontsize=8)
	ax.text(xlim[1] * 0.95, 0, "090", color="white", ha="center", va="bottom", fontsize=8)


def _plot_fan(ax, image_data: np.ndarray, ranges: np.ndarray, beam_angles: np.ndarray, title: str) -> None:
	x_edge, z_edge = _polar_edge_mesh(ranges, beam_angles)
	ax.pcolormesh(x_edge, z_edge, magnitude_log10(image_data), cmap="hot", shading="flat")
	ax.set_aspect("equal")
	ax.set_facecolor("black")
	ax.invert_xaxis()
	ax.set_title(title)
	ax.set_xlabel("X (m)")
	ax.set_ylabel("Z (m)")
	add_matplotlib_polar_grid(ax, ranges, beam_angles)


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Python parity workflow for MATLAB test_split_beam.m."
	)
	parser.add_argument("--file", required=True, help="Path to .mmb file")
	parser.add_argument(
		"--ping-index",
		type=int,
		default=1,
		help="Ping index from start of file (default: 1 to mirror MATLAB example).",
	)
	parser.add_argument(
		"--image-index",
		type=int,
		default=0,
		help="Image index for pings with multiple images (default: 0).",
	)
	parser.add_argument(
		"--save-dir",
		default="outputs",
		help="Directory to save output artifacts (default: outputs).",
	)
	parser.add_argument(
		"--no-show",
		action="store_true",
		help="Save artifacts without opening display windows.",
	)
	args = parser.parse_args()

	sess = MatlabSession()
	sess.start()
	try:
		abs_filepath = os.path.abspath(args.file)
		print(
			f"Running split-beam parity for ping index {args.ping_index} "
			f"(image index {args.image_index}) from {abs_filepath}..."
		)
		(
			header,
			beam_angles_ml,
			range_list_ml,
			image_full_ml,
			image_sub_1_ml,
			image_sub_2_ml,
			phase_angles_ml,
			phase_values_ml,
			mag_angles_ml,
			mag_values_ml,
			fit_angles_ml,
			fit_values_ml,
			aoa_results,
		) = sess.split_beam_ping(abs_filepath, args.ping_index, args.image_index)
		print("Split-beam workflow successful.")

		beam_angles = np.asarray(beam_angles_ml, dtype=np.float32).ravel()
		ranges = np.asarray(range_list_ml, dtype=np.float32).ravel()
		image_full = np.asarray(image_full_ml)
		image_sub_1 = np.asarray(image_sub_1_ml)
		image_sub_2 = np.asarray(image_sub_2_ml)
		phase_angles = np.asarray(phase_angles_ml, dtype=np.float32).ravel()
		phase_values = np.asarray(phase_values_ml, dtype=np.float32).ravel()
		mag_angles = np.asarray(mag_angles_ml, dtype=np.float32).ravel()
		mag_values = np.asarray(mag_values_ml, dtype=np.float32).ravel()
		fit_angles = np.asarray(fit_angles_ml, dtype=np.float32).ravel()
		fit_values = np.asarray(fit_values_ml, dtype=np.float32).ravel()

		save_dir = os.path.abspath(args.save_dir)
		os.makedirs(save_dir, exist_ok=True)
		file_stem = os.path.splitext(os.path.basename(abs_filepath))[0]
		ping_counter = int(float(header.get("Ping_Counter", args.ping_index)))

		fig_full, ax_full = plt.subplots(figsize=(8, 6))
		fig_full.canvas.manager.set_window_title("Split Beam - Full Array")
		_plot_fan(ax_full, image_full, ranges, beam_angles, f"{file_stem} Full Array (ping {ping_counter})")

		fig_sub1, ax_sub1 = plt.subplots(figsize=(8, 6))
		fig_sub1.canvas.manager.set_window_title("Split Beam - Sub Array 1")
		_plot_fan(ax_sub1, image_sub_1, ranges, beam_angles, f"{file_stem} Sub-Array 1 (ping {ping_counter})")

		fig_sub2, ax_sub2 = plt.subplots(figsize=(8, 6))
		fig_sub2.canvas.manager.set_window_title("Split Beam - Sub Array 2")
		_plot_fan(ax_sub2, image_sub_2, ranges, beam_angles, f"{file_stem} Sub-Array 2 (ping {ping_counter})")

		fig_phase, ax_phase = plt.subplots(figsize=(8, 4))
		fig_phase.canvas.manager.set_window_title("Split Beam - Phase Difference")
		ax_phase.plot(phase_angles, phase_values, "b.-")
		ax_phase.grid(True, alpha=0.3)
		ax_phase.set_xlabel("Beam Angle (deg)")
		ax_phase.set_ylabel("Phase Difference (rad)")
		ax_phase.set_title("Split-Beam Phase Difference")

		fig_mag, ax_mag = plt.subplots(figsize=(8, 4))
		fig_mag.canvas.manager.set_window_title("Split Beam - Magnitude Fit")
		ax_mag.plot(mag_angles, mag_values, "b:.", label="Magnitude dB")
		ax_mag.plot(fit_angles, fit_values, "k-", label="Quadratic Fit")
		ax_mag.plot(
			float(aoa_results.get("AOA_degrees", 0.0)),
			float(aoa_results.get("strength_dB", 0.0)),
			"ko",
			label="AOA Estimate",
		)
		ax_mag.grid(True, alpha=0.3)
		ax_mag.set_xlabel("Beam Angle (deg)")
		ax_mag.set_ylabel("Amplitude (dB)")
		ax_mag.set_title("Split-Beam Magnitude Fit")
		ax_mag.legend(loc="best")

		full_path = os.path.join(save_dir, f"{file_stem}_ping{ping_counter}_split_full_array.png")
		sub1_path = os.path.join(save_dir, f"{file_stem}_ping{ping_counter}_split_sub_array_1.png")
		sub2_path = os.path.join(save_dir, f"{file_stem}_ping{ping_counter}_split_sub_array_2.png")
		phase_path = os.path.join(save_dir, f"{file_stem}_ping{ping_counter}_split_phase_diff.png")
		mag_path = os.path.join(save_dir, f"{file_stem}_ping{ping_counter}_split_magnitude_fit.png")
		summary_path = os.path.join(save_dir, f"{file_stem}_ping{ping_counter}_split_beam_summary.json")

		fig_full.savefig(full_path, dpi=200, bbox_inches="tight")
		fig_sub1.savefig(sub1_path, dpi=200, bbox_inches="tight")
		fig_sub2.savefig(sub2_path, dpi=200, bbox_inches="tight")
		fig_phase.savefig(phase_path, dpi=200, bbox_inches="tight")
		fig_mag.savefig(mag_path, dpi=200, bbox_inches="tight")

		summary = {
			"script": "examples/play_split_beam.py",
			"source_file": abs_filepath,
			"ping_index_requested": args.ping_index,
			"image_index_requested": args.image_index,
			"header_subset": {
				"Ping_Number": header.get("Ping_Number"),
				"Ping_Counter": header.get("Ping_Counter"),
				"Phase_Seq_Index": header.get("Phase_Seq_Index"),
				"Num_Beams": header.get("Num_Beams"),
				"Velocity_Sound": header.get("Velocity_Sound"),
				"Sub_Array_Frequency": header.get("Sub_Array_Frequency"),
			},
			"beam_angle_span_deg": {
				"min": float(np.min(beam_angles)),
				"max": float(np.max(beam_angles)),
			},
			"range_span_m": {
				"min": float(np.min(ranges)),
				"max": float(np.max(ranges)),
			},
			"shapes": {
				"image_full": list(image_full.shape),
				"image_sub_1": list(image_sub_1.shape),
				"image_sub_2": list(image_sub_2.shape),
				"phase_values": list(phase_values.shape),
				"mag_values": list(mag_values.shape),
				"fit_values": list(fit_values.shape),
			},
			"aoa_results": aoa_results,
			"full_array_magnitude_stats": array_stats(image_full, use_magnitude=True),
			"sub_array_1_magnitude_stats": array_stats(image_sub_1, use_magnitude=True),
			"sub_array_2_magnitude_stats": array_stats(image_sub_2, use_magnitude=True),
		}
		write_json(summary_path, summary)

		print(f"Saved full-array plot:      {full_path}")
		print(f"Saved sub-array-1 plot:     {sub1_path}")
		print(f"Saved sub-array-2 plot:     {sub2_path}")
		print(f"Saved phase plot:           {phase_path}")
		print(f"Saved magnitude-fit plot:   {mag_path}")
		print(f"Saved split-beam summary:   {summary_path}")

		if args.no_show:
			plt.close(fig_full)
			plt.close(fig_sub1)
			plt.close(fig_sub2)
			plt.close(fig_phase)
			plt.close(fig_mag)
		else:
			print("\nDisplaying plots. Close all plot windows to exit.")
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
