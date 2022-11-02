import argparse
import logging
import os
import shutil

from doomworld_downloader.upload_config import CONFIG, VALID_NO_ISSUE_DIR, FAILED_UPLOADS_FILE, \
    FAILED_UPLOADS_LOG_DIR
from doomworld_downloader.utils import get_log_level, run_cmd


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

    no_issue_dir = os.path.join(CONFIG.demo_download_directory, VALID_NO_ISSUE_DIR)
    failed_uploads_log_dir = os.path.join(CONFIG.demo_download_directory, FAILED_UPLOADS_LOG_DIR)
    for json_file in os.listdir(no_issue_dir):
        json_path = os.path.join(no_issue_dir, json_file)
        upload_cmd = f'ruby {CONFIG.dsda_api_directory}/dsda-client.rb "{json_path}"'
        run_cmd(upload_cmd, dryrun=args.dryrun)
        if os.path.exists(FAILED_UPLOADS_FILE):
            LOGGER.error('JSON %s failed upload.', json_file)
            os.makedirs(failed_uploads_log_dir, exist_ok=True)
            shutil.move(
                FAILED_UPLOADS_FILE,
                os.path.join(failed_uploads_log_dir,
                             f'{os.path.splitext(json_file)[0]}_{FAILED_UPLOADS_FILE}')
            )


if __name__ == '__main__':
    main()
