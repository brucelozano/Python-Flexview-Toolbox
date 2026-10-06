function [summary_json] = export_google_map_py(data_folder, html_filename, ping_step)
% EXPORT_GOOGLE_MAP_PY Python-friendly wrapper around test_google_map flow.

if nargin < 3 || isempty(ping_step)
    ping_step = 10;
end

if ~isfolder(data_folder)
    error('Data folder not found: %s', data_folder);
end

html_out = fullfile(data_folder, html_filename);

filelist = dir(fullfile(data_folder, '*.mmb'));
N = numel(filelist);
if N == 0
    error('No .mmb files found in folder: %s', data_folder);
end

extract = struct([]);

for ii = 1:N
    filename = filelist(ii).name;
    lat_vec = [];
    lon_vec = [];
    time_s_vec = [];
    time_ms_vec = [];
    ping_i = 0;
    done = 0;
    while ~done
        try
            [hdr, ~, ~] = load_raw_data(fullfile(data_folder, filename), ping_i);
            lat_vec = [lat_vec; hdr.Reference_Latitude];
            lon_vec = [lon_vec; hdr.Reference_Longitude];
            time_s_vec = [time_s_vec; hdr.Time_s];
            time_ms_vec = [time_ms_vec; hdr.Time_ms];
            ping_i = ping_i + ping_step;
        catch
            done = 1;
        end
    end

    extract(ii).filename = filename;
    extract(ii).lat_vec = lat_vec;
    extract(ii).lon_vec = lon_vec;
    extract(ii).time_s_vec = time_s_vec;
    extract(ii).time_ms_vec = time_ms_vec;
end

sw_corner.latitude = Inf;
sw_corner.longitude = Inf;
ne_corner.latitude = -Inf;
ne_corner.longitude = -Inf;

for ii = 1:N
    lat_vec = extract(ii).lat_vec;
    lon_vec = extract(ii).lon_vec;
    if isempty(lat_vec) || isempty(lon_vec)
        continue;
    end

    sw_corner.latitude = min(sw_corner.latitude, min(lat_vec));
    sw_corner.longitude = min(sw_corner.longitude, min(lon_vec));
    ne_corner.latitude = max(ne_corner.latitude, max(lat_vec));
    ne_corner.longitude = max(ne_corner.longitude, max(lon_vec));

    M = length(lat_vec);
    if M > 10
        m_i = round(linspace(1, M, 10));
        extract(ii).lat_vec = lat_vec(m_i);
        extract(ii).lon_vec = lon_vec(m_i);
        extract(ii).time_s_vec = extract(ii).time_s_vec(m_i);
        extract(ii).time_ms_vec = extract(ii).time_ms_vec(m_i);
    end
end

settings = struct();
settings.sw_corner = sw_corner;
settings.ne_corner = ne_corner;
settings.tracks = [];
settings.markers = [];

SECONDS_PER_DAY = 24 * 3600;
SECONDS_1970_01_Jan = datenum('01-Jan-1970 00:00:00', 'dd-mmm-yyyy HH:MM:SS') * SECONDS_PER_DAY;

marker_idx = 0;
track_idx = 0;
for ii = 1:N
    if isempty(extract(ii).lat_vec) || isempty(extract(ii).lon_vec)
        continue;
    end

    marker_idx = marker_idx + 1;
    timestamp_s = extract(ii).time_s_vec(1);
    timestamp_date = datestr((timestamp_s + SECONDS_1970_01_Jan)/SECONDS_PER_DAY, 'dd-mmm-yyyy HH:MM:SS');

    settings.markers(marker_idx).latitude = extract(ii).lat_vec(1);
    settings.markers(marker_idx).longitude = extract(ii).lon_vec(1);
    settings.markers(marker_idx).label = extract(ii).filename;
    settings.markers(marker_idx).tip = timestamp_date;

    track_idx = track_idx + 1;
    for k = 1:length(extract(ii).lat_vec)
        settings.tracks(track_idx).track(k).latitude = extract(ii).lat_vec(k);
        settings.tracks(track_idx).track(k).longitude = extract(ii).lon_vec(k);
    end
end

options = struct();
generate_google_map(html_out, settings, options);

coord_folder = fileparts(which('generate_google_map'));
copyfile(fullfile(coord_folder, 'markerwithlabel.js'), fullfile(data_folder, 'markerwithlabel.js'));

summary = struct();
summary.data_folder = data_folder;
summary.html_output = html_out;
summary.file_count = N;
summary.track_count = length(settings.tracks);
summary.marker_count = length(settings.markers);
summary.ping_step = ping_step;
summary.sw_lat = settings.sw_corner.latitude;
summary.sw_lon = settings.sw_corner.longitude;
summary.ne_lat = settings.ne_corner.latitude;
summary.ne_lon = settings.ne_corner.longitude;
summary_json = jsonencode(summary);
end
