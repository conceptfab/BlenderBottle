## FILEPATH ----------

def has_extension(fname, extension):
    return get_extension(fname).lower() == extension

def has_image_extension(fname):
    return any(
        map(lambda ext: has_extension(fname, ext),
            image_file_extensions))

def get_fname_with_name(patterns_folderpath, img_name, extension=None, img_extension=False):
    fnames = filter(lambda fname: name_from_fname(fname) == img_name,
                    os.listdir(patterns_folderpath))
    if extension:
        return next(filter(lambda fname: has_extension(fname, extension),
                           fnames))
    elif img_extension:
        return next(filter(has_image_extension,fnames))
    else:
        return next(fnames)

## PATH DATA ---

def assemble_flat_path_data(root_path, gen_key=True):
    path_data = {}
    if gen_key:
        for fname in os.listdir(root_path):
            key = key_from_name(name_from_fname(fname))
            path_data[key] = root_path / fname
    else:
        for fname in os.listdir(root_path):
            key = name_from_fname(fname)
            path_data[key] = root_path / fname
    return path_data

# two layer deep data structure (flat sub-dictionaries)
# {K:{K:V}}
def assemble_recipient_pattern_path_data(fpaths_data):
    recipient_patterns = {}
    for pattern_key in os.listdir(fpaths_data['recipient_pattern_textures_root']):
        recipient_patterns[pattern_key] = {}
        for res_key in PATTERN_RES_KEYS:
            recipient_patterns[pattern_key][res_key] = fpaths_data['recipient_pattern_textures_root'].joinpath(
                pattern_key, f'{pattern_key}_{res_key}.png')
    return recipient_patterns

FPATHS = {}
FPATHS['addon_root'] = pathlib.Path(
    os.path.dirname(os.path.realpath(__file__)))

FPATHS['data_root'] = FPATHS['addon_root'] / 'data'

FPATHS['urls'] = FPATHS['data_root'] / 'urls.json'
FPATHS['blendfs_root'] = FPATHS['data_root'] / 'blendfs'
FPATHS['blend_assets'] = FPATHS['blendfs_root'] / 'LiquidFeel_MASTER.blend'

# Filepath data for input data
FPATHS['input_field_data'] = FPATHS['data_root'] / 'ui_control_inputs.json'
# FPATHS['material_input_data'] = FPATHS['data_root'] / 'material_input_data.json'

# Filepath data for icons
FPATHS['icons_root'] = FPATHS['data_root'] / 'icons'
FPATHS['icons'] = assemble_flat_path_data(FPATHS['icons_root'])

# Filepath data for material thumbnails
FPATHS['material_thumbnails_root'] = FPATHS['data_root'] / 'material_thumbnails'
FPATHS['material_thumbnails'] = assemble_flat_path_data(FPATHS['material_thumbnails_root'])

# Filepath data for recipient pattern textures
FPATHS['recipient_pattern_textures_root'] = FPATHS['data_root'] / 'recipient_pattern_textures'
FPATHS['recipient_pattern_textures'] = assemble_recipient_pattern_path_data(FPATHS)

# Filepath data for recipient thumbnails
FPATHS['recipient_asset_thumbnails_root'] = FPATHS['data_root'] / 'recipient_asset_thumbnails'
FPATHS['recipient_asset_thumbnails'] = assemble_flat_path_data(FPATHS['recipient_asset_thumbnails_root'], gen_key=False)
# FPATHS['recipient_asset_append_fpath'] = FPATHS['blendfs_root'] / 'LiquiFeel_Glass_Assets.blend'
FPATHS['recipient_asset_parenting_data'] = FPATHS['data_root'] / 'recipient_asset_parenting_data.json'

FPATHS['node_socket_data'] = FPATHS['data_root'] / 'node_socket_data.json'
FPATHS['input_ui_type_data'] = FPATHS['data_root'] / 'input_ui_type_data.json'

exported_constants = [FPATHS]

from filepaths import exported_constants
