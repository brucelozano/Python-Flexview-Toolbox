function [header_json, beam_angles, ref_pulse, raw_data] = load_raw_data_py(filename, ping_index, image_index)
% LOAD_RAW_DATA_PY Python-friendly wrapper around load_raw_data.
% Returns header metadata as JSON and beam angles as a numeric vector
% to avoid MATLAB Engine limitations around nested struct fields.

if nargin < 3
    image_index = 0;
end

[header, ref_pulse, raw_data] = load_raw_data(filename, ping_index, image_index);

beam_angles = [];
if isfield(header, 'Beamlist')
    beamlist = header.Beamlist;
    if isstruct(beamlist) && ~isempty(beamlist) && isfield(beamlist, 'Angle')
        try
            beam_angles = reshape([beamlist.Angle], [], 1);
        catch
            beam_angles = zeros(numel(beamlist), 1);
            for k = 1:numel(beamlist)
                angle_value = beamlist(k).Angle;
                beam_angles(k) = angle_value(1);
            end
        end
    elseif isnumeric(beamlist)
        beam_angles = beamlist(:);
    end
end

% Remove nested struct fields before JSON conversion.
if isfield(header, 'Beamlist')
    header = rmfield(header, 'Beamlist');
end
if isfield(header, 'Focal_Zone_Paras')
    header = rmfield(header, 'Focal_Zone_Paras');
end

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
