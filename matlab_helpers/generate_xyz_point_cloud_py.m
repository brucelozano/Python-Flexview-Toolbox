function [summary_json] = generate_xyz_point_cloud_py(filename_pmb, filename_xyz, ...
    ping_start, ping_end, z_max, pitch_sensor_offset, roll_sensor_offset, hdg_sensor_offset, ...
    figures_dir, figure_prefix)
% GENERATE_XYZ_POINT_CLOUD_PY Python-friendly wrapper around
% generate_xyz_point_cloud.m with summary output.

if nargin < 3 || isempty(ping_start)
    ping_start = 0;
end
if nargin < 4 || isempty(ping_end)
    ping_end = 9999;
end
if nargin < 5 || isempty(z_max)
    z_max = inf;
end
if nargin < 6 || isempty(pitch_sensor_offset)
    pitch_sensor_offset = 0;
end
if nargin < 7 || isempty(roll_sensor_offset)
    roll_sensor_offset = 0;
end
if nargin < 8 || isempty(hdg_sensor_offset)
    hdg_sensor_offset = 0;
end
if nargin < 9
    figures_dir = '';
end
if nargin < 10 || isempty(figure_prefix)
    figure_prefix = 'georef';
end

settings = struct();
settings.filename_pmb = filename_pmb;
settings.filename_xyz = filename_xyz;

options = struct();
options.ping_start = ping_start;
options.ping_end = ping_end;
options.z_max = z_max;
options.pitch_sensor_offset = pitch_sensor_offset;
options.roll_sensor_offset = roll_sensor_offset;
options.hdg_sensor_offset = hdg_sensor_offset;

fig_before = findall(0, 'Type', 'figure');
fig_before_ids = double(fig_before(:));

% Suppress MATLAB GUI figure windows during Python-driven runs.
old_default_figure_visible = get(0, 'DefaultFigureVisible');
set(0, 'DefaultFigureVisible', 'off');
restore_visibility = onCleanup(@() set(0, 'DefaultFigureVisible', old_default_figure_visible)); %#ok<NASGU>

generate_xyz_point_cloud(settings, options);

fig_after = findall(0, 'Type', 'figure');
fig_after_ids = double(fig_after(:));
new_fig_ids = setdiff(fig_after_ids, fig_before_ids);

figure_files = {};
new_fig_handles = [];
for ii = 1:numel(fig_after)
    if ismember(double(fig_after(ii)), new_fig_ids)
        new_fig_handles = [new_fig_handles; fig_after(ii)];
    end
end

if ~isempty(figures_dir)
    if ~isfolder(figures_dir)
        mkdir(figures_dir);
    end
    for kk = 1:numel(new_fig_handles)
        out_file = fullfile(figures_dir, sprintf('%s_matlab_fig_%02d.png', figure_prefix, kk));
        try
            exportgraphics(new_fig_handles(kk), out_file, 'Resolution', 200);
        catch
            saveas(new_fig_handles(kk), out_file);
        end
        figure_files{end+1} = out_file;
    end
end

for kk = 1:numel(new_fig_handles)
    if isgraphics(new_fig_handles(kk))
        close(new_fig_handles(kk));
    end
end

summary = struct();
summary.filename_pmb = filename_pmb;
summary.filename_xyz = filename_xyz;
summary.ping_start = ping_start;
summary.ping_end = ping_end;
summary.z_max = z_max;
summary.pitch_sensor_offset = pitch_sensor_offset;
summary.roll_sensor_offset = roll_sensor_offset;
summary.hdg_sensor_offset = hdg_sensor_offset;
summary.figure_count = numel(figure_files);
summary.figure_files = figure_files;

if exist(filename_xyz, 'file')
    xyz = dlmread(filename_xyz, ' ');
    if isempty(xyz)
        xyz = zeros(0, 3);
    end
else
    xyz = zeros(0, 3);
end

summary.total_points = size(xyz, 1);
if summary.total_points > 0
    summary.x_min = min(xyz(:,1));
    summary.x_max = max(xyz(:,1));
    summary.y_min = min(xyz(:,2));
    summary.y_max = max(xyz(:,2));
    summary.z_min = min(xyz(:,3));
    summary.z_max_points = max(xyz(:,3));
else
    summary.x_min = 0;
    summary.x_max = 0;
    summary.y_min = 0;
    summary.y_max = 0;
    summary.z_min = 0;
    summary.z_max_points = 0;
end

summary_json = jsonencode(summary);
end
