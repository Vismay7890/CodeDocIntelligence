import os
import logging
from flask import Flask, render_template, request, jsonify, session
from services.crawler import SitemapCrawler
from services.embedder import DocumentEmbedder
from services.query_engine import QueryEngine
from config import OPENAI_API_KEY, DEFAULT_MODEL

# Set up logging
logging.basicConfig(level=logging.DEBUG, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SESSION_SECRET", "dev-secret-key")

# Initialize services
crawler = SitemapCrawler()
embedder = DocumentEmbedder()
query_engine = QueryEngine(model=DEFAULT_MODEL, api_key=OPENAI_API_KEY)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/crawl', methods=['POST'])
def crawl_site():
    """Crawl a documentation site and generate sitemap"""
    data = request.json
    base_url = data.get('base_url')
    
    if not base_url:
        return jsonify({"error": "Base URL is required"}), 400
    
    try:
        logger.info(f"Starting crawl for: {base_url}")
        urls = crawler.crawl(base_url)
        session['urls'] = urls  # Store URLs in session for processing
        return jsonify({
            "message": f"Crawled {len(urls)} URLs",
            "url_count": len(urls),
            "sample_urls": urls[:5] if urls else []
        })
    except Exception as e:
        logger.error(f"Crawl error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/process', methods=['POST'])
def process_documents():
    """Process crawled URLs and generate embeddings"""
    if 'urls' not in session or not session['urls']:
        return jsonify({"error": "No URLs found. Please crawl a site first."}), 400
    
    try:
        logger.info(f"Processing {len(session['urls'])} URLs")
        urls = session['urls']
        
        # Process in batches to avoid timeout
        batch_size = min(50, len(urls))
        selected_urls = urls[:batch_size]
        
        # Process documents and generate embeddings
        processed_count = embedder.process_documents(selected_urls)
        
        # Update session with remaining URLs
        session['urls'] = urls[batch_size:]
        
        return jsonify({
            "message": f"Processed {processed_count} documents",
            "remaining": len(session['urls']),
            "processed": processed_count
        })
    except Exception as e:
        logger.error(f"Processing error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/query', methods=['POST'])
def query():
    """Query the RAG system with a user question"""
    data = request.json
    query_text = data.get('query')
    
    if not query_text:
        return jsonify({"error": "Query text is required"}), 400
    
    try:
        logger.info(f"Processing query: {query_text}")
        
        # Get context from vector store
        context_docs = embedder.retrieve_relevant_context(query_text, k=5)
        
        # Generate response using OpenAI
        response = query_engine.generate_response(query_text, context_docs)
        
        return jsonify({
            "answer": response["answer"],
            "sources": response["sources"]
        })
    except Exception as e:
        logger.error(f"Query error: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/status', methods=['GET'])
def status():
    """Get the status of the vector store"""
    try:
        stats = embedder.get_stats()
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Status error: {str(e)}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
