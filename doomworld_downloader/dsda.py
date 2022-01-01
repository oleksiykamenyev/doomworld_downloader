"""
Various utilities to parse DSDA pages
"""

import logging
import os
import requests

from urllib.parse import urlparse, urlunparse

from .upload_config import CONFIG
from .utils import get_download_filename, download_response, get_page


LOGGER = logging.getLogger(__name__)


def verify_dsda_url(url, page_types=None):
    """Verify that given DSDA URL is actually a URL for the DSDA.

    Supported page type options:
      - wad: check if it is a WAD URL (note: only default view).
      - player: check if it is a player URL (note: excluding stats view).

    :param url: URL
    :param page_types: Page types to check for
    :raises ValueError if provided URL isn't a DSDA URL of the requested type.
    :return Actual type of URL found
    """
    url_parsed = urlparse(url)
    if not url_parsed.netloc.endswith('dsdarchive.com'):
        raise ValueError(f'URL "{url}" is not a DSDA URL.')

    if page_types:
        path_split = url_parsed.path.strip('/').split('/')
        path_split_len = len(path_split)
        actual_type = 'UNKNOWN'
        if path_split_len >= 2:
            if path_split[0] == 'wads':
                if path_split_len > 2:
                    raise ValueError(f'Only WAD URLs in default view supported, got "{url}".')
                actual_type = 'wad'
            elif path_split[0] == 'players':
                if path_split_len > 2 and path_split[2] not in ['history', 'record_view']:
                    raise ValueError(f'Unsupported player URL view for URL "{url}".')
                actual_type = 'player'

        if actual_type not in page_types:
            raise ValueError(
                f'Incorrect DSDA URL {url}; wanted one of {page_types}, got {actual_type}.'
            )

        return actual_type


def fix_dsda_link(link_url):
    """Fix link on DSDA to be full URL path.

    :param link_url: DSDA link URL
    :return: Fixed DSDA link URL
    """
    if link_url.startswith('/'):
        link_url = 'https://www.dsdarchive.com' + link_url
    return link_url


def parse_dsda_cell(cell):
    """Parse single cell on DSDA page.

    Parses text out of DSDA URL, mapped to the link URL if the cell is a link.

    :param cell: DSDA cell elem
    :return: DSDA cell parsed
    """
    cell_text = cell.getText().strip()
    cell_links = cell.find_all('a')
    if cell_links:
        for cell_link in cell_links:
            if cell_link.getText().strip() != cell_text:
                continue

            # TODO: Does this actually work for video URLs on DSDA?
            link_url = fix_dsda_link(cell_link['href'])
            return {cell_text: link_url}

    # Span element info is kept track of for dubious/WR/etc. notes.
    # TODO: Need to make sure this doesn't actually include the timeline spans for categories.
    cell_spans = cell.find_all('span')
    if cell_spans is not None and cell_spans != []:
        cell_contents = []
        for span in cell_spans:
            span_title = span.get('title')
            if span_title:
                cell_contents.append(span_title)
        if cell_contents:
            if cell_text:
                cell_contents.append(cell_text)
            return cell_contents

    return cell_text


def parse_demo_page_headers(page_soup):
    """Parse headers for a demo page on DSDA.

    Empty headers are skipped. All other headers are returned with relevant info:
      - main header (player name, wad name) returned, with wad name as dictionary mapping name to
        ink
      - other headers returned and parsed accordingly

    :param page_soup: DSDA page soup
    :return: Parsed demo page headers
    """
    headers = page_soup.findAll('div', {'class': 'center-text'})
    parsed_headers = {}
    for header in headers:
        # All DSDA demo pages have a single empty header for some reason.
        header_text = header.getText().strip()
        if not header_text:
            continue

        link_elem = header.find('a')
        # WAD pages always have the primary header link somewhere, so we can assume if there's a
        # a link, it must be a WAD page, otherwise, it is a player page.
        if link_elem:
            link_url = link_elem['href']
            # WADs that are marked deprecated have this header text. Otherwise, assume any link is
            # a link to the WAD download (or page/additional files in cases that the WAD is
            # commercial).
            if header_text == 'This wad has a more recent version':
                parsed_headers['new_wad_url'] = link_url
            else:
                parsed_headers['wad_name'] = header_text
                parsed_headers['wad_url'] = link_url
        else:
            parsed_headers['player_name'] = header_text

    return parsed_headers


def dsda_demo_page_to_json(dsda_url):
    """Convert DSDA demo page to JSON.

    :param dsda_url: DSDA URL
    :return: JSON of demos from given DSDA URL
    """
    # TODO: What the fuck is this code?
    url_type = verify_dsda_url(dsda_url, page_types=['player', 'wad'])
    soup = get_page(dsda_url)
    demo_table = soup.find('table')
    table_header = demo_table.find('thead')
    header_cols = table_header.find('tr').find_all('th')
    col_names = []
    for col in header_cols:
        col_span = col.find('span')
        # Handle columns that are denoted by an icon (e.g., video icon)
        if col_span is not None:
            col_names.append(col_span['aria-label'])
        else:
            col_names.append(col.getText().strip())

    rows = demo_table.find('tbody').find_all('tr')
    demo_list = []
    multi_col_cur_values = []
    for row in rows:
        if not row.getText():
            continue

        cols = row.find_all('td')
        tag_cols = [col for col in cols if 'tag-text' in col.get('class', '')]
        if tag_cols:
            if not demo_list[-1]['Note']:
                demo_list[-1]['Note'] = []
            if not isinstance(demo_list[-1]['Note'], list):
                demo_list[-1]['Note'] = [demo_list[-1]['Note']]

            for col in tag_cols:
                demo_list[-1]['Note'].append(col.getText().strip())
            continue

        multi_cols = [col for col in cols if 'no-stripe-panel' in col.get('class', '')]
        other_cols = [col for col in cols if 'no-stripe-panel' not in col.get('class', '')]

        for idx, col in enumerate(reversed(multi_cols)):
            col_text = parse_dsda_cell(col)
            if len(multi_col_cur_values) == idx:
                multi_col_cur_values.append(col_text)
            else:
                multi_col_cur_values[idx] = col_text

        row_values = (list(reversed(multi_col_cur_values)) +
                      [parse_dsda_cell(col) for col in other_cols])
        demo_list.append(dict(zip(col_names, row_values)))

    return demo_list


def get_wad_name_from_dsda_url(dsda_url):
    """Get WAD name from DSDA URL.

    :param dsda_url: DSDA URL
    :return: WAD name from DSDA URL
    """
    # https://www.dsdarchive.com/wads/scythe:
    #   path: /wads/scythe
    return urlparse(dsda_url).path.strip('/').split('/')[1]


def download_wad_from_dsda(dsda_url, overwrite=True):
    """Download WAD from DSDA URL.

    :param dsda_url: DSDA URL
    :param overwrite: Flag indicating whether to overwrite the local path if it exists
    :return: Path to local wad download from DSDA
    :raises ValueError if a non-wad URL is provided to this function
    """
    verify_dsda_url(dsda_url, page_types=['wad'])
    soup = get_page(dsda_url)
    wad_url = parse_demo_page_headers(soup).get('wad_url')
    if not wad_url or not wad_url.startswith('/files'):
        LOGGER.info('No link available for page: %s.', dsda_url)
        LOGGER.info('This should only happen if this is a commercial product.')
        return

    wad_url = fix_dsda_link(wad_url)
    response = requests.get(wad_url)
    default_filename = urlparse(wad_url).path.strip('/').split('/')[-1]
    download_filename = get_download_filename(response, default_filename=default_filename)
    wad_name = get_wad_name_from_dsda_url(dsda_url)
    download_dir = os.path.join(CONFIG.wad_download_directory, wad_name)
    download_response(response, download_dir, download_filename, overwrite=overwrite)
    return os.path.join(download_dir, download_filename)


def conform_dsda_wad_url(dsda_wad_url):
    """Conform DSDA WAD URL.

    Limit path to first two parts (up to the WAD name) and remove any query/fragment/etc. Assume
    that the URL is already conformed to include a scheme, so the urllib parse library parses it
    correctly.

    :param dsda_wad_url: DSAD WAD URL
    :return: Conformed DSDA WAD URL
    """
    parsed_url = urlparse(dsda_wad_url)
    # Do not strip URL because it will be prepended with "/" and we need to retain that, so we go
    # to the 3rd element even though the wad name is second.
    parsed_url = parsed_url._replace(path='/'.join(parsed_url.path.split('/')[:3]))
    parsed_url = parsed_url._replace(params='')._replace(query='')._replace(fragment='')
    return urlunparse(parsed_url)
