"""Gunicorn WSGI server entry point for Railway deployment."""

from app import create_app
from utils.logging_config import setup_logging, get_logger
from utils.config import Config

# Get configuration
config = Config()

# Setup standardized logging
setup_logging(level=config.log_level, structured=config.log_structured)

logger = get_logger(__name__)

# Create Flask app
logger.info(f"Creating Flask application...")
app = create_app()

# Run the application
# if __name__ == '__main__':
#     from app import main
#     main()
