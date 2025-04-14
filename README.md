# Code Documentation RAG Assistant

A RAG-based code documentation assistant that crawls documentation websites, generates embeddings, and provides accurate answers to code-related queries using LLMs.

## Features

- Multi-CPU crawler that generates sitemaps from documentation websites
- Local hash-based embedding generation (no external API required for embeddings)
- ChromaDB vector database for efficient storage and retrieval
- Groq LLM for generating responses to user queries
- Responsive web interface

## How to Run Locally

### Prerequisites

- Python 3.10+
- PostgreSQL database
- Groq API key

### Installation Steps

1. Clone this repository:
   ```
   git clone <repository-url>
   cd code-documentation-assistant
   ```

2. Install the required packages:
   ```
   pip install -r requirements.txt
   ```

3. Set up environment variables:
   ```
   export GROQ_API_KEY=your_groq_api_key
   export DATABASE_URL=postgresql://username:password@localhost:5432/dbname
   ```

4. Run the application:
   ```
   gunicorn --bind 0.0.0.0:5000 --reuse-port --reload main:app
   ```

5. Open your browser and go to `http://localhost:5000`

## Usage Guide

### 1. Crawl a Documentation Site

- Enter the URL of a documentation website in the "Base URL" field
- Click "Start Crawling"
- Wait for the crawler to finish

### 2. Generate Embeddings

- After crawling is complete, click "Process Documents"
- The system will extract content from the crawled URLs and generate embeddings
- This process uses local hash-based embeddings so no API call is needed

### 3. Ask Questions

- Once embeddings are generated, you can ask questions in the query field
- The system will retrieve relevant documentation and generate an answer
- The answer includes sources for verification

## Architecture

The application is built with a modular architecture:

- `app.py`: Main Flask application
- `services/crawler.py`: Multi-CPU crawler for generating sitemaps
- `services/embedder.py`: Custom hash-based embedding generation
- `services/query_engine.py`: Groq-based query engine for generating responses

## How It Works

1. **Crawling**: The system crawls a documentation website to discover pages using robots.txt and sitemap.xml or by following links.

2. **Embedding Generation**: Content is extracted from discovered pages, split into chunks, and embedded using a custom hash-based embedding function.

3. **Storage**: Embeddings and document chunks are stored in ChromaDB.

4. **Retrieval**: When a query is received, the system finds the most relevant chunks using vector similarity.

5. **Response Generation**: Relevant chunks are passed to the Groq LLM along with the query to generate a response.

## Troubleshooting

- **Database issues**: Ensure your PostgreSQL database is running and the connection string is correct.
- **Groq API key**: Make sure your Groq API key is valid and has sufficient rate limits.
- **Crawling issues**: Some websites may have robots.txt restrictions - consider respecting these and focusing on publicly accessible documentation sites.

## Local Embedding System

The system uses a custom hash-based embedding function that works entirely locally:

1. Tokenizes text into words and n-grams
2. Generates hash values for each token
3. Uses hashes to create a deterministic embedding vector
4. Normalizes the vector for consistent similarity calculations

This approach provides decent retrieval performance without requiring external API calls.