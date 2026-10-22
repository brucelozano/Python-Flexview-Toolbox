function [ok, header_json, beam_angles, image_data, range_list, actual_ping_num, err_msg] = beamform_ping_quiet_py(filename, ping_index, image_index)
% BEAMFORM_PING_QUIET_PY Suppress command-window spam from beamform_ping_py.
% Returns ok flag and error message for Python-side graceful handling.

if nargin < 3
    image_index = 0;
end

ok = true;
err_msg = '';
header_json = '{}';
beam_angles = [];
image_data = [];
range_list = [];
actual_ping_num = ping_index;

try
    evalc('[header_json, beam_angles, image_data, range_list, actual_ping_num] = beamform_ping_py(filename, ping_index, image_index);');
catch ME
    ok = false;
    err_msg = ME.message;
end
end
