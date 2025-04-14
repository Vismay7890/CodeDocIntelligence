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
    USE_CUSTOM_EMBEDDINGS
)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class HashEmbeddingFunction(embedding_functions.EmbeddingFunction):
    """
    Custom embedding function using hash-based techniques for generating embeddings.
    This doesn't require external API calls and works fully locally.
    """
    def __init__(self):
        # Set a fixed dimension for the embeddings
        self.dimension = EMBEDDING_DIMENSION
        # Fixed seed for consistent embeddings across runs
        self.seed = 42
        np.random.seed(self.seed)
        # Pre-generate random projection vectors (this gives us semantic-like matching)
        self.projection_vectors = np.random.normal(0, 1, (self.dimension, 1000))
        
    def __call__(self, texts):
        """
        Generate embeddings for a list of texts using hash-based techniques
        
        Args:
            texts (list): List of texts to embed
            
        Returns:
            list: List of embeddings
        """
        try:
            # Handle empty texts
            if not texts:
                return []
            
            embeddings = []
            
            for text in texts:
                # Create a feature vector from the text
                feature_vector = self._extract_features(text)
                
                # Project the features to get embedding-like representation
                embedding = np.dot(self.projection_vectors, feature_vector)
                
                # Normalize to unit length (important for cosine similarity)
                embedding_norm = np.linalg.norm(embedding)
                if embedding_norm > 0:
                    embedding = embedding / embedding_norm
                
                # Convert to list and add to results
                embeddings.append(embedding.flatten().tolist())
            
            return embeddings
        except Exception as e:
            logger.error(f"Error generating hash embeddings: {e}")
            # Return zero embeddings as fallback
            return [[0.0] * self.dimension] * len(texts)
    
    def _extract_features(self, text):
        """
        Extract feature vector from text using various techniques
        
        Args:
            text (str): Input text
            
        Returns:
            numpy.ndarray: Feature vector
        """
        # Initialize feature vector (all zeros)
        feature_vec = np.zeros(1000)
        
        if not text:
            return feature_vec
        
        # Normalize text
        text = text.lower()
        
        # Extract word-level features
        words = re.findall(r'\b\w+\b', text)
        
        # Calculate word hashes and update feature vector
        for i, word in enumerate(words):
            # Get word hash
            word_hash = int(hashlib.md5(word.encode()).hexdigest(), 16) % 1000
            
            # Position-aware weighting (words at beginning/end matter more)
            position_weight = 1.0
            if i < len(words) * 0.2:  # First 20% of words
                position_weight = 1.5
            elif i > len(words) * 0.8:  # Last 20% of words
                position_weight = 1.2
                
            # Update feature at the hashed position
            feature_vec[word_hash] += position_weight
            
            # Add bigram features if possible
            if i < len(words) - 1:
                bigram = word + " " + words[i+1]
                bigram_hash = int(hashlib.md5(bigram.encode()).hexdigest(), 16) % 1000
                feature_vec[bigram_hash] += 0.5  # Lower weight for bigrams
        
        # Extract character n-gram features
        for n in [3, 4]:  # trigrams and quadgrams
            for i in range(len(text) - n + 1):
                ngram = text[i:i+n]
                ngram_hash = int(hashlib.md5(ngram.encode()).hexdigest(), 16) % 1000
                feature_vec[ngram_hash] += 0.2  # Low weight for character n-grams
        
        # Normalize the feature vector
        norm = np.linalg.norm(feature_vec)
        if norm > 0:
            feature_vec = feature_vec / norm
            
        return feature_vec


class DocumentEmbedder:
    """
    Service for generating embeddings from documentation content and storing them in ChromaDB.
    Uses OpenAI's embedding model for generating embeddings.
    """
    
    def __init__(self):
        """Initialize the embedder with ChromaDB and embedding function"""
        # Set up ChromaDB client
        self.client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIRECTORY)
        
        # Use our custom hash-based embedding function
        logger.info("Using custom hash-based embeddings")
        self.embedding_function = HashEmbeddingFunction()
        
        # Check for and create collection if it doesn't exist
        try:
            self.collection = self.client.get_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_function
            )
            logger.info(f"Connected to existing collection: {COLLECTION_NAME}")
        except Exception:
            logger.info(f"Creating new collection: {COLLECTION_NAME}")
            self.collection = self.client.create_collection(
                name=COLLECTION_NAME,
                embedding_function=self.embedding_function,
                metadata={"dimension": EMBEDDING_DIMENSION}
            )
        
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
    
    def process_documents(self, urls):
        """
        Process a list of URLs, extract content, and generate embeddings
        
        Args:
            urls (list): List of URLs to process
            
        Returns:
            int: Number of successfully processed documents
        """
        processed_count = 0
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_url = {executor.submit(self.process_single_document, url): url for url in urls}
            
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    result = future.result()
                    if result:
                        processed_count += 1
                except Exception as e:
                    logger.error(f"Error processing document {url}: {e}")
        
        return processed_count
    
    def process_single_document(self, url):
        """
        Process a single document URL
        
        Args:
            url (str): URL to process
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Generate a document ID from the URL
            doc_id = hashlib.md5(url.encode()).hexdigest()
            
            # Check if the document already exists in the collection
            try:
                existing = self.collection.get(ids=[doc_id])
                if existing and existing['ids']:
                    logger.info(f"Document already exists: {url}")
                    return True
            except Exception:
                pass  # If the document doesn't exist, continue processing
            
            # Fetch and extract content
            content = self.extract_content(url)
            if not content:
                logger.warning(f"No content extracted from {url}")
                return False
            
            # Split content into chunks for better retrieval
            chunks = self.chunk_text(content)
            if not chunks:
                logger.warning(f"No chunks generated for {url}")
                return False
            
            # Add document chunks to ChromaDB
            chunk_ids = [f"{doc_id}_{i}" for i in range(len(chunks))]
            metadata_list = [{"url": url, "chunk_index": i, "source": url} for i in range(len(chunks))]
            
            self.collection.add(
                ids=chunk_ids,
                documents=chunks,
                metadatas=metadata_list
            )
            
            logger.info(f"Successfully processed document: {url}")
            return True
            
        except Exception as e:
            logger.error(f"Error processing document {url}: {e}")
            return False
    
    def extract_content(self, url):
        """
        Extract content from a URL
        
        Args:
            url (str): URL to extract content from
            
        Returns:
            str: Extracted content
        """
        try:
            # First try trafilatura, which is good at getting main content
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                content = trafilatura.extract(downloaded, include_formatting=True, include_links=True)
                if content and len(content) > 100:  # Ensure we have meaningful content
                    return content
            
            # Fallback to a more basic approach if trafilatura fails
            response = self.session.get(url, timeout=TIMEOUT)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch {url}: HTTP {response.status_code}")
                return None
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Remove script, style, and header/footer elements
            for element in soup(['script', 'style', 'header', 'footer', 'nav']):
                element.decompose()
            
            # Try to find the main content first
            main_content = soup.find('main') or soup.find(id='content') or soup.find(id='main')
            
            if main_content:
                return main_content.get_text(separator=' ', strip=True)
            elif soup.body:
                # If no main content identified, use the body if it exists
                return soup.body.get_text(separator=' ', strip=True)
            else:
                # Fallback to just the whole document
                return soup.get_text(separator=' ', strip=True)
                
        except Exception as e:
            logger.error(f"Error extracting content from {url}: {e}")
            return None
    
    def chunk_text(self, text, chunk_size=1000, overlap=100):
        """
        Split text into overlapping chunks for better retrieval
        
        Args:
            text (str): Text to split
            chunk_size (int): Size of each chunk
            overlap (int): Overlap between chunks
            
        Returns:
            list: List of text chunks
        """
        if not text:
            return []
        
        # Clean and normalize text
        text = re.sub(r'\s+', ' ', text).strip()
        
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            end = min(start + chunk_size, text_length)
            
            # Try to find a sentence boundary for better chunks
            if end < text_length:
                # Look for sentence endings (.!?) followed by space
                sentence_end = max(
                    text.rfind('. ', start, end),
                    text.rfind('! ', start, end),
                    text.rfind('? ', start, end)
                )
                
                if sentence_end != -1:
                    end = sentence_end + 1  # Include the period
            
            # Add the chunk
            chunks.append(text[start:end].strip())
            
            # Move start position for next chunk, considering overlap
            start = end - overlap if end < text_length else text_length
        
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
        try:
            results = self.collection.query(
                query_texts=[query],
                n_results=k
            )
            
            # Format results for easier consumption
            documents = []
            if results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    metadata = results['metadatas'][0][i]
                    documents.append({
                        'content': doc,
                        'metadata': metadata,
                        'distance': results['distances'][0][i] if 'distances' in results else None
                    })
            
            return documents
        except Exception as e:
            logger.error(f"Error retrieving context: {e}")
            return []
    
    def get_stats(self):
        """
        Get statistics about the vector store
        
        Returns:
            dict: Statistics about the vector store
        """
        try:
            count = self.collection.count()
            return {
                "collection_name": COLLECTION_NAME,
                "document_count": count,
                "embedding_model": EMBEDDING_MODEL,
                "embedding_dimension": EMBEDDING_DIMENSION
            }
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {
                "collection_name": COLLECTION_NAME,
                "error": str(e)
            }
