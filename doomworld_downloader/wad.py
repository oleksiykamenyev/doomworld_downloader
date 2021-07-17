"""
WAD object with supported data values mirroring what is available in the DSDA WAD config.
"""

import logging

from dataclasses import dataclass


LOGGER = logging.getLogger(__name__)


@dataclass
class Wad:
    """WAD data class."""
    # Name, mostly for logging (e.g., Scythe)
    name: str
    iwad: str
    # Files needed for the wad mapped to their MD5 hashes (e.g., scythe.wad: {hash})
    files: dict
    # Complevel needed for the wad (e.g., 2)
    complevel: int
    # Special info on the different maps in the wad; for example, whether any maps are nomo, etc.
    map_info: dict
    idgames_url: str
    dsda_url: str
    # If this wad isn't on idgames or DSDA, it may have some other URL to download it.
    other_url: str
    # Whether the DSDA page for this wad has multiple pages
    dsda_paginated: bool
    doomworld_thread: str

    # Playback command line for the wad (e.g., "-file scythe")
    playback_cmd_line: str = ''
    # DSDA name of the WAD, in cases where the URL doesn't match it
    dsda_name: str = None
