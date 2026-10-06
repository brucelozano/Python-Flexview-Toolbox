from __future__ import annotations

import sys


def run() -> int:
	try:
		from PySide6.QtWidgets import QApplication
	except Exception as exc:  # pragma: no cover
		print(
			"Failed to import PySide6 Qt bindings. "
			"Try reinstalling with `py -3 -m pip install --upgrade --force-reinstall PySide6` "
			"or run inside a clean venv.",
			file=sys.stderr,
		)
		print(f"Import details: {exc}", file=sys.stderr)
		return 1

	from .playback_controller import PlaybackController
	from .ui_main_window import MainWindow

	app = QApplication(sys.argv)
	controller = PlaybackController()
	window = MainWindow(controller)
	window.show()
	return app.exec()


if __name__ == "__main__":
	raise SystemExit(run())
