"""
Windows-specific script to run the Code Documentation RAG Assistant application.

This script provides a Windows-compatible way to start the application
since gunicorn is not available on Windows.
"""

from app import app

if __name__ == '__main__':
    print("Starting Code Documentation RAG Assistant...")
    print("---------------------------------------------")
    print("Access the application at http://localhost:5000")
    print("Press Ctrl+C to stop the server")
    print("---------------------------------------------")
    
    # Start the Flask development server
    app.run(host='0.0.0.0', port=5000, debug=True)