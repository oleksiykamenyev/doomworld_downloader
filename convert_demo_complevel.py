import argparse
import logging
import os
import yaml

from doomworld_downloader.dsda import get_players, get_player_stats
from doomworld_downloader.utils import get_log_level


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
    parser = argparse.ArgumentParser(description='Convert demo complevel.')

    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Control verbosity of output.')

    return parser.parse_args()


def main():
    """Main function."""
    with open('.\eunomo5846.lmp', 'rb+') as lmp_bytes:
        lmp_bytes.seek(0)
        lmp_bytes.write(b'\xdd\x1d\x4d\x42\x46\xe6\x00\x03\x01\x01\x00\x00\x01\x00\x01\x00\x00\x01\x91\xa8\x39\x44\x01\x00\x00\x00\x00\x01\x01\x00\x01\x00\x2d')
        lmp_bytes.seek(0)
        version = lmp_bytes.read(1)

    print(version)


if __name__ == '__main__':
    main()
