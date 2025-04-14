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
# Make sure this is configured in your main app or here if run standalone
# logging.basicConfig(level=logging.DEBUG) 
logger = logging.getLogger(__name__) # Get logger instance

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
        logger.debug("SitemapCrawler initialized.")

    def crawl(self, base_url):
        """
        Main entry point for crawling a website.

        Args:
            base_url (str): The base URL of the documentation website

        Returns:
            list: List of discovered URLs
        """
        self.reset()
        logger.info(f"Starting crawl for base URL: {base_url}")
        self.base_url = base_url
        parsed_url = urlparse(base_url)
        self.base_domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
        logger.debug(f"Base domain set to: {self.base_domain}")

        # First check if a sitemap exists
        sitemap_urls = self.discover_sitemaps_from_robots()

        if sitemap_urls:
            logger.info(f"Found {len(sitemap_urls)} sitemaps from robots.txt: {sitemap_urls}")
            urls = self.process_existing_sitemaps(sitemap_urls)
        else:
            logger.info("No sitemaps found in robots.txt, attempting site crawl manually.")
            urls = self.crawl_site_for_urls(base_url)

        final_urls = list(self.discovered_urls)
        logger.info(f"Crawl finished. Discovered {len(final_urls)} unique URLs.")
        logger.debug(f"Sample discovered URLs: {final_urls[:10]}")
        return final_urls

    def reset(self):
        """Reset the crawler state"""
        logger.debug("Resetting crawler state.")
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
        logger.debug(f"Checking for sitemaps in: {robots_url}")

        try:
            response = self.session.get(robots_url, timeout=TIMEOUT)
            logger.debug(f"robots.txt status code: {response.status_code}")
            if response.status_code == 200:
                for line in response.text.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        logger.debug(f"Found sitemap entry: {sitemap_url}")
                        sitemaps.append(sitemap_url)
            else:
                 logger.warning(f"robots.txt not found or inaccessible (status {response.status_code}) at {robots_url}")

        except Exception as e:
            logger.warning(f"Error fetching or parsing robots.txt from {robots_url}: {e}", exc_info=True)

        return sitemaps

    def process_existing_sitemaps(self, sitemap_urls):
        """
        Process existing sitemaps to extract URLs

        Args:
            sitemap_urls (list): List of sitemap URLs

        Returns:
            list: List of URLs extracted from sitemaps
        """
        logger.info(f"Processing {len(sitemap_urls)} sitemap URLs.")
        all_urls = [] # Note: This local variable isn't really used, self.discovered_urls is updated

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            for sitemap_url in sitemap_urls:
                 if len(self.discovered_urls) >= MAX_URLS:
                    logger.info(f"Reached MAX_URLS limit ({MAX_URLS}) during sitemap processing. Stopping.")
                    break
                 future = executor.submit(self.extract_urls_from_sitemap, sitemap_url)
                 futures[future] = sitemap_url

            for future in concurrent.futures.as_completed(futures):
                sitemap_url = futures[future]
                try:
                    urls = future.result()
                    count_before = len(self.discovered_urls)
                    self.discovered_urls.update(urls)
                    count_after = len(self.discovered_urls)
                    logger.debug(f"Extracted {len(urls)} URLs from {sitemap_url}. Added {count_after - count_before} new URLs.")

                    if len(self.discovered_urls) >= MAX_URLS:
                        logger.info(f"Reached maximum URL limit ({MAX_URLS}) after processing {sitemap_url}")
                        # We can cancel remaining futures if needed, but completing is usually fine
                        break
                except Exception as e:
                    logger.error(f"Error processing sitemap {sitemap_url}: {e}", exc_info=True)

        return list(self.discovered_urls) # Return the accumulated URLs

    def extract_urls_from_sitemap(self, sitemap_url):
        """
        Extract URLs from a sitemap

        Args:
            sitemap_url (str): The URL of the sitemap

        Returns:
            list: List of URLs extracted from the sitemap
        """
        urls = []
        logger.debug(f"Attempting to extract URLs from sitemap: {sitemap_url}")

        try:
            response = self.session.get(sitemap_url, timeout=TIMEOUT)
            logger.debug(f"Sitemap fetch status for {sitemap_url}: {response.status_code}")

            if response.status_code != 200:
                logger.warning(f"Failed to fetch sitemap: {sitemap_url}, status: {response.status_code}")
                return urls

            content_type = response.headers.get('Content-Type', '').lower()
            logger.debug(f"Sitemap content type for {sitemap_url}: {content_type}")

            # Handle potential large files (though less common for sitemaps)
            if len(response.content) > 10 * 1024 * 1024: # 10 MB limit
                 logger.warning(f"Sitemap {sitemap_url} is very large ({len(response.content)} bytes). Skipping.")
                 return urls
            
            sitemap_content = response.text

            # Check if it's a sitemap index
            if "<sitemapindex" in sitemap_content:
                logger.debug(f"{sitemap_url} appears to be a sitemap index.")
                root = ET.fromstring(sitemap_content)
                namespace = self.get_namespace(root.tag)

                sitemap_elements = root.findall(f".//{namespace}sitemap")
                logger.debug(f"Found {len(sitemap_elements)} child sitemaps in index {sitemap_url}")
                for sitemap in sitemap_elements:
                    loc = sitemap.find(f"{namespace}loc")
                    if loc is not None and loc.text:
                        child_sitemap_url = loc.text
                        logger.debug(f"Recursively processing child sitemap: {child_sitemap_url}")
                        # Recursive call - potentially deep, consider iterative approach for very deep indexes
                        child_urls = self.extract_urls_from_sitemap(child_sitemap_url)
                        urls.extend(child_urls)
                        if len(self.discovered_urls) + len(urls) >= MAX_URLS: # Check limit frequently
                            logger.info(f"Reached MAX_URLS limit ({MAX_URLS}) during child sitemap processing.")
                            break
            elif "<urlset" in sitemap_content:
                # Regular sitemap
                logger.debug(f"{sitemap_url} appears to be a regular URL set.")
                root = ET.fromstring(sitemap_content)
                namespace = self.get_namespace(root.tag)

                url_elements = root.findall(f".//{namespace}url")
                logger.debug(f"Found {len(url_elements)} URL entries in {sitemap_url}")
                for url_element in url_elements:
                    loc = url_element.find(f"{namespace}loc")
                    if loc is not None and loc.text:
                        urls.append(loc.text)
                        if len(self.discovered_urls) + len(urls) >= MAX_URLS: # Check limit frequently
                             break # Stop processing this sitemap if limit reached
            else:
                logger.warning(f"Could not determine sitemap type for {sitemap_url}. Content snippet: {sitemap_content[:200]}")


        except ET.ParseError as e:
             logger.error(f"XML Parsing Error for sitemap {sitemap_url}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error parsing sitemap {sitemap_url}: {e}", exc_info=True)

        logger.debug(f"Finished extracting from {sitemap_url}. Found {len(urls)} URLs locally.")
        return urls

    def get_namespace(self, tag):
        """
        Extract namespace from XML tag

        Args:
            tag (str): XML tag

        Returns:
            str: Namespace prefix
        """
        if '}' in tag:
            namespace = tag.split('}')[0][1:]
            logger.debug(f"Detected XML namespace: {namespace}")
            return "{" + namespace + "}"
        logger.debug("No XML namespace detected in root tag.")
        return ""

    def crawl_site_for_urls(self, start_url):
        """
        Crawl a website to discover documentation pages

        Args:
            start_url (str): The starting URL for crawling

        Returns:
            list: List of discovered URLs
        """
        logger.info(f"Starting manual site crawl from: {start_url}")
        if start_url not in self.discovered_urls:
             self.discovered_urls.add(start_url)
             logger.debug(f"Added start URL to discovered set: {start_url}")
        
        queue = [start_url]
        processed_in_batch = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {}
            while queue and len(self.discovered_urls) < MAX_URLS:
                
                # Submit new tasks if workers are available and queue has items
                while len(futures) < MAX_WORKERS and queue:
                     url_to_process = queue.pop(0)
                     if url_to_process not in self.visited_urls:
                          logger.debug(f"Submitting task to scrape: {url_to_process}")
                          future = executor.submit(self.scrape_page, url_to_process)
                          futures[future] = url_to_process
                     else:
                          logger.debug(f"Skipping already visited URL from queue: {url_to_process}")


                # Process completed futures
                if not futures: # Break if no tasks are running or queued
                     if not queue:
                          logger.debug("Crawl queue and running futures are empty.")
                          break
                     else:
                          logger.debug("Waiting for running tasks to complete...")
                          time.sleep(0.1) # Avoid busy-waiting if queue has items but workers are full
                          continue # Go back to check futures

                done, _ = concurrent.futures.wait(futures.keys(), timeout=0.1, return_when=concurrent.futures.FIRST_COMPLETED)

                for future in done:
                    url_scraped = futures.pop(future) # Remove from tracking
                    processed_in_batch += 1
                    try:
                        new_urls_found = future.result()
                        logger.debug(f"Scrape result for {url_scraped}: Found {len(new_urls_found)} potential new links.")
                        added_count = 0
                        for url in new_urls_found:
                            # Double check conditions before adding
                            is_new = url not in self.discovered_urls
                            within_limit = len(self.discovered_urls) < MAX_URLS
                            
                            if is_new and within_limit:
                                self.discovered_urls.add(url)
                                queue.append(url)
                                added_count += 1
                                # logger.debug(f"Added new discovered URL: {url}") # Can be verbose
                            elif not is_new:
                                logger.debug(f"URL already discovered, not adding to queue: {url}")
                            elif not within_limit:
                                logger.info(f"Reached MAX_URLS limit ({MAX_URLS}). Stopping adding new URLs.")
                                # Clear the queue to stop processing further levels? Or just stop adding?
                                # Clearing queue is more definitive stop.
                                queue.clear() 
                                break # Stop processing links from this page

                        logger.debug(f"Added {added_count} new URLs to queue from {url_scraped}. Queue size: {len(queue)}, Discovered: {len(self.discovered_urls)}")

                    except Exception as e:
                        logger.error(f"Error processing scrape result for {url_scraped}: {e}", exc_info=True)
                
                # Optional: Add delay if desired, but concurrency might already pace it
                # logger.debug(f"Batch processed {processed_in_batch} pages. Queue: {len(queue)}, Discovered: {len(self.discovered_urls)}")
                # time.sleep(random.uniform(0.05, 0.1)) # Shorter delay ok with workers


        logger.info(f"Manual crawl finished. Total discovered URLs: {len(self.discovered_urls)}")
        return list(self.discovered_urls)

    def scrape_page(self, url):
        """
        Scrape a page to find links

        Args:
            url (str): URL to scrape

        Returns:
            list: List of discovered URLs on the page
        """
        # This check happens before submitting, but double check is safe.
        if url in self.visited_urls:
            logger.debug(f"Scrape request for already visited URL: {url}")
            return []
        
        self.visited_urls.add(url)
        logger.debug(f"Scraping page: {url}")
        new_urls = []

        try:
            response = self.session.get(url, timeout=TIMEOUT)
            status_code = response.status_code
            content_type = response.headers.get('Content-Type', '').lower()
            logger.debug(f"Scrape fetch status {status_code}, type '{content_type}' for {url}")

            # Only process HTML content
            if status_code != 200 or 'text/html' not in content_type:
                logger.debug(f"Skipping non-HTML or non-200 response for {url}")
                return new_urls

            # Handle potential large pages before parsing
            if len(response.content) > 5 * 1024 * 1024: # 5 MB limit for HTML parsing
                 logger.warning(f"HTML page {url} is very large ({len(response.content)} bytes). Skipping scrape.")
                 return new_urls

            soup = BeautifulSoup(response.text, 'html.parser')

            links_found = soup.find_all('a', href=True)
            logger.debug(f"Found {len(links_found)} anchor tags in {url}")

            for link in links_found:
                href = link['href']
                if not href or href.startswith('#') or href.lower().startswith('javascript:'):
                    logger.debug(f"Skipping empty, fragment, or javascript href: '{href}'")
                    continue

                absolute_url = urljoin(url, href)
                parsed_link_url = urlparse(absolute_url)

                # Only include URLs from the same domain (or subdomain if needed)
                # Using netloc checks for exact domain match. Adjust if subdomains are ok.
                if parsed_link_url.netloc == urlparse(self.base_url).netloc:
                    # Clean URL: remove fragments and query parameters
                    cleaned_url = urljoin(absolute_url, parsed_link_url.path) # Rebuilds without query/fragment
                    # Alternative cleaning:
                    # cleaned_url = absolute_url.split('#')[0].split('?')[0]

                    # Filter for likely documentation pages
                    link_text = link.text.strip()
                    # logger.debug(f"Checking internal link: {cleaned_url} (Text: '{link_text[:50]}...')")
                    if self.is_likely_documentation(cleaned_url, link_text):
                        if cleaned_url not in self.visited_urls and cleaned_url not in self.discovered_urls:
                            logger.debug(f"Found likely doc link to add: {cleaned_url}")
                            new_urls.append(cleaned_url)
                        # else: # Verbose
                        #    logger.debug(f"Doc link already seen/visited: {cleaned_url}")
                    # else: # Verbose
                    #    logger.debug(f"Filtered out (not doc criteria): {cleaned_url}")
                # else: # Verbose
                #     logger.debug(f"Skipping external link: {absolute_url}")

        except requests.exceptions.Timeout:
             logger.warning(f"Timeout scraping {url}")
        except requests.exceptions.RequestException as e:
             logger.warning(f"Request error scraping {url}: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error scraping {url}: {e}", exc_info=True)

        logger.debug(f"Finished scraping {url}. Found {len(new_urls)} new potential doc URLs.")
        return new_urls

    def is_likely_documentation(self, url, link_text=""):
        """
        Determine if a URL is likely to be a documentation page.
        (Keep this logic, but logging in scrape_page shows its effect)

        Args:
            url (str): URL to check
            link_text (str): The text of the link

        Returns:
            bool: True if the URL is likely documentation
        """
        # Basic check: ignore common non-doc file types early
        ignored_extensions = ['.pdf', '.zip', '.png', '.jpg', '.jpeg', '.gif', '.css', '.js', '.xml', '.json', '.svg', '.woff', '.ttf']
        if any(url.lower().endswith(ext) for ext in ignored_extensions):
            # logger.debug(f"[is_likely] Ignoring common non-doc extension: {url}")
            return False
            
        path = urlparse(url).path.lower()
        if not path or path == '/': # Ignore root path? Maybe allow if base_url is root.
            # Allow if it's the exact base URL?
            # if url == self.base_url: return True 
            # logger.debug(f"[is_likely] Ignoring root or empty path: {url}")
            return False # Often links back to homepage

        # Common documentation paths (more specific first)
        doc_indicators = [
            '/docs/', '/documentation/', '/api/', '/reference/', '/guide/', '/tutorial/',
            '/developer/', '/dev/', '/apis/', '/guides/', '/tutorials/',
            '/sdk/', '/lib/', '/library/', '/modules/', '/classes/', '/functions/', '/methods/',
            '/getting-started/', '/quickstart/', '/introduction/', '/concepts/',
            '/examples/', '/usage/', '/how-to/',
            '/manual/', '/handbook/', '/learn/', '/help/', '/support/',
            # Less common but possible
             '/kb/', '/knowledgebase/', '/faq/'
        ]

        # Common documentation file extensions (or lack thereof for clean URLs)
        doc_extensions = ['.html', '.htm', '.md', '.rst']

        # Check path segments
        path_segments = [seg for seg in path.split('/') if seg]
        if any(indicator.strip('/') in path_segments for indicator in doc_indicators):
            # logger.debug(f"[is_likely] Matched doc indicator in path segments: {url}")
            return True
            
        # Check full path prefix (less common now with segments)
        # if any(path.startswith(indicator) for indicator in doc_indicators):
        #    logger.debug(f"[is_likely] Matched doc indicator prefix: {url}")
        #    return True

        # Check if it likely ends like a doc file or directory (clean URL)
        ends_like_doc = path.endswith('/') or any(path.endswith(ext) for ext in doc_extensions)
        if ends_like_doc:
            # Optionally add keyword check in link text for these cases
            doc_keywords = [
                'documentation', 'docs', 'api', 'reference', 'guide', 'tutorial', 'developer',
                'getting started', 'quickstart', 'introduction', 'concepts', 'examples', 'usage',
                'sdk', 'library', 'module', 'class', 'function', 'method',
                'manual', 'handbook', 'learn', 'help', 'support', 'faq'
            ]
            # logger.debug(f"[is_likely] Ends like doc file/dir: {url}. Checking keywords in '{link_text[:50]}...'")
            if not link_text or any(keyword in link_text.lower() for keyword in doc_keywords):
                # logger.debug(f"[is_likely] Matched end and keywords (or no text): {url}")
                return True

        # logger.debug(f"[is_likely] No doc criteria met for: {url}")
        return False

    def generate_xml_sitemap(self):
        """
        Generate an XML sitemap from the discovered URLs

        Returns:
            str: XML sitemap content
        """
        logger.info(f"Generating XML sitemap for {len(self.discovered_urls)} discovered URLs.")
        root = ET.Element("urlset")
        root.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")

        for url in self.discovered_urls:
            url_element = ET.SubElement(root, "url")
            loc = ET.SubElement(url_element, "loc")
            loc.text = url

            # Optional: Add lastmod, changefreq, priority if needed
            # lastmod = ET.SubElement(url_element, "lastmod")
            # lastmod.text = datetime.now().strftime("%Y-%m-%d")
            # changefreq = ET.SubElement(url_element, "changefreq")
            # changefreq.text = "monthly"
            # priority = ET.SubElement(url_element, "priority")
            # priority.text = "0.8"

        xml_string = ET.tostring(root, encoding="unicode")
        logger.info("XML sitemap generation complete.")
        return xml_string