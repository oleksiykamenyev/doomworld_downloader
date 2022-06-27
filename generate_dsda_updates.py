"""
Generate DSDA updates.

This is meant to run as a follow-on to the DSDA mode downloader. The downloader will download all of
the runs, produce a config with their local paths and DSDA info, and generate upload JSONs for all
of the demos. Then, this script will compare the info in the upload JSONs to the DSDA info and
produce update JSONs wherever applicable.

The reason for the 2-step process is to allow for manual verification in between the download and
update.
"""

import argparse
import json
import logging
import os

import yaml

from doomworld_downloader.upload_config import CONFIG
from doomworld_downloader.utils import get_log_level


DELETE_JSON_DIR = 'demos_for_upload/delete_jsons'
ISSUE_JSON_DIR = 'demos_for_upload/issue_jsons'
NO_ISSUE_JSON_DIR = 'demos_for_upload/no_issue_jsons'
UPDATE_JSON_DIR = 'demos_for_upload/update_jsons'

MATCH_KEY_MAPPING = ['players', 'level', 'time', 'wad', 'category']

LOGGER = logging.getLogger(__name__)


def check_demo_for_updates(demo_name, demo_json, demo_dict):
    """Check single demo pair for updates.

    :param demo_name: Demo filename
    :param demo_json: Demo JSON
    :param demo_dict: Demo DSDA dictionary
    :return: Demo update if it is needed, None otherwise
    """
    demo_info = demo_dict['dsda_info']
    demo_update = {}
    for key, value in demo_info.items():
        test_value = value
        final_key = key
        if key == 'note':
            test_value = value == 'TAS'
            json_value = demo_json['tas']
            final_key = 'tas'
        elif key == 'tags':
            json_tags = demo_json.get(key)
            if json_tags:
                json_value = json_tags[0]['text']
            else:
                json_value = None
        else:
            json_value = demo_json.get(key)

        if (test_value or json_value) and test_value != json_value:
            LOGGER.debug('Difference for demo %s found in key %s!.', demo_name, key)

            if not CONFIG.dsda_mode_replace_zips:
                demo_update[final_key] = demo_json.get(final_key, {})

    if CONFIG.dsda_mode_replace_zips or demo_update:
        demo_update['match_details'] = {
            'category': demo_info['category'], 'level': demo_info['level'],
            'wad': demo_info['wad'], 'time': demo_info['time']
        }
        if len(demo_dict['player_list']) == 1:
            demo_update['match_details']['player'] = demo_dict['player_list'][0]

        return demo_update

    return None


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Generate DSDA updates.')

    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Control verbosity of output.')

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    log_level = get_log_level(args.verbose)
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')

    dsda_mode_cache = os.path.join(CONFIG.dsda_mode_download_directory, 'demo_info.yaml')
    with open(dsda_mode_cache, encoding='utf-8') as cache_stream:
        cache_dict = yaml.safe_load(cache_stream)

    demo_json_map = {}
    extra_jsons = []
    for json_file in os.listdir(NO_ISSUE_JSON_DIR):
        json_path = os.path.join(NO_ISSUE_JSON_DIR, json_file)
        with open(json_path, encoding='utf-8') as json_stream:
            demo_json = json.load(json_stream)

        internal_json = demo_json.get('demo', demo_json.get('demo_pack', {}))
        if not internal_json:
            raise RuntimeError(f'Broken json {json_file} found with unexpected internal structure.')

        demo_filename = internal_json['file']['name'].replace('\\', '/')
        demo_json_map[demo_filename] = demo_json

    demo_changes = []
    for demo, demo_list in cache_dict.items():
        demo = demo.replace('\\', '/')
        full_demo_json = demo_json_map.get(demo)
        if not full_demo_json:
            LOGGER.error('Could not find demo %s in demo JSONs.', demo)
            continue

        # If there's a single demo on each side, just compare that.
        if len(demo_list) == 1 and 'demo' in full_demo_json:
            demo_update = check_demo_for_updates(demo, full_demo_json['demo'], demo_list[0])
            if demo_update:
                demo_changes.append(demo_update)
        else:
            demo_jsons = full_demo_json['demo_pack']['demos']
            # If we are comparing demo packs on both sides, we need some fuzzy matching logic.
            for demo_dict in demo_list:
                dsda_info = demo_dict['dsda_info']
                # This is the key used to match the demos; each piece of info is included in order
                # of most importance. Specifically, if we cannot match to the other side with all of
                # the pieces of info, the last one will be removed for a more fuzzy matching
                # strategy in case the update script changed that value. As such, any value that is
                # most likely to update is placed last in the list. If at any point, the fuzzy
                # matching returns more than one demo, we cannot match this one and a warning will
                # be output.
                match_key = [demo_dict['player_list'], dsda_info['level'], dsda_info['time'],
                             dsda_info['wad'], dsda_info['category']]
                found_match = False
                matching_demo_json = None
                while match_key:
                    for demo_json in demo_jsons:
                        found_match = True
                        for idx, value in enumerate(match_key):
                            if demo_json[MATCH_KEY_MAPPING[idx]] != value:
                                found_match = False
                                break

                        if found_match:
                            matching_demo_json = demo_json
                            break
                        else:
                            continue

                    if found_match:
                        break
                    else:
                        match_key = match_key[:-1]

                if found_match:
                    demo_update = check_demo_for_updates(demo, matching_demo_json, demo_dict)
                    if demo_update:
                        demo_changes.append(demo_update)
                    demo_jsons.remove(matching_demo_json)
                else:
                    LOGGER.warning('Demo with ID %s not matched to JSON.', demo_dict['demo_id'])

            if demo_jsons:
                LOGGER.warning('Extra JSONs remaining in list not accounted for on DSDA.')
                extra_jsons.append(full_demo_json)

    if demo_changes:
        if CONFIG.dsda_mode_replace_zips:
            os.makedirs(DELETE_JSON_DIR, exist_ok=True)
            header = 'demo_delete'
        else:
            os.makedirs(UPDATE_JSON_DIR, exist_ok=True)
            header = 'demo_updates'

        if header == 'demo_delete':
            for idx, delete in enumerate(demo_changes):
                delete_json = os.path.join(DELETE_JSON_DIR, f'delete_{str(idx).zfill(5)}.json')
                with open(delete_json, 'w', encoding='utf-8') as update_stream:
                    json.dump({header: delete}, update_stream, indent=4, sort_keys=True)
        else:
            update_json = os.path.join(UPDATE_JSON_DIR, 'update.json')
            with open(update_json, 'w', encoding='utf-8') as update_stream:
                json.dump({header: demo_changes}, update_stream, indent=4, sort_keys=True)

    if extra_jsons:
        extras_json = os.path.join(ISSUE_JSON_DIR, 'extras.json')
        with open(extras_json, 'w', encoding='utf-8') as update_stream:
            json.dump(extra_jsons, update_stream, indent=4, sort_keys=True)



if __name__ == '__main__':
    main()
