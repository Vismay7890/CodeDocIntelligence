import os
import logging
import concurrent.futures
import requests
from bs4 import BeautifulSoup
import chromadb
from chromadb.config import Settings
from chromadb.utils import embedding_functions
import trafilatura
import hashlib
import re
import numpy as np
from config import (
    EMBEDDING_MODEL,
    EMBEDDING_DIMENSION,
    CHROMA_PERSIST_DIRECTORY,
    COLLECTION_NAME,
    TIMEOUT,
    USER_AGENT,
    MAX_WORKERS,
    USE_CUSTOM_EMBEDDINGS # This config isn't used here, HashEmbeddingFunction is hardcoded below
)

# Set up logging
# logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__) # Get logger instance

class HashEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """
    Very simple hash-based embedding function that works locally.
    """
    def __init__(self):
        # Set a fixed dimension for the embeddings
        self.dimension = EMBEDDING_DIMENSION
        logger.debug(f"HashEmbeddingFunction initialized with dimension: {self.dimension}")

    def __call__(self, texts):
        """
        Generate embeddings for a list of texts using hash-based techniques

        Args:
            texts (list): List of texts to embed

        Returns:
            list: List of embeddings
        """
        if not texts:
            logger.debug("HashEmbeddingFunction called with empty text list.")
            return []

        logger.debug(f"HashEmbeddingFunction generating embeddings for {len(texts)} texts.")
        embeddings = []
        for i, text in enumerate(texts):
            # logger.debug(f"Generating hash embedding for text {i+1}/{len(texts)}") # Can be very verbose
            embedding = self._create_simple_embedding(text)
            embeddings.append(embedding)

        logger.debug(f"HashEmbeddingFunction finished generating {len(embeddings)} embeddings.")
        return embeddings

    def _create_simple_embedding(self, text):
        """
        Create a simple deterministic embedding from text using hashing

        Args:
            text (str): Text to embed

        Returns:
            list: Embedding vector
        """
        embedding = [0.0] * self.dimension

        if not text:
            logger.debug("Creating zero embedding for empty text.")
            return embedding

        # Normalize and tokenize text
        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)
        # logger.debug(f"Found {len(words)} words for hash embedding.") # Verbose

        # Generate embedding based on word hashes
        for i, word in enumerate(words):
            hash_obj = hashlib.md5(word.encode('utf-8'))
            hash_int = int(hash_obj.hexdigest(), 16)

            # Use the hash to determine which dimensions to update and values
            for j in range(min(10, self.dimension)):  # Limit updates based on dimension
                dim_index = (hash_int + j) % self.dimension
                # More robust value calculation (avoiding pure modulo bias)
                val = (int(hash_obj.hexdigest()[j*2:(j+1)*2], 16) / 255.0) * 2.0 - 1.0 # Value between -1 and 1 based on different hash parts
                embedding[dim_index] += val

        # Normalize the embedding to unit length (L2 normalization)
        norm_sq = sum(x**2 for x in embedding)
        if norm_sq > 1e-9: # Avoid division by zero or near-zero
             norm = norm_sq ** 0.5
             embedding = [x / norm for x in embedding]
        # else: # Verbose
             # logger.debug("Embedding norm is near zero, not normalizing.")


        return embedding


class DocumentEmbedder:
    """
    Service for generating embeddings from documentation content and storing them in ChromaDB.
    Uses a hash-based embedding function.
    """

    def __init__(self):
        """Initialize the embedder with ChromaDB and embedding function"""
        logger.info("Initializing DocumentEmbedder...")
        # Set up ChromaDB client
        logger.debug(f"Using ChromaDB persistent path: {CHROMA_PERSIST_DIRECTORY}")
        self.client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIRECTORY)

        # Use our custom hash-based embedding function
        logger.info(f"Using custom HashEmbeddingFunction with dimension {EMBEDDING_DIMENSION}.")
        self.embedding_function = HashEmbeddingFunction()

        # Get or create collection
        try:
            logger.debug(f"Attempting to get collection: {COLLECTION_NAME}")
            # Pass the function instance directly
            self.collection = self.client.get_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_function # Pass instance
            )
            logger.info(f"Connected to existing ChromaDB collection: {COLLECTION_NAME}")
        except Exception as e:
            logger.warning(f"Collection '{COLLECTION_NAME}' not found or error getting it: {e}. Attempting to create.")
            try:
                 # Pass the function instance directly
                self.collection = self.client.create_collection(
                    name=COLLECTION_NAME,
                    embedding_function=self.embedding_function, # Pass instance
                    metadata={"hnsw:space": "cosine"} # Specify index type if needed, cosine is common
                )
                logger.info(f"Successfully created new ChromaDB collection: {COLLECTION_NAME}")
            except Exception as create_exc:
                 logger.error(f"Failed to create collection '{COLLECTION_NAME}': {create_exc}", exc_info=True)
                 raise # Re-raise the exception if collection creation fails

        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        logger.info("DocumentEmbedder initialized successfully.")

    def process_documents(self, urls):
        """
        Process a list of URLs, extract content, and generate embeddings

        Args:
            urls (list): List of URLs to process

        Returns:
            int: Number of successfully processed documents
        """
        if not urls:
             logger.warning("process_documents called with empty URL list.")
             return 0
             
        processed_count = 0
        total_urls = len(urls)
        logger.info(f"Starting processing of {total_urls} documents using up to {MAX_WORKERS} workers.")

        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(self.process_single_document, url): url for url in urls}

            for i, future in enumerate(concurrent.futures.as_completed(future_to_url)):
                url = future_to_url[future]
                logger.debug(f"Processing future {i+1}/{total_urls} for URL: {url}")
                try:
                    result = future.result() # Will be True if successful, False otherwise
                    if result:
                        processed_count += 1
                        logger.info(f"Successfully processed: {url} ({processed_count}/{total_urls})")
                    else:
                        logger.warning(f"Processing failed or skipped for: {url}")
                except Exception as e:
                    # This catches errors *raised* from process_single_document
                    logger.error(f"Exception occurred while processing future for {url}: {e}", exc_info=True)

        logger.info(f"Finished processing batch. Successfully processed {processed_count} out of {total_urls} URLs.")
        return processed_count

    def process_single_document(self, url):
        """
        Process a single document URL

        Args:
            url (str): URL to process

        Returns:
            bool: True if successful, False otherwise
        """
        logger.debug(f"[{url}] Starting process_single_document.")
        try:
            # Simple validation check
            if not url or not isinstance(url, str) or not url.startswith('http'):
                logger.warning(f"[{url}] Invalid URL format. Skipping.")
                return False

            # Generate a document ID from the URL
            doc_id = hashlib.md5(url.encode()).hexdigest()
            logger.debug(f"[{url}] Generated doc ID: {doc_id}")

            # Check if the document *chunks* already exist (more reliable than checking for just doc_id)
            try:
                # Check for the first potential chunk ID
                potential_first_chunk_id = f"{doc_id}_0"
                existing = self.collection.get(ids=[potential_first_chunk_id], limit=1)
                if existing and existing['ids']:
                    logger.info(f"[{url}] Document chunk {potential_first_chunk_id} already exists. Skipping processing.")
                    return True # Treat as successfully processed if already exists
            except Exception as get_exc:
                 # Handle potential errors during the get call, e.g., connection issues
                 logger.warning(f"[{url}] Error checking for existing document chunk {potential_first_chunk_id}: {get_exc}. Proceeding with processing.")
                 # Don't pass here, proceed as if it doesn't exist


            # Fetch and extract content
            logger.debug(f"[{url}] Starting content extraction.")
            content = self.extract_content(url, timeout=20) # Increased timeout slightly for content pages
            if not content:
                # extract_content logs warnings internally
                logger.warning(f"[{url}] No content extracted or extraction failed.")
                return False
            logger.debug(f"[{url}] Content extracted (length: {len(content)}). Starting chunking.")

            # Limit content size (redundant if extract_content does it, but safe)
            MAX_CONTENT_LEN = 500000
            if len(content) > MAX_CONTENT_LEN:
                content = content[:MAX_CONTENT_LEN]
                logger.warning(f"[{url}] Content truncated to {MAX_CONTENT_LEN} chars before chunking.")

            # Split content into chunks
            chunks = self.chunk_text(content, chunk_size=500, overlap=50) # Adjusted overlap
            if not chunks:
                logger.warning(f"[{url}] No chunks generated from content.")
                return False
            logger.debug(f"[{url}] Generated {len(chunks)} chunks.")

            # Limit number of chunks
            MAX_CHUNKS = 100 # Increased limit slightly
            if len(chunks) > MAX_CHUNKS:
                chunks = chunks[:MAX_CHUNKS]
                logger.warning(f"[{url}] Number of chunks limited to {MAX_CHUNKS}.")

            # Prepare data for ChromaDB
            chunk_ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
            metadata_list = [{"url": url, "chunk_index": i, "source": url} for i in range(len(chunks))]
            # Ensure documents are strings
            documents_list = [str(chunk) for chunk in chunks]

            # --- Critical Section: Add to ChromaDB ---
            logger.debug(f"[{url}] Attempting to add {len(chunks)} chunks to ChromaDB. First ID: {chunk_ids[0]}")
            try:
                self.collection.add(
                    ids=chunk_ids,
                    documents=documents_list, # Use the validated list
                    metadatas=metadata_list
                    # Embeddings are generated automatically by the function
                )
                logger.debug(f"[{url}] Successfully added {len(chunks)} chunks to ChromaDB.")
                # ---- End Critical Section ----

                # NOTE: The original code logged success *before* the return,
                # moved logging to process_documents for clarity on completion.
                return True # Indicate success

            except Exception as db_add_exc:
                 # Catch errors specifically from the add operation
                 logger.error(f"[{url}] CRITICAL: Failed to add chunks to ChromaDB: {db_add_exc}", exc_info=True)
                 # Depending on the error, you might want to attempt cleanup or just report failure
                 return False # Indicate failure


        except Exception as e:
            # Catch any other unexpected errors during the process
            logger.error(f"[{url}] Unexpected error in process_single_document: {e}", exc_info=True)
            return False

    def extract_content(self, url, timeout=None):
        """
            Extract content from a URL using requests for fetching and trafilatura for extraction.

            Args:
                url (str): URL to extract content from
                timeout (int, optional): Timeout in seconds for fetching.

            Returns:
                str: Extracted content or None if failed.
        """
        effective_timeout = timeout if timeout is not None else TIMEOUT
        logger.debug(f"[{url}] Attempting content extraction with timeout {effective_timeout}s.")
        downloaded_html = None # Variable to store the fetched HTML

        try:
            # 1. Fetch content using requests session for control over timeout/headers
            logger.debug(f"[{url}] Fetching URL with requests session...")
            response = self.session.get(url, timeout=effective_timeout) # self.session already has headers
            logger.debug(f"[{url}] Requests fetch status: {response.status_code}")
            response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                 logger.warning(f"[{url}] Content type is not HTML ('{content_type}'). Skipping extraction.")
                 return None

            # Check size before reading potentially huge content
            MAX_DOWNLOAD_SIZE = 5 * 1024 * 1024 # 5MB limit for raw download
            if int(response.headers.get('Content-Length', 0)) > MAX_DOWNLOAD_SIZE:
                 logger.warning(f"[{url}] Content-Length ({response.headers.get('Content-Length')}) exceeds limit {MAX_DOWNLOAD_SIZE}. Skipping.")
                 return None
            
            downloaded_html = response.text

            # Additional size check after reading text (in case Content-Length was missing/wrong)
            if len(downloaded_html) > MAX_DOWNLOAD_SIZE:
                logger.warning(f"[{url}] Actual downloaded content size ({len(downloaded_html)}) exceeds limit {MAX_DOWNLOAD_SIZE}. Truncating.")
                downloaded_html = downloaded_html[:MAX_DOWNLOAD_SIZE]

            if not downloaded_html:
                 logger.warning(f"[{url}] Fetched HTML content is empty.")
                 return None

            # 2. Try Trafilatura extraction on the fetched HTML
            logger.debug(f"[{url}] Requests fetch successful. Trying Trafilatura extraction...")
            # Pass the HTML content directly to extract
            content = trafilatura.extract(
                downloaded_html,
                include_comments=False,
                include_tables=True,
                favor_precision=True,
                output_format='txt',
                include_formatting=False,
                include_links=False
                # url=url # Optionally provide the original URL as metadata hint to trafilatura
            )

            if content and len(content.strip()) > 50:
                logger.info(f"[{url}] Trafilatura extracted content successfully (length: {len(content)}).")
                return content.strip()
            else:
                logger.warning(f"[{url}] Trafilatura extracted very little or no content (length: {len(content or '')}). Falling back to BeautifulSoup.")
                # Fall through to BeautifulSoup fallback using the already downloaded_html


            # 3. Fallback to basic BeautifulSoup if Trafilatura failed on fetched HTML
            logger.debug(f"[{url}] Trafilatura failed or yielded insufficient content. Using BeautifulSoup fallback on fetched HTML.")
            
            # We already have downloaded_html from the requests fetch above
            soup = BeautifulSoup(downloaded_html, 'html.parser')

            # Remove noise elements
            for element in soup(['script', 'style', 'header', 'footer', 'nav', 'aside', 'form', 'noscript']):
                element.decompose()

            # Try common main content selectors (same logic as before)
            main_content = soup.find('main') or \
                           soup.find('article') or \
                           soup.find(role='main') or \
                           soup.find(id='main') or \
                           soup.find(id='content') or \
                           soup.find(class_='content') or \
                           soup.find(class_='main-content') 

            body_text = ""
            if main_content:
                logger.debug(f"[{url}] Fallback found main content element: {main_content.name}")
                body_text = main_content.get_text(separator=' ', strip=True)
            elif soup.body:
                logger.debug(f"[{url}] Fallback using full body text.")
                body_text = soup.body.get_text(separator=' ', strip=True)
            else:
                 logger.warning(f"[{url}] Fallback could not find main content or body.")
                 return None # No useful content found

            if len(body_text) > 50:
                 logger.info(f"[{url}] Fallback BeautifulSoup extracted content successfully (length: {len(body_text)}).")
                 return body_text
            else:
                 logger.warning(f"[{url}] Fallback BeautifulSoup extracted very little content (length: {len(body_text)}).")
                 return None


        except requests.exceptions.Timeout:
             logger.warning(f"[{url}] Timeout during requests fetch.")
             return None
        except requests.exceptions.HTTPError as e:
             logger.warning(f"[{url}] HTTP error during requests fetch: {e.response.status_code} {e.response.reason}")
             return None
        except requests.exceptions.RequestException as e:
             logger.warning(f"[{url}] Request error during requests fetch: {e}")
             return None
        except Exception as e:
            # Catch errors during extraction (Trafilatura or BS4) or other unexpected issues
            logger.error(f"[{url}] Unexpected error during content extraction process: {e}", exc_info=True)
            return None

    def chunk_text(self, text, chunk_size=500, overlap=50):
        """
        Split text into overlapping chunks. Tries to respect sentence boundaries.

        Args:
            text (str): Text to split
            chunk_size (int): Target size of each chunk
            overlap (int): Overlap between chunks

        Returns:
            list: List of text chunks
        """
        if not text:
            logger.warning("chunk_text called with empty text.")
            return []

        logger.debug(f"Starting chunking: text length {len(text)}, chunk_size {chunk_size}, overlap {overlap}")

        text = re.sub(r'\n\s*\n', '\n', text)
        text = re.sub(r'[ \t]+', ' ', text).strip()

        chunks = []
        start_index = 0
        text_length = len(text)

        while start_index < text_length:
            end_index = min(start_index + chunk_size, text_length)
            best_end_index = end_index # Default end

            # Try to find a better end point only if not at the very end
            if end_index < text_length:
                # Look backwards from end_index for sentence terminators or double newlines
                # Search range adjusted slightly to avoid missing breaks right at the edge
                search_start = max(start_index, end_index - chunk_size // 2) # Don't look too far back
                sentence_ends = [m.start() + 1 for m in re.finditer(r'[.!?]\s', text[search_start:end_index + 20])]
                para_ends = [m.start() + 1 for m in re.finditer(r'\n\n', text[search_start:end_index + 20])]
                
                # Correct indices relative to the original text start_index
                possible_ends = [search_start + p for p in sentence_ends + para_ends if search_start + p <= end_index and search_start + p > start_index]

                if possible_ends:
                    best_end_index = max(possible_ends) 
                # If no good break found, stick with the original end_index

            # Ensure end index is valid and didn't somehow regress
            best_end_index = max(best_end_index, start_index + 1) # Must advance at least 1 char if possible
            best_end_index = min(best_end_index, text_length) # Cannot go past end

            chunk = text[start_index:best_end_index].strip()

            if chunk:
                chunks.append(chunk)

            # --- NEW ADVANCEMENT LOGIC ---
            # Calculate the desired start of the next chunk
            next_start_candidate = best_end_index - overlap

            # Ensure the next start index *always* advances beyond the current start index
            # unless we have processed the entire text.
            if best_end_index < text_length:
                start_index = max(next_start_candidate, start_index + 1)
            else:
                # We've reached the end of the text with the last chunk
                start_index = text_length # Ensure loop termination
            # --- END NEW LOGIC ---

            # Remove the old safety break - the loop should terminate correctly now
            # if len(chunks) > 10000:
            #     logger.error("Chunking limit exceeded. Potential infinite loop detected.")
            #     break

        logger.debug(f"Finished chunking. Generated {len(chunks)} chunks.")
        # Remove the stall warning as the new logic should prevent stalling
        # if next_start <= start_index and best_end_index < text_length: ...
        
        return chunks


    def retrieve_relevant_context(self, query, k=5):
        """
        Retrieve relevant context for a query

        Args:
            query (str): Query text
            k (int): Number of chunks to retrieve

        Returns:
            list: List of relevant document chunks with metadata
        """
        logger.info(f"Retrieving {k} relevant contexts for query: '{query[:100]}...'")
        if not query:
             logger.warning("retrieve_relevant_context called with empty query.")
             return []
             
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=k,
                include=['documents', 'metadatas', 'distances'] # Request distances too
            )
            logger.debug(f"ChromaDB query returned {len(results.get('ids', [[]])[0])} results.")

            documents = []
            if results and results.get('ids') and results['ids'][0]: # Check if results are valid
                ids = results['ids'][0]
                docs = results['documents'][0]
                metadatas = results['metadatas'][0]
                distances = results.get('distances', [None]*len(ids))[0] # Handle if distances are missing

                for i in range(len(ids)):
                     doc_info = {
                        'id': ids[i],
                        'content': docs[i],
                        'metadata': metadatas[i],
                        'distance': distances[i] if distances else None # Add distance if available
                     }
                     documents.append(doc_info)
                     # logger.debug(f"Retrieved context: ID {ids[i]}, Dist {distances[i] if distances else 'N/A'}, Meta {metadatas[i]}") # Verbose

            logger.info(f"Retrieved {len(documents)} context documents.")
            return documents
        except Exception as e:
            logger.error(f"Error retrieving context from ChromaDB: {e}", exc_info=True)
            return []

    def get_stats(self):
        """
        Get statistics about the vector store

        Returns:
            dict: Statistics about the vector store
        """
        logger.debug("Fetching vector store stats...")
        try:
            count = self.collection.count()
            # peek_result = self.collection.peek(limit=1) # Get sample item if needed
            stats = {
                "collection_name": self.collection.name, # Use actual collection name
                "document_count (chunks)": count,
                "embedding_model": "Custom Hash", # Or derive from function if possible
                "embedding_dimension": EMBEDDING_DIMENSION,
                "persistent_path": CHROMA_PERSIST_DIRECTORY
                # Add more stats if available, e.g., index type from metadata if set
            }
            logger.info(f"Vector store stats retrieved: {stats}")
            return stats
        except Exception as e:
            logger.error(f"Error getting vector store stats: {e}", exc_info=True)
            return {
                "collection_name": COLLECTION_NAME, # Use config as fallback
                "error": f"Failed to get stats: {str(e)}"
            }