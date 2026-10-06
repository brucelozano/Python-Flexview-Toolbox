function [header_json, beam_angles, range_list, image_full, image_sub_1, image_sub_2, ...
          phase_angles, phase_values, mag_angles, mag_values, fit_angles, fit_values, ...
          aoa_json] = split_beam_ping_py(filename, ping_index, image_index)
% SPLIT_BEAM_PING_PY Python-friendly wrapper for split-beam parity workflow.
% Mirrors examples/test_split_beam.m and returns arrays/metadata safe for
% MATLAB Engine transfer.

if nargin < 3
    image_index = 0;
end

[header, ref_pulse, raw_data] = load_raw_data(filename, ping_index, image_index);

if ((header.Num_Images > 1) && any(header.Ref_Pulse_Length))
    ref_pulse = ref_pulse(1:header.Ref_Pulse_Length(1), 1);
end

beam_list = header.Beamlist;
num_beams = header.Num_Beams;
beam_angles = zeros(num_beams, 1);
for beam_index = 1:num_beams
    beam_angles(beam_index) = beam_list(beam_index).Angle;
end

full_array_elements = 1:64;
sub_array_1_elements = 1:44;
sub_array_2_elements = 21:64;

full_array_center = mean(header.Sub_Array_Geometry_XYZ(full_array_elements, :), 1);
sub_array_1_center = mean(header.Sub_Array_Geometry_XYZ(sub_array_1_elements, :), 1);
sub_array_2_center = mean(header.Sub_Array_Geometry_XYZ(sub_array_2_elements, :), 1);
sub_array_separation = sqrt(sum((sub_array_1_center - sub_array_2_center).^2));

settings = struct();
settings.ref_pulse = ref_pulse;
settings.beam_list = beam_list;
settings.raw_data_header = header;
settings.rx_corrns = header.Rx_Phase_Amp_Corrections(full_array_elements);

beamform_opt = struct();
beamform_opt.sub_array_center = full_array_center;
beamform_opt.apply_rx_corrns = 1;
beamform_opt.display_plots = 0;
beamform_opt.verbose = 0;
[image_full, range_list] = beamform(raw_data, settings, beamform_opt);

beamform_opt.sub_array = sub_array_1_elements;
beamform_opt.sub_array_center = full_array_center;
beamform_opt.redo_focal_zone_paras = 1;
beamform_opt.modified_azi_kaiser_coeff = -1;
[image_sub_1, range_list] = beamform(raw_data, settings, beamform_opt);

beamform_opt.sub_array = sub_array_2_elements;
beamform_opt.redo_focal_zone_paras = 1;
beamform_opt.modified_azi_kaiser_coeff = -1;
beamform_opt.sub_array_center = full_array_center;
[image_sub_2, range_list] = beamform(raw_data, settings, beamform_opt);

MM = 100;
range_list = range_list(1:end-MM);
image_full = image_full(1:end-MM, :);
image_sub_1 = image_sub_1(1:end-MM, :);
image_sub_2 = image_sub_2(1:end-MM, :);

images = struct();
images.full_array = image_full;
images.sub_array_1 = image_sub_1;
images.sub_array_2 = image_sub_2;

split_beam_settings = struct();
split_beam_settings.sub_array_separation = sub_array_separation;
split_beam_settings.lambda = header.Velocity_Sound/header.Sub_Array_Frequency;
split_beam_settings.beam_list = beam_angles.';
split_beam_settings.range_list = range_list.';

[pk_vec, pk_vec_i] = max(abs(images.full_array));
[~, pk_beam_i] = max(pk_vec);
split_beam_settings.target_range_index = pk_vec_i(pk_beam_i);
split_beam_settings.target_beam_index = pk_beam_i;

split_beam_opt = struct();
split_beam_opt.verbose = 0;
split_beam_opt.display_plots = 0;
aoa_results = split_beam_aoa(images, split_beam_settings, split_beam_opt);

% Phase/magnitude arrays for parity plot artifacts (same as split_beam_aoa internals).
range_slice_full = images.full_array(split_beam_settings.target_range_index, :);
range_slice_1 = images.sub_array_1(split_beam_settings.target_range_index, :);
range_slice_2 = images.sub_array_2(split_beam_settings.target_range_index, :);

phase_diff = angle(range_slice_2) - angle(range_slice_1);

max_num_beams_display = 15;
nn = floor(max_num_beams_display/2) - 1;
i1 = max(split_beam_settings.target_beam_index - nn, 1);
i2 = min(split_beam_settings.target_beam_index + nn, length(split_beam_settings.beam_list));

phase_values = unwrap(phase_diff(i1:i2));
phase_values = phase_values - mean(phase_values);
phase_angles = split_beam_settings.beam_list(i1:i2).';

range_slice_full_dB = 20*log10(abs(range_slice_full));
mag_angles = split_beam_settings.beam_list(i1:i2).';
mag_values = range_slice_full_dB(i1:i2).';

j1 = max(split_beam_settings.target_beam_index - 1, 1);
j2 = min(split_beam_settings.target_beam_index + 1, length(split_beam_settings.beam_list));
p_fit = polyfit(split_beam_settings.beam_list(j1:j2), range_slice_full_dB(j1:j2), 2);
fit_angles = linspace(split_beam_settings.beam_list(j1), split_beam_settings.beam_list(j2), 100).';
fit_values = polyval(p_fit, fit_angles);

header_json = jsonencode(flatten_header_for_json(header));
aoa_json = jsonencode(flatten_header_for_json(aoa_results));
end

function out = flatten_header_for_json(in)
out = struct();
fields = fieldnames(in);
for ii = 1:numel(fields)
    field_name = fields{ii};
    value = in.(field_name);
    if isnumeric(value) && isreal(value) && isscalar(value)
        out.(field_name) = double(value);
    elseif islogical(value) && isscalar(value)
        out.(field_name) = logical(value);
    elseif ischar(value)
        out.(field_name) = value;
    end
end
end
