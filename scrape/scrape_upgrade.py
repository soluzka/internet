import os
import re
import json
import base64
import random
import asyncio
import logging
import tempfile
import threading
import aiohttp
import requests
import html2text
import yt_dlp
from bs4 import BeautifulSoup
from datetime import datetime
from urllib.parse import urljoin, quote, urlparse, parse_qs, unquote

# Locate ffmpeg binary for yt-dlp merging
try:
    import imageio_ffmpeg
    FFMPEG_PATH = os.path.dirname(imageio_ffmpeg.get_ffmpeg_exe())
except Exception:
    FFMPEG_PATH = 'ffmpeg'
from typing import List, Dict, Any
from flask import send_file, jsonify, request
from flask_socketio import emit


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Supported content URL patterns (videos + social/website links)
SUPPORTED_VIDEO_PATTERNS = [
    # YouTube
    r'https?://(?:www\.)?youtube\.com/watch\?v=[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?youtu\.be/[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?youtube\.com/embed/[a-zA-Z0-9_-]{11}',
    r'https?://(?:www\.)?youtube\.com/shorts/[a-zA-Z0-9_-]{11}',
    # TikTok
    r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/video/\d+',
    r'https?://vm\.tiktok\.com/[a-zA-Z0-9]+',
    r'https?://(?:www\.)?tiktok\.com/@[\w.-]+/live',
    # Dailymotion
    r'https?://(?:www\.)?dailymotion\.com/video/[a-zA-Z0-9]+',
    r'https?://dai\.ly/[a-zA-Z0-9]+',
    # Vimeo
    r'https?://(?:www\.)?vimeo\.com/\d+',
    # Instagram
    r'https?://(?:www\.)?instagram\.com/(?:reel|p)/[a-zA-Z0-9_-]+',
    r'https?://(?:www\.)?instagram\.com/(?:stories|tv)/[a-zA-Z0-9_-]+',
    # Twitter/X
    r'https?://(?:www\.)?(?:twitter|x)\.com/\w+/status/\d+',
    # Facebook
    r'https?://(?:www\.)?facebook\.com/(?:watch\?v=|reel/|video\.php\?v=)\d+',
    r'https?://(?:www\.)?facebook\.com/[\w.]+/videos/\d+',
    r'https?://fb\.watch/[a-zA-Z0-9]+',
    # Twitch
    r'https?://(?:www\.)?twitch\.tv/\w+/clip/[a-zA-Z0-9_-]+',
    r'https?://(?:www\.)?twitch\.tv/videos/\d+',
    # Reddit
    r'https?://(?:www\.)?reddit\.com/r/\w+/comments/[a-zA-Z0-9]+',
    r'https?://(?:www\.)?redd\.it/[a-zA-Z0-9]+',
    # Streamable
    r'https?://(?:www\.)?streamable\.com/[a-zA-Z0-9]+',
    # Bilibili
    r'https?://(?:www\.)?bilibili\.com/video/[a-zA-Z0-9]+',
    # Rumble
    r'https?://(?:www\.)?rumble\.com/v[a-zA-Z0-9_-]+',
    r'https?://(?:www\.)?rumble\.com/embed/[a-zA-Z0-9_-]+',
    # Odysee
    r'https?://(?:www\.)?odysee\.com/@[\w.-]+:[\w]+/[\w-]+:[\w]+',
    r'https?://(?:www\.)?odysee\.com/[\w$:.+-]+:[\w]+',
    # VK
    r'https?://(?:www\.)?vk\.com/video-\d+_\d+',
    r'https?://(?:www\.)?vkvideo\.ru/video-\d+_\d+',
    # Imgur
    r'https?://(?:www\.)?imgur\.com/(?:gallery|a)/[a-zA-Z0-9]+',
    r'https?://i\.imgur\.com/[a-zA-Z0-9]+\.\w+',
    # SoundCloud
    r'https?://(?:www\.)?soundcloud\.com/[\w-]+/[\w-]+',
    # Bandcamp
    r'https?://[\w-]+\.bandcamp\.com/(?:track|album)/[\w-]+',
    # Flickr
    r'https?://(?:www\.)?flickr\.com/photos/[\w-]+/\d+',
    # Getty / Unsplash (images/video)
    r'https?://(?:www\.)?gettyimages\.com/detail/(?:photo|video)/[\w-]+',
    r'https?://(?:www\.)?unsplash\.com/photos/[\w-]+',
    # Pinterest
    r'https?://(?:www\.)?pinterest\.[a-z]+/pin/\d+',
    r'https?://pin\.it/[a-zA-Z0-9]+',
    # Tumblr
    r'https?://[\w-]+\.tumblr\.com/post/\d+',
    r'https?://(?:www\.)?tumblr\.com/[\w-]+/\d+',
    # LinkedIn
    r'https?://(?:www\.)?linkedin\.com/posts/[\w-]+',
    r'https?://(?:www\.)?linkedin\.com/feed/update/urn:li:activity:\d+',
    # Snapchat
    r'https?://(?:www\.)?snapchat\.com/discover/[\w-]+/\d+',
    r'https?://(?:www\.)?snapchat\.com/p/[a-zA-Z0-9]+',
    # Threads
    r'https?://(?:www\.)?threads\.net/t/[a-zA-Z0-9_-]+',
    # Bluesky
    r'https?://(?:www\.)?bsky\.app/profile/[\w.-]+/post/[a-zA-Z0-9]+',
    # Mastodon
    r'https?://[\w.-]+/@\w+/\d+',
    # Medium
    r'https?://(?:www\.)?medium\.com/@[\w.-]+/[\w-]+',
    r'https?://[\w-]+\.medium\.com/[\w-]+',
    # Quora
    r'https?://(?:www\.)?quora\.com/[\w-]+',
    # Spotify
    r'https?://(?:open\.)?spotify\.com/(?:track|album|playlist|episode)/[a-zA-Z0-9]+',
]

# Map domain substrings to display names
PLATFORM_NAMES = [
    ('youtube.com', 'YouTube'), ('youtu.be', 'YouTube'),
    ('tiktok.com', 'TikTok'), ('vm.tiktok.com', 'TikTok'),
    ('dailymotion.com', 'Dailymotion'), ('dai.ly', 'Dailymotion'),
    ('vimeo.com', 'Vimeo'),
    ('instagram.com', 'Instagram'),
    ('twitter.com', 'Twitter'), ('x.com', 'Twitter'), ('mobile.twitter.com', 'Twitter'),
    ('facebook.com', 'Facebook'), ('fb.watch', 'Facebook'),
    ('twitch.tv', 'Twitch'),
    ('reddit.com', 'Reddit'), ('redd.it', 'Reddit'),
    ('streamable.com', 'Streamable'),
    ('bilibili.com', 'Bilibili'),
    ('rumble.com', 'Rumble'),
    ('odysee.com', 'Odysee'),
    ('vk.com', 'VK'), ('vkvideo.ru', 'VK'),
    ('imgur.com', 'Imgur'),
    ('soundcloud.com', 'SoundCloud'),
    ('bandcamp.com', 'Bandcamp'),
    ('flickr.com', 'Flickr'),
    ('gettyimages.com', 'Getty Images'),
    ('unsplash.com', 'Unsplash'),
    ('pinterest.com', 'Pinterest'), ('pin.it', 'Pinterest'),
    ('tumblr.com', 'Tumblr'),
    ('linkedin.com', 'LinkedIn'),
    ('snapchat.com', 'Snapchat'),
    ('threads.net', 'Threads'),
    ('bsky.app', 'Bluesky'),
    ('mastodon.social', 'Mastodon'),
    ('medium.com', 'Medium'),
    ('quora.com', 'Quora'),
    ('spotify.com', 'Spotify'), ('open.spotify.com', 'Spotify'),
]


def extract_real_video_url(html_text):
    """Extract a real, downloadable video URL from HTML text (e.g. Bing element HTML)."""
    for pattern in SUPPORTED_VIDEO_PATTERNS:
        match = re.search(pattern, html_text)
        if match:
            return match.group(0)
    return None


def detect_source_platform(url):
    """Detect the platform name from a URL."""
    if not url:
        return 'Unknown'
    url_lower = url.lower()
    for domain, name in PLATFORM_NAMES:
        if domain in url_lower:
            return name
    if 'bing.com' in url_lower or 'bing.co.uk' in url_lower:
        return 'Bing'
    return 'Unknown'


def is_video_url(url):
    """Return True if the URL points to a known video/audio host."""
    if not url:
        return False
    video_hosts = {
        'youtube.com', 'youtu.be', 'm.youtube.com',
        'tiktok.com', 'vm.tiktok.com',
        'dailymotion.com', 'dai.ly',
        'vimeo.com',
        'instagram.com',
        'twitter.com', 'x.com', 'mobile.twitter.com',
        'facebook.com', 'fb.watch',
        'twitch.tv',
        'reddit.com', 'redd.it',
        'streamable.com',
        'bilibili.com',
        'rumble.com',
        'odysee.com',
        'vk.com', 'vkvideo.ru',
        'imgur.com',
        'soundcloud.com',
        'bandcamp.com',
        'spotify.com', 'open.spotify.com',
    }
    netloc = urlparse(url).netloc.lower()
    return any(host in netloc for host in video_hosts)


def decode_bing_redirect(url):
    """Unwrap a Bing click-tracking URL to get the real destination."""
    try:
        parsed = urlparse(url)
        if 'bing.com' not in parsed.netloc.lower():
            return url
        qs = parse_qs(parsed.query)
        u = qs.get('u', [''])[0]
        if u:
            if u.startswith('a1'):
                u = u[2:]
            decoded = base64.urlsafe_b64decode(u + '==').decode('utf-8', errors='ignore')
            if decoded.startswith('http'):
                return decoded
    except Exception as e:
        logger.debug(f'Could not decode Bing redirect: {e}')
    return url


def decode_duckduckgo_redirect(url):
    """Unwrap a DuckDuckGo redirect URL to get the real destination."""
    try:
        parsed = urlparse(url)
        if 'duckduckgo.com' not in parsed.netloc.lower():
            return url
        qs = parse_qs(parsed.query)
        uddg = qs.get('uddg', [''])[0]
        if uddg:
            return unquote(uddg)
    except Exception as e:
        logger.debug(f'Could not decode DuckDuckGo redirect: {e}')
    return url


def favicon_url(url):
    """Return a favicon URL for a given page using Google's favicon service."""
    try:
        domain = urlparse(url).netloc
        if domain:
            return f'https://www.google.com/s2/favicons?domain={domain}&sz=128'
    except Exception:
        pass
    return ''


class VideoSearchCrawler:
    def __init__(self, topic: str):
        self.main_topic = topic
        self.search_results = []
        self.seen_links = set()

        self.html_converter = html2text.HTML2Text()
        self.html_converter.ignore_links = False

        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0',
        }

    async def collect_results(self):
        """Collect video and web results from multiple sources"""
        try:
            logger.info(f'Starting search for: {self.main_topic}')

            tasks = [
                self._search_youtube(self.main_topic),
                self._search_youtube_mobile(self.main_topic),
                self._search_bing_videos(self.main_topic),
                self._search_bing_videos_uk(self.main_topic),
                self._search_bing_web(self.main_topic),
                self._search_bing_web_uk(self.main_topic),
            ]

            results = await asyncio.gather(*tasks)

            seen = set()
            all_results = []
            for engine_results in results:
                if not engine_results:
                    continue
                platform = engine_results[0].get('platform', 'Unknown') if engine_results else 'Unknown'
                logger.info(f'Found {len(engine_results)} results from {platform}')
                for result in engine_results:
                    url = result.get('url', '')
                    if not url or url in seen:
                        continue
                    seen.add(url)
                    all_results.append(result)

            random.shuffle(all_results)
            return all_results
        except Exception as e:
            logger.error(f'Error in collect_results: {str(e)}')
            raise

    async def _search_youtube(self, query: str) -> List[Dict]:
        """Search for videos on YouTube."""
        results = []
        try:
            sort_params = ['', '&sp=CAI%253D', '&sp=CAM%253D']
            for sort_param in sort_params:
                if len(results) >= 75:
                    break

                search_url = f'https://www.youtube.com/results?search_query={quote(query)}{sort_param}'

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()

                            video_ids = re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)
                            video_titles = re.findall(r'"title":{"runs":\[{"text":"([^"]+)"}]}', html)
                            video_durations = re.findall(r'"simpleText":"([0-9:]+)"', html)
                            video_views = re.findall(r'"viewCountText":{"simpleText":"([^"]+)"}', html)

                            seen_ids = set()
                            for i, video_id in enumerate(video_ids):
                                if video_id in seen_ids or len(results) >= 75:
                                    continue

                                seen_ids.add(video_id)
                                title = video_titles[i] if i < len(video_titles) else 'Untitled Video'
                                duration = video_durations[i] if i < len(video_durations) else 'Unknown'
                                views = video_views[i] if i < len(video_views) else 'Unknown views'

                                video_url = f'https://www.youtube.com/watch?v={video_id}'
                                thumbnail_url = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'

                                results.append({
                                    'title': title,
                                    'url': video_url,
                                    'thumbnail': thumbnail_url,
                                    'duration': duration,
                                    'views': views,
                                    'platform': 'YouTube',
                                    'description': f'Watch this video on YouTube: {title}',
                                    'source': 'YouTube',
                                })
        except Exception as e:
            logger.error(f'Error searching YouTube: {str(e)}')

        return results[:75]

    async def _search_youtube_mobile(self, query: str) -> List[Dict]:
        """Search for videos on YouTube mobile site"""
        results = []
        try:
            for page in range(1, 4):
                if len(results) >= 75:
                    break

                search_url = f'https://m.youtube.com/results?search_query={quote(query)}&page={page}'
                logger.info(f'Searching YouTube Mobile page {page}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            video_elements = soup.find_all('div', class_='compact-media-item')
                            logger.info(f'Found {len(video_elements)} video elements on YouTube Mobile page {page}')

                            for element in video_elements:
                                try:
                                    if len(results) >= 75:
                                        break

                                    link = element.find('a', href=True)
                                    if not link:
                                        continue

                                    href = link.get('href', '')
                                    if not href or '/watch?v=' not in href:
                                        continue

                                    video_id = href.split('watch?v=')[-1].split('&')[0]
                                    if not video_id:
                                        continue

                                    title_elem = element.find(['h4', 'h3', 'span'], class_='compact-media-item-headline')
                                    title = title_elem.text.strip() if title_elem else ''
                                    if not title:
                                        continue

                                    thumbnail = f'https://i.ytimg.com/vi/{video_id}/hqdefault.jpg'

                                    duration = 'Unknown'
                                    duration_elem = element.find('span', class_='compact-media-item-metadata')
                                    if duration_elem:
                                        duration = duration_elem.text.strip()

                                    results.append({
                                        'title': title,
                                        'url': f'https://www.youtube.com/watch?v={video_id}',
                                        'thumbnail': thumbnail,
                                        'duration': duration,
                                        'platform': 'YouTube Mobile',
                                        'description': title,
                                        'source': 'YouTube',
                                    })
                                    logger.debug(f'Added YouTube Mobile result: {title}')
                                except Exception as e:
                                    logger.error(f'Error processing YouTube Mobile result: {str(e)}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Error searching YouTube Mobile: {str(e)}')

        logger.info(f'Found {len(results)} results from YouTube Mobile')
        return results[:75]

    async def _search_bing_videos(self, query: str) -> List[Dict]:
        """Search for videos using Bing Video Search."""
        results = []
        try:
            for offset in range(0, 100, 25):
                if len(results) >= 75:
                    break

                search_url = f'https://www.bing.com/videos/search?q={quote(query)}&first={offset}'
                logger.info(f'Searching Bing videos offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            video_elements = soup.find_all('div', class_='dg_u')
                            if not video_elements:
                                video_elements = soup.find_all('div', class_='mc_vtvc')
                            if not video_elements:
                                video_elements = soup.find_all('div', class_='mc_vtvc_meta')
                            logger.info(f'Found {len(video_elements)} video elements on Bing offset {offset}')

                            for element in video_elements:
                                try:
                                    if len(results) >= 75:
                                        break

                                    title = None
                                    title_elem = element.find(['div', 'span'], class_='mc_vtvc_title')
                                    if title_elem:
                                        title = title_elem.text.strip()

                                    video_url = None
                                    link = element.find('a', href=True)
                                    if link:
                                        video_url = link.get('href', '')

                                    # Try to extract the real video URL from within the element HTML
                                    el_html = str(element)
                                    video_url = extract_real_video_url(el_html) or video_url

                                    if video_url and not video_url.startswith('http'):
                                        video_url = f'https://www.bing.com{video_url}'

                                    if not title or not video_url:
                                        logger.debug('Skipping Bing result - missing title or URL')
                                        continue

                                    thumbnail = None
                                    img = element.find('img')
                                    if img:
                                        thumbnail = img.get('src') or img.get('data-src')

                                    duration = 'Unknown'
                                    duration_elem = element.find(['div', 'span'], class_='mc_vtvc_duration')
                                    if duration_elem:
                                        duration = duration_elem.text.strip()

                                    # Detect the actual source platform
                                    source_platform = detect_source_platform(video_url)

                                    results.append({
                                        'title': title,
                                        'url': video_url,
                                        'thumbnail': thumbnail,
                                        'duration': duration,
                                        'platform': 'Bing',
                                        'description': title,
                                        'source': source_platform,
                                    })
                                    logger.debug(f'Added Bing result: {title}')
                                except Exception as e:
                                    logger.error(f'Error processing Bing result: {str(e)}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Error searching Bing: {str(e)}')

        logger.info(f'Found {len(results)} results from Bing')
        return results[:75]

    async def _search_bing_videos_uk(self, query: str) -> List[Dict]:
        """Search for videos using Bing UK Video Search."""
        results = []
        try:
            for offset in range(0, 100, 25):
                if len(results) >= 75:
                    break

                search_url = f'https://www.bing.co.uk/videos/search?q={quote(query)}&first={offset}'
                logger.info(f'Searching Bing UK videos offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            video_elements = soup.find_all('div', class_='dg_u')
                            if not video_elements:
                                video_elements = soup.find_all('div', class_='mc_vtvc')
                            if not video_elements:
                                video_elements = soup.find_all('div', class_='mc_vtvc_meta')
                            logger.info(f'Found {len(video_elements)} video elements on Bing UK offset {offset}')

                            for element in video_elements:
                                try:
                                    if len(results) >= 75:
                                        break

                                    title = None
                                    title_elem = element.find(['div', 'span'], class_='mc_vtvc_title')
                                    if title_elem:
                                        title = title_elem.text.strip()

                                    video_url = None
                                    link = element.find('a', href=True)
                                    if link:
                                        video_url = link.get('href', '')

                                    # Try to extract the real video URL from within the element HTML
                                    el_html = str(element)
                                    video_url = extract_real_video_url(el_html) or video_url

                                    if video_url and not video_url.startswith('http'):
                                        video_url = f'https://www.bing.co.uk{video_url}'

                                    if not title or not video_url:
                                        logger.debug('Skipping Bing UK result - missing title or URL')
                                        continue

                                    thumbnail = None
                                    img = element.find('img')
                                    if img:
                                        thumbnail = img.get('src') or img.get('data-src')

                                    duration = 'Unknown'
                                    duration_elem = element.find(['div', 'span'], class_='mc_vtvc_duration')
                                    if duration_elem:
                                        duration = duration_elem.text.strip()

                                    # Detect the actual source platform
                                    source_platform = detect_source_platform(video_url)

                                    results.append({
                                        'title': title,
                                        'url': video_url,
                                        'thumbnail': thumbnail,
                                        'duration': duration,
                                        'platform': 'Bing UK',
                                        'description': title,
                                        'source': source_platform,
                                    })
                                    logger.debug(f'Added Bing UK result: {title}')
                                except Exception as e:
                                    logger.error(f'Error processing Bing UK result: {str(e)}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Error searching Bing UK: {str(e)}')

        logger.info(f'Found {len(results)} results from Bing UK')
        return results[:75]

    async def _search_bing_web(self, query: str) -> List[Dict]:
        """Search for general web pages using Bing Web Search."""
        results = []
        try:
            for offset in range(0, 100, 25):
                if len(results) >= 75:
                    break

                search_url = f'https://www.bing.com/search?q={quote(query)}&first={offset}'
                logger.info(f'Searching Bing Web offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            result_items = soup.find_all('li', class_='b_algo')
                            logger.info(f'Found {len(result_items)} web results on Bing offset {offset}')

                            for item in result_items:
                                try:
                                    if len(results) >= 75:
                                        break

                                    h2 = item.find('h2')
                                    link = h2.find('a', href=True) if h2 else item.find('a', href=True)
                                    if not link:
                                        continue

                                    raw_url = link.get('href', '')
                                    if raw_url.startswith('/'):
                                        continue

                                    url = decode_bing_redirect(raw_url)
                                    if not url or not url.startswith('http'):
                                        continue

                                    parsed_url = urlparse(url)
                                    if 'bing.com' in parsed_url.netloc.lower():
                                        continue

                                    title = h2.get_text(strip=True) if h2 else link.get_text(strip=True)
                                    if not title:
                                        continue

                                    snippet = ''
                                    p = item.find('p', class_=lambda x: x and 'b_lineclamp' in x)
                                    if not p:
                                        p = item.find('p')
                                    if p:
                                        snippet = p.get_text(strip=True)

                                    result_type = 'video' if is_video_url(url) else 'website'
                                    source = detect_source_platform(url)
                                    if source == 'Unknown':
                                        source = parsed_url.netloc.replace('www.', '').capitalize() or 'Website'

                                    results.append({
                                        'title': title,
                                        'url': url,
                                        'thumbnail': favicon_url(url),
                                        'duration': '' if result_type != 'video' else 'Unknown',
                                        'views': '',
                                        'platform': 'Bing Web',
                                        'description': snippet or title,
                                        'source': source,
                                        'type': result_type,
                                    })
                                    logger.debug(f'Added Bing web result: {title}')
                                except Exception as e:
                                    logger.error(f'Error processing Bing web result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Error searching Bing web: {e}')

        logger.info(f'Found {len(results)} results from Bing Web')
        return results[:75]

    async def _search_bing_web_uk(self, query: str) -> List[Dict]:
        """Search for general web pages using Bing UK Web Search."""
        results = []
        try:
            for offset in range(0, 100, 25):
                if len(results) >= 75:
                    break

                search_url = f'https://www.bing.co.uk/search?q={quote(query)}&first={offset}'
                logger.info(f'Searching Bing UK Web offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            result_items = soup.find_all('li', class_='b_algo')
                            logger.info(f'Found {len(result_items)} web results on Bing UK offset {offset}')

                            for item in result_items:
                                try:
                                    if len(results) >= 75:
                                        break

                                    h2 = item.find('h2')
                                    link = h2.find('a', href=True) if h2 else item.find('a', href=True)
                                    if not link:
                                        continue

                                    raw_url = link.get('href', '')
                                    if raw_url.startswith('/'):
                                        continue

                                    url = decode_bing_redirect(raw_url)
                                    if not url or not url.startswith('http'):
                                        continue

                                    parsed_url = urlparse(url)
                                    if 'bing.co.uk' in parsed_url.netloc.lower():
                                        continue

                                    title = h2.get_text(strip=True) if h2 else link.get_text(strip=True)
                                    if not title:
                                        continue

                                    snippet = ''
                                    p = item.find('p', class_=lambda x: x and 'b_lineclamp' in x)
                                    if not p:
                                        p = item.find('p')
                                    if p:
                                        snippet = p.get_text(strip=True)

                                    result_type = 'video' if is_video_url(url) else 'website'
                                    source = detect_source_platform(url)
                                    if source == 'Unknown':
                                        source = parsed_url.netloc.replace('www.', '').capitalize() or 'Website'

                                    results.append({
                                        'title': title,
                                        'url': url,
                                        'thumbnail': favicon_url(url),
                                        'duration': '' if result_type != 'video' else 'Unknown',
                                        'views': '',
                                        'platform': 'Bing UK Web',
                                        'description': snippet or title,
                                        'source': source,
                                        'type': result_type,
                                    })
                                    logger.debug(f'Added Bing UK web result: {title}')
                                except Exception as e:
                                    logger.error(f'Error processing Bing UK web result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Error searching Bing UK web: {e}')

        logger.info(f'Found {len(results)} results from Bing UK Web')
        return results[:75]

    async def _search_duckduckgo(self, query: str) -> List[Dict]:
        """Search for web pages using DuckDuckGo HTML search."""
        results = []
        try:
            for offset in [0, 30]:
                if len(results) >= 75:
                    break

                search_url = f'https://html.duckduckgo.com/html/?q={quote(query)}&s={offset}'
                logger.info(f'Searching DuckDuckGo offset {offset}: {search_url}')

                async with aiohttp.ClientSession() as session:
                    async with session.get(search_url, headers=self.headers) as response:
                        if response.status == 200:
                            html = await response.text()
                            soup = BeautifulSoup(html, 'html.parser')
                            result_items = soup.find_all('div', class_='result')
                            logger.info(f'Found {len(result_items)} web results on DuckDuckGo offset {offset}')

                            for item in result_items:
                                try:
                                    if len(results) >= 75:
                                        break

                                    link = item.find('a', class_='result__a', href=True)
                                    if not link:
                                        link = item.find('a', href=True)
                                    if not link:
                                        continue

                                    raw_url = link.get('href', '')
                                    url = decode_duckduckgo_redirect(raw_url)
                                    if not url or not url.startswith('http'):
                                        url = raw_url
                                        if url.startswith('//'):
                                            url = 'https:' + url
                                    if not url or not url.startswith('http'):
                                        continue

                                    parsed_url = urlparse(url)
                                    if 'duckduckgo.com' in parsed_url.netloc.lower():
                                        continue

                                    title = link.get_text(strip=True)
                                    if not title:
                                        continue

                                    snippet_elem = item.find('a', class_='result__snippet')
                                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''

                                    result_type = 'video' if is_video_url(url) else 'website'
                                    source = detect_source_platform(url)
                                    if source == 'Unknown':
                                        source = parsed_url.netloc.replace('www.', '').capitalize() or 'Website'

                                    results.append({
                                        'title': title,
                                        'url': url,
                                        'thumbnail': favicon_url(url),
                                        'duration': '' if result_type != 'video' else 'Unknown',
                                        'views': '',
                                        'platform': 'DuckDuckGo',
                                        'description': snippet or title,
                                        'source': source,
                                        'type': result_type,
                                    })
                                    logger.debug(f'Added DuckDuckGo result: {title}')
                                except Exception as e:
                                    logger.error(f'Error processing DuckDuckGo result: {e}')

                await asyncio.sleep(1)
        except Exception as e:
            logger.error(f'Error searching DuckDuckGo: {e}')

        logger.info(f'Found {len(results)} results from DuckDuckGo')
        return results[:75]


def setup_routes(app, socketio):
    """Set up Flask routes and Socket.IO event handlers"""
    search_in_progress = False

    @socketio.on('connect')
    def handle_connect():
        logger.info('Client connected')
        emit('connected', {'status': 'Connected to server'})

    @socketio.on('disconnect')
    def handle_disconnect():
        logger.info('Client disconnected')

    @socketio.on('search_query')
    def handle_search_query(data):
        """Handle incoming search queries"""
        nonlocal search_in_progress

        try:
            logger.info(f'Received search query: {json.dumps(data, indent=2)}')

            if search_in_progress:
                logger.warning('Search already in progress')
                emit('search_error', {'error': 'A search is already in progress'})
                return

            query = data.get('query', '').strip()
            if not query:
                logger.warning('Empty query received')
                emit('search_error', {'error': 'Please enter a search query'})
                return

            search_in_progress = True
            logger.info(f'Starting search for: {query}')

            emit('search_started', {
                'query': query,
                'message': f'Starting search for: {query}',
            })

            try:
                crawler = VideoSearchCrawler(query)
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                all_results = loop.run_until_complete(crawler.collect_results())
                loop.close()

                processed_results = []
                for result in all_results:
                    processed_result = {
                        'url': result.get('url', ''),
                        'title': result.get('title', 'Untitled'),
                        'description': result.get('description', ''),
                        'thumbnail': result.get('thumbnail', ''),
                        'source': result.get('source', 'Unknown'),
                        'duration': result.get('duration', 'Unknown'),
                        'type': result.get('type', 'video'),
                    }
                    processed_results.append(processed_result)

                    emit('new_result', {'result': processed_result})

                logger.info(f'Search completed with {len(processed_results)} results')
                emit('search_completed', {
                    'results': processed_results,
                    'total': len(processed_results),
                    'query': query,
                })
            except Exception as e:
                logger.error(f'Search error: {str(e)}')
                emit('search_error', {'error': str(e)})
            finally:
                search_in_progress = False
        except Exception as e:
            logger.error(f'Error handling search query: {str(e)}')
            emit('search_error', {'error': str(e)})

    # --- Video download ---

    # Token-based store for downloaded files (token -> {path, title, tmp_dir})
    download_tokens = {}
    token_lock = threading.Lock()

    def resolve_video_url(url):
        """Resolve Bing wrapper URLs to their actual video URLs for yt-dlp."""
        parsed = urlparse(url)

        # If the URL is already a direct video platform URL, use it as-is
        real_url = extract_real_video_url(url)
        if real_url:
            return real_url

        # Bing video URLs need to be resolved to the actual video source
        if 'bing.com' in parsed.netloc or 'bing.co.uk' in parsed.netloc:
            try:
                logger.info(f'Resolving Bing URL: {url}')

                # First, try extracting from the churl query parameter
                from urllib.parse import parse_qs
                qs = parse_qs(parsed.query)
                if 'churl' in qs:
                    churl = qs['churl'][0]
                    # Check if churl itself is a downloadable video URL
                    churl_real = extract_real_video_url(churl)
                    if churl_real:
                        logger.info(f'Resolved Bing URL via churl: {churl_real}')
                        return churl_real

                # Fetch the Bing page and look for embedded video URLs
                resp = requests.get(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                }, allow_redirects=True, timeout=10)
                final_url = resp.url
                html = resp.text

                # Check if redirect landed on a supported site
                real = extract_real_video_url(final_url)
                if real:
                    logger.info(f'Resolved Bing URL via redirect: {real}')
                    return real

                # Search the page HTML for any supported video URL
                real = extract_real_video_url(html)
                if real:
                    logger.info(f'Resolved Bing URL from page: {real}')
                    return real

                # Look for other video source URLs in JSON data
                for pattern in [r'"playUrl"\s*:\s*"([^"]+)"', r'"contentUrl"\s*:\s*"([^"]+)"', r'"embedUrl"\s*:\s*"([^"]+)"', r'"murl"\s*:\s*"([^"]+)"']:
                    m = re.search(pattern, html)
                    if m:
                        resolved = m.group(1).replace('\\/', '/')
                        logger.info(f'Resolved Bing URL to: {resolved}')
                        return resolved

                logger.warning(f'Could not resolve Bing URL, trying as-is: {url}')
            except Exception as e:
                logger.error(f'Error resolving Bing URL: {str(e)}')

        return url

    @app.route('/download_file/<token>')
    def download_file(token):
        """Serve a previously downloaded file by token."""
        with token_lock:
            entry = download_tokens.pop(token, None)

        if not entry or not os.path.exists(entry['path']):
            return jsonify({'error': 'File not found or expired'}), 404

        safe_title = re.sub(r'[\\/:*?"<>|]', '_', entry.get('title', 'video'))
        filename = f'{safe_title}.mp4'
        file_path = entry['path']
        tmp_dir = entry.get('tmp_dir')

        logger.info(f'Serving downloaded file: {file_path} ({os.path.getsize(file_path)} bytes)')

        response = send_file(
            file_path,
            as_attachment=True,
            download_name=filename,
            mimetype='video/mp4',
        )

        @response.call_on_close
        def cleanup():
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                if tmp_dir and os.path.exists(tmp_dir):
                    os.rmdir(tmp_dir)
                logger.info(f'Cleaned up temp file: {file_path}')
            except Exception as e:
                logger.error(f'Error cleaning up temp file: {e}')

        return response

    @socketio.on('download_video')
    def handle_download_video(data):
        """Handle download requests with progress reporting via Socket.IO."""
        original_url = (data or {}).get('url', '').strip()
        if not original_url:
            emit('download_error', {'url': '', 'error': 'No URL provided'})
            return

        # Resolve Bing wrapper URLs to actual video URLs
        url = resolve_video_url(original_url)
        logger.info(f'Download request for: {url}')

        def progress_hook(d):
            if d['status'] == 'downloading':
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                percent = (downloaded / total * 100) if total else 0
                speed = d.get('speed') or 0
                eta = d.get('eta') or 0
                socketio.emit('download_progress', {
                    'url': original_url,
                    'percent': round(percent, 1),
                    'downloaded': downloaded,
                    'total': total,
                    'speed': speed,
                    'eta': eta,
                })
            elif d['status'] == 'finished':
                socketio.emit('download_progress', {
                    'url': original_url,
                    'percent': 100,
                    'status': 'finished',
                })

        tmp_dir = tempfile.mkdtemp(prefix='ytdl_')
        ydl_opts = {
            # Prefer single-stream formats that don't need ffmpeg merging;
            # fall back to merged format (ffmpeg available via imageio-ffmpeg)
            'format': 'best[height<=1080][ext=mp4]/bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080]/best',
            'merge_output_format': 'mp4',
            'ffmpeg_location': FFMPEG_PATH,
            'outtmpl': os.path.join(tmp_dir, '%(title).200s.%(ext)s'),
            'noplaylist': True,
            'quiet': True,
            'no_warnings': True,
            'progress_hooks': [progress_hook],
        }

        def run_download():
            try:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    downloaded_path = ydl.prepare_filename(info)
                    if not os.path.exists(downloaded_path):
                        base = os.path.splitext(downloaded_path)[0]
                        downloaded_path = base + '.mp4'
                    if not os.path.exists(downloaded_path):
                        for fname in os.listdir(tmp_dir):
                            if fname.endswith(('.mp4', '.webm', '.mkv', '.m4a')):
                                downloaded_path = os.path.join(tmp_dir, fname)
                                break

                    if not os.path.exists(downloaded_path):
                        socketio.emit('download_error', {
                            'url': original_url,
                            'error': 'File not found after download',
                        })
                        return

                    # Generate a token and store the file info
                    import uuid
                    token = uuid.uuid4().hex
                    with token_lock:
                        download_tokens[token] = {
                            'path': downloaded_path,
                            'title': info.get('title', 'video'),
                            'tmp_dir': tmp_dir,
                        }

                    socketio.emit('download_complete', {
                        'url': original_url,
                        'token': token,
                        'title': info.get('title', 'video'),
                    })
            except yt_dlp.utils.DownloadError as e:
                err_msg = str(e)
                if 'Unsupported URL' in err_msg:
                    err_msg = 'This video source is not supported for download. YouTube videos work best.'
                logger.error(f'Download error: {err_msg}')
                socketio.emit('download_error', {'url': original_url, 'error': err_msg})
            except Exception as e:
                logger.error(f'Download error: {str(e)}')
                socketio.emit('download_error', {'url': original_url, 'error': str(e)})

        thread = threading.Thread(target=run_download, daemon=True)
        thread.start()
