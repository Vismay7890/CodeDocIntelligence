import os
import logging
from flask import Flask, render_template, request, jsonify, session
from services.crawler import SitemapCrawler
from services.embedder import DocumentEmbedder
from services.query_engine import QueryEngine
from config import GROQ_API_KEY, DEFAULT_MODEL, MAX_URLS_TO_PROCESS_PER_REQUEST # Added new config

# Set up logging (make sure this runs before other modules import logging)
logging.basicConfig(level=logging.DEBUG,
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # Get logger instance for app

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key") # Ensure this is set securely in production
if app.secret_key == "dev-secret-key":
    logger.warning("Using default Flask session secret key. Set SESSION_SECRET environment variable for production.")

# Initialize services
logger.info("Initializing services...")
try:
    crawler = SitemapCrawler()
    embedder = DocumentEmbedder()
    query_engine = QueryEngine(model=DEFAULT_MODEL, api_key=GROQ_API_KEY)
    logger.info("Services initialized successfully.")
except Exception as e:
    logger.critical(f"Failed to initialize services: {e}", exc_info=True)
    # Depending on the severity, you might want to exit or handle this gracefully
    raise # Re-raise to stop the app if services are essential


@app.route('/')
def index():
    logger.debug("Serving index page.")
    return render_template('index.html')

@app.route('/api/crawl', methods=['POST'])
def crawl_site():
    """Crawl a documentation site and generate sitemap"""
    logger.info("Received request for /api/crawl")
    data = request.json
    base_url = data.get('base_url')
    logger.debug(f"Received base_url: {base_url}")

    if not base_url or not isinstance(base_url, str) or not base_url.startswith('http'):
        logger.warning("Invalid or missing base_url.")
        return jsonify({"error": "Valid base_url starting with http(s) is required"}), 400

    try:
        logger.info(f"Starting crawl process for: {base_url}")
        urls = crawler.crawl(base_url) # This now returns the list
        
        # Store URLs in session for processing
        session['urls'] = urls
        logger.info(f"Stored {len(urls)} URLs in session.")
        logger.debug(f"Session URLs sample: {session.get('urls', [])[:5]}")

        return jsonify({
            "message": f"Crawling initiated. Found {len(urls)} potential URLs.",
            "url_count": len(urls),
            "sample_urls": urls[:10] # Show a few more samples
        })
    except Exception as e:
        logger.error(f"Error during crawl for {base_url}: {str(e)}", exc_info=True)
        return jsonify({"error": f"An internal error occurred during crawling: {str(e)}"}), 500

@app.route('/api/process', methods=['POST'])
def process_documents():
    """Process crawled URLs and generate embeddings"""
    logger.info("Received request for /api/process")
    data = request.json or {}
    manual_urls = data.get('manual_urls', [])
    
    urls_to_process = []
    source = "none"

    # Determine the source of URLs
    if manual_urls:
        if isinstance(manual_urls, list):
             urls_to_process = manual_urls
             source = "manual"
             logger.info(f"Processing {len(urls_to_process)} manually provided URLs.")
        else:
             logger.warning("Received non-list data for manual_urls.")
             return jsonify({"error": "manual_urls must be a list"}), 400
    elif 'urls' in session and session['urls']:
        # Retrieve URLs from session (could be large, handle carefully)
        session_urls = session.get('urls', [])
        if session_urls: # Check if list is not empty
            urls_to_process = session_urls
            source = "session"
            logger.info(f"Processing {len(urls_to_process)} URLs found in session.")
        else:
             logger.warning("URLs key found in session, but the list is empty.")
             # Fall through to sample URLs if session is empty
    
    # Fallback to sample URLs if no other source provided URLs
    if not urls_to_process:
        logger.warning("No URLs found in session or manual input. Using sample URLs for testing.")
        # Use updated/verified sample URLs if possible
        sample_urls = [
            "https://python.langchain.com/docs/introduction", # Updated URL
            "https://python.langchain.com/docs/expression_language/", # Example of another section
            "https://docs.python.org/3/tutorial/index.html",
            "https://docs.python.org/3/library/index.html",
            "https://docs.python.org/3/reference/index.html" # Add another Python doc
        ]
        urls_to_process = sample_urls
        source = "sample"
        logger.info(f"Using {len(urls_to_process)} sample URLs.")

    if not urls_to_process:
        logger.error("URL list for processing is unexpectedly empty after all checks.")
        return jsonify({"error": "No URLs available to process."}), 400

    try:
        # Process in batches to avoid long requests and manage session data
        batch_size = MAX_URLS_TO_PROCESS_PER_REQUEST # Use config value
        
        urls_in_batch = urls_to_process[:batch_size]
        remaining_urls = urls_to_process[batch_size:]
        
        logger.info(f"Processing batch of {len(urls_in_batch)} URLs (Source: {source}).")
        logger.debug(f"URLs in this batch: {urls_in_batch}")

        # Process documents and generate embeddings
        processed_count = embedder.process_documents(urls_in_batch) # This calls the embedder service

        # Update session only if the source was the session
        if source == "session":
            session['urls'] = remaining_urls
            session.modified = True # Explicitly mark session as modified
            logger.info(f"Updated session. {len(remaining_urls)} URLs remaining.")
        elif source == "manual" or source == "sample":
             logger.info("Manual or sample URLs processed, session not updated.")

        return jsonify({
            "message": f"Processed batch of {len(urls_in_batch)} URLs. Successfully embedded {processed_count}.",
            "processed_in_batch": processed_count,
            "urls_processed_in_batch": urls_in_batch, # Show which URLs were attempted
            "remaining_in_session": len(remaining_urls) if source == "session" else 0 # Only relevant if using session
        })
    except Exception as e:
        logger.error(f"Error during document processing: {str(e)}", exc_info=True)
        # Attempt to clear session URLs if processing fails badly? Maybe not.
        return jsonify({"error": f"An internal error occurred during processing: {str(e)}"}), 500

@app.route('/api/query', methods=['POST'])
def query():
    """Query the RAG system with a user question"""
    logger.info("Received request for /api/query")
    data = request.json
    query_text = data.get('query')
    logger.debug(f"Received query: '{query_text[:100]}...'")

    if not query_text or not isinstance(query_text, str):
        logger.warning("Missing or invalid query text.")
        return jsonify({"error": "Query text is required and must be a string"}), 400

    try:
        # 1. Retrieve relevant context from vector store
        logger.debug("Retrieving relevant context...")
        context_docs = embedder.retrieve_relevant_context(query_text, k=5) # k=5 is reasonable default
        if not context_docs:
             logger.warning(f"No relevant context found for query: '{query_text[:100]}...'")
             # Decide how to handle: answer without context or inform user?
             # Option 1: Answer without context (might hallucinate)
             # response = query_engine.generate_response(query_text, []) 
             # Option 2: Inform user
             return jsonify({
                 "answer": "I couldn't find specific documentation context for your query. Please try rephrasing or asking about topics covered in the indexed documents.",
                 "sources": []
             }), 200 # Or maybe 404 if desired


        logger.debug(f"Retrieved {len(context_docs)} context documents.")

        # 2. Generate response using LLM with context
        logger.debug("Generating response using query engine...")
        response = query_engine.generate_response(query_text, context_docs) # Pass context to engine
        logger.debug(f"Generated answer: '{response['answer'][:100]}...'")
        logger.debug(f"Sources: {response['sources']}")

        return jsonify({
            "answer": response["answer"],
            "sources": response["sources"] # Include sources returned by query engine
        })
    except Exception as e:
        logger.error(f"Error during query processing: {str(e)}", exc_info=True)
        return jsonify({"error": f"An internal error occurred during query processing: {str(e)}"}), 500

@app.route('/api/status', methods=['GET'])
def status():
    """Get the status of the vector store"""
    logger.info("Received request for /api/status")
    try:
        stats = embedder.get_stats()
        logger.debug(f"Retrieved status: {stats}")
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error getting status: {str(e)}", exc_info=True)
        return jsonify({"error": f"An internal error occurred while getting status: {str(e)}"}), 500

# Add a config variable for batch processing size
# In config.py add:
# MAX_URLS_TO_PROCESS_PER_REQUEST = 50 # Or another number

if __name__ == '__main__':
    # Consider using waitress or gunicorn for production instead of Flask dev server
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    debug_mode = os.environ.get('FLASK_DEBUG', 'true').lower() == 'true' # Default to debug true locally
    
    logger.info(f"Starting Flask server on {host}:{port} (Debug Mode: {debug_mode})")
    app.run(host=host, port=port, debug=debug_mode)