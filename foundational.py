## MISC FUNCTIONS --------------------------------------------------------------------------------

def key_from_name(name):
    return name.replace(' ', '_').lower().replace(';', '_').replace('/', '_').replace('.', '_')

def name_from_fname(fname):
    return '.'.join(fname.split('.')[:-1])

def name_from_key(key):
    return ' '.join(
        map(lambda elem: elem.capitalize(),
            key.split('_')))

def class_name_from_key(key):
    return ''.join(
        map(lambda elem: elem.capitalize(),
            key.split('_')))

def bl_version_lesser(v1, v2):
    if v1[0] > v2[0]:
        return False
    elif v1[1] > v2[1]:
        return False
    else:
        return v1[2] < v2[2]

def bl_version_greater(v1, v2):
    if v1[0] < v2[0]:
        return False
    elif v1[1] < v2[1]:
        return False
    else:
        return v1[2] > v2[2]

def strip_name(name):
    elems = name.split(' ')
    return ' '.join(
        filter(lambda elem: elem != '', elems)
    )

# This generates a dictionary with correlates stripped keys with unstripped keys.
# it is useful for aiding in the access to data refferenced by keys with accidentally
# included leading or trailing whitespace
def stripped_correlator(data):
    corr = {}
    for key in data.keys():
        corr[strip_name(key)] = key
    return corr

# Read the comment to the function defined above.
def index_stripped(data, key):
    corr = stripped_correlator(data)
    return data[corr[strip_name(key)]]

def does_dict_have_key_path(data, key_path):
    if len(key_path) == 1:
        return key_path[0] in data.keys()
    elif key_path[0] in data.keys():
        return does_dict_have_key_path(data[key_path[0]], key_path[1:])
    else:
        return False
        
## JSON  -------------

def parse_json_string(json_string):
    data = json.loads(json_string)
    return data

## WEB -------------

def make_single_user_and_apply_transforms(context, obj__):
    select_and_set_active(context, obj__, deselect_all=True)
    bpy.ops.object.make_single_user(object=True, obdata=True, material=True)
    # Apparently we don't have to apply the rotation
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)

## WEB -------------

def open_webpage(url):
    webbrowser.open(url)

## PIP -----------------

def upgrade_pip():
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '--upgrade', 'pip'], check=True)
        print(f"pip upgraded successfully.")
    except subprocess.CalledProcessError:
        print(f"Failed to upgrade pip. Please do it manually.")

def install_package(package_name):
    """
    Attempts to install a package using pip and sys.executable to ensure
    compatibility across Windows, Linux, and macOS.
    """
    try:
        subprocess.run([sys.executable, '-m', 'pip', 'install', package_name], check=True)
        print(f"{package_name} installed successfully.")
    except subprocess.CalledProcessError:
        print(f"Failed to install {package_name}. Please install it manually.")

def check_and_install_package(package_name, package_import_name=None):
    try:
        # Attempt to import the package
        if package_import_name:
            __import__(package_import_name)
        else:
            __import__(package_name)
        print(f"{package_name} is already installed.")
    except ImportError:
        # The package is not installed; attempt to install
        upgrade_pip()
        print(f"{package_name} is not installed. Attempting to install...")
        install_package(package_name)

# def install_python_package(package_name):
#     import pip._internal
#     pip._internal.main(['install', package_name])

# def remove_python_package(package_name):
#     import pip._internal
#     pip._internal.main(['remove', package_name])

# remove_python_package('pillow')

# # List installed
# subprocess.run([sys.executable, '-m', 'pip', 'list'], check=True)
# # Uninstall
# subprocess.run([sys.executable, '-m', 'pip', 'uninstall', 'pillow'], check=True)

check_and_install_package('Pillow', package_import_name='PIL')

## BLENDER -------------

def undo_push(n):
    if n == 1:
        def decorator(f):
            def wrapper(arg):
                bpy.ops.ed.undo_push()
                return f(arg)
            return wrapper
        return decorator
    if n == 2:
        def decorator(f):
            def wrapper(instance, context):
                bpy.ops.ed.undo_push()
                return f(instance, context)
            return wrapper
        return decorator
    elif n == 3:
        def decorator(f):
            def wrapper(a, b, c):
                bpy.ops.ed.undo_push()
                return f(a, b, c)
            return wrapper
        return decorator
    elif n == 4:
        def decorator(f):
            def wrapper(a, b, c, d):
                bpy.ops.ed.undo_push()
                return f(a, b, c, d)
            return wrapper
        return decorator

# def undo_push(f):
#     def wrapper(instance, context):
#         bpy.ops.ed.undo_push()
#         return f(instance, context)
#     return wrapper

@undo_push(1)
def unused_data_purge(context):
    bpy.ops.outliner.orphans_purge(
        do_local_ids=True, do_linked_ids=True, do_recursive=True)

def is_active_selected_ob(context):
    ob = context.active_object
    if ob:
        return ob.select_get()
    return False        

def deselect_all_objects(context):
    for ob in context.selected_objects:
        ob.select_set(False)

def select_and_set_active(context, ob, deselect_all=False):
    if deselect_all:
        deselect_all_objects(context)
    context.view_layer.objects.active = ob
    ob.select_set(True)

heavy_render_bounce_params = {
    'max_bounces': 24,
    'transmission_bounces': 24,
    'volume_bounces': 2
}

light_render_bounce_params = {
    'max_bounces': 8,
    'transmission_bounces': 8,
    'volume_bounces': 0
}

def adjust_render_settings(context, light=False):
    if light:
        params = light_render_bounce_params
        for key, val in params.items():
            if getattr(context.scene.cycles, key) > val:
                setattr(context.scene.cycles, key, val)
    else:
        params = heavy_render_bounce_params
        for key, val in params.items():
            if getattr(context.scene.cycles, key) < val:
                setattr(context.scene.cycles, key, val)

## RNA SYSTEM -------

def getattr_rec(obj__, attr_key_path):
    try:
        return ft.reduce(getattr, attr_key_path, obj__)
    except:
        return None

# obsolet, old system, now we use REDUX_INPUT_DATA and it has a
# different hierarchy.
def getattr_rec__by_names(
        obj__, shading_modality_key, library_key, mat_name, target_type, group_name, input_name, prop_key=None):
    lib_key, mat_key, trgt_key, group_key, prop_key__ = map(
        key_from_name,
        [library_key, mat_name, target_type, group_name, input_name])
    if not(prop_key):
        prop_key = prop_key__
    prop_key_chain = [
        f'liquifeel_field_inputs',
        f'{shading_modality_key}_shading',
        f'{lib_key}_inputs',
        f'{mat_key}',
        f'{trgt_key}',
        f'{group_key}',
        f'{prop_key}',
    ]
    return getattr_rec(obj__, prop_key_chain)

# CONCESSION START --------------------------------------------------
# We refference hierarchically placed properties by recursing up the path.

def ref_ob_key_pair_rec__(obj__, key_chain):
    if len(key_chain) == 1:
        return obj__, key_chain[-1]
    else:
        key = key_chain.pop()
        return ref_ob_key_pair_rec__(
            getattr(obj__, key),
            key_chain)

def ref_ob_key_pair(obj__, key_chain):
    key_chain__ = key_chain.copy()
    key_chain__.reverse()
    return ref_ob_key_pair_rec__(obj__, key_chain__)

def ref_input_field_property(
        obj__, shading_modality_key, library_key, mat_name, target_type, group_name, input_name, prop_key=None):
    lib_key, mat_key, trgt_key, group_key, prop_key__ = map(
        key_from_name,
        [library_key, mat_name, target_type, group_name, input_name])
    if not(prop_key):
        prop_key = prop_key__
    prop_key_chain = [
        f'liquifeel_field_inputs',
        f'{shading_modality_key}_shading',
        f'{lib_key}_inputs',
        f'{mat_key}',
        f'{trgt_key}',
        f'{group_key}',
        f'{prop_key}',
    ]
    return ref_ob_key_pair(obj__, prop_key_chain)

# CONCESSION STOP --------------------------------------------------

def load_image(path):
    im = bpy.data.images.load(str(path))
    return im

def maybe_load_image(path):
    fname = path.name
    if fname in bpy.data.images.keys():
        return bpy.data.images[fname]
    else:
        im = bpy.data.images.load(str(path))
        return im

## MESH ISLAND COUNT ---

def get_vert_graph(verts, edges):
    # Initialize the path with all vertices indices
    graph = {v.index: set() for v in verts}
    # Add the possible paths via edges
    for e in edges:
        graph[e.vertices[0]].add(e.vertices[1])
        graph[e.vertices[1]].add(e.vertices[0])
    return graph

def follow_edges(starting_index, paths):
    current_selected_vert_indices = [starting_index]
    follow = True
    while follow:
        # Get indices that are still in the paths
        eligible = set([ind for ind in current_selected_vert_indices if ind in paths])
        if len(eligible) == 0:
            follow = False # Stops if no more
        else:
            # Get the corresponding links
            next = [paths[i] for i in eligible]
            # Remove the previous from the paths
            for key in eligible: paths.pop( key )
            # Get the new links as new inputs
            current_selected_vert_indices = set([ind for sub in next for ind in sub])

def count_mesh_islands(obj__):
    # Prepare the paths/links from each vertex to others
    graph = get_vert_graph(obj__.data.vertices, obj__.data.edges)
    found = True
    n = 0
    while found:
        try:
            # Get one input as long there is one
            starting_index = next(iter(graph.keys() ) )
            n = n + 1
            # Deplete the graph dictionary following this starting index
            follow_edges(starting_index, graph)               
        except:
            found = False
    return n

# exported_functions = [
#     key_from_name,
#     name_from_fname,
#     name_from_key,
#     class_name_from_key,
#     bl_version_lesser,
#     bl_version_greater,
#     strip_name,
#     stripped_correlator,
#     index_stripped,
#     does_dict_have_key_path,
#     parse_json_string,
#     make_single_user_and_apply_transforms,
#     open_webpage,
#     upgrade_pip,
#     install_package,
#     check_and_install_package,
#     undo_push,
#     unused_data_purge,
#     is_active_selected_ob,
#     deselect_all_objects,
#     select_and_set_active,
#     adjust_render_settings,
#     getattr_rec,
#     getattr_rec__by_names,
#     ref_ob_key_pair_rec__,
#     ref_ob_key_pair,
#     ref_input_field_property,
#     load_image,
#     maybe_load_image,
#     get_vert_graph,
#     follow_edges,
#     count_mesh_islands,
# ]

# from foundational import key_from_name, name_from_fname, name_from_key, class_name_from_key, bl_version_lesser, bl_version_greater, strip_name, stripped_correlator, index_stripped, does_dict_have_key_path, parse_json_string, make_single_user_and_apply_transforms, open_webpage, upgrade_pip, install_package, check_and_install_package, undo_push, unused_data_purge, is_active_selected_ob, deselect_all_objects, select_and_set_active, adjust_render_settings, getattr_rec, getattr_rec__by_names, ref_ob_key_pair_rec__, ref_ob_key_pair, ref_input_field_property, load_image, maybe_load_image, get_vert_graph, follow_edges, count_mesh_islands
