from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


_VALID_IMAGE_TYPES = {0x1002, 0x1003, 0x2003}
_SYNC_WORDS = (0x8000, 0x8000, 0x8000, 0x8000)


@dataclass
class NativeFlexviewFrame:
	header: dict[str, Any]
	beam_angles_deg: np.ndarray
	image: np.ndarray
	ranges_m: np.ndarray
	ping_index: int


class NativeFlexviewReader:
	"""Native Python decoder for FlexView packetized IMB/MMB files."""

	def __init__(self, file_path: str) -> None:
		self._file_path = str(Path(file_path).resolve())
		self._file_sequence = self._discover_file_sequence(self._file_path)
		self._file_sizes: list[int] = []
		self._frame_locations: list[tuple[str, int]] = []
		self._frame_count = 0
		self._handle = None
		self._current_handle_path: str | None = None
		self._build_frame_index()

	@property
	def frame_count(self) -> int:
		return int(self._frame_count)

	def close(self) -> None:
		if self._handle is not None:
			self._handle.close()
			self._handle = None
			self._current_handle_path = None

	def load_frame(self, ping_index: int) -> NativeFlexviewFrame:
		if self._frame_count <= 0:
			raise RuntimeError("No FlexView acoustic packets found in file.")
		if ping_index < 0 or ping_index >= self._frame_count:
			raise IndexError(f"Ping index {ping_index} out of range (0..{self._frame_count - 1}).")

		packet_path, packet_offset = self._frame_locations[int(ping_index)]

		handle = self._open_handle(packet_path)
		handle.seek(packet_offset, os.SEEK_SET)

		prefix = handle.read(56)
		if len(prefix) < 56:
			raise RuntimeError("Incomplete packet prefix.")
		data_type = struct.unpack("<H", prefix[8:10])[0]
		body_size = struct.unpack("<I", prefix[52:56])[0]

		body_prefix = handle.read(76)
		if len(body_prefix) < 76:
			raise RuntimeError("Incomplete packet body prefix.")

		velocity_sound = float(struct.unpack("<f", body_prefix[48:52])[0])
		if velocity_sound <= 0.0:
			velocity_sound = 1500.0
		num_samples = int(struct.unpack("<I", body_prefix[52:56])[0])
		swst = float(struct.unpack("<f", body_prefix[64:68])[0])
		swl = float(struct.unpack("<f", body_prefix[68:72])[0])
		num_beams = int(struct.unpack("<H", body_prefix[72:74])[0])

		beam_list_bytes = handle.read(4096)
		if len(beam_list_bytes) < 4096:
			raise RuntimeError("Incomplete beam list in packet.")
		all_beams = struct.unpack("<1024f", beam_list_bytes)
		beam_angles = np.asarray(all_beams[:num_beams], dtype=np.float32)

		post_beam = handle.read(544)
		if len(post_beam) < 544:
			raise RuntimeError("Incomplete post-beam metadata block in packet.")
		image_sample_interval = float(struct.unpack("<f", post_beam[0:4])[0])
		txwst = float(struct.unpack("<f", post_beam[324:328])[0])
		ping_number = int(struct.unpack("<I", post_beam[36:40])[0])

		if image_sample_interval <= 0.0 and num_samples > 0:
			image_sample_interval = float(swl) / float(num_samples)

		expected_pixels = max(0, num_beams) * max(0, num_samples)
		bytes_per_pixel = 1 if data_type == 0x2003 else (8 if data_type == 0x1002 else 4)
		data_body_size = expected_pixels * bytes_per_pixel

		header_data_read = 76 + 4096 + 544
		remaining_body = int(body_size) - header_data_read - data_body_size
		if remaining_body > 0:
			handle.seek(remaining_body, os.SEEK_CUR)

		raw_pixels = handle.read(data_body_size)
		if len(raw_pixels) < data_body_size:
			raise RuntimeError("Incomplete image payload in packet.")

		if data_type == 0x2003:
			image = np.frombuffer(raw_pixels, dtype=np.uint8).reshape((num_beams, num_samples)).astype(np.float32)
		elif data_type == 0x1002:
			float_data = np.frombuffer(raw_pixels, dtype=np.float32)
			complex_data = float_data.reshape((num_beams, num_samples, 2))
			image = complex_data[..., 0] + 1j * complex_data[..., 1]
		else:
			image = np.frombuffer(raw_pixels, dtype=np.float32).reshape((num_beams, num_samples))

		# Convert to [range_samples, beams] to match player rendering path.
		image = image.T
		if beam_angles.size > 1 and float(beam_angles[0]) > float(beam_angles[-1]):
			beam_angles = beam_angles[::-1]
			image = image[:, ::-1]

		range_samples = np.arange(1, num_samples + 1, dtype=np.float32)
		ranges_m = (swst - txwst + (image_sample_interval * range_samples)) * velocity_sound / 2.0
		ranges_m = ranges_m.astype(np.float32)

		header = {
			"Ping_Number": ping_number if ping_number > 0 else int(ping_index),
			"Num_Beams": int(num_beams),
			"Num_Samples": int(num_samples),
			"SWST": float(swst),
			"TXWST": float(txwst),
			"Image_Sample_Interval": float(image_sample_interval),
			"Velocity_Sound": float(velocity_sound),
			"Data_Type": int(data_type),
		}
		return NativeFlexviewFrame(
			header=header,
			beam_angles_deg=beam_angles,
			image=image,
			ranges_m=ranges_m,
			ping_index=int(ping_index),
		)

	def _discover_file_sequence(self, root_path: str) -> list[str]:
		base_name, _ = os.path.splitext(root_path)
		sequence = [root_path]
		seq_idx = 1
		while True:
			next_path = f"{base_name}.{seq_idx:03d}"
			if not os.path.exists(next_path):
				break
			sequence.append(next_path)
			seq_idx += 1
		return sequence

	def _build_frame_index(self) -> None:
		if not self._file_sequence:
			return

		self._file_sizes = [os.path.getsize(path) for path in self._file_sequence]
		self._frame_locations.clear()
		for file_path, file_size in zip(self._file_sequence, self._file_sizes):
			if file_size <= 0:
				continue
			with open(file_path, "rb") as handle:
				while handle.tell() < file_size:
					pos = int(handle.tell())
					prefix = handle.read(56)
					if len(prefix) < 56:
						break

					sync_words = struct.unpack("<4H", prefix[0:8])
					if sync_words != _SYNC_WORDS:
						# Resync one byte at a time when malformed/metadata regions are present.
						handle.seek(pos + 1, os.SEEK_SET)
						continue

					data_type = int(struct.unpack("<H", prefix[8:10])[0])
					body_size = int(struct.unpack("<I", prefix[52:56])[0])
					packet_size = int(56 + body_size + 44)
					if body_size <= 0 or packet_size <= 100:
						handle.seek(pos + 1, os.SEEK_SET)
						continue

					next_pos = pos + packet_size
					if next_pos > file_size:
						break

					if data_type in _VALID_IMAGE_TYPES and body_size > 4172:
						self._frame_locations.append((file_path, pos))

					handle.seek(next_pos, os.SEEK_SET)
		self._frame_count = int(len(self._frame_locations))

	def _open_handle(self, file_path: str):
		if self._handle is None or self._current_handle_path != file_path:
			self.close()
			self._handle = open(file_path, "rb")
			self._current_handle_path = file_path
		return self._handle

	def __del__(self) -> None:  # pragma: no cover
		self.close()


def _self_check() -> None:
	import tempfile

	def _mk_packet(data_type: int, body: bytes) -> bytes:
		prefix = bytearray(56)
		prefix[0:8] = struct.pack("<4H", *_SYNC_WORDS)
		prefix[8:10] = struct.pack("<H", int(data_type))
		prefix[52:56] = struct.pack("<I", len(body))
		return bytes(prefix) + body + (b"\x00" * 44)

	def _mk_image_body(ping_number: int, *, num_beams: int = 2, num_samples: int = 3) -> bytes:
		body_prefix = bytearray(76)
		body_prefix[48:52] = struct.pack("<f", 1500.0)
		body_prefix[52:56] = struct.pack("<I", num_samples)
		body_prefix[64:68] = struct.pack("<f", 0.01)
		body_prefix[68:72] = struct.pack("<f", 0.003)
		body_prefix[72:74] = struct.pack("<H", num_beams)

		beam = bytearray(4096)
		beam[0:4096] = struct.pack("<1024f", -10.0, 10.0, *([0.0] * 1022))

		post = bytearray(544)
		post[0:4] = struct.pack("<f", 0.001)
		post[36:40] = struct.pack("<I", int(ping_number))
		post[324:328] = struct.pack("<f", 0.0001)

		img = np.arange(num_beams * num_samples, dtype=np.float32).reshape((num_beams, num_samples))
		return bytes(body_prefix) + bytes(beam) + bytes(post) + img.tobytes(order="C")

	with tempfile.TemporaryDirectory() as tmp_dir:
		path = Path(tmp_dir) / "self_check.imb"
		packets = [
			_mk_packet(0x1003, _mk_image_body(1000)),
			_mk_packet(0x2222, b"\x11" * 64),
			_mk_packet(0x1003, _mk_image_body(1001)),
			_mk_packet(0x1003, _mk_image_body(1002)),
		]
		path.write_bytes(b"".join(packets))

		reader = NativeFlexviewReader(str(path))
		assert reader.frame_count == 3
		frame0 = reader.load_frame(0)
		frame1 = reader.load_frame(1)
		frame2 = reader.load_frame(2)
		assert int(frame0.header["Ping_Number"]) == 1000
		assert int(frame1.header["Ping_Number"]) == 1001
		assert int(frame2.header["Ping_Number"]) == 1002
		assert frame1.image.shape == (3, 2)
		reader.close()


if __name__ == "__main__":
	_self_check()
	print("native_flexview_reader self-check passed")
