
## CONSTANT DATA --------------------------------------------------------------------------------

## SIMPLE -----------------------------

DEV = True
if DEV:
    debug_buffer = []

SPACING_H = 0.4
SML_H = 1.2
MID_H = 1.8
LRG_H = 2.4

SELECT_OUTER_NG_NAME = 'LiquiFeel_Select Outer'
# FILL_NG_NAME = 'LiquiFeelv1.2'
FILL_NG_NAME = 'LiquiFeelv1.3'
HIDE_RECIPIENT_NG_NAME = 'Hide_Recipient'
DROPLET_GEN_NG_NAME  = 'DropletGen'

UI_THUMB_SCALE = 13.2 * 0.75
POPUP_THUMB_SCALE = 13.2 / 2

LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR = 0.6

## COMPOUND -----------------------------

LQFL_OBJECT_TAG_ATTACHED_DATA_KEYS = [
    'liquifeel',
]

PATTERN_RES_KEYS = ['256', '512', '1k', '2k']

image_file_extensions = ['png', 'jpg']

## DYNAMIC -----------------------------

## MAIN TABS ----------

# MAIN_TAB_KEYS = ['fill', 'shading', 'condensation']
# MAIN_TAB_KEYS = ['geometry', 'shading', 'effects', 'recipients']
MAIN_TAB_KEYS = ['geometry', 'shading', 'recipients']
MAIN_TAB_NAMES = {key: key.capitalize() for key in MAIN_TAB_KEYS}
MAIN_TAB_NAMES['recipients'] = 'Recipients'
MAIN_TAB_BUILTIN_ICONS = {
    'shading': 'MATERIAL',
}

# exported_constants = [
#     DEV,
#     SPACING_H,
#     SML_H,
#     MID_H,
#     LRG_H,
#     SELECT_OUTER_NG_NAME,
#     FILL_NG_NAME,
#     HIDE_RECIPIENT_NG_NAME,
#     DROPLET_GEN_NG_NAME,
#     UI_THUMB_SCALE,
#     POPUP_THUMB_SCALE,
#     LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR,
#     LQFL_OBJECT_TAG_ATTACHED_DATA_KEYS,
#     PATTERN_RES_KEYS,
#     image_file_extensions,
#     MAIN_TAB_KEYS,
#     MAIN_TAB_NAMES,
#     MAIN_TAB_BUILTIN_ICONS,
# ]

# from constants import DEV, SPACING_H, SML_H, MID_H, LRG_H, SELECT_OUTER_NG_NAME, FILL_NG_NAME, HIDE_RECIPIENT_NG_NAME, DROPLET_GEN_NG_NAME, UI_THUMB_SCALE, POPUP_THUMB_SCALE, LEFT_JUSTIFIED_BUTTON_SPLIT_FACTOR, LQFL_OBJECT_TAG_ATTACHED_DATA_KEYS, PATTERN_RES_KEYS, image_file_extensions, MAIN_TAB_KEYS, MAIN_TAB_NAMES, MAIN_TAB_BUILTIN_ICONS
