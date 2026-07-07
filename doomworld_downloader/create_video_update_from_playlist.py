import json
import re


wad_name_to_key_map = {
    '10 Line Genocide: Episode 1': '10linee1',
    '10 Line Genocide: Episode 2': '10linee2',
    '10 Line Genocide: Episode 3': '10linee3',
    '60 Minute Marathon': '60mm',
    '60 Minute Marathon 2': '60mm2',
    'Brisk': 'brisk',
    'Crate Expectations': 'crate_escape',
    'Crispy Chicken Speedmap Session 01': 'ccss01',
    'GOODWAD': 'goodwad',
    'Junkfood': 'junkfood',
    'Junkfood 3: Wow Wow West': 'junkfood3',
    'The Nights Cut': 'nightscut',
    "NoReason's Speedmaps 2": 'nosp2',
    "NoReason's Speedmaps 3": 'nosp3',
    'Pacifist Paradise Secret Santa': 'ppss',
    'Pacifist Paradise Secret Santa 2': 'ppss2',
    'PUSS XXX: Quick And Dirty: Volume 1': 'puss30_qnd_vol1',
    'Revenant Hallway': 'revhallway',
    'Sunlust': 'sunlust',
    'This SUXX!': 'thissuxx',
    'With Love For Phoenyx': 'wl4phoenyx',
}


def custom_category_logic(category):
    """Run custom category logic if needed.

    :param category: Raw category
    :return True category
    """
    if category == 'UV-Speed':
        return 'UV Speed'
    if category == 'UV-Max':
        return 'UV Max'
    if category == 'UV-Fast':
        return 'UV Fast'
    if category == 'NM-Speed':
        return 'NM Speed'
    if category == 'NM-Speed Reality':
        return 'NM Speed'
    if category == 'UV-Tyson':
        return 'Tyson'
    if category == 'UV-Tyson [TAS]':
        return 'Tyson'

    return category


def custom_wad_logic(wad_name):
    """Run custom WAD name logic if needed.

    :param wad_name: Raw WAD name
    :return True WAD name
    """
    return wad_name_to_key_map.get(wad_name)


def custom_map_logic(map_number):
    """Run custom map number logic if needed.

    :param map_number: Raw map number
    :return True map number
    """
    return 'Map ' + map_number


title_re = re.compile(
    r'^Doom II:\s+(?P<wad_name>.+)\s+MAP(?P<map_number>\d{2}s?)\s+in\s+(?P<time>\d+:\d+(:\d+)?(\.\d+))?\s+(?P<category>.+)$'
)


with open('playlist_page.xml') as playlist_page_in:
    playlist_page_lines = playlist_page_in.read().splitlines()

video_updates = []
video_links = set()
for idx, line in enumerate(playlist_page_lines):
    line = line.strip()
    if line.startswith('<a id="video-title" ') and line.endswith('>'):
        line_split = line.split()
        title = playlist_page_lines[idx + 1].strip()
        video_link_txt = ''
        for elem in line_split:
            if elem.startswith('href='):
                video_link_txt = elem.split('href=')[1]

        video_link_atts = video_link_txt.split('?')[1].split('&')
        video_link_dsda = None
        for video_link_att in video_link_atts:
            att, att_value = video_link_att.split('=')
            if att == 'v':
                video_link_dsda = att_value

        title_match = title_re.match(title)
        if title_match:
            wad_name = title_match.group('wad_name')
            map_number = title_match.group('map_number')
            time = title_match.group('time')
            category = title_match.group('category')

            wad_name = custom_wad_logic(wad_name)
            if wad_name is None:
                print(title_match.group('wad_name'))
            video_updates.append(
                {'match_details': {
                    "category": custom_category_logic(category),
                    "level": custom_map_logic(map_number),
                    "wad": wad_name,
                    "player": "NiGHTS108",
                    "time": time
                },
                "video_link": video_link_dsda}
            )

            if video_link_dsda in video_links:
                print(video_link_dsda)
            video_links.add(video_link_dsda)

video_update = {'demo_updates': video_updates}

with open('playlist_page.json', 'w') as playlist_page_out:
    json.dump(video_update, playlist_page_out, indent=4, sort_keys=True)
