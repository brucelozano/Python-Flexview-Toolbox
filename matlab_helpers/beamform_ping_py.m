function [header_json, beam_angles, image_data, range_list, actual_ping_num] = beamform_ping_py(filename, ping_index, image_index)
% BEAMFORM_PING_PY Python-friendly wrapper for one-ping beamforming.
% Mirrors the workflow from examples/test_beamformer.m but returns
% Python-safe outputs.

if nargin < 3
    image_index = 0;
end

[header, ref_pulse, raw_data] = load_raw_data(filename, ping_index, image_index);
actual_ping_num = ping_index;
while (header.Num_Beams < 10)
    actual_ping_num = actual_ping_num + 1;
    [header, ref_pulse, raw_data] = load_raw_data(filename, actual_ping_num, image_index);
end

if ((header.Num_Images > 1) && any(header.Ref_Pulse_Length))
    ref_pulse = ref_pulse(1:header.Ref_Pulse_Length(1), 1);
end

settings.ref_pulse = ref_pulse;
settings.raw_data_header = header;
settings.rx_corrns = header.Rx_Phase_Amp_Corrections;

beamform_opt.azimuth_process = 1;
beamform_opt.apply_rx_corrns = 1;
beamform_opt.display_plots = 0;
beamform_opt.verbose = 0;

[image_data, range_list] = beamform(raw_data, settings, beamform_opt);

beam_list = header.Beamlist;
if isstruct(beam_list) && ~isempty(beam_list) && isfield(beam_list, 'Angle')
    beam_angles = reshape([beam_list.Angle], [], 1);
elseif isnumeric(beam_list)
    beam_angles = beam_list(:);
else
    beam_angles = [];
end

% Flatten header metadata to JSON-safe scalar fields.
header_flat = struct();
header_fields = fieldnames(header);
for ii = 1:numel(header_fields)
    field_name = header_fields{ii};
    field_value = header.(field_name);
    if isnumeric(field_value) && isreal(field_value) && isscalar(field_value)
        header_flat.(field_name) = double(field_value);
    elseif islogical(field_value) && isscalar(field_value)
        header_flat.(field_name) = logical(field_value);
    elseif ischar(field_value)
        header_flat.(field_name) = field_value;
    end
end

header_json = jsonencode(header_flat);
end
