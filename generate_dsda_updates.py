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
import re

from shutil import rmtree

import yaml

from doomworld_downloader.upload_config import CONFIG
from doomworld_downloader.utils import checksum, get_log_level, zip_extract


NO_ISSUE_JSON_DIR = 'demos_for_upload/no_issue_jsons'

CHECKSUM_RE = re.compile(r'checksum: (null|\".*\")')
WAD_FILE_EXTENSIONS = ['.bex', '.deh', '.pk3', '.pk7', '.wad']

DSDA_URL_TO_WAD_INFO_FILE = 'doomworld_downloader/dsda_url_to_wad_info.yaml'
DSDA_URL_TO_WAD_INFO_BACKUP = 'doomworld_downloader/backup_dsda_url_to_wad_info.yaml'

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

    for demo, demo_dict in cache_dict.items():
        demo_info = demo_dict['dsda_info']
        demo = demo.replace('\\', '/')
        demo_json = demo_json_map.get(demo)
        if not demo_json:
            LOGGER.error('Could not find demo %s in demo JSONs.', demo)
            continue

        for key, value in demo_info.items():
            test_value = value
            if key == 'note':
                test_value = value == 'TAS'
                json_value = demo_json['demo']['tas']
            elif key == 'tags':
                json_value = demo_json['demo'].get(key, {})['text']
            else:
                json_value = demo_json['demo'].get(key)

            if test_value and json_value and test_value != json_value:
                LOGGER.debug('Difference for demo %s found in key %s!.', demo, key)


if __name__ == '__main__':
    main()
