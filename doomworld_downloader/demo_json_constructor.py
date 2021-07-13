"""
Demo JSON constructor.

This will take all of the data, which should already be pre-processed to be as accurate as
reasonably possible with just the automated process and generate the demo JSON. It will also keep
track of any JSONs that require attention, so that further on they can be stored separately for
manual inspection.
"""
import logging
import re


LOGGER = logging.getLogger(__name__)


class DemoJsonConstructor:
    """Construct demo JSON."""
    SKILL_CATEGORY_NOTE_RE = re.compile('^Skill \d .+$')

    # We could have all of these keys consistent with the JSON keys, but I find the verbose names
    # are more useful for searching/debugging.
    KEY_TO_JSON_MAP = {'is_tas': 'tas', 'is_solo_net': 'solo_net', 'num_players': 'guys',
                       'source_port': 'engine', 'player_list': 'players'}
    # Note: the version key is required by the uploader spec but is currently always hardcoded to 0.
    KEY_TO_DEFAULT_MAP = {'tas': False, 'solo_net': False, 'version': '0'}
    REQUIRED_KEYS = [
        'tas', 'solo_net', 'guys', 'version', 'wad', 'file', 'kills', 'items', 'secrets', 'engine',
        'time', 'level', 'levelstat', 'category', 'secret_exit', 'recorded_at', 'players'
    ]

    def __init__(self, data_manager, note_strings, zip_file):
        """Initialized demo JSON constructor."""
        self.data_manager = data_manager
        self.note_strings = note_strings
        self.zip_file = zip_file
        self.demo_json = {'file': {'name': zip_file}}

        self._parse_data_manager()

    def _parse_data_manager(self):
        """Parse data from data manager.

        :raises RuntimeError if there are required keys missing in the final demo JSON.
        """
        for evaluation in self.data_manager:
            if evaluation.needs_attention:
                # TODO: Move this to a separate function; this will handle the following cases:
                #   - Special cases where we can assume one of the sources is correct even if they
                #     are not certain
                #   - Setting the final JSON to some placeholder when we are not certain at all
                if evaluation.key == 'category':
                    playback_category = None
                    textfile_category = None
                    # TODO: Category may come from other sources (the post)
                    for possible_value, sources in evaluation.possible_values.items():
                        if 'playback' in sources:
                            playback_category = possible_value
                        elif 'textfile' in sources:
                            textfile_category = possible_value

                    # If the playback showed nomo100s, it's guaranteed to be an accurate category;
                    # it's safe to assume the textfile specified nomo by error or because of
                    # unavoidable secrets.
                    if playback_category == 'NoMo 100S' and textfile_category == 'NoMo':
                        LOGGER.info('Inferred NoMo 100S category for zip file %s.', self.zip_file)
                        self.demo_json[evaluation.key] = playback_category
            else:
                # Convert to JSON keys, default to value in the map.
                key_to_insert = self.KEY_TO_JSON_MAP.get(evaluation.key, evaluation.key)
                self.demo_json[key_to_insert] = next(iter(evaluation.possible_values.keys()))

        for key, default in DemoJsonConstructor.KEY_TO_DEFAULT_MAP.items():
            if key not in self.demo_json:
                self.demo_json[key] = default

        # The players list is set to a tuple in the data manager so that it is a hashable type; we
        # need to convert it to a list to match the JSON spec.
        self.demo_json['players'] = list(self.demo_json['players'])
        for key in self.REQUIRED_KEYS:
            if key not in self.demo_json:
                raise RuntimeError('Key {} not found in final demo JSON.'.format(key))

    def _construct_tags(self):
        """Construct tags array for demo JSON

        Does nothing if there are no note strings passed to the constructor.
        """
        if not self.note_strings:
            return

        # This is inherently a bit wonky code, but I would prefer that all of the tags are
        # consistently placed in each entry, and there's no real way to do that without iterating
        # the note strings multiple times.
        final_tag = self._construct_other_movie_tag()
        final_tag += self._construct_skill_tag()
        final_tag += self._construct_misc_tags()
        self.demo_json['tags'] = {'show': True, 'text': final_tag}

    def _construct_other_movie_tag(self):
        """Construct other movie tag.

        :return: Other movie tag.
        """
        other_movie = ''
        no_secret_maps = ''
        for note_string in self.note_strings:
            if note_string.startswith('Other Movie '):
                # We don't actually need the "Other Movie" part, as that info is present in the
                # level info; it is included so this note is more easy to detect in this function.
                other_movie = note_string.split('Other Movie ')[1]
            if note_string == 'Does not visit secret maps.':
                no_secret_maps = note_string + '\n'

        if other_movie and not no_secret_maps:
            other_movie += '\n'

        return other_movie + '. ' + no_secret_maps

    def _construct_skill_tag(self):
        """Construct skill tag.

        :return: Skill tag.
        :raises RuntimeError if there are mismatches between notes and other info in the class
        """
        category = self.demo_json['category']
        incompatible = False
        additional_info = ''
        for note_string in self.note_strings:
            if DemoJsonConstructor.SKILL_CATEGORY_NOTE_RE.match('note_string'):
                # Override category in case the category is Other and there's a note string that
                # indicates the actual category (e.g., in cases of wrong skill level).
                if category != 'Other':
                    raise RuntimeError('Other skill run found without Other category: {}.'.format(
                        self.zip_file
                    ))
                category = note_string
            if note_string == 'Incompatible':
                incompatible = True
            if note_string in ['-altdeath', '-solo-net', 'fast']:
                if not additional_info:
                    additional_info = ' with ' + note_string
                else:
                    additional_info += ' and ' + note_string

        if incompatible:
           category = 'Incompatible {}'.format(category)

        skill_tag = category + additional_info
        if skill_tag:
            return skill_tag + '\n'

        return skill_tag

    def _construct_misc_tags(self):
        """Construct misc tags.

        All misc tags are just appended in alphabetical order and separated by newlines.

        :return: Misc tag.
        """
        misc_tags = []
        for note_string in self.note_strings:
            # Note: even though both Reality and Almost Reality are listed here, prior processing
            # should ensure that only one should be added to the notes.
            # TODO: Update Uses turbo logic to require manual effort to verify turbo value
            if (note_string in ['Also Reality', 'Also Almost Reality', 'Uses turbo'] or
                    note_string.startswith('Recorded in skill ')):
                misc_tags.append(note_string)

        return '\n'.join(sorted(misc_tags))
