import sys
import os
import traceback

# 1. SETUP PATHS
# Ensure the current directory is at the beginning of the Python Path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

# 2. DEBUG MODE WRAPPER
# This wrapper will catch any errors that happen during the import of app.py
# and display them in the web browser instead of showing a generic 500 error.
def application(environ, start_response):
    try:
        from app import app
        return app(environ, start_response)
    except Exception:
        status = '500 Internal Server Error'
        
        # Collect the full error message
        error_details = traceback.format_exc()
        
        # Add a helpful message for cPanel users
        message = (
            "PYTHON DEPLOYMENT ERROR DETECTED\n"
            "==============================\n\n"
            "If you see a 'ModuleNotFoundError', go to 'Setup Python App' in cPanel "
            "and click 'RUN PIP INSTALL' for your requirements.txt.\n\n"
            "Detailed Traceback:\n"
            "-------------------\n"
        )
        
        output = (message + error_details).encode('utf-8')
        
        response_headers = [
            ('Content-type', 'text/plain; charset=utf-8'),
            ('Content-Length', str(len(output)))
        ]
        start_response(status, response_headers)
        return [output]
