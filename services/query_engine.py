import os
import logging
import groq
from config import (
    GROQ_API_KEY, 
    DEFAULT_MODEL, 
    MAX_TOKENS, 
    TEMPERATURE
)

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

class QueryEngine:
    """
    Engine for generating responses to user queries using the RAG approach.
    Uses Groq's API to generate responses based on retrieved context.
    """
    
    def __init__(self, model=DEFAULT_MODEL, api_key=None):
        """
        Initialize the query engine with the appropriate API client
        
        Args:
            model (str): Model to use (Groq API)
            api_key (str): API key
        """
        self.model = model
        
        # Initialize Groq client
        logger.info("Using Groq for query engine")
        self.api_key = api_key or GROQ_API_KEY
        self.client = groq.Groq(api_key=self.api_key)
        
        # System prompt template for the RAG assistant
        self.system_prompt = """
        You are a code documentation assistant that helps developers find accurate information about code.
        
        When answering questions:
        1. Use ONLY the provided context to answer the question.
        2. If the context doesn't contain the information needed, say "I don't have enough information to answer this question" instead of making up an answer.
        3. Be concise and direct in your responses.
        4. Include code examples where relevant.
        5. Cite the sources you used to answer the question.
        """
    
    def generate_response(self, query, context_docs):
        """
        Generate a response to a user query using retrieved context
        
        Args:
            query (str): User query
            context_docs (list): List of context documents
            
        Returns:
            dict: Response with answer and sources
        """
        if not context_docs:
            return {
                "answer": "I don't have any documentation to answer this question. Try crawling a documentation site first.",
                "sources": []
            }
        
        try:
            # Format context for the prompt
            formatted_context = self._format_context(context_docs)
            
            # Create messages for the OpenAI API
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"Context information:\n{formatted_context}\n\nQuestion: {query}"}
            ]
            
            # Generate response
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS
            )
            
            answer = response.choices[0].message.content
            
            # Get unique sources
            sources = []
            for doc in context_docs:
                if doc["metadata"]["url"] not in [s["url"] for s in sources]:
                    sources.append({
                        "url": doc["metadata"]["url"],
                        "title": self._extract_title_from_url(doc["metadata"]["url"])
                    })
            
            return {
                "answer": answer,
                "sources": sources[:5]  # Limit to top 5 sources
            }
            
        except Exception as e:
            logger.error(f"Error generating response: {e}")
            return {
                "answer": "I encountered an error while generating a response. Please try again.",
                "sources": []
            }
    
    def _format_context(self, context_docs):
        """
        Format context documents for the prompt
        
        Args:
            context_docs (list): List of context documents
            
        Returns:
            str: Formatted context
        """
        formatted_context = ""
        
        for i, doc in enumerate(context_docs):
            formatted_context += f"[Document {i+1}] Source: {doc['metadata']['url']}\n"
            formatted_context += f"{doc['content']}\n\n"
        
        return formatted_context
    
    def _extract_title_from_url(self, url):
        """
        Extract a title from a URL for display purposes
        
        Args:
            url (str): URL to extract title from
            
        Returns:
            str: Extracted title
        """
        try:
            # Extract the last part of the path
            path = url.split('/')
            last_part = path[-1] if path[-1] else path[-2]
            
            # Remove file extensions and replace hyphens/underscores with spaces
            title = last_part.split('.')[0].replace('-', ' ').replace('_', ' ')
            
            # Capitalize words
            title = ' '.join(word.capitalize() for word in title.split())
            
            return title if title else "Documentation Source"
            
        except Exception:
            return "Documentation Source"
