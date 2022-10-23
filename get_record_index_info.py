import argparse
import logging
import os
import yaml

from doomworld_downloader.dsda import get_players, get_player_stats
from doomworld_downloader.utils import get_log_level


HEADER_SPACING = 16
OUTPUT_FILE = 'record_index_info.txt'
PARTICIPANTS = []

LOGGER = logging.getLogger(__name__)


def generate_header(*args):
    """Generate table header.

    :param args: Arguments list for header
    :return: Table header
    """
    header = ''
    for arg in args:
        space = ' ' * (HEADER_SPACING - len(arg))
        header += f'{arg}{space}'

    return header


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Get record index info.')

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

    player_dict = get_players()
    record_index_map = {}
    for player_name, player_url in player_dict.items():
        player_stats = get_player_stats(player_url)
        # If a page has no demos, it will have no stats, but those pages are usually just broken
        # shit so can be safely ignored.
        if not player_stats:
            continue
        record_index_map[player_name] = player_stats['record_index']

    if os.path.exists(OUTPUT_FILE):
        LOGGER.warning(
            'Record index output path %s already exists, outputting stats table instead.',
            OUTPUT_FILE
        )
        with open(OUTPUT_FILE, encoding='utf-8') as record_index_info_stream:
            start_record_index_map = yaml.safe_load(record_index_info_stream)

        final_stats = generate_header('Player', 'Current', 'Start', 'Difference')
        for participant in PARTICIPANTS:
            if participant not in record_index_map:
                raise RuntimeError(f'Participant {participant} not in current record index info.')

            cur_record_index = record_index_map[participant]
            start_record_index = start_record_index_map.get(participant, 0)
            difference = str(int(cur_record_index) - int(start_record_index))

            final_stats += generate_header(participant, cur_record_index, start_record_index,
                                           difference)

        print(final_stats)
    else:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as record_index_info_stream:
            yaml.safe_dump(record_index_map, record_index_info_stream)


if __name__ == '__main__':
    main()
