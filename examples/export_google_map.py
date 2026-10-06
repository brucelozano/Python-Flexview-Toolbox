import argparse
import os
import sys

# Ensure project root is importable when running from examples/ or root
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from flexview_py.matlab_bridge import MatlabSession
from flexview_py.reporting import write_json


def main() -> None:
	parser = argparse.ArgumentParser(
		description="Run MATLAB google-track export parity workflow and save summary JSON."
	)
	parser.add_argument(
		"--folder",
		default="M3_MATLAB_Toolbox_1.2/data",
		help="Folder containing .mmb files (default: M3_MATLAB_Toolbox_1.2/data).",
	)
	parser.add_argument(
		"--html-filename",
		default="google_tracks.html",
		help="Name for generated HTML map file (default: google_tracks.html).",
	)
	parser.add_argument(
		"--ping-step",
		type=int,
		default=10,
		help="Ping stride for sampling tracks (default: 10 to mirror MATLAB example).",
	)
	parser.add_argument(
		"--save-dir",
		default="outputs",
		help="Directory to save summary artifact (default: outputs).",
	)
	args = parser.parse_args()

	if args.ping_step <= 0:
		raise ValueError("--ping-step must be > 0")

	data_folder = os.path.abspath(args.folder)
	save_dir = os.path.abspath(args.save_dir)
	os.makedirs(save_dir, exist_ok=True)
	summary_path = os.path.join(
		save_dir,
		f"{os.path.splitext(args.html_filename)[0]}_google_map_summary.json",
	)

	sess = MatlabSession()
	sess.start()
	try:
		print(
			f"Generating Google map from folder {data_folder} "
			f"with ping step {args.ping_step}..."
		)
		summary = sess.export_google_map(data_folder, args.html_filename, args.ping_step)
		write_json(summary_path, summary)
		print(f"Saved Google map summary: {summary_path}")
		print(f"Generated Google map HTML: {summary.get('html_output', '')}")
	except Exception as exc:
		print(f"\nAn error occurred: {exc}")
		import traceback

		traceback.print_exc()
	finally:
		sess.stop()
		print("Cleanup complete. Exiting.")


if __name__ == "__main__":
	main()
