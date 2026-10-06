from __future__ import annotations

import json
import os
from typing import Any

import numpy as np


def matlab_struct_to_dict(obj: Any) -> dict[str, Any]:
	"""Convert MATLAB struct-like objects to shallow Python dicts."""
	if isinstance(obj, dict):
		return obj
	if hasattr(obj, "_fieldnames"):
		return {field: getattr(obj, field) for field in obj._fieldnames}
	return {}


def to_serializable(value: Any) -> Any:
	"""Recursively convert NumPy/scalar values to JSON-safe Python types."""
	if isinstance(value, dict):
		return {str(k): to_serializable(v) for k, v in value.items()}
	if isinstance(value, (list, tuple)):
		return [to_serializable(v) for v in value]
	if isinstance(value, np.ndarray):
		return to_serializable(value.tolist())
	if isinstance(value, np.generic):
		return value.item()
	if isinstance(value, complex):
		return {"real": value.real, "imag": value.imag}
	return value


def write_json(path: str, payload: dict[str, Any]) -> None:
	"""Write JSON summary payload with parent directory creation."""
	parent = os.path.dirname(path)
	if parent:
		os.makedirs(parent, exist_ok=True)
	with open(path, "w", encoding="utf-8") as f:
		json.dump(to_serializable(payload), f, indent=2, sort_keys=True)


def array_stats(arr: np.ndarray, use_magnitude: bool = False) -> dict[str, float]:
	"""Compute basic summary statistics for parity checks."""
	if arr.size == 0:
		return {"min": 0.0, "max": 0.0, "mean": 0.0, "std": 0.0}
	work = np.abs(arr) if use_magnitude else arr
	work = np.asarray(work, dtype=np.float64)
	return {
		"min": float(np.min(work)),
		"max": float(np.max(work)),
		"mean": float(np.mean(work)),
		"std": float(np.std(work)),
	}
