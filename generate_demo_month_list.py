"""
Generate demo month list from DSDA.
"""

import argparse
import logging
import os
import random
import time

from glob import glob
from urllib.parse import urlparse

import yaml

from doomworld_downloader.dsda import get_wad_or_player_name_from_dsda_url, parse_dsda_demo_page_with_annotation, \
    verify_dsda_url, conform_dsda_wad_url, DSDACell, get_wads
from doomworld_downloader.utils import get_log_level


# DSDA page to get configuration.
DSDA_PAGE = None
DSDA_PAGES = []

# Cache configuration.
CACHE_DIR = 'demo_month'
WAD_LIST_CACHE_FILENAME = 'wads.yaml'
CACHE_FILENAME = 'dsda_page_info.yaml'
USE_CACHED_INFO = True

LOGGER = logging.getLogger(__name__)


def print_demo_rows(demo_list, store_to_file=None):
    """Print demo month rows.

    :param demo_list: List of demos.
    :param store_to_file: Filename to store demos to if desired.
    """
    row_output = ''
    for row in demo_list:
        wad = row['dsda_info']['wad']
        map = row['dsda_info']['level']
        category = row['dsda_info']['category']
        faster_cheated_record = row['dsda_info'].get('faster_cheated_record')
        if faster_cheated_record:
            original_player = faster_cheated_record['player_list']
            original_time = faster_cheated_record['time']
            download_link = faster_cheated_record['download_link']
        else:
            original_player = row['player_list']
            original_time = row['dsda_info']['time']
            download_link = row['download_link']

        original_player = '|'.join(original_player)
        row = [wad, map, category, original_player, original_time, download_link]

        row_string = ','.join(row)
        if not row_output:
            row_output = row_string
        else:
            row_output = f'{row_output}\n{row_string}'

    print(row_output)
    if store_to_file:
        with open(store_to_file, 'w') as out_stream:
            out_stream.write(row_output)


def simplify_dsda_row(dsda_row, wad_name, recurse=False):
    """Simplify provided DSDA row to make it possible to store into YAML for caching.

    :param dsda_row: DSDA row to simplify
    :param wad_name: WAD name
    :param recurse: Internal argument that forces recursion for only one iteration.
    :return: Simplified DSDA row
    """
    dsda_info = {}
    for key, value in dsda_row.items():
        if isinstance(value, DSDACell) or (isinstance(value, list) and value and isinstance(value[0], DSDACell)):
            if key == 'Player(s)':
                continue

            if isinstance(value, list):
                text = '\n'.join(cell.text for cell in value)
            else:
                text = value.text

            dsda_info[key.lower()] = text

            if key == 'Note' and isinstance(value, DSDACell):
                for label in value.labels:
                    if 'Dubious' in label:
                        dsda_info[key.lower()] = f'{dsda_info[key.lower()]} dubious'
                    if 'Cheated' in label:
                        dsda_info[key.lower()] = f'{dsda_info[key.lower()]} cheated'

                dsda_info[key.lower()] = dsda_info[key.lower()].strip()
        else:
            if (not recurse and
                    (key == 'actual_record' or key == 'supersedes' or key == 'faster_cheated_record') and
                    value):
                download_link = next(iter(value['Time'].links.values()))
                demo_id = urlparse(download_link).path.strip('/').split('/')[-2]
                player_list = tuple(value['Player(s)'].text.split('\n'))
                sub_dsda_info = simplify_dsda_row(value, wad_name, recurse=True)
                sub_dsda_info['download_link'] = download_link
                sub_dsda_info['demo_id'] = demo_id
                sub_dsda_info['player_list'] = player_list
                dsda_info[key] = sub_dsda_info
            elif not (isinstance(value, dict) and isinstance(value['Level'], DSDACell)):
                dsda_info[key] = value

    if dsda_row['video'].links:
        video_link = next(iter(dsda_row['video'].links.values()))
        dsda_info['video_link'] = video_link.split('=')[1]
    if not dsda_info.get('wad'):
        dsda_info['wad'] = wad_name
    if not dsda_info.get('tags'):
        dsda_info['tags'] = None

    return dsda_info


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Generate demo month list.')

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

    if DSDA_PAGE:
        dsda_pages_to_get = [DSDA_PAGE]
    elif DSDA_PAGES:
        dsda_pages_to_get = DSDA_PAGES
    else:
        wad_list_cache_file = os.path.join(CACHE_DIR, WAD_LIST_CACHE_FILENAME)
        if USE_CACHED_INFO and os.path.isfile(wad_list_cache_file):
            with open(wad_list_cache_file) as cache_stream:
                wad_cache = yaml.safe_load(cache_stream)
            dsda_pages_to_get = wad_cache.get('wads', [])
        else:
            dsda_pages_to_get = get_wads().values()
            wad_cache = {'wads': list(dsda_pages_to_get)}
            with open(wad_list_cache_file, 'w') as cache_stream:
                yaml.safe_dump(wad_cache, cache_stream)

    all_page_infos_list = []
    dsda_page_info_dirs = [os.path.basename(os.path.dirname(path))
                           for path in glob(os.path.join(CACHE_DIR, '*', CACHE_FILENAME))]
    for dsda_page in dsda_pages_to_get:
        dsda_page = conform_dsda_wad_url(dsda_page)
        dsda_page_type = verify_dsda_url(dsda_page, page_types=['wad', 'player'])
        if dsda_page_type != 'wad':
            raise ValueError('DSDA pages for demo month must be parsed from WAD pages!')

        wad_name = get_wad_or_player_name_from_dsda_url(dsda_page)

        if USE_CACHED_INFO and wad_name in dsda_page_info_dirs:
            with open(os.path.join(CACHE_DIR, wad_name, CACHE_FILENAME)) as cache_stream:
                dsda_page_info = yaml.safe_load(cache_stream)

            all_page_infos_list.append(dsda_page_info)
            continue

        dsda_page_info_raw = parse_dsda_demo_page_with_annotation(dsda_page, parse_all_pages=True)

        page_demos = []
        dsda_page_info = {'headers': dsda_page_info_raw['headers']}
        for dsda_row in dsda_page_info_raw['demo_list']:
            download_link = next(iter(dsda_row['Time'].links.values()))
            demo_id = urlparse(download_link).path.strip('/').split('/')[-2]

            dsda_info = simplify_dsda_row(dsda_row, wad_name)
            demo_info_map = {'player_list': tuple(dsda_row['Player(s)'].text.split('\n')),
                             'demo_id': demo_id, 'dsda_info': dsda_info, 'download_link': download_link}
            page_demos.append(demo_info_map)

        dsda_page_info['entry_list'] = page_demos
        cache_file = os.path.join(CACHE_DIR, wad_name, CACHE_FILENAME)
        cache_dir = os.path.dirname(cache_file)
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_file, 'w') as cache_stream:
            yaml.safe_dump(dsda_page_info, cache_stream)

        all_page_infos_list.append(dsda_page_info)

        # Add delay to not overload site.
        time.sleep(1)

    all_demos = []
    for page_info in all_page_infos_list:
        # Notably, AV old does not have the deprecated WAD warning at the moment, but adding that condition just in
        # case.
        #
        # Note: SSS01: Lunar Lights also has a unique map. Not sure if there are other similar cases.
        new_wad_url = page_info['headers'].get('new_wad_url')
        if new_wad_url and (page_info['headers']['short_name'] != 'av_old' and
                            page_info['headers']['short_name'] != 'sss01_2025_08_12'):
            continue

        if 'short_name' not in page_info['headers']:
            print(page_info['headers'])

        if page_info['headers']['short_name'] == 'av_old':
            # Only include map 25 for AV (old), which is Valley of Echoes and is unique to the older WAD.
            all_demos.extend([demo for demo in page_info['entry_list'] if demo['dsda_info']['level'] == 'Map 25'])
        else:
            all_demos.extend(page_info['entry_list'])

    for demo in all_demos:
        if 'is_record' not in demo['dsda_info']:
            print(demo)
    records_only = [demo for demo in all_demos if demo['dsda_info']['is_record']]
    over_one_second_only = [demo for demo in records_only if int(demo['dsda_info']['time_in_seconds']) >= 1]
    # four_players = [demo for demo in records_only if int(demo['dsda_info']['num_players']) == 4]

    table_fillers = [demo for demo in over_one_second_only if demo['dsda_info']['record_index'] == 0]
    somewhat_contested_demos = [demo for demo in over_one_second_only if 0 < demo['dsda_info']['record_index'] <= 5]
    very_contested_demos = [demo for demo in over_one_second_only if demo['dsda_info']['record_index'] > 5]

    # Hypothetical error tracking for cases where the sample is larger than the population of demos. This would really
    # never happen when running across the entire DSDA, mostly useful for testing.
    try:
        random_table_fillers = random.sample(table_fillers, 1)
    except ValueError:
        random_table_fillers = table_fillers
    try:
        random_somewhat_contested_demos = random.sample(somewhat_contested_demos, 0)
    except ValueError:
        random_somewhat_contested_demos = somewhat_contested_demos
    try:
        random_very_contested_demos = random.sample(very_contested_demos, 0)
    except ValueError:
        random_very_contested_demos = very_contested_demos

    print_demo_rows(random_table_fillers, store_to_file='table_fillers.txt')
    print()
    print_demo_rows(random_somewhat_contested_demos, store_to_file='somewhat_contested_demos.txt')
    print()
    print_demo_rows(random_very_contested_demos, store_to_file='very_contested_demos.txt')


if __name__ == '__main__':
    main()
