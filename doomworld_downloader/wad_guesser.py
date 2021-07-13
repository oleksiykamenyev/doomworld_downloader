"""
WAD guesser.
"""
import logging

from .upload_config import WAD_MAP_BY_DSDA_URL, WAD_MAP_BY_IDGAMES_URL


LOGGER = logging.getLogger(__name__)


def get_wad_guesses(*args):
    """Get WAD guesses from set of lists of guesses.

    Guesses may be DSDA URLs, idgames URLs, or WAD filenames. Guesses must be provided in ascending
    order of likelihood.

    :param args: Any number of lists of WAD guesses.
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
                if wad_to_guess in WAD_MAP_BY_DSDA_URL:
                    wad_guesses.append(WAD_MAP_BY_DSDA_URL[wad_to_guess])
            elif 'doomworld.com/idgames' in wad_to_guess:
                if wad_to_guess in WAD_MAP_BY_IDGAMES_URL:
                    wad_guesses.append(WAD_MAP_BY_IDGAMES_URL[wad_to_guess])
            else:
                if not wad_to_guess.endswith('.wad'):
                    wad_to_guess_sanitized = '{}.wad'.join(wad_to_guess)
                else:
                    wad_to_guess_sanitized = wad_to_guess
                for url, wad in WAD_MAP_BY_DSDA_URL.items():
                    if wad_to_guess_sanitized in wad.files.keys():
                        wad_guesses.append(wad)
                        break

    return wad_guesses
