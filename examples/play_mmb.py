import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np

# Ensure project root is importable when running from examples/ or root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flexview_py.matlab_bridge import MatlabSession
from flexview_py.reporting import array_stats, write_json


def _header_subset(header: dict, keys: list[str]) -> dict:
	return {key: header.get(key) for key in keys}


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Load and inspect one raw ping from an MMB file."
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
			f"Loading raw ping at index {args.ping_index} "
			f"(image index {args.image_index}) from {abs_filepath}..."
		)
		header, beam_angles_ml, ref_pulse_ml, raw_data_ml = sess.load_raw_data(
			abs_filepath, args.ping_index, args.image_index
		)
		print("Load successful.")

		raw_data = np.asarray(raw_data_ml)
		ref_pulse = np.asarray(ref_pulse_ml).ravel()
		beam_angles = np.asarray(beam_angles_ml, dtype=np.float32).ravel()
		raw_mag = np.abs(raw_data)
		ping_number = int(float(header.get("Ping_Number", args.ping_index)))
		file_stem = os.path.splitext(os.path.basename(abs_filepath))[0]

		save_dir = os.path.abspath(args.save_dir)
		os.makedirs(save_dir, exist_ok=True)

		# Plot 1: raw data magnitude matrix.
		fig1, ax1 = plt.subplots(figsize=(8, 6))
		fig1.canvas.manager.set_window_title("Flexview - Raw MMB Magnitude")
		im = ax1.imshow(raw_mag, aspect="auto", cmap="viridis", origin="lower")
		ax1.invert_xaxis()
		ax1.set_title(f"{file_stem} Ping = {ping_number}, |Raw Data|")
		ax1.set_xlabel("Element Index")
		ax1.set_ylabel("Sample Index")
		fig1.colorbar(im, ax=ax1, label="Magnitude", shrink=0.8)

		# Plot 2: reference pulse (real and imag).
		fig2, ax2 = plt.subplots(figsize=(8, 4))
		fig2.canvas.manager.set_window_title("Flexview - Raw MMB Reference Pulse")
		if ref_pulse.size > 0:
			ax2.plot(np.real(ref_pulse), label="Real")
			ax2.plot(np.imag(ref_pulse), label="Imag")
		ax2.set_title(f"{file_stem} Ping = {ping_number}, Reference Pulse")
		ax2.set_xlabel("Sample")
		ax2.set_ylabel("Amplitude")
		ax2.grid(True, alpha=0.3)
		ax2.legend(loc="best")

		raw_plot_path = os.path.join(
			save_dir, f"{file_stem}_ping{ping_number}_raw_magnitude.png"
		)
		ref_plot_path = os.path.join(
			save_dir, f"{file_stem}_ping{ping_number}_ref_pulse.png"
		)
		summary_path = os.path.join(
			save_dir, f"{file_stem}_ping{ping_number}_raw_summary.json"
		)

		fig1.savefig(raw_plot_path, dpi=200, bbox_inches="tight")
		fig2.savefig(ref_plot_path, dpi=200, bbox_inches="tight")

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
			"script": "examples/play_mmb.py",
			"source_file": abs_filepath,
			"ping_index_requested": args.ping_index,
			"image_index_requested": args.image_index,
			"header_subset": _header_subset(header, header_keys),
			"shapes": {
				"raw_data": list(raw_data.shape),
				"ref_pulse": list(ref_pulse.shape),
				"beam_angles": list(beam_angles.shape),
			},
			"beam_angle_span_deg": {
				"min": float(np.min(beam_angles)) if beam_angles.size else 0.0,
				"max": float(np.max(beam_angles)) if beam_angles.size else 0.0,
			},
			"raw_magnitude_stats": array_stats(raw_data, use_magnitude=True),
			"ref_pulse_magnitude_stats": array_stats(ref_pulse, use_magnitude=True),
		}
		write_json(summary_path, summary)

		print(f"Saved raw magnitude plot: {raw_plot_path}")
		print(f"Saved reference pulse plot: {ref_plot_path}")
		print(f"Saved raw parity summary: {summary_path}")

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
