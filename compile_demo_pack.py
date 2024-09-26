import argparse
import json
import logging
import os
import shutil

from collections import defaultdict
from datetime import datetime, timedelta
from zipfile import ZipFile, BadZipFile

from doomworld_downloader.upload_config import CONFIG, set_up_configs
from doomworld_downloader.utils import get_log_level, run_cmd, is_demo_filename, get_filename_no_ext


POSSIBLE_TIME_FORMATS = [
    '%H:%M:%S', '%M:%S', '%M:%S.%f'
]
KEEP_CHARS = ['_', ' ', '.', '-']
FINAL_DEMO_PACK_DIR = 'demos_for_upload/demo_pack_jsons'
VALID_DEMO_PACK_DIR = 'demos_for_upload/tmp_demo_pack_jsons'

LOGGER = logging.getLogger(__name__)


def get_lmp_filename(zip_file_name, lmp_list, txt_list):
    if len(lmp_list) != 1:
        raise RuntimeError(
            f'Single-player IL zip {zip_file_name} found with too few or too many lmps.'
        )
    if len(txt_list) > 1:
        raise RuntimeError(
            f'Single-player IL zip {zip_file_name} found with too many txts.'
        )
    lmp_file = lmp_list[0]
    if get_filename_no_ext(lmp_file) != get_filename_no_ext(zip_file_name):
        raise RuntimeError(
            f'Single-player IL zip {zip_file_name} has invalid lmp name {lmp_file}.'
        )
    if len(txt_list) == 1:
        txt_file = txt_list[0]
        if get_filename_no_ext(txt_file) != get_filename_no_ext(zip_file_name):
            raise RuntimeError(
                f'Single-player IL zip {zip_file_name} has invalid lmp name {txt_file}.'
            )

    return lmp_file


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Compile demo pack.')

    parser.add_argument('-d', '--dryrun',
                        action='store_true',
                        default=False,
                        help='Execute in dryrun mode. Will only produce the final JSON.')
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
    set_up_configs()

    main_pack = {}
    left_pack = defaultdict(list)
    for json_file in os.listdir(VALID_DEMO_PACK_DIR):
        json_path = os.path.join(VALID_DEMO_PACK_DIR, json_file)
        try:
            with open(json_path) as json_stream:
                demo_json = json.load(json_stream)
        except json.decoder.JSONDecodeError:
            LOGGER.error('Error parsing json file "%s".', json_file)
            raise

        # Faster pacifists and maxes should push UV-Speed to leftovers
        internal_json = demo_json['demo']
        if internal_json['category'] == 'Pacifist' or internal_json['category'] == 'UV Max':
            categories = [internal_json['category'], 'UV Speed']
        elif internal_json['category'] == 'NoMo 100S':
            categories = [internal_json['category'], 'NoMo']
        else:
            categories = [internal_json['category']]

        demo_duration = None
        demo_time_str = internal_json['time']
        for time_format in POSSIBLE_TIME_FORMATS:
            try:
                demo_time = datetime.strptime(demo_time_str, time_format)
            except ValueError:
                LOGGER.debug('Format %s did not match time %s.', time_format, demo_time_str)
                continue

            demo_duration = timedelta(hours=demo_time.hour, minutes=demo_time.minute,
                                      seconds=demo_time.second, microseconds=demo_time.microsecond)

        if not demo_duration:
            raise ValueError(f'Could not parse time {demo_time_str} in JSON {json_file}.')

        # The first entry in the category list is assumed to be the primary one.
        primary_category = True
        for category in categories:
            demo_key = (internal_json['level'], category, internal_json['guys'])
            if primary_category:
                demo_info = {'json': demo_json, 'time': demo_duration}
            else:
                demo_info = {'json': demo_json, 'time': demo_duration,
                             'actual_category': internal_json['category']}

            if demo_key in main_pack:
                if main_pack[demo_key]['time'] > demo_duration:
                    left_pack[demo_key].append(main_pack[demo_key])
                    main_pack[demo_key] = demo_info
                else:
                    left_pack[demo_key].append(demo_info)
            else:
                main_pack[demo_key] = demo_info

            primary_category = False

    total_time = None
    total_demos = 0
    total_main_demos = 0
    total_main_time = None
    total_main_table = {}
    final_main_json = {'demos': [], 'file': {'name': 'judg-lmps.zip'}}
    test_list = []
    player_to_engine_dict = {}
    for demo_key, top_level_json in main_pack.items():
        actual_category = top_level_json.get('actual_category')
        level, category, guys = demo_key
        is_movie = level == 'D2All' or level.startswith('Episode')
        demo_file = top_level_json['json']['demo']['file']['name']
        engine = top_level_json['json']['demo']['engine']
        lmp_file_name = None
        extract_list = []
        zip_file = None
        if demo_file.endswith('.zip'):
            try:
                zip_file = ZipFile(demo_file)
            except BadZipFile as bad_zip_err:
                LOGGER.error('Zip %s is a bad zip file, error message %s.', demo_file,
                             bad_zip_err)
                continue

            extract_list = [
                zip_file_member.filename for zip_file_member in zip_file.infolist()
                if (is_demo_filename(zip_file_member.filename) or
                    zip_file_member.filename.endswith('.txt'))
            ]
            lmp_list = [filename for filename in extract_list if is_demo_filename(filename)]
            txt_list = [filename for filename in extract_list if filename.endswith('.txt')]
            if guys == '1':
                lmp_file_name = get_lmp_filename(demo_file, lmp_list, txt_list)
        else:
            lmp_file_name = os.path.basename(demo_file)

        if not actual_category:
            test_list.append(demo_key)
            total_demos += 1
            total_main_demos += 1
            json_to_add = {
                'demo': {key: value
                         for key, value in top_level_json['json']['demo'].items() if key != 'file'}
            }
            final_main_json['demos'].append(json_to_add)

            raw_timedelta = top_level_json['time']
            time_to_add = raw_timedelta - timedelta(microseconds=raw_timedelta.microseconds)
            if total_time:
                total_time += time_to_add
            else:
                total_time = time_to_add

            if total_main_time:
                total_main_time += time_to_add
            else:
                total_main_time = time_to_add

            if not args.dryrun:
                output_dir = os.path.join(CONFIG.demo_pack_output_folder, 'main')
                category_dir = category.replace(' ', '').lower()
                if is_movie:
                    output_dir = os.path.join(output_dir, 'movies')
                    if guys == '1':
                        output_dir = os.path.join(output_dir, category_dir)
                    else:
                        output_dir = os.path.join(output_dir, 'coop', category_dir)
                else:
                    if guys == '1':
                        output_dir = os.path.join(output_dir, category_dir)
                    else:
                        output_dir = os.path.join(output_dir, 'coop', category_dir)

                os.makedirs(output_dir, exist_ok=True)
                if zip_file and extract_list:
                    zip_file.extractall(path=output_dir, members=extract_list)
                else:
                    shutil.copy2(demo_file, output_dir)

        players = ','.join(top_level_json['json']['demo']['players'])
        if players not in player_to_engine_dict:
            player_to_engine_dict[players] = set()
        player_to_engine_dict[players].add(engine)

        if not is_movie:
            continue

        if int(guys) == 1:
            if (category not in ['NoMo', 'NoMo 100S'] and
                    '.' in top_level_json['json']['demo']['time']):
                pretty_time = top_level_json['json']['demo']['time'].split('.')[0]
            else:
                pretty_time = top_level_json['json']['demo']['time']

            time_json = {'time': top_level_json['time'], 'player': players,
                         'pretty_time': pretty_time, 'actual_category': actual_category,
                         'lmp_file': lmp_file_name, 'engine': engine}
            if category not in total_main_table:
                total_main_table[category] = {level: time_json}
            else:
                total_main_table[category][level] = time_json

    total_left_table = {}
    total_left_time = None
    total_left_demos = 0
    final_left_json = {'demos': [], 'file': {'name': 'judg-left.zip'}}
    for json_list in left_pack.values():
        for top_level_json in json_list:
            if top_level_json.get('actual_category'):
                continue
            total_demos += 1
            total_left_demos += 1
            json_to_add = {
                'demo': {key: value
                         for key, value in top_level_json['json']['demo'].items() if key != 'file'}
            }
            final_left_json['demos'].append(json_to_add)
            demo_file = top_level_json['json']['demo']['file']['name']
            level = top_level_json['json']['demo']['level']
            category = top_level_json['json']['demo']['category']
            engine = top_level_json['json']['demo']['engine']
            players = ','.join(top_level_json['json']['demo']['players'])

            if players not in player_to_engine_dict:
                player_to_engine_dict[players] = set()
            player_to_engine_dict[players].add(engine)

            lmp_file_name = None
            extract_list = []
            zip_file = None
            if demo_file.endswith('.zip'):
                try:
                    zip_file = ZipFile(demo_file)
                except BadZipFile as bad_zip_err:
                    LOGGER.error('Zip %s is a bad zip file, error message %s.', demo_file,
                                 bad_zip_err)
                    continue

                extract_list = [
                    zip_file_member.filename for zip_file_member in zip_file.infolist()
                    if (is_demo_filename(zip_file_member.filename) or
                        zip_file_member.filename.endswith('.txt'))
                ]
                lmp_list = [filename for filename in extract_list if is_demo_filename(filename)]
                txt_list = [filename for filename in extract_list if filename.endswith('.txt')]
                if top_level_json['json']['demo']['guys'] == '1':
                    lmp_file_name = get_lmp_filename(demo_file, lmp_list, txt_list)
            else:
                lmp_file_name = os.path.basename(demo_file)

            if not args.dryrun:
                player_dir = ''.join(c for c in players if c.isalnum() or c in KEEP_CHARS)
                output_dir = os.path.join(CONFIG.demo_pack_output_folder, 'left', player_dir)
                os.makedirs(output_dir, exist_ok=True)
                if zip_file and extract_list:
                    zip_file.extractall(path=output_dir, members=extract_list)
                else:
                    shutil.copy2(demo_file, output_dir)

            raw_timedelta = top_level_json['time']
            time_to_add = raw_timedelta - timedelta(microseconds=raw_timedelta.microseconds)
            if total_time:
                total_time += time_to_add
            else:
                total_time = time_to_add

            if total_left_time:
                total_left_time += time_to_add
            else:
                total_left_time = time_to_add

            if (category not in ['NoMo', 'NoMo 100S'] and
                    '.' in top_level_json['json']['demo']['time']):
                pretty_time = top_level_json['json']['demo']['time'].split('.')[0]
            else:
                pretty_time = top_level_json['json']['demo']['time']

            time_json = {'time': top_level_json['time'], 'category': category,
                         'pretty_time': pretty_time, 'lmp_file': lmp_file_name,
                         'engine': engine}
            if players not in total_left_table:
                total_left_table[players] = {level: [time_json]}
            else:
                if level in  total_left_table[players]:
                    total_left_table[players][level].append(time_json)
                else:
                    total_left_table[players][level] = [time_json]

    os.makedirs(FINAL_DEMO_PACK_DIR, exist_ok=True)
    with open(os.path.join(FINAL_DEMO_PACK_DIR, 'judg-lmps.json'), 'w') as final_main_stream:
        json.dump(final_main_json, final_main_stream, indent=4, sort_keys=True)
    with open(os.path.join(FINAL_DEMO_PACK_DIR, 'judg-left.json'), 'w') as final_left_stream:
        json.dump(final_left_json, final_left_stream, indent=4, sort_keys=True)

    print(f'Total time for both packs: {total_time}')
    print(f'Total demos for both packs: {total_demos}')
    print(f'Total main pack time: {total_main_time}')
    print(f'Total main pack demos: {total_main_demos}')
    print(f'Total left pack time: {total_left_time}')
    print(f'Total left pack demos: {total_left_demos}')

    main_players = set()
    for category, cat_dict in total_main_table.items():
        print()
        print(f'Category table for {category}')
        category_total_time = None
        category_total_time_non_actual = None
        for level in sorted(list(cat_dict.keys())):
            level_dict = cat_dict[level]
            player = level_dict['player']
            main_players.add(player)

            pretty_time = level_dict['pretty_time']
            lmp_file_name = level_dict['lmp_file']
            second_space = ' ' * (25 - len(level))
            third_space = ' ' * (30 - len(lmp_file_name))
            fourth_space = ' ' * (40 - len(player))
            raw_timedelta = level_dict['time']
            time_to_add = raw_timedelta - timedelta(microseconds=raw_timedelta.microseconds)
            if not category_total_time:
                category_total_time = time_to_add
            else:
                category_total_time += time_to_add

            actual_category = level_dict.get('actual_category')
            if not actual_category:
                suffix = ''
                if not category_total_time_non_actual:
                    category_total_time_non_actual = time_to_add
                else:
                    category_total_time_non_actual += time_to_add
            else:
                suffix = f' (Also {actual_category})'

            print(f' {level}{second_space}{lmp_file_name}{third_space}{player}{fourth_space}'
                  f'{pretty_time}{suffix}')

        print(f'{category} total time: {category_total_time}')
        if category_total_time_non_actual:
            print(f'{category} non-actual total time: {category_total_time_non_actual}')

    print('Main player list:')
    print('; '.join(sorted(main_players)))

    left_categories = set()
    left_levels = set()
    for player in sorted(total_left_table.keys()):
        player_dict = total_left_table[player]
        print()
        print(f'Player table for {player}')
        player_total_time = None
        for level in sorted(list(player_dict.keys())):
            left_levels.add(level)
            for level_dict in sorted(player_dict[level], key=lambda l_dict: l_dict['time']):
                category = level_dict['category']
                left_categories.add(category)
                if player not in player_to_engine_dict:
                    player_to_engine_dict[player] = set()
                player_to_engine_dict[player].add(level_dict['engine'])

                pretty_time = level_dict['pretty_time']
                lmp_file_name = level_dict['lmp_file']
                second_space = ' ' * (25 - len(level))
                third_space = ' ' * (30 - len(lmp_file_name))
                fourth_space = ' ' * (30 - len(category))
                raw_timedelta = level_dict['time']
                time_to_add = raw_timedelta - timedelta(microseconds=raw_timedelta.microseconds)
                if not player_total_time:
                    player_total_time = time_to_add
                else:
                    player_total_time += time_to_add

                print(f' {level}{second_space}{lmp_file_name}{third_space}{category}{fourth_space}'
                      f'{pretty_time}')

        print(f'{player} total time: {player_total_time}')

    print('Leftover category list:')
    print(', '.join(left_categories))
    print('Leftover player list:')
    print('; '.join(sorted(total_left_table.keys())))
    print('Leftover level list:')
    print(', '.join(left_levels))

    print('Engines used:')
    for player in sorted(player_to_engine_dict.keys()):
        engine_set = player_to_engine_dict[player]
        player_engine_list = ', '.join(sorted(engine_set))
        print(f'{player}: {player_engine_list}')


if __name__ == '__main__':
    main()
