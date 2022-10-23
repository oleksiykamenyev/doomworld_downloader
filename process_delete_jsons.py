import argparse
import logging
import os
import pyotp
import time

from doomworld_downloader.upload_config import CONFIG
from doomworld_downloader.utils import get_log_level, run_cmd


DELETE_JSON_DIR = 'demos_for_upload/delete_jsons'

LOGGER = logging.getLogger(__name__)


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Upload JSONs.')

    parser.add_argument('-d', '--dryrun',
                        action='store_true',
                        default=False,
                        help='Execute in dryrun mode.')
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

    with open('otp.txt', encoding='utf-8') as otp_stream:
        otp = otp_stream.read().strip()

    totp = pyotp.TOTP(otp)
    for json_file in os.listdir(DELETE_JSON_DIR):
        if not json_file.endswith('.json'):
            continue

        otp = totp.now()
        json_path = os.path.join(DELETE_JSON_DIR, json_file)
        upload_cmd = f'ruby {CONFIG.dsda_api_directory}/dsda-client.rb "{json_path}" --otp {otp}'
        # TODO: Keep track of failed_uploads.json files since otherwise they could be overwritten
        run_cmd(upload_cmd, dryrun=args.dryrun)

        time.sleep(35)


if __name__ == '__main__':
    main()
