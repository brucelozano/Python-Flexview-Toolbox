"""Flatten saved per-ping annotation JSON into one CSV (one row per annotation)."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

COLUMNS = [
	"dataset", "annotator", "ping_index", "ping_number", "ping_timestamp_utc",
	"annotation_number", "measurement_id", "status", "annotation_type", "class_name",
	"centroid_x_m", "centroid_z_m", "centroid_range_m", "centroid_angle_deg",
	"length_m", "width_m", "height_m", "area_m2", "perimeter_m", "vertex_count",
	"intensity_samples", "intensity_mean_db", "intensity_max_db", "intensity_std_db",
	"saved_at_utc",
]
_METRIC_COLUMNS = COLUMNS[COLUMNS.index("centroid_x_m"):COLUMNS.index("saved_at_utc")]
_PING_TS = re.compile(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}(?:\.\d+)?) UTC")


def _iso_timestamp(value: object) -> object:
	"""'2021-05-30 16:37:21.775 UTC' -> '2021-05-30T16:37:21.775Z' (sorts/parses cleanly); other text passes through."""
	match = _PING_TS.fullmatch(str(value))
	return f"{match[1]}T{match[2]}Z" if match else value


def _row(record: dict, *, dataset: str, annotator: str, ping_index: int) -> dict:
	metrics = dict(record.get("metrics") or {})
	points = (record.get("geometry") or {}).get("points") or []
	if record.get("annotation_type") == "line" and len(points) >= 2:
		# Lines have no centroid; use the midpoint so every row has a position.
		cx = (points[0]["x_m"] + points[-1]["x_m"]) / 2.0
		cz = (points[0]["z_m"] + points[-1]["z_m"]) / 2.0
		metrics.update(
			centroid_x_m=cx,
			centroid_z_m=cz,
			centroid_range_m=math.hypot(cx, cz),
			centroid_angle_deg=math.degrees(math.atan2(cx, cz)),
		)
	timestamp = record.get("ping_timestamp_utc")
	return {
		"dataset": dataset,
		"annotator": annotator,
		"ping_index": ping_index,
		"ping_number": record.get("ping_number"),
		"ping_timestamp_utc": None if timestamp in (None, "", "-") else _iso_timestamp(timestamp),  # older records lack it
		"annotation_number": record.get("ping_measurement_index"),
		"measurement_id": record.get("measurement_id"),
		"status": "annotated",
		"annotation_type": record.get("annotation_type"),
		"class_name": record.get("class_name"),
		**{key: metrics.get(key) for key in _METRIC_COLUMNS},
		"saved_at_utc": str(record.get("saved_at_utc") or "")[:19] or None,
	}


def _fmt(value: object) -> object:
	if value is None:
		return ""
	return f"{value:.4f}" if isinstance(value, float) else value


def collect_rows(measurements_root: Path, dataset: str) -> tuple[list[dict], list[str]]:
	"""Rows sorted by ping index (numeric), then annotator, then annotation number; plus skipped file names."""
	rows: list[dict] = []
	skipped: list[str] = []
	if not measurements_root.is_dir():
		return rows, skipped
	for annotator_dir in sorted(p for p in measurements_root.iterdir() if p.is_dir()):
		annotator = annotator_dir.name
		# Exact per-ping name only, so old `_polygon`/`_box` copies are not double counted.
		pattern = re.compile(rf"ping_(\d+)_measurements_{re.escape(annotator)}\.json")
		for path in annotator_dir.iterdir():
			match = pattern.fullmatch(path.name)
			if match is None:
				continue
			ping_index = int(match.group(1))
			try:
				records = json.loads(path.read_text(encoding="utf-8"))
				if not isinstance(records, list):
					raise ValueError("not a list")
			except (OSError, ValueError):
				skipped.append(f"{annotator}/{path.name}")
				continue
			if not records:  # empty ping file == reviewed, no targets
				rows.append({"dataset": dataset, "annotator": annotator, "ping_index": ping_index, "status": "no_targets"})
				continue
			rows.extend(
				_row(r, dataset=dataset, annotator=annotator, ping_index=ping_index)
				for r in records
				if isinstance(r, dict)
			)
	rows.sort(key=lambda r: (r["ping_index"], r["annotator"], r.get("annotation_number") or 0))
	return rows, skipped


def export_annotations_csv(measurements_root: Path, csv_path: Path, dataset: str) -> dict:
	"""Write the CSV (utf-8 with BOM so Excel opens it cleanly). Writes nothing if there are no rows."""
	rows, skipped = collect_rows(measurements_root, dataset)
	summary = {
		"rows": len(rows),
		"pings": len({r["ping_index"] for r in rows}),
		"annotators": sorted({r["annotator"] for r in rows}),
		"no_target_pings": sum(1 for r in rows if r["status"] == "no_targets"),
		"skipped": skipped,
	}
	if not rows:
		return summary
	csv_path.parent.mkdir(parents=True, exist_ok=True)
	with csv_path.open("w", newline="", encoding="utf-8-sig") as handle:
		writer = csv.DictWriter(handle, COLUMNS, lineterminator="\n")
		writer.writeheader()
		for row in rows:
			writer.writerow({key: _fmt(row.get(key)) for key in COLUMNS})
	return summary


def _self_check() -> None:
	import tempfile

	def rec(ping, n, kind="polygon", **extra):
		return {"measurement_id": f"P{ping:06d}-{n:03d}", "ping_index": ping, "ping_number": ping, "ping_measurement_index": n,
				"annotation_type": kind, "class_name": "fish", "saved_at_utc": "2026-11-17T10:00:00.123+00:00",
				"geometry": {"points": [{"x_m": 0.0, "z_m": 4.0}, {"x_m": 2.0, "z_m": 4.0}]},
				"metrics": {"area_m2": 1.0, "length_m": 2.0}, **extra}

	with tempfile.TemporaryDirectory() as tmp:
		root = Path(tmp) / "measurements"
		(root / "ann").mkdir(parents=True)
		(root / "zed").mkdir()
		# Annotated out of order (jumping around), ping 15 reviewed-empty, 0-9 and 21+ never touched.
		for ping in (20, 12, 10, 18, 11):
			recs = [rec(ping, 2, "line", ping_timestamp_utc="2021-05-30 12:36:49.500 UTC"), rec(ping, 1)]
			(root / "ann" / f"ping_{ping:06d}_measurements_ann.json").write_text(json.dumps(recs))
		(root / "ann" / "ping_000015_measurements_ann.json").write_text("[]")
		(root / "ann" / "ping_000010_measurements_ann_polygon.json").write_text(json.dumps([rec(10, 9)]))  # legacy copy: ignored
		(root / "ann" / "ping_000013_measurements_ann.json").write_text("{not json")
		(root / "zed" / "ping_000010_measurements_zed.json").write_text(json.dumps([rec(10, 1)]))
		out = Path(tmp) / "reports" / "a.csv"
		summary = export_annotations_csv(root, out, "ds,1")
		with out.open(encoding="utf-8-sig", newline="") as handle:
			table = list(csv.DictReader(handle))
		assert [int(r["ping_index"]) for r in table] == [10, 10, 10, 11, 11, 12, 12, 15, 18, 18, 20, 20], table
		assert [r["annotator"] for r in table[:3]] == ["ann", "ann", "zed"] and [r["annotation_number"] for r in table[:2]] == ["1", "2"]
		assert summary["pings"] == 6 and summary["no_target_pings"] == 1 and summary["skipped"] == ["ann/ping_000013_measurements_ann.json"]
		assert table[7]["status"] == "no_targets" and table[7]["class_name"] == "" and table[0]["dataset"] == "ds,1"
		line = table[1]
		assert line["annotation_type"] == "line" and line["centroid_x_m"] == "1.0000" and line["ping_timestamp_utc"] == "2021-05-30T12:36:49.500Z"
		assert table[0]["ping_timestamp_utc"] == ""
		assert export_annotations_csv(root / "missing", Path(tmp) / "none.csv", "x")["rows"] == 0 and not (Path(tmp) / "none.csv").exists()


if __name__ == "__main__":
	_self_check()
	print("annotation_export self-check ok")
