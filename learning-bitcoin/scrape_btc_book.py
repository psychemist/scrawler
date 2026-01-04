import os
import re
import time
import logging
import requests
from urllib.parse import urljoin, urlparse, unquote

# --- Configuration ---
REPO_BASE_URL = "https://raw.githubusercontent.com/BlockchainCommons/Learning-Bitcoin-from-the-Command-Line/master/"
README_URL = urljoin(REPO_BASE_URL, "README.md")
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "btc_book")
ASSETS_DIR = "assets"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

class BtcBookCrawler:
    def __init__(self, base_url, readme_url, output_dir):
        self.base_url = base_url
        self.readme_url = readme_url
        self.output_dir = output_dir
        self.assets_dir = os.path.join(output_dir, ASSETS_DIR)
        self.session = requests.Session()
        
        # Ensure directories exist
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.assets_dir, exist_ok=True)

    def fetch_text(self, url):
        """Fetches a URL and returns the text content."""
        try:
            response = self.session.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch {url}: {e}")
            return None

    def download_asset(self, img_url, page_url=None):
        """Downloads an image/asset and returns the local relative path."""
        if not img_url:
            return ""
            
        # Resolve URL
        if not img_url.startswith('http'):
            # If page_url is provided, resolve relative to it.
            if page_url:
                full_img_url = urljoin(page_url, img_url)
            else:
                full_img_url = urljoin(self.base_url, img_url)
        else:
            full_img_url = img_url
            
        try:
            # Clean URL for filename
            parsed = urlparse(full_img_url)
            filename = os.path.basename(unquote(parsed.path))
            if not filename or '.' not in filename:
                filename = f"image_{int(time.time()*1000)}.png"
            
            # Simple sanitization
            filename = re.sub(r'[^a-zA-Z0-9._-]', '_', filename)
            
            local_path = os.path.join(self.assets_dir, filename)
            relative_path = os.path.join(ASSETS_DIR, filename)
            
            # Don't re-download if exists
            if os.path.exists(local_path):
                return relative_path

            # Download
            logger.info(f"Downloading asset: {full_img_url}")
            resp = self.session.get(full_img_url, stream=True, timeout=10)
            if resp.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in resp.iter_content(1024):
                        f.write(chunk)
                return relative_path
            else:
                logger.warning(f"Could not download asset {full_img_url} (Status {resp.status_code})")
                return img_url
        except Exception as e:
            logger.warning(f"Error downloading asset {full_img_url}: {e}")
            return img_url

    def get_toc(self):
        """Parses the README to get the list of chapters."""
        logger.info(f"Fetching TOC from {self.readme_url}...")
        text = self.fetch_text(self.readme_url)
        if not text:
            return []

        chapters = []
        
        # Regex to find links in Markdown: [Title](URL)
        # Pattern: [Title](filename.md)
        
        matches = re.findall(r'\[(.*?)\]\((.*?\.md)\)', text)
        
        for title, href in matches:
            # Clean href if it has leading parens (typo in source)
            href = href.lstrip('(')

            # Filter out non-chapter links (translations, etc)
            if 'README.md' in href:
                continue
            
            # Skip if it doesn't look like a chapter file
            # Most chapters start with digits "01_..." or "1.0..."
            if href.startswith('http'):
                continue
                
            full_url = urljoin(self.base_url, href)
            
            chapters.append({
                'title': title,
                'url': full_url,
                'filename': href # Keep original filename
            })

        logger.info(f"Found {len(chapters)} chapters.")
        return chapters

    def process_content(self, content, page_url):
        """Rewrites image links and downloads assets."""
        
        def replacer(match):
            alt_text = match.group(1)
            img_src = match.group(2)
            
            new_src = self.download_asset(img_src, page_url)
            return f"![{alt_text}]({new_src})"
            
        # Regex for images: ![alt](src)
        new_content = re.sub(r'!\[(.*?)\]\((.*?)\)', replacer, content)
        
        # Also handle HTML <img> tags if any?
        # Markdown often mixes HTML. Stick to standard Markdown syntax first.
        # Regex for <img src="...">
        def img_tag_replacer(match):
            # strict regex for simple cases
            full_tag = match.group(0)
            src_match = re.search(r'src=["\"](.*?)["\"]', full_tag)
            if src_match:
                src = src_match.group(1)
                new_src = self.download_asset(src, page_url)
                return full_tag.replace(src, new_src)
            return full_tag

        new_content = re.sub(r'<img[^>]+>', img_tag_replacer, new_content)

        return new_content

    def scrape(self):
        chapters = self.get_toc()
        if not chapters:
            logger.error("No chapters found. Exiting.")
            return

        # Create Index (README.md for the book folder)
        with open(os.path.join(self.output_dir, "README.md"), "w") as f:
            f.write("# Learning Bitcoin from the Command Line\n\n")
            f.write("Scraped from [GitHub](https://github.com/BlockchainCommons/Learning-Bitcoin-from-the-Command-Line)\n\n")
            
            for chapter in chapters:
                f.write(f"- [{chapter['title']}]({chapter['filename']})\n")

        # Process Chapters
        for i, chapter in enumerate(chapters):
            logger.info(f"Processing [{i+1}/{len(chapters)}] {chapter['title']}...")
            
            content = self.fetch_text(chapter['url'])
            if not content:
                logger.warning(f"Could not fetch content for {chapter['title']}")
                continue

            # Process content (images)
            content = self.process_content(content, chapter['url'])

            # Add title if missing? 
            # Usually these files have headers. Let's prepend metadata or source.
            full_content = f"<!-- Source: {chapter['url']} -->\n\n{content}"
            
            # Save
            # Remove any path separators from filename just in case
            safe_filename = os.path.basename(chapter['filename'])
            
            with open(os.path.join(self.output_dir, safe_filename), "w") as f:
                f.write(full_content)
            
            # Be polite
            time.sleep(0.5)

        logger.info(f"Done! Book saved to {self.output_dir}/")

if __name__ == "__main__":
    crawler = BtcBookCrawler(REPO_BASE_URL, README_URL, OUTPUT_DIR)
    crawler.scrape()
