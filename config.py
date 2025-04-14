import os

# OpenAI API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
DEFAULT_MODEL = "gpt-3.5-turbo"

# Embedding Model Configuration
EMBEDDING_MODEL = "text-embedding-ada-002"  # OpenAI embedding model
EMBEDDING_DIMENSION = 1536  # text-embedding-ada-002 has 1536 dimensions

# Vector Store Configuration
CHROMA_PERSIST_DIRECTORY = "chroma_db"
COLLECTION_NAME = "code_documentation"

# Crawler Configuration
MAX_URLS = 1000  # Maximum number of URLs to crawl
MAX_WORKERS = 2  # Default to 2 workers
TIMEOUT = 30  # Timeout in seconds for web requests
USER_AGENT = "Mozilla/5.0 (compatible; CodeDocumentationCrawler/1.0)"

# Query Engine Configuration
MAX_TOKENS = 1024
TEMPERATURE = 0.3
