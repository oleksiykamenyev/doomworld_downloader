import argparse
import logging

import pyotp


LOGGER = logging.getLogger(__name__)


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Generate OTP.')

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
    with open('otp.txt', encoding='utf-8') as otp_stream:
        otp = otp_stream.read().strip()

    totp = pyotp.TOTP(otp)
    print(totp.now())


if __name__ == '__main__':
    main()
