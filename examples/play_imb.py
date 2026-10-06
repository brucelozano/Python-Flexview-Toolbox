import argparse
import os
import sys
import numpy as np
import matplotlib.pyplot as plt

# Ensure project root is importable when running from examples/ or root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flexview_py.matlab_bridge import MatlabSession
from flexview_py.imb_reader import IMBReader
from flexview_py.geometry import (
    compute_rangelist_from_header,
    magnitude_log10,
    polar_to_cartesian,
)
from flexview_py.reporting import array_stats, write_json

def main() -> None:
	parser = argparse.ArgumentParser(
		description="A Python port of test_load_image.m. Loads and displays a single frame from a .imb file."
	)
	parser.add_argument("--file", required=True, help="Path to .imb file")
	parser.add_argument("--image-offset", type=int, default=3, help="Image offset from start of file (default: 3 to match MATLAB script)")
	parser.add_argument(
		"--ping-index",
		type=int,
		default=None,
		help="Alias for --image-offset for CLI consistency across scripts.",
	)
	parser.add_argument(
		"--save-dir",
		default="outputs",
		help="Directory to save output figures (default: outputs)",
	)
	parser.add_argument(
		"--no-show",
		action="store_true",
		help="Save figures without opening display windows.",
	)
	args = parser.parse_args()

	sess = MatlabSession()
	sess.start()
	reader = IMBReader(sess)

	try:
		# --- Load the single specified frame ---
		# Pass an absolute path to be safe with the MATLAB engine's CWD changes.
		abs_filepath = os.path.abspath(args.file)
		ping_index = args.image_offset if args.ping_index is None else args.ping_index
		print(f"Loading frame at offset: {ping_index} from {abs_filepath}...")
		header, beam_angles, image = reader.load_frame(abs_filepath, ping_index)
		print("Load successful.")

		# --- Data Processing ---
		ping_number = int(header.get('Ping_Number', 0))
		base_filename = os.path.basename(args.file)
		ranges = compute_rangelist_from_header(header)
		img_linear_disp = np.abs(image)
		img_log_disp = magnitude_log10(image)
		
		# --- Create and Display Plots in Separate Windows ---
		
		# --- Raw Data Plot (Figure 1) ---
		fig1, ax1 = plt.subplots(figsize=(7, 6))
		fig1.canvas.manager.set_window_title("Flexview - Raw Plot (Like Figure 1)")
		title_fig1 = f"{base_filename} Ping = {ping_number}, Linear Intensity Scale"
		ax1.set_title(title_fig1)
		extent = [beam_angles[0], beam_angles[-1], ranges[0], ranges[-1]]
		im_raw = ax1.imshow(img_linear_disp, aspect='auto', extent=extent, cmap='plasma', origin='lower')
		ax1.invert_xaxis()
		ax1.set_xlabel("Beam Angle (deg)")
		ax1.set_ylabel("Range (m)")
		fig1.colorbar(im_raw, ax=ax1, label="Linear Intensity", shrink=0.8)

		# --- Rendered Cartesian Plot (Figure 2) ---
		fig2, ax2 = plt.subplots(figsize=(7, 6))
		fig2.canvas.manager.set_window_title("Flexview - Rendered (Like Figure 2)")
		title_fig2 = f"{base_filename} Ping = {ping_number}"
		ax2.set_title(title_fig2)
		x, z = polar_to_cartesian(ranges, beam_angles)
		ax2.pcolormesh(x, z, img_log_disp, cmap='hot', shading='auto')
		ax2.set_aspect('equal')
		ax2.set_facecolor('black')
		ax2.invert_xaxis()
		ax2.set_xlabel("X (m)")
		ax2.set_ylabel("Z (m)")
		add_matplotlib_polar_grid(ax2, ranges, beam_angles)

		# Save both outputs with explicit names so parity checks are straightforward.
		save_dir = os.path.abspath(args.save_dir)
		os.makedirs(save_dir, exist_ok=True)
		file_stem = os.path.splitext(base_filename)[0]
		raw_plot_path = os.path.join(save_dir, f"{file_stem}_ping{ping_number}_raw_polar_linear.png")
		cartesian_plot_path = os.path.join(save_dir, f"{file_stem}_ping{ping_number}_cartesian_fan_log.png")
		summary_path = os.path.join(save_dir, f"{file_stem}_ping{ping_number}_image_summary.json")
		fig1.savefig(raw_plot_path, dpi=200, bbox_inches="tight")
		fig2.savefig(cartesian_plot_path, dpi=200, bbox_inches="tight")
		summary = {
			"script": "examples/play_imb.py",
			"source_file": abs_filepath,
			"ping_index_requested": ping_index,
			"header_subset": {
				"Ping_Number": header.get("Ping_Number"),
				"Num_Beams": header.get("Num_Beams"),
				"Num_Samples": header.get("Num_Samples"),
				"SWST": header.get("SWST"),
				"TXWST": header.get("TXWST"),
				"Image_Sample_Interval": header.get("Image_Sample_Interval"),
				"Velocity_Sound": header.get("Velocity_Sound"),
			},
			"shapes": {
				"beam_angles": list(np.asarray(beam_angles).shape),
				"image_data": list(np.asarray(image).shape),
				"ranges": list(np.asarray(ranges).shape),
			},
			"beam_angle_span_deg": {
				"min": float(np.min(beam_angles)),
				"max": float(np.max(beam_angles)),
			},
			"range_span_m": {
				"min": float(np.min(ranges)),
				"max": float(np.max(ranges)),
			},
			"image_magnitude_stats": array_stats(image, use_magnitude=True),
		}
		write_json(summary_path, summary)
		print(f"Saved raw polar intensity plot: {raw_plot_path}")
		print(f"Saved cartesian fan plot:      {cartesian_plot_path}")
		print(f"Saved image parity summary:    {summary_path}")

		if args.no_show:
			plt.close(fig1)
			plt.close(fig2)
		else:
			print("\nDisplaying plots. Close all plot windows to exit.")
			plt.show() # This will block until all windows are closed.

	except Exception as e:
		print(f"\nAn error occurred: {e}")
		import traceback
		traceback.print_exc()

	finally:
		sess.stop()
		print("Cleanup complete. Exiting.")


def add_matplotlib_polar_grid(ax, ranges, beam_angles_deg):
	"""Adds a custom polar grid and labels to a Matplotlib axes object."""
	min_range, max_range = ranges[0], ranges[-1]
	
	# --- Draw Range Arcs ---
	num_range_rings = 5
	for i in range(num_range_rings + 1):
		r = min_range + (i / num_range_rings) * (max_range - min_range)
		if r > 0:
			angle_rad = np.deg2rad(np.linspace(beam_angles_deg[0], beam_angles_deg[-1], 100))
			x_arc = r * np.sin(angle_rad)
			z_arc = r * np.cos(angle_rad)
			ax.plot(x_arc, z_arc, '--', color='gray', linewidth=0.75)
			# Add range label
			label_angle_deg = beam_angles_deg[0] + 3 # Place on the right
			ax.text(r * np.sin(np.deg2rad(label_angle_deg)),
					r * np.cos(np.deg2rad(label_angle_deg)),
					f" {r:.2f} m",
					color='white', ha='left', va='center', fontsize=8)

	# --- Draw Angle Radials ---
	line_angles_deg = [-60, -30, 0, 30, 60]
	for angle in line_angles_deg:
		if beam_angles_deg[0] <= angle <= beam_angles_deg[-1]:
			ax.plot([0, max_range * np.sin(np.deg2rad(angle))],
					[0, max_range * np.cos(np.deg2rad(angle))],
					'--', color='gray', linewidth=0.75)
			
			# Add angle label ('northup' style)
			if angle == 0: label = "000"
			elif angle > 0: label = f"{360-angle:03d}"
			else: label = f"{-angle:03d}"
			
			r_label = max_range * 1.05
			ax.text(r_label * np.sin(np.deg2rad(angle)),
					r_label * np.cos(np.deg2rad(angle)),
					label,
					color='white', ha='center', va='center', fontsize=8)

	# --- Draw Horizontal Line (270/090 axis) ---
	ax.axhline(0, color='gray', linestyle='--', linewidth=0.75)
	xlim = ax.get_xlim()
	ax.text(xlim[0] * 0.95, 0, '270', color='white', ha='center', va='bottom', fontsize=8)
	ax.text(xlim[1] * 0.95, 0, '090', color='white', ha='center', va='bottom', fontsize=8)


if __name__ == "__main__":
	main()


