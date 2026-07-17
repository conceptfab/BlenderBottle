import bpy
from pprint import pprint
import pathlib
import os
import json

def key_from_name(name):
    return name.replace(' ', '_').lower().replace(';', '_').replace('/', '_')

# This script is used to extract parenting data from the recipient assets.
# It creates and saves a JSON file called recipient_asset_parenting_data.json.
# It is a script ment to be run from the Blender Python text editor.

recipient_asset_namess = [
    ('Liquifeel Carafe', 'LiquifeelCarafe'),
    ('American Pint Glass', 'American_Pint_Glass'),
    ('Bordeaux Wine Glass', 'Bordeaux Wine Glass'),
    ('Beer Bottle 22oz', 'Bomber 22oz Bottle'),
    ('Beer Mug', 'Beer_Mug'),
    ('Bowl_2in', 'Bowl_2in'),
    ('Bowl_6.5in', 'Bowl_6in'),
    ('Bowl_7.5in', 'Bowl_7.5in'),
    ('Bowl_9in', 'Bowl_9in'),
    ('Champagne Bottle', 'Champagne 750mL'),
    ('Hurricane Glass', 'Hurricane Glass'),
    ('Ikea Carafe', 'Ikea 365+ Carafe'),
    ('Pitcher', 'Pitcher'),
    ('Soda Bottle 16.9oz', 'Soda Bottle'),
    ('Whiskey Glass', 'Whiskey Glass'),
]

ASSET3D_NAME_DATA = {}
for thumbnail_name, obj_name in recipient_asset_namess:
    key = key_from_name(thumbnail_name)
    ASSET3D_NAME_DATA[key] = {
        'thumbnail': thumbnail_name,
        'object': obj_name,
    }

def extract_parenting_data(obj__):
    data = {
        'name': obj__.name,
        'children': []
    }
    if obj__.children:
        for child in obj__.children:
            child_data = extract_parenting_data(child)
            data['children'].append(
                child_data)
    return data

if __name__ == '__main__':
    print('------------------------------------------------------')
    print('-- DATA EXTRACTION')

    data_path = pathlib.Path(
        os.path.dirname(os.path.realpath(__file__))).parent.parent

    data = {}
    for obj_key, naming_data in ASSET3D_NAME_DATA.items():
        data[obj_key] = extract_parenting_data(
            bpy.data.objects.get(naming_data['object']))
    with open(str(data_path / 'recipient_asset_parenting_data.json'), 'w') as f:
        json.dump(data, f, indent=4)

    print('-- DATA EXTRACTION')
    print('------------------------------------------------------')
