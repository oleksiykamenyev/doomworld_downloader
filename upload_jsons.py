import argparse
import logging
import os

from doomworld_downloader.utils import get_log_level, run_cmd

NO_ISSUE_JSON_DIR = 'demos_for_upload/no_issue_jsons'

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

    for json_file in os.listdir(NO_ISSUE_JSON_DIR):
        json_path = os.path.join(NO_ISSUE_JSON_DIR, json_file)
        upload_cmd = 'ruby d:/MyStuff/dsda3/dsda-r-api-client/dsda-client.rb "{}"'.format(
            json_path
        )
        # TODO: Keep track of failed_uploads.json files since otherwise they could be overwritten
        run_cmd(upload_cmd, dryrun=args.dryrun)


if __name__ == '__main__':
    main()
