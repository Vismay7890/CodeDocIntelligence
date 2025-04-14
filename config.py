import os

# API Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# Model Configuration
USE_GROQ = True  # Set to True to use Groq, False to use OpenAI
DEFAULT_MODEL = "llama3-8b-8192" if USE_GROQ else "gpt-3.5-turbo"

# Embedding Model Configuration
USE_CUSTOM_EMBEDDINGS = True  # Set to True to use our own embedding function
EMBEDDING_MODEL = "custom-hash-embeddings"
EMBEDDING_DIMENSION = 768  # Fixed dimension for our custom embeddings

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
