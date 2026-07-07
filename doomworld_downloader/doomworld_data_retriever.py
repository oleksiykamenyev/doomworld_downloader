"""
Doomworld data retriever.

This contains all of the functionality needed to download demos from Doomworld.
"""

import contextlib
import itertools
import logging
import os
import re
import shutil
import uuid
import zipfile

from dataclasses import dataclass, field
from datetime import datetime
from glob import glob
from urllib.parse import urlparse, parse_qs, unquote

import gdown
import py7zr
import rarfile
import requests
import yaml

from doomworld_downloader.upload_config import CONFIG, PLAYER_IGNORE_LIST, THREAD_MAP_KEYED_ON_ID, \
    AD_HOC_UPLOAD_CONFIG
from doomworld_downloader.utils import download_file_from_doomworld, get_page, strip_accents, create_download_path, \
    download_from_dropbox


DOOM_SPEED_DEMOS_URL = 'https://www.doomworld.com/forum/37-doom-speed-demos/?page={num}'
THREAD_URL_FMT = '{base_url}/?page={num}'
POST_URL_FMT = 'https://www.doomworld.com/forum/post/{post_id}'
DOOMWORLD_URL_FMT = 'https://www.doomworld.com/{}'
ATTACH_URL_RE = re.compile(
    r'^(https:)?//www\.doomworld\.com/applications/core/interface/file/attachment\.php\?id=\d+$'
)
KEEP_CHARS = ['_', ' ', '.', '-']
CONTENT_FILE = 'post_content.txt'
METADATA_FILE = 'demo_downloader_meta.yaml'
RAR_7Z_RE = re.compile(r'^.*\.(rar|7z)$', re.IGNORECASE)
ZIP_RE = re.compile(r'^.*\.zip$', re.IGNORECASE)
POST_CACHE_DIR = 'post_cache'
POST_INFO_FILENAME = 'post_info.yaml'
FAILED_POST_DIR = 'failed_posts'

LOGGER = logging.getLogger(__name__)


@dataclass
class Thread:
    """Thread data class."""
    name: str
    id: int
    url: str
    last_post_date: datetime or None
    last_page_num: int or None


@dataclass
class Post:
    """Post data class."""
    id: int
    author_name: str
    author_id: int
    post_date: datetime
    attachments: dict
    links: dict
    embeds: list
    post_text: str
    post_url: str
    parent: Thread

    cached_downloads: list = field(default_factory=list)


def get_links(link_elems, extract_link=False):
    """Get links as text from a set of link elements.

    :param link_elems: Link elements list
    :param extract_link: Flag indicating whether to extract the link (i.e., take the text with the
                         link out of the element.
    :return: List of links as text
    """
    links = {}
    for link_elem in link_elems:
        link_url = link_elem['href']
        # The attachment links on Doomworld do not have the protocol info, adding it manually.
        # Running this for all the links and not just attachments seems safer just in case the link
        # coding changes on the Doomworld side.
        if not link_url.startswith('http'):
            link_url = 'https:' + link_url
        # Key on URL so that links with the same text can be kept track of.
        link_text = link_elem.getText().strip()

        # Generate a UUID object
        unique_id = uuid.uuid4()

        # Convert the UUID to a 32-character string and remove hyphens
        unique_string = str(unique_id).replace('-', '')

        # A silly way to detect filenames in URLs, just so we have a default name for the download.
        # For Doomworld links and Google Drive links, use a random string instead, this should never really be used.
        if 'drive.google.com' in link_url or ('doomworld' in link_url and 'attachment' in link_url):
            link_filename = unique_string
        else:
            link_path = urlparse(link_url).path
            link_filename = os.path.basename(os.path.normpath(link_path))

        if link_text:
            link_name = link_text
        elif '.' in link_filename:
            link_name = link_filename
        else:
            link_name = ''

        links[link_url] = link_name
        if extract_link:
            link_elem.extract()
    return links


def parse_thread_list(page_number):
    """Parse thread list at given page number.

    :param page_number: Page number to get
    :return: List of all threads at the page
    """
    soup = get_page(DOOM_SPEED_DEMOS_URL.format(num=page_number))
    if 'Just a moment...' in soup.getText():
        raise RuntimeError('Reaached CloudFlare redirect, cannot get threads.')

    thread_elems = soup.find_all('li', class_='ipsDataItem')
    threads = []
    for thread in thread_elems:
        # ID will be null for the subforum at the top of the page.
        id = thread.get('data-rowid')
        if not id:
            LOGGER.debug('Ignoring thread with null ID.')
            continue

        if id in THREAD_MAP_KEYED_ON_ID:
            if THREAD_MAP_KEYED_ON_ID[id].get('additional_info', {}).get('ignore', False):
                LOGGER.debug('Ignoring thread with ID %s due to ignore list.', id)
                continue

        title = thread.find(class_='ipsDataItem_title')
        title_link = title.find_all('a')[0]
        pagination = title.find(class_='ipsPagination')
        if pagination is not None:
            last_page_num = int(pagination.getText().strip().split()[-1])
        else:
            last_page_num = 1

        last_poster = thread.find(class_='ipsDataItem_lastPoster')
        last_post_date = last_poster.find('time')['datetime']
        last_post_date = datetime.strptime(last_post_date, '%Y-%m-%dT%H:%M:%SZ')
        threads.append(Thread(title_link.getText().strip(), int(id), title_link['href'],
                              last_post_date, last_page_num))

    return threads


def cache_post(post):
    """Cache given post to local file system.

    Specifically, this will cache all of the info within the post, not the attachments of the post,
    which are cached separately. This is done so if the downloader is rerun for the same time
    period, it doesn't have to look through all of the relevant threads and posts again, since that
    can be very slow.

    :param post: Post data class
    """
    post_cache_dir = os.path.join(CONFIG.demo_download_directory, POST_CACHE_DIR, str(post.id))
    os.makedirs(post_cache_dir, exist_ok=True)
    post_cache_file = os.path.join(post_cache_dir, POST_INFO_FILENAME)
    # The post dictionary is recreated so we do not modify the class dict of the actual post object
    post_dict = {key: value for key, value in post.__dict__.items()}
    post_dict['parent'] = post.parent.__dict__
    with open(post_cache_file, 'w', encoding='utf-8') as post_info_stream:
        yaml.dump(post_dict, post_info_stream)


def get_thread_base_url(thread_url):
    """Get thread base URL.

    :param thread_url: Thread URL.
    :return: Base URL for thread.
    """
    return DOOMWORLD_URL_FMT.format(urlparse(thread_url.rstrip('/')).path.strip('/'))


def parse_thread_page(thread_url, thread=None):
    """Parse specific thread page.

    If the thread object is not provided, it will be created during this function.

    :param thread_url: Thread URL
    :param thread: Thread object, if available
    :return: All posts on specific thread page
    """
    soup = get_page(thread_url)
    post_elems = soup.find_all('article', class_='ipsComment')
    if not thread:
        thread_title_elem = soup.find('h1', class_='ipsType_pageTitle')
        # Sample thread URL: https://www.doomworld.com/forum/topic/70300-sample-3/?page=68
        #   base: https://www.doomworld.com/forum/topic/70300-sample-3
        #   ID: 70300
        thread_base_url = get_thread_base_url(requests.get(thread_url).url)
        thread_id = thread_base_url.split('/')[-1].split('-')[0]
        # We don't need the last post date or page number since this case is for ad-hoc thread/post
        # downloads
        thread = Thread(thread_title_elem.getText().strip(), int(thread_id), thread_base_url,
                        last_post_date=None, last_page_num=None)

    posts = []
    for post in post_elems:
        post_content_elem = post.find('div', class_='cPost_contentWrap')
        post_content_elem = post_content_elem.find('div', attrs={'data-role': 'commentContent'})
        # Remove all quotes from each post so we don't accidentally parse a different post's
        # category/other info and don't accidentally get attachments from a different post.
        quotes = post_content_elem.find_all('blockquote', class_='ipsQuote')
        for quote in quotes:
            quote.extract()

        attachment_links = [
            link for link in post_content_elem.find_all('a')
            if ('ipsAttachLink' in link.get('class', []) or ATTACH_URL_RE.match(link.get('href', '')) or
                'doomshack.org/uploads' in link.get('href', '') or 'drive.google.com' in link.get('href', '') or
                'dropbox.com' in link.get('href', ''))
        ]
        attachments = get_links(attachment_links, extract_link=True)
        post_id = post['id'].split('_')[1]
        # Skip posts with no attachments as they have no demos to search for
        if not attachments:
            LOGGER.debug('Skip post with no attachments with ID %s.', post_id)
            continue

        post_url = POST_URL_FMT.format(post_id=post_id)

        links = get_links(post_content_elem.find_all('a'), extract_link=True)

        embeds = post_content_elem.find_all('iframe')
        embeds = [embed['src'] for embed in embeds]

        author_elem = post.find('aside', class_='ipsComment_author')
        author_name = author_elem.find('h3', class_='cAuthorPane_author').getText().strip()
        # URL format: https://www.doomworld.com/profile/{id}-{author_name}/
        author_id = int(author_elem.find('a')['href'].rstrip('/').rsplit('/', 1)[-1].split('-')[0])
        if author_id in PLAYER_IGNORE_LIST:
            LOGGER.debug('Skip post %s from ignored author %s.', post_id, author_id)
            continue

        post_text_elem = post.find('div', class_='ipsColumn')
        post_meta_elem = post_text_elem.find('div', class_='ipsComment_meta')
        post_date = post_meta_elem.find('time')['datetime']
        post_date = datetime.strptime(post_date, '%Y-%m-%dT%H:%M:%SZ')

        post_text = post_content_elem.getText().strip()
        post_text = '\n'.join([line.strip() for line in post_text.splitlines() if line.strip()])

        posts.append(Post(int(post_id), author_name, author_id, post_date, attachments, links,
                          embeds, post_text, post_url, thread))

    return posts


def parse_ad_hoc_post(post):
    """Get post ID and URL From post in ad-hoc config.

    :param post: Post ID or full post URL
    :return: Post ID, post URL as a tuple
    """
    try:
        post_id = int(post)
    except ValueError:
        post_url = post
        post_id = int(urlparse(post).path.strip('/').split('/')[-1])
    else:
        post_url = POST_URL_FMT.format(post)

    return post_id, post_url


def get_ad_hoc_posts():
    """Get ad-hoc posts.

    :return: Ad-hoc post list
    """
    ad_hoc_posts = []
    for post in AD_HOC_UPLOAD_CONFIG.get('posts', []):
        post_id, post_url = parse_ad_hoc_post(post)

        cur_posts = parse_thread_page(post_url, thread=None)
        ad_hoc_posts.extend([post for post in cur_posts if post.id == post_id])

    for thread in AD_HOC_UPLOAD_CONFIG.get('threads', []):
        if isinstance(thread, dict):
            # Just take the first element, since we expect this to be a single key/value dict
            thread_base_url, thread_map = list(thread.items())[0]
        else:
            thread_base_url = thread
            thread_map = {}

        thread_base_url = thread_base_url.rstrip('/')
        pages_to_get = thread_map.get('pages', [])
        if not pages_to_get:
            # If we want to get the entire thread, we need to detect how many pages to iterate.
            #
            # Note that while Doomworld appears to update page numbers beyond the last page to the last page in the URL
            # in a browser, this isn't an actual redirect and must be done through JavaScript. As a result, it is tricky
            # to detect that programmatically, so we need to have logic for checking how many pages there are.
            soup = get_page(thread_base_url)
            thread_elems = soup.find_all('a', attrs={'data-page':True})
            if thread_elems:
                last_page_num = max([int(elem.get('data-page')) for elem in thread_elems])
            else:
                last_page_num = 1

            pages_to_get = [1, last_page_num]
        else:
            pages_to_get = iter(pages_to_get)

        posts_to_get = [parse_ad_hoc_post(post)[0] for post in thread_map.get('posts', [])]
        for page_num in pages_to_get:
            thread_url = THREAD_URL_FMT.format(base_url=thread_base_url, num=page_num)

            cur_posts = parse_thread_page(thread_url, thread=None)
            if posts_to_get:
                for post_to_get in posts_to_get:
                    for cur_post in cur_posts:
                        if cur_post.id == post_to_get:
                            ad_hoc_posts.append(cur_post)
            else:
                ad_hoc_posts.extend(cur_posts)

    LOGGER.debug(ad_hoc_posts)
    for post in ad_hoc_posts:
        cache_post(post)
    return ad_hoc_posts


def get_new_posts(search_start_date, search_end_date, new_threads):
    """Get new posts from all new threads.

    :param search_end_date: Search end datetime
    :param search_start_date: Search start datetime
    :param new_threads: New thread list
    :return: New post list
    """
    posts = []
    for thread in new_threads:
        for page_num in range(thread.last_page_num, 0, -1):
            cur_posts = parse_thread_page(
                THREAD_URL_FMT.format(base_url=thread.url.rstrip('/'), num=page_num),
                thread
            )
            # If the last post on a page is before the start date, we can break out immediately
            # since we are going backwards in time from the last page.
            if cur_posts and cur_posts[-1].post_date < search_start_date:
                break

            new_posts = [post for post in cur_posts
                         if search_start_date < post.post_date < search_end_date]
            posts.extend(new_posts)

    LOGGER.debug(posts)
    for post in posts:
        cache_post(post)
    return posts


def get_new_threads(search_start_date):
    """Get new threads.

    :param search_start_date: Search start date
    :return: New threads
    """
    threads = []
    for page_num in itertools.count(1):
        cur_threads = parse_thread_list(page_num)
        new_threads = [thread for thread in cur_threads
                       if thread.last_post_date > search_start_date]
        # If no new threads are found, break out of the loop.
        if not new_threads:
            break

        threads.extend(new_threads)

    LOGGER.debug(threads)
    return threads


def update_cache(post, downloads):
    """Update cache for post.

    Add attachments to local post cache after they are downloaded.

    :param post: Post to update cache for
    :param downloads: Downloads for the post
    """
    post_cache_file = os.path.join(CONFIG.demo_download_directory, POST_CACHE_DIR, str(post.id),
                                   POST_INFO_FILENAME)
    with open(post_cache_file, encoding='utf-8') as post_info_stream:
        post_dict = yaml.safe_load(post_info_stream)

    post_dict['cached_downloads'] = downloads
    with open(post_cache_file, 'w', encoding='utf-8') as post_info_stream:
        yaml.dump(post_dict, post_info_stream)


def download_attachments(post):
    """Download attachments for post.

    :param post: Post to download attachments for
    :return: Download locations on local filesystem
    """
    # Sanitize author name so that it can be used to create a local directory
    author_dir = os.path.join(
        CONFIG.demo_download_directory,
        '{}'.format(''.join(c for c in post.author_name if c.isalnum() or c in KEEP_CHARS))
    )
    author_dir = strip_accents(author_dir)
    downloads = {}
    for attach_url, attach_name in post.attachments.items():
        parsed_url = urlparse(attach_url)
        attach_id = parse_qs(parsed_url.query, keep_blank_values=True).get('id')
        attach_id = attach_id[0] if attach_id else str(uuid.uuid4())
        attach_dir = os.path.join(author_dir, attach_id)

        if 'drive.google.com' in attach_url:
            # For Google Drive, gdown doesn't support just getting a filename. Need to download first, then we have the
            # filename...
            os.makedirs(attach_dir, exist_ok=True)
            with contextlib.chdir(attach_dir):
                try:
                    attach_filename = gdown.download(url=attach_url, fuzzy=True)
                except gdown.exceptions.FileURLRetrievalError:
                    LOGGER.exception('Caught exception downloading from Google Drive URL %s.', attach_url)
                    attach_filename = None
                except OSError:
                    LOGGER.exception('Caught OSError downloading from Google Drive URL %s.', attach_url)
                    LOGGER.error('This can happen when attempting to download a directory instead of a file.')
                    attach_filename = None

            if not attach_filename:
                LOGGER.error('Failed to download from Google Drive URL %s.', attach_url)
                continue

            download = os.path.join(attach_dir, attach_filename)
        elif 'dropbox.com' in attach_url:
            # For Dropbox, this should already be set to the last element in the path, which seems to always be the
            # filename.
            attach_path = urlparse(attach_url).path
            attach_filename = unquote(os.path.basename(os.path.normpath(attach_path)))
            download = create_download_path(attach_dir, attach_filename, overwrite=True)
            downloaded = download_from_dropbox(attach_url, download)
            if not downloaded:
                continue
        else:
            download = download_file_from_doomworld(attach_url, attach_dir, attach_name)

        # TODO: Consider re-packing such files to zip.
        if py7zr.is_7zfile(download):
            LOGGER.warning('7z file %s detected for post %s.', attach_name, post.post_url)
        elif rarfile.is_rarfile(download):
            LOGGER.warning('RAR file %s detected for post %s.', attach_name, post.post_url)
        if not zipfile.is_zipfile(download):
            continue

        # Additional metadata info about post saved for debugging
        meta_info = {'url': post.post_url}
        with open(os.path.join(attach_dir, METADATA_FILE), 'w') as meta_file:
            yaml.dump(meta_info, meta_file)
        content_file = os.path.join(attach_dir, CONTENT_FILE)
        with open(content_file, 'w', encoding='utf-8') as content_file:
            content_file.write(post.post_text)

        downloads[download] = {}

    update_cache(post, downloads)
    post.cached_downloads = downloads
    return downloads



def move_post_cache_to_failed(post):
    """Move specific post cache dir to failed directory.

    :param post: Post to move cache dir for
    """
    post_cache_dir = os.path.join(CONFIG.demo_download_directory, POST_CACHE_DIR, str(post.id))
    post_failed_dir = os.path.join(CONFIG.demo_download_directory, FAILED_POST_DIR)
    os.makedirs(os.path.join(CONFIG.demo_download_directory, FAILED_POST_DIR), exist_ok=True)
    shutil.move(post_cache_dir, post_failed_dir)


def get_doomworld_posts(search_end_date, search_start_date, use_cached_downloads, force_redownload=False):
    """Get Doomworld posts for download.

    :param search_start_date: Search start date
    :param search_end_date: Search end date
    :param use_cached_downloads: Flag indicating to use cached download info
    :param force_redownload: Flag indicating to force redownload anyway. Should only ever be on for testing
    :return: Doomworld post list
    """
    if use_cached_downloads:
        # Use cached stuff if available
        post_cache_dir = os.path.join(CONFIG.demo_download_directory, 'post_cache')
        post_info_files = glob(post_cache_dir + '/**/*.yaml', recursive=True)
        posts = []
        for post_info_file in post_info_files:
            with open(post_info_file, encoding='utf-8') as post_info_stream:
                post_dict = yaml.safe_load(post_info_stream)
            post_dict['parent'] = Thread(**post_dict['parent'])
            post_obj = Post(**post_dict)
            if force_redownload:
                download_attachments(post_obj)

            posts.append(post_obj)
    else:
        if CONFIG.upload_type == 'date-based':
            threads = get_new_threads(search_start_date)
            posts = get_new_posts(search_start_date, search_end_date, threads)
        else:
            posts = get_ad_hoc_posts()

        for post in posts:
            download_attachments(post)
    return posts
