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


NO_ISSUE_JSON_DIR = 'demos_for_upload/no_issue_jsons'
UPDATE_JSON_DIR = 'demos_for_upload/update_jsons'

LOGGER = logging.getLogger(__name__)


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
    for json_file in os.listdir(NO_ISSUE_JSON_DIR):
        json_path = os.path.join(NO_ISSUE_JSON_DIR, json_file)
        with open(json_path, encoding='utf-8') as json_stream:
            demo_json = json.load(json_stream)

        demo_filename = demo_json['demo']['file']['name'].replace('\\', '/')
        demo_json_map[demo_filename] = demo_json

    demo_updates = []
    for demo, demo_dict in cache_dict.items():
        demo_info = demo_dict['dsda_info']
        demo = demo.replace('\\', '/')
        demo_json = demo_json_map.get(demo)
        if not demo_json:
            LOGGER.error('Could not find demo %s in demo JSONs.', demo)
            continue

        demo_update = {}
        for key, value in demo_info.items():
            test_value = value
            final_key = key
            if key == 'note':
                test_value = value == 'TAS'
                json_value = demo_json['demo']['tas']
                final_key = 'tas'
            elif key == 'tags':
                json_value = demo_json['demo'].get(key, {})['text']
            else:
                json_value = demo_json['demo'].get(key)

            if test_value and json_value and test_value != json_value:
                LOGGER.debug('Difference for demo %s found in key %s!.', demo, key)

                demo_update[final_key] = demo_json['demo'].get(final_key, {})

        if demo_update:
            demo_update['match_details'] = {
                'category': demo_info['category'], 'level': demo_info['level'],
                'wad': demo_info['wad'], 'time': demo_info['time']
            }
            if len(demo_dict['player_list']) == 1:
                demo_update['match_details']['player'] = demo_dict['player_list'][0]

            demo_updates.append(demo_update)

    if demo_updates:
        os.makedirs(UPDATE_JSON_DIR, exist_ok=True)
        update_json = os.path.join(UPDATE_JSON_DIR, 'update.json')
        with open(update_json, 'w', encoding='utf-8') as update_stream:
            json.dump({'demo_updates': demo_updates}, update_stream, indent=4, sort_keys=True)


if __name__ == '__main__':
    main()
