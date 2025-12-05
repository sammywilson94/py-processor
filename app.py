"""Main Flask application for PDF processor microservice."""

import logging
import os
from datetime import datetime
from flask import Flask
from dotenv import load_dotenv

from routes.pdf_routes import pdf_bp

# Load environment variables
load_dotenv()

# Configure logging with enhanced format for better debugging
log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
    format='%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

# Import SocketIO for WebSocket support
socketio = None  # Will be initialized in create_app
try:
    from flask_socketio import SocketIO
except ImportError:
    SocketIO = None
    logger.warning("flask-socketio not installed, WebSocket support disabled")


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
        # Configure CORS to allow all origins, methods, and headers for development
        # Using simpler configuration that's more reliable for preflight requests
        CORS(app, 
             origins="*",
             methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
             allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
             supports_credentials=False)
        logger.info("CORS enabled with full access for all origins")
    except ImportError:
        logger.warning("flask-cors not installed, CORS disabled")
    
    # Health check endpoint
    @app.route('/health', methods=['GET'])
    def health_check():
        """Health check endpoint to verify server is running."""
        global socketio
        return {
            'status': 'healthy',
            'websocket_enabled': socketio is not None,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    # WebSocket status endpoint
    @app.route('/ws/status', methods=['GET'])
    def ws_status():
        """Check WebSocket server status."""
        global socketio
        try:
            from routes.chat_routes import active_sessions
            return {
                'websocket_enabled': socketio is not None,
                'active_sessions': len(active_sessions),
                'timestamp': datetime.utcnow().isoformat()
            }
        except Exception as e:
            return {
                'websocket_enabled': socketio is not None,
                'active_sessions': 0,
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }
    
    # Register blueprints
    app.register_blueprint(pdf_bp)
    
    # Initialize SocketIO for WebSocket support
    global socketio
    if SocketIO is not None:
        # Get CORS origins - support both wildcard and specific origins
        cors_origins_env = os.getenv('WEBSOCKET_CORS_ORIGINS', '*')
        if cors_origins_env == '*':
            cors_origins = '*'
        else:
            # Support comma-separated list of origins
            cors_origins = [origin.strip() for origin in cors_origins_env.split(',')]
        
        async_mode = os.getenv('WEBSOCKET_ASYNC_MODE', 'eventlet')
        # Configure ping/pong settings to prevent premature timeouts
        ping_timeout = int(os.getenv('WEBSOCKET_PING_TIMEOUT', '60'))  # Default 60 seconds
        ping_interval = int(os.getenv('WEBSOCKET_PING_INTERVAL', '25'))  # Default 25 seconds
        
        socketio = SocketIO(
            app, 
            cors_allowed_origins=cors_origins, 
            async_mode=async_mode,
            logger=True,
            engineio_logger=True,
            ping_timeout=ping_timeout,
            ping_interval=ping_interval
        )
        logger.info(f"SocketIO initialized with ping_timeout={ping_timeout}s, ping_interval={ping_interval}s")
        logger.info(f"SocketIO initialized with CORS origins: {cors_origins}, async_mode: {async_mode}")
        
        # Register chat routes
        try:
            from routes.chat_routes import register_chat_events
            register_chat_events(socketio)
            logger.info("Chat routes registered successfully")
        except ImportError as e:
            logger.error(f"Failed to import chat routes: {e}", exc_info=True)
            logger.warning("Chat routes not available - WebSocket will not function properly")
        except Exception as e:
            logger.error(f"Failed to register chat routes: {e}", exc_info=True)
    else:
        socketio = None
        logger.warning("SocketIO not available, WebSocket features disabled")
    
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
    
    # Use SocketIO.run if available, otherwise fall back to app.run
    global socketio
    if socketio is not None:
        socketio.run(app, host=host, port=port, debug=debug)
    else:
        app.run(host=host, port=port, debug=debug)


if __name__ == '__main__':
    main()

