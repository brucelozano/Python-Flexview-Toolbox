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

	# Draw range arcs.
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

	# Draw angle radials.
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

	# Draw horizontal axis labels.
	ax.axhline(0, color="gray", linestyle="--", linewidth=0.75)
	xlim = ax.get_xlim()
	ax.text(xlim[0] * 0.95, 0, "270", color="white", ha="center", va="bottom", fontsize=8)
	ax.text(xlim[1] * 0.95, 0, "090", color="white", ha="center", va="bottom", fontsize=8)


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Python parity workflow for MATLAB test_beamformer.m."
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
			f"Beamforming ping index {args.ping_index} (image index {args.image_index}) "
			f"from {abs_filepath}..."
		)
		header, beam_angles_ml, image_data_ml, range_list_ml, actual_ping = sess.beamform_ping(
			abs_filepath, args.ping_index, args.image_index
		)
		print(f"Beamform successful. Actual ping index used: {actual_ping}")

		image_data = np.asarray(image_data_ml)
		ranges = np.asarray(range_list_ml, dtype=np.float32).ravel()
		beam_angles = np.asarray(beam_angles_ml, dtype=np.float32).ravel()

		img_linear = np.abs(image_data)
		img_log = magnitude_log10(image_data)
		file_stem = os.path.splitext(os.path.basename(abs_filepath))[0]
		ping_number = int(float(header.get("Ping_Number", actual_ping)))

		save_dir = os.path.abspath(args.save_dir)
		os.makedirs(save_dir, exist_ok=True)

		# Plot 1: polar data matrix.
		fig1, ax1 = plt.subplots(figsize=(8, 6))
		fig1.canvas.manager.set_window_title("Flexview - Beamformed Polar")
		extent = [beam_angles[0], beam_angles[-1], ranges[0], ranges[-1]]
		im_raw = ax1.imshow(img_linear, aspect="auto", extent=extent, cmap="plasma", origin="lower")
		ax1.invert_xaxis()
		ax1.set_title(f'{file_stem} Ping = {ping_number}, Beamformed (Linear)')
		ax1.set_xlabel("Beam Angle (deg)")
		ax1.set_ylabel("Range (m)")
		fig1.colorbar(im_raw, ax=ax1, label="Linear Intensity", shrink=0.8)

		# Plot 2: rendered cartesian fan image (log10 scale).
		fig2, ax2 = plt.subplots(figsize=(8, 6))
		fig2.canvas.manager.set_window_title("Flexview - Beamformed Cartesian Fan")
		x_edge, z_edge = _polar_edge_mesh(ranges, beam_angles)
		ax2.pcolormesh(x_edge, z_edge, img_log, cmap="hot", shading="flat")
		ax2.set_aspect("equal")
		ax2.set_facecolor("black")
		ax2.invert_xaxis()
		ax2.set_title(f'{file_stem} Ping = {ping_number}, Beamformed (Log10)')
		ax2.set_xlabel("X (m)")
		ax2.set_ylabel("Z (m)")
		add_matplotlib_polar_grid(ax2, ranges, beam_angles)

		polar_plot_path = os.path.join(
			save_dir, f"{file_stem}_ping{ping_number}_beamformed_polar_linear.png"
		)
		cartesian_plot_path = os.path.join(
			save_dir, f"{file_stem}_ping{ping_number}_beamformed_cartesian_log.png"
		)
		summary_path = os.path.join(
			save_dir, f"{file_stem}_ping{ping_number}_beamformer_summary.json"
		)
		fig1.savefig(polar_plot_path, dpi=200, bbox_inches="tight")
		fig2.savefig(cartesian_plot_path, dpi=200, bbox_inches="tight")

		header_keys = [
			"Ping_Number",
			"Ping_Counter",
			"Num_Elements",
			"Num_Beams",
			"Num_Samples",
			"Num_Images",
			"Phase_Seq_Index",
			"Velocity_Sound",
			"Sub_Array_Frequency",
			"Raw_Sample_Interval",
			"Sampling_Window_Start_Time",
			"Start_Raw_Sample",
			"End_Raw_Sample",
		]
		summary = {
			"script": "examples/play_beamformer.py",
			"source_file": abs_filepath,
			"ping_index_requested": args.ping_index,
			"actual_ping_index_used": actual_ping,
			"image_index_requested": args.image_index,
			"header_subset": {key: header.get(key) for key in header_keys},
			"shapes": {
				"image_data": list(image_data.shape),
				"range_list": list(ranges.shape),
				"beam_angles": list(beam_angles.shape),
			},
			"beam_angle_span_deg": {
				"min": float(np.min(beam_angles)) if beam_angles.size else 0.0,
				"max": float(np.max(beam_angles)) if beam_angles.size else 0.0,
			},
			"range_span_m": {
				"min": float(np.min(ranges)) if ranges.size else 0.0,
				"max": float(np.max(ranges)) if ranges.size else 0.0,
			},
			"beamformed_magnitude_stats": array_stats(image_data, use_magnitude=True),
		}
		write_json(summary_path, summary)

		print(f"Saved beamformed polar plot: {polar_plot_path}")
		print(f"Saved beamformed fan plot:   {cartesian_plot_path}")
		print(f"Saved beamformer summary:    {summary_path}")

		if args.no_show:
			plt.close(fig1)
			plt.close(fig2)
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
