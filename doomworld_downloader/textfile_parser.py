"""
Parse data out of demo textfile.
"""

import logging
import re

from .base_parser import BaseData
from .data_manager import DataManager
from .upload_config import CONFIG
from .utils import parse_youtube_url, get_single_key_value_dict, normalize_time_to_minutes_and_seconds


LOGGER = logging.getLogger(__name__)


# TODO: Handle Heretic/Hexen categories
class TextfileData(BaseData):
    """Store all uploader-relevant data for a demo textfile."""
    CATEGORY_KEYS = ['cat', 'catagory', 'category', 'catagories', 'categories', 'discipline', 'type']
    PORT_KEYS = ['builtusing', 'builtwith', 'client', 'clients', 'engine', 'engines', 'engineexe', 'engineexes', 'exe',
                 'exes', 'gameexe', 'gameexes', 'port', 'ports', 'portused', 'portsused', 'recordedusing',
                 'recordedwith', 'sourceport', 'sourceports', 'sourceportused', 'sourceportsused', 'usingport',
                 'usingports', 'usingsourceport', 'usingsourceports']
    # These port keys could be placed at the start of a line with no colon (i.e., in cases of
    # Compet-N-style textfiles. In this case, the script will still parse them.
    NON_COLON_PORT_REGEX = re.compile(
        r'^\s*(Recorded|Built)\s*(using|with)\s*(source)?\s*(port)?\s*:?\s*(?P<value>.+)\s*',
        re.IGNORECASE
    )
    TAS_PORTS = ['DRE', 'TASDoom', 'TASMBF', 'XDRE']
    MULTI_COMPLEVEL_PORTS = ['PRBoom', 'DSDA-Doom', 'Woof', 'SpeedWoof', 'Nugget Doom']
    TAS_STRING = 'this is a tools-assisted demo'
    VIDEO_KEYS = [
        'video', 'videolink', 'videoondemand', 'videoondemandlink', 'vod', 'vodlink', 'youtube',
        'youtubelink', 'youtubevideo', 'youtubevideolink', 'yt', 'ytlink', 'ytvideo', 'ytvideolink'
    ]
    WAD_KEYS = ['mapset', 'pwad', 'pwadfile', 'wad']
    TIME_KEYS = ['time']
    SKILL_KEYS = ['skill']

    CERTAIN_KEYS = ['is_tas']
    POSSIBLE_KEYS = ['category', 'source_port', 'video_link', 'time']

    # Standard named DSDA category regexes. These are either used to guess in one of two ways:
    #   - initial category guess if a category field is provided, which may be overridden by other
    #     categories in cases where this match was inaccurate (e.g. matching UV-Max for
    #     "skill 2 max")
    #   - catchall case where the category field is not provided, so the entire txt is searched for
    #     these regexes
    STANDARD_CATEGORY_REGEXES = [
        # UV 100% is assumed to be UV-Max, but 100% alone doesn't really mean much, so this case is
        # specified separately.
        {re.compile(r'(UV|Ultra[\s*\-_]?Violence|Skill[\s*\-_]?4)[\s*\-_]?100%',
                    re.IGNORECASE): 'UV Max'},
        # NM categories are matched with precedence to avoid categorizing NM Speed as UV Speed, etc.
        {re.compile(
            r'(NM|(N|Night)[\s*\-_]?mare!?|Skill[\s*\-_]?5)[\s*\-_]?'
            r'([\s*\-_]?with)?[\s*\-_]?\(?100[s%]?[\s*\-_]?(secrets?)?\)?', re.IGNORECASE
        ): 'NM 100S'},
        {re.compile(r'(NM|(N|Night)[\s*\-_]?mare!?|Skill[\s*-_]?5)[\s*\-_]?Speed',
                    re.IGNORECASE): 'NM Speed'},
        # Heretic categories are matched with precedence to avoid using Doom conventions for them
        {re.compile(r'(SM|Smite[\s*\-_]?Meister)[\s*\-_]?(100%|Max)',
                    re.IGNORECASE): 'SM Max'},
        {re.compile(r'(SM|Smite[\s*\-_]?Meister)[\s*\-_]?Speed',
                    re.IGNORECASE): 'SM Speed'},
        {re.compile(r'(BP|Black[\s*\-_]?Plague)[\s*\-_]?(100%|Max)',
                    re.IGNORECASE): 'BP Max'},
        {re.compile(r'(BP|Black[\s*\-_]?Plague)[\s*\-_]?Speed',
                    re.IGNORECASE): 'BP Speed'},
        # Hexen categories are matched with precedence to avoid using Doom conventions for them
        {re.compile(r'(Sk4|Berserker|Cardinal|Initiate|Warlock)[\s*\-_]?(100%|Max)',
                    re.IGNORECASE): 'Sk4 Max'},
        {re.compile(r'(Sk4|Berserker|Cardinal|Initiate|Warlock)[\s*\-_]?Speed',
                    re.IGNORECASE): 'Sk4 Speed'},
        {re.compile(r'(Sk5|Titan|Pope|Mystic|Archimage)[\s*\-_]?(100%|Max)',
                    re.IGNORECASE): 'Sk5 Max'},
        {re.compile(r'(Sk5|Titan|Pope|Mystic|Archimage)[\s*\-_]?Speed',
                    re.IGNORECASE): 'Sk5 Speed'},
        # These cases are super lenient as the other category matches should override these for
        # any cases where these may return an incorrect value.
        {re.compile(r'-?fast[\s*\-_]?(Max)?', re.IGNORECASE): 'UV Fast'},
        {re.compile(r'-?respawn[\s*\-_]?(Max)?', re.IGNORECASE): 'UV Respawn'},
        {re.compile(r'Max', re.IGNORECASE): 'UV Max'},
        {re.compile(r'Speed', re.IGNORECASE): 'UV Speed'},
        {re.compile(r'Pacifist', re.IGNORECASE): 'Pacifist'},
        {re.compile(r'Tyson', re.IGNORECASE): 'Tyson'},
        {re.compile(r'Stroller', re.IGNORECASE): 'Stroller'},
        {re.compile(r'No[\s*\-_]?mo(nsters?)?([\s*\-_]?with)?[\s*\-_]?100[s%]?[\s*\-_]?secrets?',
                    re.IGNORECASE): 'NoMo 100S'},
        {re.compile(r'No[\s*\-_]?mo(nsters?)?([\s*\-_]?speed)?', re.IGNORECASE): 'NoMo'},
        # If just the difficulty is present, assume speed.
        {re.compile(r'(UV|Ultra[\s*\-_]?Violence|Skill[\s*\-_]?4)', re.IGNORECASE): 'UV Speed'},
        {re.compile(r'(NM|Night[\s*\-_]?mare!?|Skill[\s*\-_]?5)', re.IGNORECASE): 'NM Speed'}
    ]

    # Other category regexes that require notes on DSDA. Will only be run for textfiles where the
    # category is explicitly defined as a colon-separated field to optimize performance. Only a
    # subset of commonly seen other categories is included.
    OTHER_CATEGORY_REGEXES = [
        {re.compile(r'(HMP|Hurt[\s*\-_]?Me[\s*\-_]?Plenty|Skill[\s*\-_]?3)[\s*\-_]?(Max|100%)',
                    re.IGNORECASE): 'HMP Max'},
        {re.compile(r'(HMP|Hurt[\s*\-_]?Me[\s*\-_]?Plenty|Skill[\s*\-_]?3)[\s*\-_]?Speed',
                    re.IGNORECASE): 'HMP Speed'},
        {re.compile(
            r'(HNTR|Hey,?[\s*\-_]?Not[\s*\-_]?Too[\s*\-_]?Rough|Skill[\s*\-_]?2)[\s*\-_]?(Max|100%)',
            re.IGNORECASE
        ): 'HNTR Max'},
        {re.compile(r'(HNTR|Hey,?[\s*\-_]?Not[\s*\-_]?Too[\s*\-_]?Rough|Skill[\s*\-_]?2)[\s*\-_]?Speed',
                    re.IGNORECASE): 'HNTR Speed'},
        {re.compile(
            r'(ITYTD|I\'?m[\s*\-_]?Too[\s*\-_]?Young[\s*\-_]?to[\s*\-_]?Die|Skill[\s*\-_]?1)[\s*\-_]?'
            r'(Max|100%)', re.IGNORECASE
        ): 'ITYTD Max'},
        {re.compile(
            r'(ITYTD|I\'?m?[\s*\-_]?Too[\s*\-_]?Young[\s*\-_]?to[\s*\-_]?Die|Skill[\s\-_]?1)[\s*\-_]?'
            r'Speed', re.IGNORECASE
        ): 'ITYTD Speed'},
        {re.compile(r'(UV|Ultra[\s*\-_]?Violence|Skill[\s*\-_]?4)'
                    r'([\s*\-_]?with)?[\s*\-_]?100s?[\s*\-_]?secrets?', re.IGNORECASE): 'UV 100S'},
        {re.compile(r'(NM|(N|Night)[\s*\-_]?mare!?|Skill[\s*-_]?5)[\s*\-_]?Pacifist',
                    re.IGNORECASE): 'NM Pacifist'},
        {re.compile(r'(NM|(N|Night)[\s*\-_]?mare!?|Skill[\s*-_]?5)[\s*\-_]?Stroller',
                    re.IGNORECASE): 'NM Stroller'},
        {re.compile(r'(UV|Ultra[\s*\-_]?Violence|Skill[\s\-_]?4)[\s\-_]?-?fast[\s*\-_]?Tyson',
                    re.IGNORECASE): 'Tyson with -fast'},
        {re.compile(
            r'(UV|Ultra[\s*\-_]?Violence|Skill[\s*\-_]?4)[\s*\-_]?Tyson([\s*\-_]?with)?[\s*\-_]?-?fast',
            re.IGNORECASE
        ): 'Tyson with -fast'},
        {re.compile(r'(GM|Grand[\s*\-_]?master)[\s*\-_]?Tyson', re.IGNORECASE): 'Tyson with -fast'},
        {re.compile(r'(UV|Ultra[\s*\-_]?Violence|Skill[\s*\-_]?4)[\s*\-_]?Tank',
                    re.IGNORECASE): 'UV Tank'},
    ]
    OTHER_CATEGORY_TO_INFO_MAP = {
        'HMP Max': {'category': 'Other', 'note': 'Skill 3 max'},
        'HMP Speed': {'category': 'Other', 'note': 'Skill 3 speed'},
        'HNTR Max': {'category': 'Other', 'note': 'Skill 2 max'},
        'HNTR Speed': {'category': 'Other', 'note': 'Skill 2 speed'},
        'ITYTD Max': {'category': 'Other', 'note': 'Skill 1 max'},
        'ITYTD Speed': {'category': 'Other', 'note': 'Skill 1 speed'},
        'Skill 3 Max': {'category': 'Other', 'note': 'Skill 3 max'},
        'Sk3 Max': {'category': 'Other', 'note': 'Skill 3 max'},
        'Skill 3 Speed': {'category': 'Other', 'note': 'Skill 3 speed'},
        'Sk3 Speed': {'category': 'Other', 'note': 'Skill 3 speed'},
        'Skill 2 Max': {'category': 'Other', 'note': 'Skill 2 max'},
        'Sk2 Max': {'category': 'Other', 'note': 'Skill 2 max'},
        'Skill 2 Speed': {'category': 'Other', 'note': 'Skill 2 speed'},
        'Sk2 Speed': {'category': 'Other', 'note': 'Skill 2 speed'},
        'Skill 1 Max': {'category': 'Other', 'note': 'Skill 1 max'},
        'Sk1 Max': {'category': 'Other', 'note': 'Skill 1 max'},
        'Skill 1 Speed': {'category': 'Other', 'note': 'Skill 1 speed'},
        'Sk1 Speed': {'category': 'Other', 'note': 'Skill 1 speed'},
        'UV 100S': {'category': 'Other', 'note': 'UV 100S'},
        'NM Pacifist': {'category': 'NM Speed', 'note': 'Also Pacifist'},
        'NM Stroller': {'category': 'Other', 'note': 'NM Stroller'},
        'Tyson with -fast': {'category': 'Other', 'note': 'Tyson with -fast'},
        'UV Tank': {'category': 'Other', 'note': 'UV Tank'}
    }

    SKILL_REGEXES = {
        re.compile(r'(NM|(N|Night)[\s*\-_]?mare!?|(Skill)?[\s*\-_]?5)', re.IGNORECASE): 'Nightmare!',
        re.compile(r'(UV|Ultra[\s*\-_]?Violence|(Skill)?[\s*\-_]?4)', re.IGNORECASE): 'Ultra-Violence',
        re.compile(r'(HMP|Hurt[\s*\-_]?Me[\s*\-_]?Plenty|(Skill)?[\s*\-_]?3)', re.IGNORECASE): 'Hurt Me Plenty',
        re.compile(
            r'(HNTR|Hey,?[\s*\-_]?Not[\s*\-_]?Too[\s*\-_]?Rough|(Skill)?[\s*\-_]?2)', re.IGNORECASE
        ): 'Hey, Not Too Rough',
        re.compile(r'(ITYTD|I\'?m[\s*\-_]?Too[\s*\-_]?Young[\s*\-_]?to[\s*\-_]?Die|(Skill)?[\s\-_]?1)',
                   re.IGNORECASE): "I'm Too Young to Die",
        re.compile(r'(TWAWN|Thou[\s*\-_]?Need(eth)?[\s*\-_]?a[\s*\-_]?Wet[\s*\-_]?Nurse)',
                   re.IGNORECASE): 'Thou Needeth a Wet-Nurse',
        re.compile(r'(YAU|YRU|Yellowbellies[\s*\-_]?(Are|R)[\s*\-_]?Us)',
                   re.IGNORECASE): 'Yellowbellies-R-Us',
        re.compile(r'(BTO|Bring(est)?[\s*\-_]?Them[\s*\-_]?On(eth)?)',
                   re.IGNORECASE): 'Bringest Them Oneth',
        re.compile(r'((TAA)?SM|(Thou[\s*\-_]?Art[\s*\-_]?(a[\s*\-_]?)?)?Smite[\s*\-_]?Meister)',
                   re.IGNORECASE): 'Thou Art a Smite-Meister',
        re.compile(r'(BP(PT)?|Black[\s*\-_]?Plague([\s*\-_]?Possess(es)?[\s*\-_]?Thee)?)',
                   re.IGNORECASE): 'Black Plague Possesses Thee',
        re.compile(r'Squire|Altar[\s*\-_]?Boy|Novice|Apprentice', re.IGNORECASE): 'Sk1',
        # Note: Acolyte in Hexen could either be skill 2 or skill 3, but per the Doom Wiki, the skill 3 convention is
        #       only seen in the Doom 64 version of the port, so that convention is not likely to be used for DSDA
        #       demos. For the other difficulties, the Nintendo 64 conventions are not ambiguous.
        re.compile(r'Knight|Acolyte|Missionary|Enchanter', re.IGNORECASE): 'Sk2',
        re.compile(r'Warrior|Priest|Sorcerer', re.IGNORECASE): 'Sk3',
        re.compile(r'Berserker|Cardinal|Initiate|Warlock', re.IGNORECASE): 'Sk4',
        re.compile(r'Titan|Pope|Mystic|Archimage', re.IGNORECASE): 'Sk5'
    }

    SKILL_TO_SPEED_CATEGORIES_MAP = {
        'Nightmare!': 'NM Speed', 'Ultra-Violence': 'UV Speed', 'Hurt Me Plenty': 'HMP Speed',
        'Hey, Not Too Rough': 'HNTR Speed', "I'm Too Young to Die": 'ITYTD Speed',
        'Thou Needeth a Wet-Nurse': 'Skill 1 speed', 'Yellowbellies-R-Us': 'Skill 2 speed',
        'Bringest Them Oneth': 'Skill 3 speed', 'Thou Art a Smite-Meister': 'Skill 4 speed',
        'Black Plague Possesses Thee': 'Skill 5 speed', 'Sk1': 'Sk1 speed', 'Sk2': 'Sk2 speed', 'Sk3': 'Sk3 speed',
        'Sk4': 'Sk4 speed', 'Sk5': 'Sk5 speed'
    }
    SKILL_TO_MAX_CATEGORIES_MAP = {
        'Nightmare!': 'NM 100S', 'Ultra-Violence': 'UV Max', 'Hurt Me Plenty': 'HMP Max',
        'Hey, Not Too Rough': 'HNTR Max', "I'm Too Young to Die": 'ITYTD Max'
    }

    PORT_REGEXES = {
        # Chocolate family
        # Chocolate Doom
        re.compile(
            r'Chocolate(\s*|-|_)?Doom(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d\.\d+\.\d+)', re.IGNORECASE
        ): 'Chocolate DooM',
        # Crispy Doom
        re.compile(
            r'Crispy(\s*|-|_)?Doom(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d\.\d+(\.\d+)?)', re.IGNORECASE
        ): 'Crispy Doom',
        # Crispy Heretic
        re.compile(
            r'Crispy(\s*|-|_)?Heretic(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d\.\d+(\.\d+)?)', re.IGNORECASE
        ): 'Crispy Heretic',
        # CNDoom
        re.compile(
            r'CNDoom(\.exe)?\s*(v|version)?(\s*|\.)?(?P<version>\d\.\d\.\d(\.\d))?', re.IGNORECASE
        ): 'CNDoom',
        # Sprinkled Doom
        re.compile(
            r'Sprinkled(\s*|-|_)?Doom(\.exe)?\s*'
            r'(v|version)?\.?(?P<version>\d\.\d\.\d(\.\d)?)?', re.IGNORECASE
        ): 'Sprinkled Doom',

        # Boom/MBF family
        # Boom
        re.compile(r'([\s+])Boom\s*(v|version)?(\s*|\.)?(?P<version>2\.0\.[0-2])',
                   re.IGNORECASE): 'Boom',
        # MBF
        re.compile(
            r'[\S+](?P<name>MBF(386|-Sigil|-SNM)?)\s*(v|version)?(\s*|\.)?(?P<version>\d\.\d\.\d)',
            re.IGNORECASE
        ): None,
        # TASMBF
        re.compile(r'TASMBF', re.IGNORECASE): 'TASMBF',
        # PrBoom
        re.compile(
            r'(Pr|GL)Boom(\.exe)?(?!\+|-?plus)\s*(v|version)?(\s|\.)*?(?P<version>\d\.\d\.\d)',
            re.IGNORECASE
        ): 'PRBoom',
        # PrBoom+
        re.compile(
            r'(Pr|GL)(Boom)?\s*(\+|-?plus)?(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d\.\d\.\d\.\d)\s*'
            r'-?((complevel|cl)\s*(?P<complevel>\d+))?', re.IGNORECASE
        ): 'PRBoom',
        # PrBoomX
        re.compile(
            r'(Pr|GL)(Boom)?\s*X\s*(\+|-?plus)?(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d\.\d\.\d\.\d)\s*'
            r'-?((complevel|cl)\s*(?P<complevel>\d+))?', re.IGNORECASE
        ): 'PRBoomX',
        # DSDA-Doom
        re.compile(
            r'DSDA(\s*|-|_)?Doom(\.exe)?(\s*|-)?(v|version)?\.?(?P<version>\d\.\d+(\.\d+)?)\s*'
            r'-?((complevel|cl)\s*(?P<complevel>\d+))?',
            re.IGNORECASE
        ): 'DSDA-Doom',
        # Woof
        re.compile(
            r'Woof!?(\.exe)?(\s*|-)?(v|version)?(\s*|\.)?(?P<version>\d\.\d+(\.\d+)?)\s*'
            r'-?((complevel|cl)\s*(?P<complevel>\d+))?',
            re.IGNORECASE
        ): 'Woof',
        # Nugget Doom
        re.compile(
            r'Nugget(\s*|-|_)?Doom(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d\.\d+(\.\d+)?)\s*'
            r'-?((complevel|cl)\s*(?P<complevel>\d+))?',
            re.IGNORECASE
        ): 'Nugget Doom',
        # rboom
        re.compile(r'^rboom(\.exe)?', re.IGNORECASE): 'rboom',

        # ZDoom family
        # ZDoom
        re.compile(r'^\s*ZDoom(\.exe)?(\s*|-)?(v|version)?(\s*|\.)?(?P<version>\d\.\d(\.\d+)?)?',
                   re.IGNORECASE): 'ZDoom',
        # GZDoom
        re.compile(r'GZDoom(\.exe)?(\s*|-)?(v|version)?(\s*|\.)?(?P<version>\d\.\d\.\d+)',
                   re.IGNORECASE): 'GZDoom',
        # ZDaemon
        re.compile(r'ZDaemon(\.exe)?(\s*|-)?(v|version)?(\s*|\.)?(?P<version>\d\.\d\.\d+)',
                   re.IGNORECASE): 'ZDaemon',
        # Zandronum
        re.compile(
            r'Zandronum(\.exe)?(\s*|-)?(v|version)?(\s*|\.)?(?P<version>\d\.\d(\.\d+)?(\s*Alpha)?)',
            re.IGNORECASE
        ): 'Zandronum',

        # Other ports
        # Strawberry Doom
        re.compile(r'Strawberry(\s*|-|_)?Doom(\.exe)?(\s*|-)?r(?P<version>\d+)',
                   re.IGNORECASE): 'Strawberry Doom',

        # TAS
        re.compile(r'XDRE(\.exe)?(\s*|-)?(v|version)?(\s*|\.)?(?P<version>\d(\.\d+)?)',
                   re.IGNORECASE): 'XDRE',

        # Eternity Engine
        re.compile(
            r'Eternity(\s*|-|_)?(Engine)?(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d+\.\d+(\.\d+)?)',
            re.IGNORECASE
        ): 'Eternity Engine',

        # Doom Legacy
        re.compile(
            r'(Doom)?(\s*|-|_)?Legacy(\s*|-|_)?(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d+\.\d+(\.\d+)?)',
            re.IGNORECASE
        ): 'Legacy',

        # Doomsday
        re.compile(
            r'Doomsday(\s*|-|_)?(\s*|-|_)?(Engine)?(\.exe)?(\s*|-)?'
            r'(v|version)?(\s*|\.)?(?P<version>\d+\.\d+(\.\d+)?)',
            re.IGNORECASE
        ): 'Doomsday',

        # Doom95
        re.compile(
            r'Doomsday(\s*|-|_)?(?P<version>95)(\s*|-|_)?(Engine)?(\.exe)?(\s*|-)?',
            re.IGNORECASE
        ): 'DooM2',

        # jHeretic
        re.compile(
            r'jHeretic(\s*|-|_)?(?P<version>\d+\.\d+(\(se\d+\))?)(\s*|-|_)?(Engine)?(\.exe)?(\s*|-)?',
            re.IGNORECASE
        ): 'jHeretic',
    }

    VANILLA_PORT_REGEXES = {
        re.compile(
            r'((The\s+)?Ultimate\s*)?Doom(\.exe)?\s+(v|version)?\s*(?P<version>\d\.\d+(\.\d+)?)',
            re.IGNORECASE
        ): 'DooM',
        re.compile(r'(The\s+)?Doom\s*2(\.exe)?\s+(v|version)?\s*(?P<version>\d\.\d+(\.\d+)?)',
                   re.IGNORECASE): 'DooM2',

        # Both of these regexes go to Final Doom, but if both Final and f are marked optional, it
        # could match Doom2.exe, so splitting into two. Final Doom demos will require special logic
        # as the port name is marked identically on DSDA, just the version has f appended.
        re.compile(
            r'(The\s+)?Final\s*Doom(\s*2)?(\.exe)?\s+(v|version)?\s*(?P<version>\d\.\d+(\.\d+)?)f?',
            re.IGNORECASE
        ): 'Final Doom',
        re.compile(
            r'(The\s+)?(Final\s*)?Doom(\s*2)?(\.exe)?\s+'
            r'(v|version)?\s*(?P<version>\d\.\d+(\.\d+)?)f', re.IGNORECASE
        ): 'Final Doom'
    }

    TIME_RE = re.compile(r'(?P<time>(\d+:)?\d+:\d+(\.\d+)?)', re.IGNORECASE)
    TIME_RE_SECONDS = re.compile(r'(?P<num_seconds>\d+)[\s*_\-]?(s|seconds?)?', re.IGNORECASE)

    CATEGORY_IN_TIME_RE = re.compile(
        r'^(?P<category>[a-zA-Z0-9()_\-\s]+)\s+in\s+(?P<time>(\d+:)?\d+:\d+(\.\d+)?)', re.IGNORECASE
    )

    def __init__(self, textfile_path):
        """Initialize textfile data class.

        :param textfile_path: Path to textfile on local filesystem.
        """
        super().__init__()
        self.data = {}
        self.raw_data = {'wad_strings': [], 'video_links': []}
        self.note_strings = set()
        self.textfile_path = textfile_path
        self._raw_textfile = None

    def analyze(self):
        """Analyze info provided to playback parser."""
        self._parse_textfile()

    def populate_data_manager(self, data_manager):
        """Populate data manager with info from textfile.

        :param data_manager: Data manager to populate
        """
        for key, value in self.data.items():
            if not value:
                continue

            if key in TextfileData.CERTAIN_KEYS:
                data_manager.insert(key, value, DataManager.CERTAIN, source='textfile')
            elif key in TextfileData.POSSIBLE_KEYS:
                data_manager.insert(key, value, DataManager.POSSIBLE, source='textfile')
            else:
                raise ValueError('Unrecognized key found in data dictionary: {}.'.format(key))

    def _parse_textfile(self):
        """Parse textfile path."""
        try:
            with open(self.textfile_path, encoding='utf-8') as textfile_stream:
                self._raw_textfile = textfile_stream.read()
        except ValueError as value_error:
            LOGGER.warning('Caught error %s reading textfile %s, ignoring.', value_error,
                           self.textfile_path)
            with open(self.textfile_path, encoding='utf-8', errors='ignore') as textfile_stream:
                self._raw_textfile = textfile_stream.read()

        if TextfileData.TAS_STRING in self._raw_textfile.lower():
            self.data['is_tas'] = True

        text_lines = self._raw_textfile.splitlines()
        in_line = None
        in_line_match = None
        for line in text_lines:
            # If we find a line that looks like {something} in {time}, we will take the first one we find for potential
            # category/time verification.
            if not in_line_match:
                in_line = line.lower()
                in_line_match = self.CATEGORY_IN_TIME_RE.match(line.lower())

            non_colon_port_match = TextfileData.NON_COLON_PORT_REGEX.match(line)
            if ':' in line:
                key, value = line.split(':', 1)
                key = ''.join(character for character in key.lower() if character.isalnum())
                value = value.strip()
            elif ' - ' in line:
                key, value = line.split(' - ', 1)
                key = ''.join(character for character in key.lower() if character.isalnum())
                value = value.strip()
            elif '\t' in line:
                key, value = line.split('\t', 1)
                key = ''.join(character for character in key.lower() if character.isalnum())
                value = value.strip()
            elif ' ' in line:
                key, value = line.split(' ', 1)
                key = ''.join(character for character in key.lower() if character.isalnum())
                value = value.strip()
            elif non_colon_port_match:
                key = 'engine'
                value = non_colon_port_match.group('value')
            else:
                continue

            value_lowercase = value.lower().replace('"', '')
            if key in TextfileData.CATEGORY_KEYS:
                self.data['category'] = self._parse_category(value_lowercase, check_other=True)
                self.raw_data['raw_category'] = value_lowercase
                if 'tas' in value_lowercase.split():
                    self.data['is_tas'] = True
            elif key in TextfileData.PORT_KEYS:
                self.data['source_port'] = self._parse_port(value_lowercase)
            elif key in TextfileData.VIDEO_KEYS:
                youtube_url_key = parse_youtube_url(value)
                # Some YouTube URLs won't produce any value here (e.g., channel pages). Ignore
                # these.
                if youtube_url_key:
                    youtube_url_key = ''.join(character for character in youtube_url_key
                                              if character.isalnum() or character in ('_', '-'))
                    self.raw_data['video_links'].append(youtube_url_key)
            elif key in TextfileData.WAD_KEYS:
                self.raw_data['wad_strings'].append(value_lowercase)
            elif key in TextfileData.TIME_KEYS:
                parsed_time = self._parse_time(value_lowercase)
                if parsed_time:
                    self.data['time'] = parsed_time
            elif key == 'iwad':
                self.raw_data['iwad'] = value_lowercase
            elif key in TextfileData.SKILL_KEYS:
                self.raw_data['skill'] = self._parse_skill(value_lowercase)

        iwad = self.raw_data.get('iwad')
        if not self.raw_data['wad_strings'] and iwad:
            self.raw_data['wad_strings'].append(iwad)

        if len(self.raw_data['video_links']) == 1:
            self.data['video_link'] = self.raw_data['video_links'][0]

        if in_line_match and (not self.data.get('category') or not self.data.get('time')):
            raw_category = in_line_match.group('category').strip().lower()
            self.raw_data['raw_category'] = raw_category
            category_guess = self._parse_category(raw_category)
            time_guess = self._parse_time(in_line_match.group('time').strip().lower())

            if not self.data.get('category'):
                self.data['category'] = category_guess
            if not self.data.get('time'):
                self.data['time'] = time_guess

            if 'tas' in in_line.split():
                self.data['is_tas'] = True

        category_based_on_skill_guess = self._guess_category_based_on_skill()
        if category_based_on_skill_guess:
            self.data['category'] = category_based_on_skill_guess

        # If we were unable to parse the category or source port from key/value pairs in the
        # textfile, we just try the entire textfile; this is likely to be wrong since someone could
        # just have a category or port name in their general comments, but better than nothing.
        if not self.data.get('category'):
            self.data['category'] = self._parse_category(self._raw_textfile, check_other=False)
            if not self.data.get('category'):
                LOGGER.info('Could not parse category from textfile %s.', self.textfile_path)
                self.data.pop('category')

        if not self.data.get('source_port'):
            self.data['source_port'] = self._parse_port(self._raw_textfile, skip_vanilla_check=True)

        source_port = self.data.get('source_port')
        if source_port:
            for tas_port in TextfileData.TAS_PORTS:
                if tas_port in source_port:
                    self.data['is_tas'] = True

            is_multi_cl_port = False
            for multi_cl_port in self.MULTI_COMPLEVEL_PORTS:
                if source_port.startswith(multi_cl_port):
                    is_multi_cl_port = True
                    break

            # If this port can support multiple complevels, the LMP parser might be able to provide
            # a more accurate guess for the cl, so the complevel logic will be calculated later.
            if is_multi_cl_port:
                self.raw_data['source_port'] = self.data['source_port']
                self.data['source_port'] = None
        else:
            LOGGER.info('Could not parse source port from textfile %s.', self.textfile_path)
            self.data.pop('source_port')

    def _parse_category(self, text_str, check_other=False):
        """Parse category from a provided text string.

        :param text_str: Text string
        :param check_other: Check other categories as part of the function
        :return: Category name if it was possible to parse, else None
        """
        category_name = None
        for category_dict in TextfileData.STANDARD_CATEGORY_REGEXES:
            category_regex, cur_category_name = get_single_key_value_dict(category_dict)
            match = category_regex.search(text_str)
            if match:
                category_name = cur_category_name
                break

        if check_other:
            for category_dict in TextfileData.OTHER_CATEGORY_REGEXES:
                category_regex, cur_category_name = get_single_key_value_dict(category_dict)
                match = category_regex.search(text_str)
                if match:
                    return self._handle_other_category(cur_category_name)

        return category_name

    @staticmethod
    def _parse_port(text_str, skip_vanilla_check=False):
        """Parse port from a provided text string.

        :param text_str: Text string
        :param skip_vanilla_check: Skip checking for vanilla ports
        :return: Port name if it was possible to parse, else None
        """
        port_found = None
        for port_regex, port_name in TextfileData.PORT_REGEXES.items():
            match = port_regex.search(text_str)
            if match:
                # A whole bunch of hacky finagling to try to parse all kinds of different formats
                # for a port name and conform them to a single naming convention.
                try:
                    version = match.group('version')
                except IndexError:
                    version = ''

                port_name_final = port_name
                if not port_name_final:
                    port_name_final = match.group('name')

                if version:
                    # If someone formats DSDA-Doom version as just #.##, set to #.##.0 by default
                    if port_name_final == 'DSDA-Doom' and version.count('.') == 1:
                        version = f'{version}.0'

                    # No need to fail on this since most ports don't have complevels anyway
                    try:
                        complevel = match.group('complevel')
                    except IndexError:
                        complevel = None
                    if complevel:
                        version = f'{version}cl{complevel}'

                    if not version.startswith('v'):
                        version = f'v{version}'

                    version = f' {version}'
                else:
                    version = ''

                port_found = f'{port_name_final}{version}'
                break

        if port_found:
            return port_found
        elif not skip_vanilla_check:
            for port_regex, port_name in TextfileData.VANILLA_PORT_REGEXES.items():
                match = port_regex.search(text_str)
                if match:
                    version = match.group('version')
                    if not version:
                        if CONFIG.assume_latest_version_for_vanilla_ports:
                            version = 'v1.9'
                        else:
                            break

                    if not version.startswith('v'):
                        version = f'v{version}'

                    if port_name == 'Final Doom':
                        port_name_final = 'DooM2'
                        version = f'{version}f'
                    else:
                        port_name_final = port_name

                    port_found = f'{port_name_final} {version}'
                    break

        return port_found

    def _parse_time(self, text_str):
        """Parse time from a provided text string.

        :param text_str: Text string
        :return: Time if it was possible to parse, else None
        """
        time_re_seconds_match = self.TIME_RE_SECONDS.match(text_str)
        time_re_match = self.TIME_RE.match(text_str)
        if time_re_match:
            time_string = time_re_match.group('time')
            return normalize_time_to_minutes_and_seconds(time_string)
        if time_re_seconds_match:
            num_seconds = int(time_re_seconds_match.group('num_seconds'))
            if num_seconds > 60:
                minutes = int(num_seconds / 60)
                seconds = num_seconds % 60
            else:
                minutes = 0
                seconds = num_seconds

            return f'{minutes}:{seconds:02}'

        return None

    def _parse_skill(self, skill_str):
        """Parse skill from a provided skill string.

        :param skill_str: Skill string
        :return: Time if it was possible to parse, else None
        """
        for skill_re, skill_name in self.SKILL_REGEXES.items():
            if skill_re.match(skill_str):
                return skill_name

        return None

    def _guess_category_based_on_skill(self):
        """Guess category based on skill.

        The skill and current category guess are already assumed to be stored in the raw_data and data maps.

        :return: Category based on skill if it was possible to guess, or None
        """
        # Add a category from the skill level if available, or replace excessively vague category strings if the skill
        # level disagrees with the guess.
        skill = self.raw_data.get('skill')
        category = self.data.get('category')
        raw_category = self.raw_data.get('raw_category')
        if skill and (not category or (category == 'UV Speed' and raw_category == 'speed')):
            if not category or raw_category == 'speed':
                assumed_category = 'speed'
            elif raw_category == 'max':
                assumed_category = 'max'
            else:
                # In all other cases, we currently trust the current category guess
                return None

            if assumed_category == 'speed':
                category_guess = self.SKILL_TO_SPEED_CATEGORIES_MAP.get(skill)
            elif assumed_category == 'max':
                category_guess = self.SKILL_TO_MAX_CATEGORIES_MAP.get(skill)
            else:
                category_guess = None

            if category_guess in self.OTHER_CATEGORY_TO_INFO_MAP:
                return self._handle_other_category(category_guess)

            return category_guess

    def _handle_other_category(self, category_guess):
        """Handle Other categories based on category guess

        Category guess provided is assumed to be an Other category already.

        :param category_guess: Category guess provided.
        :return Category guess true category
        """
        other_category_info = TextfileData.OTHER_CATEGORY_TO_INFO_MAP[category_guess]
        self.note_strings.add(other_category_info['note'])
        return other_category_info['category']

