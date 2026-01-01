"""Main Flask application for PDF processor microservice."""

import logging
import os
import socket
import sys
from datetime import datetime
from flask import Flask

from routes.pdf_routes import pdf_bp
from routes.cleanup_routes import cleanup_bp
from routes.job_routes import job_bp
from utils.config import Config
from utils.logging_config import setup_logging, get_logger

# Get configuration
config = Config()

# Setup standardized logging
setup_logging(level=config.log_level, structured=config.log_structured)

logger = get_logger(__name__)

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
    app.config['MAX_CONTENT_LENGTH'] = config.max_file_size
    app.config['UPLOAD_FOLDER'] = config.upload_folder
    
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
    app.register_blueprint(cleanup_bp, url_prefix='/api/cleanup')
    app.register_blueprint(job_bp, url_prefix='/api/jobs')
    
    # Initialize SocketIO for WebSocket support
    global socketio
    if SocketIO is not None:
        # Get CORS origins - support both wildcard and specific origins
        cors_origins_env = config.websocket_cors_origins
        if cors_origins_env == '*':
            cors_origins = '*'
        else:
            # Support comma-separated list of origins
            cors_origins = [origin.strip() for origin in cors_origins_env.split(',')]
        
        async_mode = "gevent"
        # Configure ping/pong settings to prevent premature timeouts
        ping_timeout = config.websocket_ping_timeout
        ping_interval = config.websocket_ping_interval
        
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
        
        # Register MCP routes
        try:
            from routes.mcp_routes import register_mcp_events
            register_mcp_events(socketio)
            logger.info("MCP routes registered successfully")
        except ImportError as e:
            logger.error(f"Failed to import MCP routes: {e}", exc_info=True)
        except Exception as e:
            logger.error(f"Failed to register MCP routes: {e}", exc_info=True)
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


def is_port_available(host: str, port: int) -> bool:
    """
    Check if a port is available for binding.
    
    Args:
        host: Host address to check
        port: Port number to check
        
    Returns:
        True if port is available, False otherwise
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            result = sock.bind((host, port))
            return True
    except OSError:
        return False


def find_available_port(host: str, start_port: int, max_attempts: int = 10) -> int:
    """
    Find an available port starting from start_port.
    
    Args:
        host: Host address to check
        start_port: Starting port number
        max_attempts: Maximum number of ports to try
        
    Returns:
        Available port number, or None if none found
    """
    for i in range(max_attempts):
        port = start_port + i
        if is_port_available(host, port):
            return port
    return None


def main() -> None:
    """Run the Flask application."""
    app = create_app()
    
    # Get configuration
    host = config.host
    port = int(os.getenv("PORT", config.port))
    debug = config.debug
    allow_port_fallback = True  # Default behavior
    
    # Check if port is available
    if not is_port_available(host, port):
        logger.warning(f"Port {port} is already in use!")
        
        if allow_port_fallback:
            logger.info(f"Attempting to find an available port starting from {port}...")
            available_port = find_available_port(host, port)
            if available_port:
                logger.info(f"Found available port: {available_port}. Using it instead of {port}.")
                port = available_port
            else:
                logger.error(f"Could not find an available port after checking {port} to {port + 10}.")
                logger.error("Please:")
                logger.error("1. Stop any other instances of this application")
                logger.error("2. Or set a different PORT in your environment variables")
                logger.error("3. Or kill the process using the port with: netstat -ano | findstr :5001")
                sys.exit(1)
        else:
            logger.error(f"Port {port} is already in use and port fallback is disabled.")
            logger.error("Please:")
            logger.error("1. Stop any other instances of this application")
            logger.error("2. Or set a different PORT in your environment variables")
            logger.error("3. Or kill the process using the port")
            logger.error("   Windows: netstat -ano | findstr :{port}")
            logger.error("   Then: taskkill /PID <PID> /F")
            sys.exit(1)
    
    logger.info(f"Starting Flask server on {host}:{port} (debug={debug})")
    
    # Use SocketIO.run if available, otherwise fall back to app.run
    global socketio
    try:
        if socketio is not None:
            socketio.run(app, host=host, port=port, debug=debug)
        else:
            app.run(host=host, port=port, debug=debug)
    except OSError as e:
        if "10048" in str(e) or "Only one usage" in str(e):
            logger.error(f"Port {port} is already in use!")
            logger.error("This can happen if:")
            logger.error("1. Another instance of this application is running")
            logger.error("2. A previous instance didn't shut down properly")
            logger.error("3. Another application is using this port")
            logger.error("\nTo resolve:")
            logger.error(f"Windows: netstat -ano | findstr :{port}")
            logger.error("Then find the PID and kill it: taskkill /PID <PID> /F")
            logger.error(f"Or set a different port: set PORT=<different_port>")
            sys.exit(1)
        else:
            raise


if __name__ == '__main__':
    main()

