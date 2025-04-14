"""
Windows production server using Waitress for the Code Documentation RAG Assistant.

Waitress is a production-quality WSGI server that works on Windows.
Install it with: pip install waitress
"""

from waitress import serve
from app import app

if __name__ == '__main__':
    print("Starting Code Documentation RAG Assistant with Waitress...")
    print("---------------------------------------------")
    print("Access the application at http://localhost:5000")
    print("This is a production server - debug mode is OFF")
    print("Press Ctrl+C to stop the server")
    print("---------------------------------------------")
    
    # Start the Waitress production server
    serve(app, host='0.0.0.0', port=5000)