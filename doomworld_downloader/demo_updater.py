"""
Generate demo update JSONs.

In DSDA update mode, this will run after all the demos (and potentially replacement zips for demos)
are processed and validated. The upload JSONs for all of the demos will still be output as a means
to debug any issues with the update process, while this generates update JSONs for any demos that
got processed successfully.
"""

import json
import logging
import os

from collections import defaultdict

from .upload_config import CONFIG, UPDATE_JSON_DIR


LOGGER = logging.getLogger(__name__)


class DemoUpdater:
    """Demo Updater."""

    MATCH_KEY_MAPPING = ['players', 'level', 'time', 'wad', 'category']

    def __init__(self, dsda_demo_info, dsda_output_jsons, replacement_output_jsons=None):
        """Initialize demo JSON dumper.

        :param dsda_demo_info: DSDA demo info
        :param dsda_output_jsons: DSDA output JSONs
        :param replacement_output_jsons: Replacements output JSONs
        """
        self._demo_id_to_filename = {}

        self.dsda_demo_info = dsda_demo_info
        self.dsda_output_jsons = self._process_output_jsons(dsda_output_jsons)
        self.replacement_output_jsons = self._process_output_jsons(replacement_output_jsons)

        self.demo_update_jsons = defaultdict(list)
        self.demo_upload_jsons = {}

    def _process_output_jsons(self, output_jsons):
        """Process demo JSONs provided from demo JSON dumper to a convenient format.

        :param output_jsons: Output JSONs
        :return: Processed demo JSONs
        """
        processed_output_jsons = {}
        for entry_json in output_jsons:
            # A JSON for a single demo will be keyed on demo; otherwise, the top level key is demo
            # pack, with demos underneath.
            single_demo_json = entry_json.get('demo')
            entry_json_demos = ([single_demo_json] if single_demo_json
                                else entry_json.get('demo_pack', {}).get('demos', []))
            demo_path = (single_demo_json['file']['name'] if single_demo_json
                         else entry_json.get('demo_pack', {})['file']['name'])
            demo_filename = os.path.basename(demo_path)
            demo_id = entry_json_demos[0].get('demo_id')
            if demo_id:
                demo_key = demo_id
                self._demo_id_to_filename[demo_id] = demo_filename
            else:
                demo_key = demo_filename

            processed_output_jsons[demo_key] = entry_json_demos

        return processed_output_jsons

    def generate_update_jsons(self):
        """Add demo JSON to dumper."""
        for demo_location, dsda_demo_info_list in self.dsda_demo_info['entry_list'].items():
            demo_id = dsda_demo_info_list[0]['demo_id']
            full_demo_jsons = self.dsda_output_jsons.get(demo_id)
            if not full_demo_jsons:
                LOGGER.error('Could not find demo %s in demo JSONs.', demo_location)
                continue

            if len(dsda_demo_info_list) == 1 and len(full_demo_jsons) == 1:
                self._check_demo_for_updates(demo_location, dsda_demo_info_list[0],
                                             full_demo_jsons[0])
            else:
                # If we are comparing demo packs on both sides, we need some fuzzy matching logic.
                for demo_dict in dsda_demo_info_list:
                    dsda_info = demo_dict['dsda_info']
                    # This is the key used to match the demos; each piece of info is included in
                    # order of most importance. Specifically, if we cannot match to the other side
                    # with all of the pieces of info, the last one will be removed for a more fuzzy
                    # matching strategy in case the update script changed that value. As such, any
                    # value that is most likely to update is placed last in the list. If at any
                    # point, the fuzzy matching returns more than one demo, we cannot match this one
                    # and a warning will be output.
                    match_key = [demo_dict['player_list'], dsda_info['level'], dsda_info['time'],
                                 dsda_info['wad'], dsda_info['category']]
                    found_match = False
                    matching_demo_json = None
                    while match_key:
                        for demo_json in full_demo_jsons:
                            found_match = True
                            for idx, value in enumerate(match_key):
                                json_key = self.MATCH_KEY_MAPPING[idx]
                                json_value = demo_json[json_key]
                                if json_value != value:
                                    # In case of the time, also check if cutting out the tics in the
                                    # JSON value will provide a match; this is possible if a demo on
                                    # DSDA has no tics and the updater added tics.
                                    # TODO: Time comparison should take into account that time is
                                    #       displayed in minutes:seconds from DSDA-Doom output, but
                                    #       includes hours on DSDA
                                    if json_key == 'time' and json_value.split('.')[0] != value:
                                        found_match = False
                                        break

                            if found_match:
                                matching_demo_json = demo_json
                                break
                            else:
                                continue

                        if found_match:
                            break
                        else:
                            match_key = match_key[:-1]

                    if found_match:
                        self._check_demo_for_updates(demo_location, demo_dict, matching_demo_json)
                        full_demo_jsons.remove(matching_demo_json)
                    else:
                        LOGGER.warning('Demo with ID %s not matched to JSON.', demo_dict['demo_id'])

                if full_demo_jsons:
                    LOGGER.warning('Extra JSONs remaining in list not accounted for on DSDA.')
                    # Rename demo_id field to DSDA API client convention
                    for demo_json in full_demo_jsons:
                        demo_json['file_id'] = demo_json.pop('demo_id')
                    self.demo_upload_jsons[demo_id] = full_demo_jsons

    def _check_demo_for_updates(self, demo_location, dsda_demo_info, full_demo_json):
        """Check demo for updates.

        :param demo_location: Demo location
        :param dsda_demo_info: Demo info from DSDA
        :param full_demo_json: Full demo JSON from processing it through DSDA-Doom
        """
        dsda_demo_info_to_check = dsda_demo_info['dsda_info']
        demo_update = {}
        is_advanced_port = self._check_advanced_port(full_demo_json['engine'])
        # TODO: If a demo is cheated, should not try to mark it TAS
        for key, value in dsda_demo_info_to_check.items():
            test_value = value
            final_key = key
            if key == 'note':
                test_value = value == 'TAS'
                json_value = full_demo_json['tas']
                final_key = 'tas'
            elif key == 'tags':
                json_tags = full_demo_json.get(key)
                if json_tags:
                    json_value = json_tags[0]['text']
                else:
                    json_value = None
            else:
                json_value = full_demo_json.get(key)

            # TODO: Time comparison should take into account that time is displayed in
            #       minutes:seconds from DSDA-Doom output, but includes hours on DSDA
            if (test_value or json_value) and test_value != json_value:
                # In case of advanced ports, we can't trust the output anyway.
                if is_advanced_port:
                    continue

                # We shouldn't override video links obtained from DSDA with nothing.
                if not json_value and test_value and key == 'video_link':
                    pass
                else:
                    LOGGER.debug('Difference for demo %s found in key %s!.', demo_location, key)
                    if not CONFIG.dsda_mode_replace_zips:
                        final_value = full_demo_json.get(final_key, {})
                        if final_value != 'UNKNOWN' or not CONFIG.dsda_mode_skip_unknowns:
                            demo_update[final_key] = full_demo_json.get(final_key, {})

        if is_advanced_port and CONFIG.dsda_mode_mark_advanced_demos_incompatible:
            demo_update['category'] = 'Other'
            demo_update['tags'] = [
                {'show': True, 'text': 'Incompatible {}'.format(full_demo_json['category'])}
            ]

        if CONFIG.dsda_mode_replace_zips:
            # TODO: At this point, we need to make sure the replacement JSON is identical to the old
            #       one, then perform the following instead of a regular update:
            #   - create a delete request for the existing demo
            #   - copy the new replacement upload JSON to the update directory
            pass
        else:
            if demo_update:
                demo_update['match_details'] = {
                    'category': dsda_demo_info_to_check['category'],
                    'level': dsda_demo_info_to_check['level'],
                    'wad': dsda_demo_info_to_check['wad'], 'time': dsda_demo_info_to_check['time']
                }
                player_list = dsda_demo_info['player_list']
                if len(player_list) == 1:
                    demo_update['match_details']['player'] = player_list[0]

                self.demo_update_jsons[dsda_demo_info['demo_id']].append(demo_update)

    def dump_json_updates(self):
        """Dump demo JSONs as uploads.

        :raises RuntimeError if there are no demos to dump.
        """
        if not self.demo_update_jsons:
            raise RuntimeError('No demo update JSONs to dump!')

        for demo_id, demo_update_json in self.demo_update_jsons.items():
            json_filename = f'{demo_id}_update.json'
            json_path = self._set_up_demo_json_file(json_filename, UPDATE_JSON_DIR)

            demo_update_json_final = {'demo_updates': demo_update_json}
            with open(json_path, 'w', encoding='utf-8') as out_stream:
                json.dump(demo_update_json_final, out_stream, indent=4, sort_keys=True)

        for demo_id, demo_upload_jsons in self.demo_upload_jsons.items():
            json_filename = f'{demo_id}_upload.json'
            json_path = self._set_up_demo_json_file(json_filename, UPDATE_JSON_DIR)

            demo_upload_json_final = {'demos': demo_upload_jsons}
            with open(json_path, 'w', encoding='utf-8') as out_stream:
                json.dump(demo_upload_json_final, out_stream, indent=4, sort_keys=True)

    @staticmethod
    def _set_up_demo_json_file(json_filename, json_dir):
        """Set up demo JSON file creation.

        :param json_filename: JSON filename
        :param json_dir: Directory to create JSON under
        :return: Path to JSON file to create
        """
        demo_parent_dir = CONFIG.demo_download_directory
        json_dir = os.path.join(demo_parent_dir, json_dir)
        os.makedirs(json_dir, exist_ok=True)
        json_path = os.path.join(json_dir, json_filename)
        return json_path

    @staticmethod
    def _check_advanced_port(port_name):
        """Check if port provided is an advanced engine.

        e.g., ZDoom, ZDaemon, etc.

        :param port_name: Port name
        :return: Port name to check
        """
        if 'ZDoom' in port_name or 'ZDaemon' in port_name or 'Doomsday' in port_name:
            return True

        return False
