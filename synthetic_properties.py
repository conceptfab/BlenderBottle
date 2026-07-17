
@undo_push(2)
def geometry_object_attached_liquid_amount_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Liquid Amount',
        'geometry',
        'object_attached',
        'None')

@undo_push(2)
def geometry_object_attached_meniscus_type_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Meniscus Type',
        'geometry',
        'object_attached',
        'None')

@undo_push(2)
def geometry_object_attached_seal_container_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Seal Container',
        'geometry',
        'object_attached',
        'None')

@undo_push(2)
def geometry_object_attached_hide_recipient_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Hide Recipient',
        'geometry',
        'object_attached',
        'None')

@undo_push(2)
def geometry_object_attached_lip_threshold_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Lip Threshold',
        'geometry',
        'object_attached',
        'None')

class ObjectAttached_Synthetic_Geometry_InputProps(bpy.types.PropertyGroup):
    liquid_amount: bpy.props.FloatProperty(
        name='Liquid Amount',
        update=geometry_object_attached_liquid_amount_updt,
        min=1.0,
        soft_min=1.0,
        max=100.0,
        soft_max=100.0,
        subtype='PERCENTAGE',
        precision=3,
        step=0.1,
    )
    meniscus_type: bpy.props.EnumProperty(
        name='Meniscus Type',
        update=geometry_object_attached_meniscus_type_updt,
        default=0,
        items=[('Concave Meniscus', 'Concave Meniscus', 'Concave Meniscus'), ('Convex Meniscus', 'Convex Meniscus', 'Convex Meniscus')],
    )
    seal_container: bpy.props.BoolProperty(
        name='Seal Container',
        update=geometry_object_attached_seal_container_updt,
    )
    hide_recipient: bpy.props.BoolProperty(
        name='Hide Recipient',
        update=geometry_object_attached_hide_recipient_updt,
    )
    lip_threshold: bpy.props.FloatProperty(
        name='Lip Threshold',
        update=geometry_object_attached_lip_threshold_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
registerable_classes.append(ObjectAttached_Synthetic_Geometry_InputProps)
@undo_push(2)
def shading_object_attached_transmission_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Transmission',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_smoothie_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Smoothie',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_pulp_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pulp',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_foam_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_foam_center_distribution_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Center Distribution',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_foam_amount_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Amount',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_secondary_foam_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_secondary_foam_opacity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam Opacity',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_secondary_foam_scale_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam Size',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_bubbles_scale_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Bubbles Scale',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_bubbles_value_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Bubbles Value',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_small_bubbles_presence_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Small Bubbles Presence',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_medium_bubbles_presence_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Medium Bubbles Presence',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_large_bubbles_presence_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Large Bubbles Presence',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_normal_strength_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Normal Strength',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_foam_seed_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Seed',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_bubbles_seed_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Bubbles Seed',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_carbonation_bubbles_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonation Bubbles',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_carbonation_bubbles_quantity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonation Bubbles Quantity',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_carbonation_bubbles_size_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonation Bubbles Size',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_carbonated_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonated',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_quantity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Quantity',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_size_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Size',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_seed_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Seed',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_pulp_amount_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pulp Amount',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_juice_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Juice Color',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_smoothie_chunks_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Smoothie Chunks',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_static_bubbles_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Static Bubbles',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_pattern_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pattern',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_mapping_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Mapping',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_use_vertex_group_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Use Vertex Group',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_upper_limit_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Upper Limit',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_lower_limit_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Lower Limit',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_pattern_falloff_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pattern Falloff',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_lip_threshold_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Lip Threshold',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_patttern_extrusion_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Patttern Extrusion',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_pattern_size_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pattern Tiling',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_ior_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'IoR',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_rim_darkness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Rim Darkness',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_dispersion_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Dispersion',
        'shading',
        'object_attached',
        'slot')

@undo_push(2)
def shading_object_attached_glass_roughness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Glass Roughness',
        'shading',
        'object_attached',
        'slot')

class ObjectAttached_Synthetic_SlotShading_InputProps(bpy.types.PropertyGroup):
    transmission: bpy.props.FloatProperty(
        name='Transmission',
        update=shading_object_attached_transmission_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    smoothie: bpy.props.FloatProperty(
        name='Smoothie',
        update=shading_object_attached_smoothie_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pulp: bpy.props.FloatProperty(
        name='Pulp',
        update=shading_object_attached_pulp_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam: bpy.props.BoolProperty(
        name='Foam',
        update=shading_object_attached_foam_updt,
    )
    foam_center_distribution: bpy.props.FloatProperty(
        name='Foam Center Distribution',
        update=shading_object_attached_foam_center_distribution_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam_amount: bpy.props.FloatProperty(
        name='Foam Amount',
        update=shading_object_attached_foam_amount_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='PERCENTAGE',
        precision=3,
        step=0.1,
    )
    secondary_foam: bpy.props.BoolProperty(
        name='Secondary Foam',
        update=shading_object_attached_secondary_foam_updt,
    )
    secondary_foam_opacity: bpy.props.FloatProperty(
        name='Secondary Foam Opacity',
        update=shading_object_attached_secondary_foam_opacity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    secondary_foam_scale: bpy.props.FloatProperty(
        name='Secondary Foam Size',
        update=shading_object_attached_secondary_foam_scale_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    bubbles_scale: bpy.props.FloatProperty(
        name='Bubbles Scale',
        update=shading_object_attached_bubbles_scale_updt,
        min=0.0,
        soft_min=0.0,
        max=2000.0,
        soft_max=2000.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    bubbles_value: bpy.props.FloatProperty(
        name='Bubbles Value',
        update=shading_object_attached_bubbles_value_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    small_bubbles_presence: bpy.props.FloatProperty(
        name='Small Bubbles Presence',
        update=shading_object_attached_small_bubbles_presence_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    medium_bubbles_presence: bpy.props.FloatProperty(
        name='Medium Bubbles Presence',
        update=shading_object_attached_medium_bubbles_presence_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    large_bubbles_presence: bpy.props.FloatProperty(
        name='Large Bubbles Presence',
        update=shading_object_attached_large_bubbles_presence_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    normal_strength: bpy.props.FloatProperty(
        name='Normal Strength',
        update=shading_object_attached_normal_strength_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam_seed: bpy.props.FloatProperty(
        name='Foam Seed',
        update=shading_object_attached_foam_seed_updt,
        min=-3.4028234663852886e+38,
        soft_min=-3.4028234663852886e+38,
        max=3.4028234663852886e+38,
        soft_max=3.4028234663852886e+38,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    bubbles_seed: bpy.props.IntProperty(
        name='Bubbles Seed',
        min=-10000,
        soft_min=-10000,
        max=10000,
        soft_max=10000,
        subtype='NONE',
        update=shading_object_attached_bubbles_seed_updt,
    )
    carbonation_bubbles: bpy.props.BoolProperty(
        name='Carbonation Bubbles',
        update=shading_object_attached_carbonation_bubbles_updt,
    )
    carbonation_bubbles_quantity: bpy.props.FloatProperty(
        name='Carbonation Bubbles Quantity',
        update=shading_object_attached_carbonation_bubbles_quantity_updt,
        min=-3.4028234663852886e+38,
        soft_min=-3.4028234663852886e+38,
        max=3.4028234663852886e+38,
        soft_max=3.4028234663852886e+38,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    carbonation_bubbles_size: bpy.props.FloatProperty(
        name='Carbonation Bubbles Size',
        update=shading_object_attached_carbonation_bubbles_size_updt,
        min=0.0,
        soft_min=0.0,
        max=2.0,
        soft_max=2.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    carbonated: bpy.props.BoolProperty(
        name='Carbonated',
        update=shading_object_attached_carbonated_updt,
    )
    quantity: bpy.props.FloatProperty(
        name='Quantity',
        update=shading_object_attached_quantity_updt,
        min=0.0,
        soft_min=0.0,
        max=300.0,
        soft_max=300.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    size: bpy.props.FloatProperty(
        name='Size',
        update=shading_object_attached_size_updt,
        min=0.0,
        soft_min=0.0,
        max=3.0,
        soft_max=3.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    seed: bpy.props.IntProperty(
        name='Seed',
        min=-2147483648,
        soft_min=-2147483648,
        max=2147483647,
        soft_max=2147483647,
        subtype='NONE',
        update=shading_object_attached_seed_updt,
    )
    pulp_amount: bpy.props.FloatProperty(
        name='Pulp Amount',
        update=shading_object_attached_pulp_amount_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    juice_color: bpy.props.FloatVectorProperty(
        name='Juice Color',
        update=shading_object_attached_juice_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    smoothie_chunks: bpy.props.FloatProperty(
        name='Smoothie Chunks',
        update=shading_object_attached_smoothie_chunks_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    static_bubbles: bpy.props.BoolProperty(
        name='Static Bubbles',
        update=shading_object_attached_static_bubbles_updt,
    )
    pattern: bpy.props.BoolProperty(
        name='Pattern',
        update=shading_object_attached_pattern_updt,
    )
    mapping: bpy.props.BoolProperty(
        name='Mapping',
        update=shading_object_attached_mapping_updt,
    )
    use_vertex_group: bpy.props.BoolProperty(
        name='Use Vertex Group',
        update=shading_object_attached_use_vertex_group_updt,
    )
    upper_limit: bpy.props.FloatProperty(
        name='Upper Limit',
        update=shading_object_attached_upper_limit_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    lower_limit: bpy.props.FloatProperty(
        name='Lower Limit',
        update=shading_object_attached_lower_limit_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pattern_falloff: bpy.props.FloatProperty(
        name='Pattern Falloff',
        update=shading_object_attached_pattern_falloff_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    lip_threshold: bpy.props.FloatProperty(
        name='Lip Threshold',
        update=shading_object_attached_lip_threshold_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    patttern_extrusion: bpy.props.FloatProperty(
        name='Patttern Extrusion',
        update=shading_object_attached_patttern_extrusion_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pattern_size: bpy.props.FloatProperty(
        name='Pattern Tiling',
        update=shading_object_attached_pattern_size_updt,
        min=0.10000000149011612,
        soft_min=0.10000000149011612,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    ior: bpy.props.FloatProperty(
        name='IoR',
        update=shading_object_attached_ior_updt,
        min=1.2999999523162842,
        soft_min=1.2999999523162842,
        max=1.75,
        soft_max=1.75,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    rim_darkness: bpy.props.FloatProperty(
        name='Rim Darkness',
        update=shading_object_attached_rim_darkness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    dispersion: bpy.props.FloatProperty(
        name='Dispersion',
        update=shading_object_attached_dispersion_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    glass_roughness: bpy.props.FloatProperty(
        name='Glass Roughness',
        update=shading_object_attached_glass_roughness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
registerable_classes.append(ObjectAttached_Synthetic_SlotShading_InputProps)
@undo_push(2)
def shading_object_attached_transmission_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Transmission',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_smoothie_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Smoothie',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_pulp_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pulp',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_foam_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_foam_center_distribution_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Center Distribution',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_foam_amount_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Amount',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_secondary_foam_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_secondary_foam_opacity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam Opacity',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_secondary_foam_scale_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam Size',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_bubbles_scale_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Bubbles Scale',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_bubbles_value_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Bubbles Value',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_small_bubbles_presence_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Small Bubbles Presence',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_medium_bubbles_presence_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Medium Bubbles Presence',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_large_bubbles_presence_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Large Bubbles Presence',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_normal_strength_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Normal Strength',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_foam_seed_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Seed',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_bubbles_seed_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Bubbles Seed',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_carbonation_bubbles_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonation Bubbles',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_carbonation_bubbles_quantity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonation Bubbles Quantity',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_carbonation_bubbles_size_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonation Bubbles Size',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_carbonated_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Carbonated',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_quantity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Quantity',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_size_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Size',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_seed_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Seed',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_pulp_amount_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pulp Amount',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_juice_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Juice Color',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_smoothie_chunks_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Smoothie Chunks',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_static_bubbles_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Static Bubbles',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_pattern_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pattern',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_mapping_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Mapping',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_use_vertex_group_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Use Vertex Group',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_upper_limit_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Upper Limit',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_lower_limit_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Lower Limit',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_pattern_falloff_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pattern Falloff',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_lip_threshold_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Lip Threshold',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_patttern_extrusion_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Patttern Extrusion',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_pattern_size_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pattern Tiling',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_ior_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'IoR',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_rim_darkness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Rim Darkness',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_dispersion_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Dispersion',
        'shading',
        'object_attached',
        'fill')

@undo_push(2)
def shading_object_attached_glass_roughness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Glass Roughness',
        'shading',
        'object_attached',
        'fill')

class ObjectAttached_Synthetic_FillShading_InputProps(bpy.types.PropertyGroup):
    transmission: bpy.props.FloatProperty(
        name='Transmission',
        update=shading_object_attached_transmission_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    smoothie: bpy.props.FloatProperty(
        name='Smoothie',
        update=shading_object_attached_smoothie_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pulp: bpy.props.FloatProperty(
        name='Pulp',
        update=shading_object_attached_pulp_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam: bpy.props.BoolProperty(
        name='Foam',
        update=shading_object_attached_foam_updt,
    )
    foam_center_distribution: bpy.props.FloatProperty(
        name='Foam Center Distribution',
        update=shading_object_attached_foam_center_distribution_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam_amount: bpy.props.FloatProperty(
        name='Foam Amount',
        update=shading_object_attached_foam_amount_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='PERCENTAGE',
        precision=3,
        step=0.1,
    )
    secondary_foam: bpy.props.BoolProperty(
        name='Secondary Foam',
        update=shading_object_attached_secondary_foam_updt,
    )
    secondary_foam_opacity: bpy.props.FloatProperty(
        name='Secondary Foam Opacity',
        update=shading_object_attached_secondary_foam_opacity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    secondary_foam_scale: bpy.props.FloatProperty(
        name='Secondary Foam Size',
        update=shading_object_attached_secondary_foam_scale_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    bubbles_scale: bpy.props.FloatProperty(
        name='Bubbles Scale',
        update=shading_object_attached_bubbles_scale_updt,
        min=0.0,
        soft_min=0.0,
        max=2000.0,
        soft_max=2000.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    bubbles_value: bpy.props.FloatProperty(
        name='Bubbles Value',
        update=shading_object_attached_bubbles_value_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    small_bubbles_presence: bpy.props.FloatProperty(
        name='Small Bubbles Presence',
        update=shading_object_attached_small_bubbles_presence_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    medium_bubbles_presence: bpy.props.FloatProperty(
        name='Medium Bubbles Presence',
        update=shading_object_attached_medium_bubbles_presence_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    large_bubbles_presence: bpy.props.FloatProperty(
        name='Large Bubbles Presence',
        update=shading_object_attached_large_bubbles_presence_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    normal_strength: bpy.props.FloatProperty(
        name='Normal Strength',
        update=shading_object_attached_normal_strength_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam_seed: bpy.props.FloatProperty(
        name='Foam Seed',
        update=shading_object_attached_foam_seed_updt,
        min=-3.4028234663852886e+38,
        soft_min=-3.4028234663852886e+38,
        max=3.4028234663852886e+38,
        soft_max=3.4028234663852886e+38,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    bubbles_seed: bpy.props.IntProperty(
        name='Bubbles Seed',
        min=-10000,
        soft_min=-10000,
        max=10000,
        soft_max=10000,
        subtype='NONE',
        update=shading_object_attached_bubbles_seed_updt,
    )
    carbonation_bubbles: bpy.props.BoolProperty(
        name='Carbonation Bubbles',
        update=shading_object_attached_carbonation_bubbles_updt,
    )
    carbonation_bubbles_quantity: bpy.props.FloatProperty(
        name='Carbonation Bubbles Quantity',
        update=shading_object_attached_carbonation_bubbles_quantity_updt,
        min=-3.4028234663852886e+38,
        soft_min=-3.4028234663852886e+38,
        max=3.4028234663852886e+38,
        soft_max=3.4028234663852886e+38,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    carbonation_bubbles_size: bpy.props.FloatProperty(
        name='Carbonation Bubbles Size',
        update=shading_object_attached_carbonation_bubbles_size_updt,
        min=0.0,
        soft_min=0.0,
        max=2.0,
        soft_max=2.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    carbonated: bpy.props.BoolProperty(
        name='Carbonated',
        update=shading_object_attached_carbonated_updt,
    )
    quantity: bpy.props.FloatProperty(
        name='Quantity',
        update=shading_object_attached_quantity_updt,
        min=0.0,
        soft_min=0.0,
        max=300.0,
        soft_max=300.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    size: bpy.props.FloatProperty(
        name='Size',
        update=shading_object_attached_size_updt,
        min=0.0,
        soft_min=0.0,
        max=3.0,
        soft_max=3.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    seed: bpy.props.IntProperty(
        name='Seed',
        min=-2147483648,
        soft_min=-2147483648,
        max=2147483647,
        soft_max=2147483647,
        subtype='NONE',
        update=shading_object_attached_seed_updt,
    )
    pulp_amount: bpy.props.FloatProperty(
        name='Pulp Amount',
        update=shading_object_attached_pulp_amount_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    juice_color: bpy.props.FloatVectorProperty(
        name='Juice Color',
        update=shading_object_attached_juice_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    smoothie_chunks: bpy.props.FloatProperty(
        name='Smoothie Chunks',
        update=shading_object_attached_smoothie_chunks_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    static_bubbles: bpy.props.BoolProperty(
        name='Static Bubbles',
        update=shading_object_attached_static_bubbles_updt,
    )
    pattern: bpy.props.BoolProperty(
        name='Pattern',
        update=shading_object_attached_pattern_updt,
    )
    mapping: bpy.props.BoolProperty(
        name='Mapping',
        update=shading_object_attached_mapping_updt,
    )
    use_vertex_group: bpy.props.BoolProperty(
        name='Use Vertex Group',
        update=shading_object_attached_use_vertex_group_updt,
    )
    upper_limit: bpy.props.FloatProperty(
        name='Upper Limit',
        update=shading_object_attached_upper_limit_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    lower_limit: bpy.props.FloatProperty(
        name='Lower Limit',
        update=shading_object_attached_lower_limit_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pattern_falloff: bpy.props.FloatProperty(
        name='Pattern Falloff',
        update=shading_object_attached_pattern_falloff_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    lip_threshold: bpy.props.FloatProperty(
        name='Lip Threshold',
        update=shading_object_attached_lip_threshold_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    patttern_extrusion: bpy.props.FloatProperty(
        name='Patttern Extrusion',
        update=shading_object_attached_patttern_extrusion_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pattern_size: bpy.props.FloatProperty(
        name='Pattern Tiling',
        update=shading_object_attached_pattern_size_updt,
        min=0.10000000149011612,
        soft_min=0.10000000149011612,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    ior: bpy.props.FloatProperty(
        name='IoR',
        update=shading_object_attached_ior_updt,
        min=1.2999999523162842,
        soft_min=1.2999999523162842,
        max=1.75,
        soft_max=1.75,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    rim_darkness: bpy.props.FloatProperty(
        name='Rim Darkness',
        update=shading_object_attached_rim_darkness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    dispersion: bpy.props.FloatProperty(
        name='Dispersion',
        update=shading_object_attached_dispersion_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    glass_roughness: bpy.props.FloatProperty(
        name='Glass Roughness',
        update=shading_object_attached_glass_roughness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
registerable_classes.append(ObjectAttached_Synthetic_FillShading_InputProps)
@undo_push(2)
def shading_material_attached_liquid_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Liquid Color',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_intensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Intensity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_turbidity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Turbidity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_subsurface_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Subsurface',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_particles_opacity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Particles Opacity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_foam_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Color',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_secondary_foam_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam Color',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_tea_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Tea Color',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Color',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_coffee_intensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Coffee Intensity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_crystallization_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Crystallization',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_crystallization_scale_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Crystallization Scale',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_pulp_particles_opacity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pulp Particles Opacity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_glass_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Glass Color',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_glassdensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'GlassDensity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_ior_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'IOR',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_roughness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Roughness',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_color_intensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Color Intensity',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_cloudiness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Cloudiness',
        'shading',
        'material_attached',
        'slot')

@undo_push(2)
def shading_material_attached_color_brightness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Color Brightness',
        'shading',
        'material_attached',
        'slot')

class MaterialAttached_Synthetic_SlotShading_InputProps(bpy.types.PropertyGroup):
    liquid_color: bpy.props.FloatVectorProperty(
        name='Liquid Color',
        update=shading_material_attached_liquid_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    intensity: bpy.props.FloatProperty(
        name='Intensity',
        update=shading_material_attached_intensity_updt,
        min=0.0,
        soft_min=0.0,
        max=5000.0,
        soft_max=5000.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    turbidity: bpy.props.FloatProperty(
        name='Turbidity',
        update=shading_material_attached_turbidity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    subsurface: bpy.props.FloatProperty(
        name='Subsurface',
        update=shading_material_attached_subsurface_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    particles_opacity: bpy.props.FloatProperty(
        name='Particles Opacity',
        update=shading_material_attached_particles_opacity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam_color: bpy.props.FloatVectorProperty(
        name='Foam Color',
        update=shading_material_attached_foam_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    secondary_foam_color: bpy.props.FloatVectorProperty(
        name='Secondary Foam Color',
        update=shading_material_attached_secondary_foam_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    tea_color: bpy.props.FloatVectorProperty(
        name='Tea Color',
        update=shading_material_attached_tea_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    color: bpy.props.FloatVectorProperty(
        name='Color',
        update=shading_material_attached_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    coffee_intensity: bpy.props.FloatProperty(
        name='Coffee Intensity',
        update=shading_material_attached_coffee_intensity_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    crystallization: bpy.props.FloatProperty(
        name='Crystallization',
        update=shading_material_attached_crystallization_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    crystallization_scale: bpy.props.FloatProperty(
        name='Crystallization Scale',
        update=shading_material_attached_crystallization_scale_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pulp_particles_opacity: bpy.props.FloatProperty(
        name='Pulp Particles Opacity',
        update=shading_material_attached_pulp_particles_opacity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    glass_color: bpy.props.FloatVectorProperty(
        name='Glass Color',
        update=shading_material_attached_glass_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    glassdensity: bpy.props.FloatProperty(
        name='GlassDensity',
        update=shading_material_attached_glassdensity_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    ior: bpy.props.FloatProperty(
        name='IOR',
        update=shading_material_attached_ior_updt,
        min=0.0,
        soft_min=0.0,
        max=1000.0,
        soft_max=1000.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    roughness: bpy.props.FloatProperty(
        name='Roughness',
        update=shading_material_attached_roughness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    color_intensity: bpy.props.FloatProperty(
        name='Color Intensity',
        update=shading_material_attached_color_intensity_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    cloudiness: bpy.props.FloatProperty(
        name='Cloudiness',
        update=shading_material_attached_cloudiness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    color_brightness: bpy.props.FloatProperty(
        name='Color Brightness',
        update=shading_material_attached_color_brightness_updt,
        min=0.0,
        soft_min=0.0,
        max=2.0,
        soft_max=2.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
registerable_classes.append(MaterialAttached_Synthetic_SlotShading_InputProps)
@undo_push(2)
def shading_material_attached_liquid_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Liquid Color',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_intensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Intensity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_turbidity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Turbidity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_subsurface_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Subsurface',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_particles_opacity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Particles Opacity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_foam_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Foam Color',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_secondary_foam_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Secondary Foam Color',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_tea_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Tea Color',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Color',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_coffee_intensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Coffee Intensity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_crystallization_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Crystallization',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_crystallization_scale_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Crystallization Scale',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_pulp_particles_opacity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Pulp Particles Opacity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_glass_color_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Glass Color',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_glassdensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'GlassDensity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_ior_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'IOR',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_roughness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Roughness',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_color_intensity_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Color Intensity',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_cloudiness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Cloudiness',
        'shading',
        'material_attached',
        'fill')

@undo_push(2)
def shading_material_attached_color_brightness_updt(slf, context):
    set_input__at_prop_update(
        slf,
        context,
        'Color Brightness',
        'shading',
        'material_attached',
        'fill')

class MaterialAttached_Synthetic_FillShading_InputProps(bpy.types.PropertyGroup):
    liquid_color: bpy.props.FloatVectorProperty(
        name='Liquid Color',
        update=shading_material_attached_liquid_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    intensity: bpy.props.FloatProperty(
        name='Intensity',
        update=shading_material_attached_intensity_updt,
        min=0.0,
        soft_min=0.0,
        max=5000.0,
        soft_max=5000.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    turbidity: bpy.props.FloatProperty(
        name='Turbidity',
        update=shading_material_attached_turbidity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    subsurface: bpy.props.FloatProperty(
        name='Subsurface',
        update=shading_material_attached_subsurface_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    particles_opacity: bpy.props.FloatProperty(
        name='Particles Opacity',
        update=shading_material_attached_particles_opacity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    foam_color: bpy.props.FloatVectorProperty(
        name='Foam Color',
        update=shading_material_attached_foam_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    secondary_foam_color: bpy.props.FloatVectorProperty(
        name='Secondary Foam Color',
        update=shading_material_attached_secondary_foam_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    tea_color: bpy.props.FloatVectorProperty(
        name='Tea Color',
        update=shading_material_attached_tea_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    color: bpy.props.FloatVectorProperty(
        name='Color',
        update=shading_material_attached_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    coffee_intensity: bpy.props.FloatProperty(
        name='Coffee Intensity',
        update=shading_material_attached_coffee_intensity_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    crystallization: bpy.props.FloatProperty(
        name='Crystallization',
        update=shading_material_attached_crystallization_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    crystallization_scale: bpy.props.FloatProperty(
        name='Crystallization Scale',
        update=shading_material_attached_crystallization_scale_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    pulp_particles_opacity: bpy.props.FloatProperty(
        name='Pulp Particles Opacity',
        update=shading_material_attached_pulp_particles_opacity_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    glass_color: bpy.props.FloatVectorProperty(
        name='Glass Color',
        update=shading_material_attached_glass_color_updt,
        min=0.0, max=1.0, soft_min=0.0, soft_max=1.0,
        subtype='COLOR',
    )
    glassdensity: bpy.props.FloatProperty(
        name='GlassDensity',
        update=shading_material_attached_glassdensity_updt,
        min=0.0,
        soft_min=0.0,
        max=100.0,
        soft_max=100.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    ior: bpy.props.FloatProperty(
        name='IOR',
        update=shading_material_attached_ior_updt,
        min=0.0,
        soft_min=0.0,
        max=1000.0,
        soft_max=1000.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    roughness: bpy.props.FloatProperty(
        name='Roughness',
        update=shading_material_attached_roughness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    color_intensity: bpy.props.FloatProperty(
        name='Color Intensity',
        update=shading_material_attached_color_intensity_updt,
        min=0.0,
        soft_min=0.0,
        max=10.0,
        soft_max=10.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    cloudiness: bpy.props.FloatProperty(
        name='Cloudiness',
        update=shading_material_attached_cloudiness_updt,
        min=0.0,
        soft_min=0.0,
        max=1.0,
        soft_max=1.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
    color_brightness: bpy.props.FloatProperty(
        name='Color Brightness',
        update=shading_material_attached_color_brightness_updt,
        min=0.0,
        soft_min=0.0,
        max=2.0,
        soft_max=2.0,
        subtype='NONE',
        precision=3,
        step=0.1,
    )
registerable_classes.append(MaterialAttached_Synthetic_FillShading_InputProps)