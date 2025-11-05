"""Main Flask application for PDF processor microservice."""

import logging
import os
from flask import Flask
from dotenv import load_dotenv

from routes.pdf_routes import pdf_bp

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)


def create_app() -> Flask:
    """
    Create and configure the Flask application.

    Returns:
        Configured Flask application instance
    """
    app = Flask(__name__)
    
    # Configuration
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
    app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', '/tmp')
    
    # Enable CORS for NestJS communication
    try:
        from flask_cors import CORS
        CORS(app)
        logger.info("CORS enabled")
    except ImportError:
        logger.warning("flask-cors not installed, CORS disabled")
    
    # Register blueprints
    app.register_blueprint(pdf_bp)
    
    # Error handlers
    @app.errorhandler(400)
    def bad_request(error):
        """Handle 400 Bad Request errors."""
        from utils.response_formatter import error_response
        return error_response("Bad request", status_code=400)
    
    @app.errorhandler(404)
    def not_found(error):
        """Handle 404 Not Found errors."""
        from utils.response_formatter import error_response
        return error_response("Endpoint not found", status_code=404)
    
    @app.errorhandler(413)
    def request_entity_too_large(error):
        """Handle 413 Request Entity Too Large errors."""
        from utils.response_formatter import error_response
        return error_response("File size exceeds maximum allowed size", status_code=413)
    
    @app.errorhandler(500)
    def internal_error(error):
        """Handle 500 Internal Server Error."""
        from utils.response_formatter import error_response
        logger.error(f"Internal server error: {str(error)}", exc_info=True)
        return error_response("Internal server error", status_code=500)
    
    @app.errorhandler(Exception)
    def handle_exception(error):
        """Handle all unhandled exceptions."""
        from utils.response_formatter import error_response
        logger.error(f"Unhandled exception: {str(error)}", exc_info=True)
        return error_response(
            "An unexpected error occurred",
            status_code=500
        )
    
    logger.info("Flask application created and configured")
    
    return app


def main() -> None:
    """Run the Flask application."""
    app = create_app()
    
    # Get configuration from environment
    host = os.getenv('HOST', '0.0.0.0')
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    logger.info(f"Starting Flask server on {host}:{port} (debug={debug})")
    
    app.run(
        host=host,
        port=port,
        debug=debug
    )


if __name__ == '__main__':
    main()

