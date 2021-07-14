"""
Doomworld data retriever.

This contains all of the functionality needed to download demos from Doomworld.
"""
# TODO: Perhaps the retriever should be a class?

import itertools
import logging
import os
import re
import shutil

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import requests
import yaml

from doomworld_downloader.upload_config import CONFIG, PLAYER_IGNORE_LIST, THREAD_MAP_KEYED_ON_ID
from doomworld_downloader.utils import get_download_filename, download_response, get_page


DOOM_SPEED_DEMOS_URL = 'https://www.doomworld.com/forum/37-doom-speed-demos/?page={num}'
THREAD_URL = '{base_url}/?page={num}'
POST_URL = 'https://www.doomworld.com/forum/post/{post_id}'
ATTACH_URL_RE = re.compile(
    r'^(https:)?//www.doomworld.com/applications/core/interface/file/attachment.php?id=\d+$'
)
KEEP_CHARS = ['_', ' ', '.', '-']
CONTENT_FILE = 'post_content.txt'
METADATA_FILE = 'demo_downloader_meta.yaml'
ZIP_RE = re.compile(r'^.*\.zip$')
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
    last_post_date: datetime
    last_page_num: int


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
        links[link_elem.getText().strip()] = link_url
        if extract_link:
            link_elem.extract()
    return links


def parse_thread_list(page_number):
    """Parse thread list at given page number.

    :param page_number: Page number to get
    :return: List of all threads at the page
    """
    soup = get_page(DOOM_SPEED_DEMOS_URL.format(num=page_number))
    thread_elems = soup.find_all('li', class_='ipsDataItem')
    threads = []
    for thread in thread_elems:
        id = thread['data-rowid']
        if id in THREAD_MAP_KEYED_ON_ID:
            if THREAD_MAP_KEYED_ON_ID[id].get('additional_info', {}).get('ignore', False):
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


def parse_thread_page(base_url, page_number, thread):
    """Parse specific thread page.

    :param base_url: Base thread URL
    :param page_number: Page number
    :param thread: Thread object
    :return: All posts on specific thread page
    """
    soup = get_page(THREAD_URL.format(base_url=base_url, num=page_number))
    post_elems = soup.find_all('article', class_='ipsComment')
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
            if 'ipsAttachLink' in link.get('class', []) or ATTACH_URL_RE.match(link['href'])
        ]
        attachments = get_links(attachment_links, extract_link=True)
        # TODO: Consider repackaging rars and 7zs so we don't have to ask the posters to do it
        attachments = {attach: attach_url for attach, attach_url in attachments.items()}
        # Skip posts with no attachments as they have no demos to search for
        if not attachments:
            continue

        post_id = post['id'].split('_')[1]
        post_url = POST_URL.format(post_id=post_id)

        # TODO: We may not want to extract_link here because that removes the links, so it might be
        # harder to infer which wad maps to which demos from a multi-wad multi-demo post
        links = get_links(post_content_elem.find_all('a'), extract_link=True)

        embeds = post_content_elem.find_all('iframe')
        embeds = [embed['src'] for embed in embeds]

        author_elem = post.find('aside', class_='ipsComment_author')
        author_name = author_elem.find('h3', class_='cAuthorPane_author').getText().strip()
        # URL format: https://www.doomworld.com/profile/{id}-{author_name}/
        author_id = int(author_elem.find('a')['href'].rstrip('/').rsplit('/', 1)[-1].split('-')[0])
        if author_id in PLAYER_IGNORE_LIST:
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


def get_new_posts(search_start_date, search_end_date, testing_mode, new_threads):
    """Get new posts from all new threads.

    :param search_end_date: Search end datetime
    :param search_start_date: Search start datetime
    :param testing_mode: Flag indicating that testing mode is on
    :param new_threads: New thread list
    :return: New post list
    """
    posts = []
    for thread in new_threads:
        # In case of testing, use dummy data
        if testing_mode:
            break
        for page_num in range(thread.last_page_num, 0, -1):
            cur_posts = parse_thread_page(thread.url, page_num, thread)
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


def get_new_threads(search_start_date, testing_mode):
    """Get new threads.

    :param search_start_date: Search start date
    :param testing_mode: Flag indicating that testing mode is on
    :return: New threads
    """
    threads = []
    for page_num in itertools.count(1):
        # In case of testing, use dummy data
        if testing_mode:
            break
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
    :raises RuntimeError if the attachment filename for a given post cannot be determined
    """
    if post.cached_downloads:
        return post.cached_downloads

    # Sanitize author name so that it can be used to create a local directory
    author_dir = os.path.join(
        CONFIG.demo_download_directory,
        '{}'.format(''.join(c for c in post.author_name if c.isalnum() or c in KEEP_CHARS))
    )
    downloads = []
    for attach_name, attach_url in post.attachments.items():
        response = requests.get(attach_url)
        try:
            attach_filename = get_download_filename(response, default_filename=attach_name)
        except RuntimeError:
            LOGGER.error('Could not get attachment filename for attachment name %s, URL %s.',
                         attach_name, attach_url)
            raise
        if not ZIP_RE.match(attach_filename):
            continue

        parsed_url = urlparse(attach_url)
        attach_id = parse_qs(parsed_url.query, keep_blank_values=True)['id']
        attach_dir = os.path.join(author_dir, attach_id[0])
        download = download_response(response, attach_dir, attach_filename)

        # Additional metadata info about post saved for debugging
        meta_info = {'url': post.post_url}
        with open(os.path.join(attach_dir, METADATA_FILE), 'w') as meta_file:
            yaml.dump(meta_info, meta_file)
        content_file = os.path.join(attach_dir, CONTENT_FILE)
        with open(content_file, 'w', encoding='utf-8') as content_file:
            content_file.write(post.post_text)

        downloads.append(download)

    update_cache(post, downloads)
    return downloads

def move_post_cache_to_failed(post):
    """Move specific post cache dir to failed directory.

    :param post: Post to move cache dir for
    """
    post_cache_dir = os.path.join(CONFIG.demo_download_directory, POST_CACHE_DIR, str(post.id))
    shutil.move(post_cache_dir, FAILED_POST_DIR)
