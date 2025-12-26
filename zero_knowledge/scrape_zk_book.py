import os
import time
import logging
import requests
import re
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter

# --- Configuration ---
BASE_URL = "https://rareskills.io"
TOC_URL = "https://rareskills.io/zk-book"
OUTPUT_DIR = "zk_book"
ASSETS_DIR = "assets"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class ZKBookCrawler:
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

    def download_asset(self, img_url):
        """Downloads an image/asset and returns the local relative path."""
        if not img_url:
            return ""
            
        # Handle relative URLs
        if not img_url.startswith('http'):
            img_url = urljoin(self.base_url, img_url)
            
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
            # Filter out tracking pixels or tiny images if needed, but for now just get it.
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
        # Based on inspection: links have class 'modules-item-title'
        # The structure is Modules -> Chapters.
        # We will try to preserve the Module structure if possible, but a flat list is easier to start.
        # The inspection showed:
        # <div class="module-card"> ... <div class="brxe-czbqff">Module X</div> ... <a class="modules-item-title" href=">Title</a>
        
        module_cards = soup.find_all(class_='module-card')
        
        if not module_cards:
            logger.warning("No module cards found. Trying fallback selector...")
            # Fallback: just find all links that look like chapters
            links = soup.find_all('a', class_='modules-item-title')
            for link in links:
                chapters.append({
                    'module': 'General',
                    'title': link.get_text(strip=True),
                    'url': link['href']
                })
        else:
            for card in module_cards:
                # Try to find module title
                module_title_tag = card.find(class_='brxe-czbqff') or card.find(class_='brxe-hnwsjy')
                module_title = module_title_tag.get_text(strip=True) if module_title_tag else "Uncategorized"
                
                # Find chapters in this module
                links = card.find_all('a', class_='modules-item-title')
                for link in links:
                    chapters.append({
                        'module': module_title,
                        'title': link.get_text(strip=True),
                        'url': link['href']
                    })

        logger.info(f"Found {len(chapters)} chapters.")
        return chapters

    def convert_to_markdown(self, soup, content_selector):
        """Converts the selected HTML content to Markdown, handling assets."""
        
        content_div = soup.select_one(content_selector)
        if not content_div:
            return ""

        crawler_self = self # Closure for inner class

        class ImageDownloaderConverter(MarkdownConverter):
            def convert_img(self, el, text, convert_as_inline=False, **kwargs):
                src = el.get('src')
                alt = el.get('alt') or ''
                new_src = crawler_self.download_asset(src)
                return f"![{alt}]({new_src})"
            
            # Preserve MathJax
            # default markdownify usually preserves raw text, but let's be safe
            # If math is in a span/div with a specific class, handle it.
            # But the site seems to use raw $...$ text or \( ... \) which markdownify handles fine as text.

        converter = ImageDownloaderConverter(heading_style="ATX", code_language="solidity")
        return converter.convert_soup(content_div)

    def scrape(self):
        chapters = self.get_toc()
        if not chapters:
            logger.error("No chapters found. Exiting.")
            return

        # Create Index (README.md)
        with open(os.path.join(self.output_dir, "README.md"), "w") as f:
            f.write("# The RareSkills Book of Zero Knowledge\n\n")
            
            current_module = None
            for idx, chapter in enumerate(chapters):
                if chapter['module'] != current_module:
                    current_module = chapter['module']
                    f.write(f"\n## {current_module}\n\n")
                
                # Create a safe filename
                safe_title = re.sub(r'[^a-zA-Z0-9]', '_', chapter['title']).lower()
                # trim underscores
                safe_title = re.sub(r'_+', '_', safe_title).strip('_')
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
            # Based on inspection: <div class="brxe-post-content">
            content = self.convert_to_markdown(soup, '.brxe-post-content')
            
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
    crawler = ZKBookCrawler(BASE_URL, TOC_URL, OUTPUT_DIR)
    crawler.scrape()