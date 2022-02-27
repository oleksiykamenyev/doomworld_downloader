"""
WAD guesser.
"""

import logging
import os

from .dsda import conform_dsda_wad_url
from .upload_config import WAD_MAP_BY_DSDA_URL, WAD_MAP_BY_IDGAMES_URL
from .utils import conform_url, conform_idgames_url


DEFAULT_WAD_GUESSES = [
    'https://www.dsdarchive.com/wads/doom', 'https://www.dsdarchive.com/wads/doom2',
    'https://www.dsdarchive.com/wads/plutonia', 'https://www.dsdarchive.com/wads/tnt'
]


LOGGER = logging.getLogger(__name__)


def get_wad_guesses(*args, iwad=None):
    """Get WAD guesses from set of lists of guesses.

    Guesses may be DSDA URLs, idgames URLs, or WAD filenames. Guesses must be provided in ascending
    order of likelihood.

    :param args: Any number of lists of WAD guesses.
    :param iwad: IWAD guess if available
    :return: Set of WAD guesses parsed from provided lists
    :raises ValueError if any argument that is provided isn't a list
    """
    wad_guesses = []
    for arg in args:
        if not isinstance(arg, list):
            raise ValueError('Wads to guess must be passed as a list, received: "{}".'.format(
                arg
            ))
        for wad_to_guess in arg:
            if 'dsdarchive.com/wads' in wad_to_guess:
                wad_to_guess = conform_dsda_wad_url(conform_url(wad_to_guess))
                if wad_to_guess in WAD_MAP_BY_DSDA_URL:
                    wad_guesses.append(WAD_MAP_BY_DSDA_URL[wad_to_guess])
            elif 'doomworld.com/idgames' in wad_to_guess:
                wad_to_guess = conform_idgames_url(conform_url(wad_to_guess))
                if wad_to_guess in WAD_MAP_BY_IDGAMES_URL:
                    wad_guesses.append(WAD_MAP_BY_IDGAMES_URL[wad_to_guess])
            else:
                wad_to_guess_sanitized = os.path.basename(wad_to_guess.lower())
                if not wad_to_guess_sanitized.endswith('.wad'):
                    wad_to_guess_sanitized = '{}.wad'.format(wad_to_guess_sanitized)
                for url, wad in WAD_MAP_BY_DSDA_URL.items():
                    if wad_to_guess_sanitized.lower() in [os.path.basename(wad_file.lower())
                                                          for wad_file in wad.files.keys()]:
                        wad_guesses.append(wad)
                        break

    # If we actually find no guesses, just default to guessing all IWADs.
    if not wad_guesses:
        if iwad == 'heretic':
            return [WAD_MAP_BY_DSDA_URL['https://www.dsdarchive.com/wads/heretic']]
        if iwad == 'hexen':
            return [WAD_MAP_BY_DSDA_URL['https://www.dsdarchive.com/wads/hexen']]
        if iwad == 'chex':
            return [WAD_MAP_BY_DSDA_URL['https://www.dsdarchive.com/wads/chex']]

        return [WAD_MAP_BY_DSDA_URL[default_wad] for default_wad in DEFAULT_WAD_GUESSES]

    return wad_guesses
