import cv2
import numpy as np

from .geometry import polar_to_cartesian

_REMAP_CACHE_MAX = 8
_REMAP_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}
_REMAP_CACHE_ORDER: list[tuple] = []
_HOT_LUT: np.ndarray | None = None


def _remap_cache_get(key: tuple) -> tuple[np.ndarray, np.ndarray] | None:
	value = _REMAP_CACHE.get(key)
	if value is None:
		return None
	try:
		_REMAP_CACHE_ORDER.remove(key)
	except ValueError:
		pass
	_REMAP_CACHE_ORDER.append(key)
	return value


def _remap_cache_put(key: tuple, map_x: np.ndarray, map_y: np.ndarray) -> None:
	if key not in _REMAP_CACHE:
		_REMAP_CACHE_ORDER.append(key)
	_REMAP_CACHE[key] = (map_x, map_y)
	while len(_REMAP_CACHE_ORDER) > _REMAP_CACHE_MAX:
		evict_key = _REMAP_CACHE_ORDER.pop(0)
		_REMAP_CACHE.pop(evict_key, None)


def _hot_colormap(image_u8: np.ndarray) -> np.ndarray:
	"""Apply a matplotlib-like HOT colormap with OpenCV fallback."""
	global _HOT_LUT
	if _HOT_LUT is None:
		try:
			# Build once so player frames avoid matplotlib runtime overhead.
			from matplotlib import cm  # local import to keep startup light

			rgb = (cm.get_cmap("hot")(np.linspace(0, 1, 256))[:, :3] * 255.0).astype(np.uint8)
			_HOT_LUT = rgb[:, ::-1].reshape((256, 1, 3))  # BGR for OpenCV
		except Exception:
			_HOT_LUT = np.empty((0, 0, 0), dtype=np.uint8)

	if _HOT_LUT.size > 0:
		try:
			return cv2.applyColorMap(image_u8, _HOT_LUT)
		except Exception:
			pass
	return cv2.applyColorMap(image_u8, cv2.COLORMAP_HOT)


def show_polar_image(image_disp: np.ndarray, window: str = "Flexview") -> None:
	"""Display a raw polar data matrix (range vs. angle) with OpenCV."""
	img = image_disp
	img = img - np.min(img)
	if np.max(img) > 0:
		img = img / np.max(img)
	img8 = (img * 255.0).astype(np.uint8)
	cimg = cv2.applyColorMap(img8, cv2.COLORMAP_INFERNO)
	cv2.imshow(window, cimg)


def render_cartesian_image(
    image_disp: np.ndarray,
    x_coords: np.ndarray,
    z_coords: np.ndarray,
    output_width_px: int = 800,
) -> np.ndarray:
    """Render polar data onto Cartesian fan close to matplotlib pcolormesh."""
    src = np.asarray(image_disp, dtype=np.float32)
    if src.ndim != 2 or src.size == 0:
        return np.zeros((100, max(1, int(output_width_px)), 3), dtype=np.uint8)

    src_norm = src - float(np.min(src))
    src_max = float(np.max(src_norm))
    if src_max > 0:
        src_norm = src_norm / src_max

    # Determine canvas size from coordinates.
    x_min = float(np.min(x_coords))
    x_max = float(np.max(x_coords))
    z_max = float(np.max(z_coords))
    z_min_render = 0.0
    width_m = x_max - x_min
    height_m = z_max - z_min_render
    if width_m <= 0 or height_m <= 0:
        return np.zeros((100, max(1, int(output_width_px)), 3), dtype=np.uint8)

    output_width_px = max(1, int(output_width_px))
    scale = output_width_px / width_m
    output_height_px = max(1, int(round(height_m * scale)))

    # Derive source polar axes.
    ranges = np.hypot(x_coords[:, 0], z_coords[:, 0]).astype(np.float32)
    beam_angles_deg = np.rad2deg(np.arctan2(x_coords[0, :], z_coords[0, :])).astype(np.float32)

    # Ensure monotonic ascending interpolation axes.
    src_interp = src_norm
    if ranges.size >= 2 and ranges[0] > ranges[-1]:
        ranges = ranges[::-1]
        src_interp = src_interp[::-1, :]
    if beam_angles_deg.size >= 2 and beam_angles_deg[0] > beam_angles_deg[-1]:
        beam_angles_deg = beam_angles_deg[::-1]
        src_interp = src_interp[:, ::-1]

    remap_key = (
        output_width_px,
        output_height_px,
        int(ranges.size),
        int(beam_angles_deg.size),
        round(float(ranges[0]), 5),
        round(float(ranges[-1]), 5),
        round(float(beam_angles_deg[0]), 5),
        round(float(beam_angles_deg[-1]), 5),
        round(x_min, 5),
        round(x_max, 5),
        round(z_max, 5),
    )
    maps = _remap_cache_get(remap_key)
    if maps is None:
        u = np.arange(output_width_px, dtype=np.float32)
        v = np.arange(output_height_px, dtype=np.float32)
        uu, vv = np.meshgrid(u, v, indexing="xy")

        x_world = x_max - (uu / scale)
        z_world = z_min_render + ((output_height_px - 1 - vv) / scale)
        r_world = np.hypot(x_world, z_world)
        a_world = np.rad2deg(np.arctan2(x_world, z_world))

        r_idx = np.interp(
            r_world.ravel(),
            ranges,
            np.arange(ranges.size, dtype=np.float32),
        ).reshape(output_height_px, output_width_px)
        a_idx = np.interp(
            a_world.ravel(),
            beam_angles_deg,
            np.arange(beam_angles_deg.size, dtype=np.float32),
        ).reshape(output_height_px, output_width_px)

        outside = (
            (r_world < float(ranges[0]))
            | (r_world > float(ranges[-1]))
            | (a_world < float(beam_angles_deg[0]))
            | (a_world > float(beam_angles_deg[-1]))
        )
        map_x = a_idx.astype(np.float32)
        map_y = r_idx.astype(np.float32)
        map_x[outside] = -1.0
        map_y[outside] = -1.0
        _remap_cache_put(remap_key, map_x, map_y)
    else:
        map_x, map_y = maps

    remapped = cv2.remap(
        src_interp.astype(np.float32),
        map_x,
        map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=0.0,
    )
    remapped_u8 = np.clip(np.round(remapped * 255.0), 0, 255).astype(np.uint8)
    return _hot_colormap(remapped_u8)


def draw_polar_grid(
	canvas: np.ndarray,
	ranges: np.ndarray,
	beam_angles_deg: np.ndarray,
	num_range_rings: int = 5,
	azimuth_mode: str = 'northup',
	color: tuple[int, int, int] = (200, 200, 200),
	font_scale: float = 0.4,
) -> None:
	"""Overlay a polar grid with labels onto the Cartesian canvas."""
	h, w, _ = canvas.shape
	
	# --- Calculate scale and origin based on canvas dimensions ---
	# This logic mirrors render_cartesian_image to map meters -> pixels
	x_coords, _ = polar_to_cartesian(ranges, beam_angles_deg)
	x_min, x_max = np.min(x_coords), np.max(x_coords)
	
	width_m = x_max - x_min
	scale = w / width_m
	
	# Sonar origin in pixel coordinates
	origin_u = int(((0 - x_min) * scale))
	origin_v = h - 1

	# --- Draw Range Rings (Arcs) ---
	min_range, max_range = ranges[0], ranges[-1]
	# Draw num_range_rings + 1 rings to include the start and end
	for i in range(num_range_rings + 1):
		r_m = min_range + (i / num_range_rings) * (max_range - min_range)
		r_px = int(r_m * scale)
		
		if r_px > 0:
			# Draw the arc
			cv2.ellipse(canvas, (origin_u, origin_v), (r_px, r_px), 0, 
						-90 - beam_angles_deg[-1], -90 - beam_angles_deg[0], color, 1, cv2.LINE_AA)

			# Draw the label
			label = f"{r_m:.2f} m"
			# Position label slightly inside the last ring for visibility
			label_r_px = r_px - 2 if i == num_range_rings else r_px + 2
			text_angle_rad = np.deg2rad(90 + beam_angles_deg[0] + 3) # Place on the right side
			text_u = int(origin_u - label_r_px * np.cos(text_angle_rad))
			text_v = int(origin_v - label_r_px * np.sin(text_angle_rad))
			cv2.putText(canvas, label, (text_u, text_v), cv2.FONT_HERSHEY_SIMPLEX, 
						font_scale, color, 1, cv2.LINE_AA)

	# --- Draw Angle Lines (Radials) ---
	# Use a fixed set of angles for labeling to match MATLAB's style
	line_angles_deg = [-60, -30, 0, 30, 60]
	
	for angle in line_angles_deg:
		# Only draw lines that are within the sonar's actual beam width
		if beam_angles_deg[0] <= angle <= beam_angles_deg[-1]:
			# Apply a negative sign to sin to flip the horizontal axis
			end_u = int(origin_u - max_range * scale * np.sin(np.deg2rad(angle)))
			end_v = int(origin_v - max_range * scale * np.cos(np.deg2rad(angle)))
			cv2.line(canvas, (origin_u, origin_v), (end_u, end_v), color, 1, cv2.LINE_AA)
			
			# Draw the label
			if azimuth_mode == 'northup':
				if angle == 0:
					label = "000"
				elif angle > 0:
					label = f"{360-angle:03d}"
				else: # angle < 0
					label = f"{-angle:03d}"
			else: # standard mode
				label = f"{angle:.0f}"

			# Apply a negative sign to sin to flip the horizontal axis
			text_u = int(origin_u - (max_range * 1.05) * scale * np.sin(np.deg2rad(angle)))
			text_v = int(origin_v - (max_range * 1.05) * scale * np.cos(np.deg2rad(angle)))
			cv2.putText(canvas, label, (text_u, text_v), cv2.FONT_HERSHEY_SIMPLEX, 
						font_scale, color, 1, cv2.LINE_AA)

	# --- Draw Horizontal Line (270/090 axis) ---
	line_v = origin_v
	cv2.line(canvas, (0, line_v), (w, line_v), color, 1, cv2.LINE_AA)
	cv2.putText(canvas, "270", (5, line_v - 5), cv2.FONT_HERSHEY_SIMPLEX, 
				font_scale, color, 1, cv2.LINE_AA)
	cv2.putText(canvas, "090", (w - 30, line_v - 5), cv2.FONT_HERSHEY_SIMPLEX, 
				font_scale, color, 1, cv2.LINE_AA)


