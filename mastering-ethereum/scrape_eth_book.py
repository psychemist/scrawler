import os
import re
import time
import logging
import requests
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

# --- Configuration ---
BASE_URL = "https://masteringethereum.xyz/"
TOC_URL = "https://masteringethereum.xyz/"
OUTPUT_DIR = "eth_book"
ASSETS_DIR = "assets"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class EthBookCrawler:
    def __init__(self, base_url, toc_url, output_dir):
        self.base_url = base_url
        self.toc_url = toc_url
        self.output_dir = output_dir
        self.assets_dir = os.path.join(output_dir, ASSETS_DIR)
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })
        
        # Ensure directories exist
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

    def fetch_soup(self, url):
        """Fetches a URL and returns a BeautifulSoup object."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, 'html.parser')
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def download_asset(self, img_url, page_url):
        """Downloads an image/asset and returns the local relative path."""
        if not img_url:
            return ""
            
        # Handle relative URLs. 
        # Note: In mdBook, images might be relative to the page URL or root.
        # Usually relative to the page.
        if not img_url.startswith('http'):
            img_url = urljoin(page_url, img_url)
            
        try:
            # Clean URL for filename (remove query params, etc)
            parsed = urlparse(img_url)
            filename = os.path.basename(parsed.path)
            if not filename or '.' not in filename:
                filename = f"image_{int(time.time()*1000)}.png" # Fallback
            
            # Simple sanitization
            filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
            
            local_path = os.path.join(self.assets_dir, filename)
            relative_path = os.path.join(ASSETS_DIR, filename)
            
            # Don't re-download if exists
            if os.path.exists(local_path):
                return relative_path

            # Download
            resp = self.session.get(img_url, stream=True, timeout=10)
            if resp.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(1024):
                        f.write(chunk)
                return relative_path
            else:
                logger.warning(f"Could not download asset {img_url} (Status {resp.status_code})")
                return img_url # Return original as fallback
        except Exception as e:
            logger.warning(f"Error downloading asset {img_url}: {e}")
            return img_url

    def get_toc(self):
        """Parses the main page to get the list of chapters."""
        logger.info(f"Fetching TOC from {self.toc_url}...")
        soup = self.fetch_soup(self.toc_url)
        if not soup:
            return []

        chapters = []
        
        # mdBook TOC structure:
        # <nav id="sidebar"> ... <ol class="chapter"> <li class="chapter-item"> <a href="...">...</a>
        
        sidebar = soup.find('nav', id='sidebar')
        if not sidebar:
            logger.error("Could not find sidebar navigation.")
            return []

        links = sidebar.select('ol.chapter li.chapter-item a')
        
        for link in links:
            href = link.get('href')
            if not href:
                continue
                
            # Skip empty or anchor-only links if any
            if href.startswith('#'):
                continue

            full_url = urljoin(self.toc_url, href)
            title = link.get_text(strip=True)
            
            # Remove the "1. ", "2. " prefixes if desired, but they are useful for ordering.
            # mdBook puts them in <strong> tags usually.
            
            chapters.append({
                'title': title,
                'url': full_url
            })

        logger.info(f"Found {len(chapters)} chapters.")
        return chapters

    def convert_to_markdown(self, soup, content_selector, page_url):
        """Converts the selected HTML content to Markdown, handling assets."""
        
        content_div = soup.select_one(content_selector)
        if not content_div:
            return ""
            
        # mdBook specific: remove header links (e.g. the link icon next to headers)
        for a in content_div.find_all('a', class_='header'):
            a.decompose()

        crawler_self = self # Closure for inner class

        class ImageDownloaderConverter(MarkdownConverter):
            def convert_img(self, el, text, convert_as_inline=False, **kwargs):
                src = el.get('src')
                alt = el.get('alt') or ''
                new_src = crawler_self.download_asset(src, page_url)
                return f"![{alt}]({new_src})"
            
            # mdBook code blocks often have class "language-xxx"
            # Markdownify handles this well usually.

        converter = ImageDownloaderConverter(heading_style="ATX")
        return converter.convert_soup(content_div)

    def scrape(self):
        chapters = self.get_toc()
        if not chapters:
            logger.error("No chapters found. Exiting.")
            return

        # Create Index (README.md)
        with open(os.path.join(self.output_dir, "README.md"), "w") as f:
            f.write("# Mastering Ethereum\n\n")
            
            for idx, chapter in enumerate(chapters):
                # Create a safe filename
                # title might be "1. Intro", let's make it safe
                safe_title = re.sub(r'[^a-zA-Z0-9]', '_', chapter['title']).lower()
                safe_title = re.sub(r'_+', '_', safe_title).strip('_')
                
                # Ensure ordering by prepending index if title doesn't have it
                # The text from mdBook usually includes "1. ", so we might get "1__intro"
                filename = f"{idx+1:02d}_{safe_title}.md"
                chapter['filename'] = filename
                
                f.write(f"- [{chapter['title']}]({filename})\n")

            f.write(f"Scraped from [{self.toc_url}]({self.toc_url})\n\n")

        # Process Chapters
        for i, chapter in enumerate(chapters):
            logger.info(f"Processing [{i+1}/{len(chapters)}] {chapter['title']}...")
            
            soup = self.fetch_soup(chapter['url'])
            if not soup:
                continue

            # Identify content area
            # mdBook uses <main> inside #content
            content = self.convert_to_markdown(soup, 'main', chapter['url'])
            
            if not content:
                logger.warning(f"Could not find content for {chapter['title']}")
                content = "*Error: Could not extract content.*"

            # Add title to top of file
            full_content = f"# {chapter['title']}\n\nSource: {chapter['url']}\n\n{content}"
            
            # Save
            with open(os.path.join(self.output_dir, chapter['filename']), "w") as f:
                f.write(full_content)
            
            # Be polite
            time.sleep(1)

        logger.info(f"Done! Book saved to {self.output_dir}/")

if __name__ == "__main__":
    crawler = EthBookCrawler(BASE_URL, TOC_URL, OUTPUT_DIR)
    crawler.scrape()
