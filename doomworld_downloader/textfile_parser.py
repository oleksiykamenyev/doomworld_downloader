"""
Stub: textfile parser

TODO: We can start working on this earlier. Please operate off the following assumptions:
  - You're provided a textfile in a local directory
  - Your output should be a dictionary of all relevant info for the final JSON
"""

import itertools
import re

from dataclasses import dataclass
from datetime import datetime

import requests
import yaml

from bs4 import BeautifulSoup
from lxml import etree

PORT_REGEXES = [
    # Vanilla

    # Chocolate family
    # Chocolate Doom
    re.compile(r'Chocolate\s*Doom\s*v?\d\.\d\.\d', re.IGNORECASE),
    # Crispy Doom
    re.compile(r'Crispy\s*Doom\s*v?\d\.\d\.\d', re.IGNORECASE),
    # CNDoom
    re.compile(r'CNDoom\s*v?\d\.\d\.\d(\.\d)?', re.IGNORECASE),

    # Boom/MBF family
    # Boom
    re.compile(r'^([\S+])Boom\s*v?2\.0\.[0-2]', re.IGNORECASE),
    # MBF
    re.compile(r'^[\S+]MBF(386|-Sigil|-SNM)\s*v?\d\.\d\.\d', re.IGNORECASE),
    # TASMBF
    re.compile(r'TASMBF', re.IGNORECASE),
    # PrBoom+
    re.compile(r'(Pr|GL)Boom(\+|-plus)\s*v?\d\.\d\.\d\.\d', re.IGNORECASE),
    # PrBoom
    re.compile(r'(Pr|GL)Boom^(\+|-plus)\s*v?\d\.\d\.\d', re.IGNORECASE),

    # ZDoom family
    # GZDoom
    re.compile(r'GZDoom\s*v?\d\.\d\.\d+', re.IGNORECASE),
    # ZDoom
    re.compile(r'^[\S+]ZDoom\s*v?\d\.\d(\.\S+)?', re.IGNORECASE),
    # ZDaemon
    re.compile(r'ZDaemon\s*v?\d\.\d\.\d+', re.IGNORECASE),
    # Zandronum
    re.compile(r'Zandronum\s*v?\d\.\d(\.\d+)?(\s*Alpha)', re.IGNORECASE),

    # Other ports
    # Strawberry Doom
    re.compile(r'Strawberry\s*Doom\s*r\d+', re.IGNORECASE),
]


