function [ok, header, beamlist, image_data, err_msg] = load_image_data_quiet_py(filename, image_offset)
% LOAD_IMAGE_DATA_QUIET_PY Suppress command-window spam from load_image_data.
% Returns ok flag and error message for Python-side graceful handling.

ok = true;
err_msg = '';
header = struct();
beamlist = [];
image_data = [];

try
    % evalc captures any command-window output from MEX errors.
    evalc('[header, beamlist, image_data] = load_image_data(filename, image_offset);');
catch ME
    ok = false;
    err_msg = ME.message;
end
end
