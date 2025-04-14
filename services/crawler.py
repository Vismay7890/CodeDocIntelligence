import os
import logging
import concurrent.futures
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import xml.etree.ElementTree as ET
from datetime import datetime
import time
import random
from config import MAX_URLS, MAX_WORKERS, TIMEOUT, USER_AGENT

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class SitemapCrawler:
    """
    A multi-CPU core crawler service to generate XML sitemaps from documentation base URL.
    It handles robots.txt for discovering sitemaps and can also crawl websites to generate sitemaps.
    """
    
    def __init__(self):
        self.visited_urls = set()
        self.discovered_urls = set()
        self.base_domain = None
        self.base_url = None
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
    
    def crawl(self, base_url):
        """
        Main entry point for crawling a website.
        
        Args:
            base_url (str): The base URL of the documentation website
            
        Returns:
            list: List of discovered URLs
        """
        self.reset()
        self.base_url = base_url
        parsed_url = urlparse(base_url)
        self.base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        
        # First check if a sitemap exists
        sitemap_urls = self.discover_sitemaps_from_robots()
        
        if sitemap_urls:
            logger.info(f"Found {len(sitemap_urls)} sitemaps from robots.txt")
            urls = self.process_existing_sitemaps(sitemap_urls)
        else:
            logger.info("No sitemaps found in robots.txt, crawling the site manually")
            urls = self.crawl_site_for_urls(base_url)
        
        return list(self.discovered_urls)
    
    def reset(self):
        """Reset the crawler state"""
        self.visited_urls = set()
        self.discovered_urls = set()
        self.base_domain = None
        self.base_url = None
    
    def discover_sitemaps_from_robots(self):
        """
        Check robots.txt for sitemap entries
        
        Returns:
            list: List of sitemap URLs
        """
        robots_url = urljoin(self.base_domain, "/robots.txt")
        sitemaps = []
        
        try:
            response = self.session.get(robots_url, timeout=TIMEOUT)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        sitemaps.append(sitemap_url)
        except Exception as e:
            logger.warning(f"Error fetching robots.txt: {e}")
        
        return sitemaps
    
    def process_existing_sitemaps(self, sitemap_urls):
        """
        Process existing sitemaps to extract URLs
        
        Args:
            sitemap_urls (list): List of sitemap URLs
            
        Returns:
            list: List of URLs extracted from sitemaps
        """
        all_urls = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = []
            for sitemap_url in sitemap_urls:
                futures.append(executor.submit(self.extract_urls_from_sitemap, sitemap_url))
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    urls = future.result()
                    all_urls.extend(urls)
                    self.discovered_urls.update(urls)
                    
                    if len(self.discovered_urls) >= MAX_URLS:
                        logger.info(f"Reached maximum URL limit: {MAX_URLS}")
                        break
                except Exception as e:
                    logger.error(f"Error processing sitemap: {e}")
        
        return list(self.discovered_urls)
    
    def extract_urls_from_sitemap(self, sitemap_url):
        """
        Extract URLs from a sitemap
        
        Args:
            sitemap_url (str): The URL of the sitemap
            
        Returns:
            list: List of URLs extracted from the sitemap
        """
        urls = []
        
        try:
            response = self.session.get(sitemap_url, timeout=TIMEOUT)
            
            if response.status_code != 200:
                logger.warning(f"Failed to fetch sitemap: {sitemap_url}, status: {response.status_code}")
                return urls
            
            # Check if it's a sitemap index
            if "<sitemapindex" in response.text:
                root = ET.fromstring(response.text)
                namespace = self.get_namespace(root.tag)
                
                for sitemap in root.findall(f".//{namespace}sitemap"):
                    loc = sitemap.find(f"{namespace}loc")
                    if loc is not None and loc.text:
                        child_urls = self.extract_urls_from_sitemap(loc.text)
                        urls.extend(child_urls)
            else:
                # Regular sitemap
                root = ET.fromstring(response.text)
                namespace = self.get_namespace(root.tag)
                
                for url_element in root.findall(f".//{namespace}url"):
                    loc = url_element.find(f"{namespace}loc")
                    if loc is not None and loc.text:
                        urls.append(loc.text)
        
        except Exception as e:
            logger.error(f"Error parsing sitemap {sitemap_url}: {e}")
        
        return urls
    
    def get_namespace(self, tag):
        """
        Extract namespace from XML tag
        
        Args:
            tag (str): XML tag
            
        Returns:
            str: Namespace prefix
        """
        if "}" in tag:
            return "{" + tag.split("}")[0][1:] + "}"
        return ""
    
    def crawl_site_for_urls(self, start_url):
        """
        Crawl a website to discover documentation pages
        
        Args:
            start_url (str): The starting URL for crawling
            
        Returns:
            list: List of discovered URLs
        """
        self.discovered_urls.add(start_url)
        queue = [start_url]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            while queue and len(self.discovered_urls) < MAX_URLS:
                # Process up to MAX_WORKERS URLs at a time
                batch = [queue.pop(0) for _ in range(min(MAX_WORKERS, len(queue)))]
                futures = [executor.submit(self.scrape_page, url) for url in batch]
                
                for future in concurrent.futures.as_completed(futures):
                    try:
                        new_urls = future.result()
                        for url in new_urls:
                            if url not in self.discovered_urls and len(self.discovered_urls) < MAX_URLS:
                                self.discovered_urls.add(url)
                                queue.append(url)
                    except Exception as e:
                        logger.error(f"Error in crawling: {e}")
                
                # Add a small delay to be nice to the server
                time.sleep(random.uniform(0.1, 0.3))
        
        return list(self.discovered_urls)
    
    def scrape_page(self, url):
        """
        Scrape a page to find links
        
        Args:
            url (str): URL to scrape
            
        Returns:
            list: List of discovered URLs on the page
        """
        if url in self.visited_urls:
            return []
        
        self.visited_urls.add(url)
        new_urls = []
        
        try:
            response = self.session.get(url, timeout=TIMEOUT)
            
            if response.status_code != 200 or 'text/html' not in response.headers.get('Content-Type', ''):
                return new_urls
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            for link in soup.find_all('a', href=True):
                href = link['href']
                absolute_url = urljoin(url, href)
                
                # Only include URLs from the same domain
                parsed_url = urlparse(absolute_url)
                if parsed_url.netloc == urlparse(self.base_url).netloc:
                    # Remove fragments
                    absolute_url = absolute_url.split('#')[0]
                    # Remove query parameters
                    absolute_url = absolute_url.split('?')[0]
                    
                    # Filter for documentation-like pages
                    if self.is_likely_documentation(absolute_url, link.text):
                        new_urls.append(absolute_url)
        
        except Exception as e:
            logger.warning(f"Error scraping {url}: {e}")
        
        return new_urls
    
    def is_likely_documentation(self, url, link_text=""):
        """
        Determine if a URL is likely to be a documentation page
        
        Args:
            url (str): URL to check
            link_text (str): The text of the link
            
        Returns:
            bool: True if the URL is likely documentation
        """
        path = urlparse(url).path.lower()
        
        # Common documentation paths
        doc_indicators = [
            '/docs/', '/documentation/', '/guide/', '/tutorial/', 
            '/api/', '/reference/', '/manual/', '/examples/',
            '/getting-started/', '/quickstart/', '/introduction/',
            '/functions/', '/classes/', '/methods/', '/modules/',
            '/handbook/', '/learn/', '/help/'
        ]
        
        # Common documentation file extensions
        doc_extensions = ['.html', '.htm', '.md', '.rst', '/']
        
        # Check path
        for indicator in doc_indicators:
            if indicator in path:
                return True
        
        # Check extension
        if any(path.endswith(ext) for ext in doc_extensions):
            # Look for documentation keywords in the link text
            doc_keywords = [
                'documentation', 'guide', 'tutorial', 'api', 'reference',
                'manual', 'example', 'getting started', 'quickstart',
                'introduction', 'function', 'class', 'method', 'module'
            ]
            if any(keyword.lower() in link_text.lower() for keyword in doc_keywords):
                return True
        
        return False
    
    def generate_xml_sitemap(self):
        """
        Generate an XML sitemap from the discovered URLs
        
        Returns:
            str: XML sitemap content
        """
        root = ET.Element("urlset")
        root.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")
        
        for url in self.discovered_urls:
            url_element = ET.SubElement(root, "url")
            loc = ET.SubElement(url_element, "loc")
            loc.text = url
            
            lastmod = ET.SubElement(url_element, "lastmod")
            lastmod.text = datetime.now().strftime("%Y-%m-%d")
            
            changefreq = ET.SubElement(url_element, "changefreq")
            changefreq.text = "monthly"
            
            priority = ET.SubElement(url_element, "priority")
            priority.text = "0.8"
        
        return ET.tostring(root, encoding="unicode")
