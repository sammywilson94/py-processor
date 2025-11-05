"""Routes for PDF processing endpoints."""

import logging
from flask import Blueprint, request, current_app
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

from services.pdf_service import PDFService
from utils.response_formatter import success_response, error_response

logger = logging.getLogger(__name__)

# Create blueprint
pdf_bp = Blueprint('pdf', __name__)

# Initialize PDF service
pdf_service = PDFService()


def allowed_file(filename: str) -> bool:
    """
    Check if the uploaded file has an allowed extension.

    Args:
        filename: Name of the file to check

    Returns:
        True if file extension is allowed, False otherwise
    """
    # Allow common document formats that docling supports
    allowed_extensions = {
        'pdf', 'docx', 'doc', 'pptx', 'ppt', 
        'xlsx', 'xls', 'html', 'htm', 'txt', 'md'
    }
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in allowed_extensions


@pdf_bp.route('/process-pdf', methods=['POST'])
def process_pdf() -> tuple:
    """
    Process an uploaded PDF or document file.

    Expects:
        - multipart/form-data with field name 'file'
        - File can be PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, HTML, TXT, or MD

    Returns:
        JSON response with:
            - status: "success" | "error"
            - data: { metadata, content, sections }
            - message: Optional message
    """
    try:
        # Check if file is present in request
        if 'file' not in request.files:
            return error_response(
                "No file provided. Please upload a file with field name 'file'",
                status_code=400
            )
        
        file = request.files['file']
        
        # Check if file was actually selected
        if file.filename == '':
            return error_response(
                "No file selected. Please select a file to upload",
                status_code=400
            )
        
        # Validate file extension
        if not allowed_file(file.filename):
            return error_response(
                "Invalid file type. Allowed types: PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, HTML, TXT, MD",
                status_code=400
            )
        
        # Secure the filename
        filename = secure_filename(file.filename)
        logger.info(f"Processing file: {filename}")
        
        # Process the document
        try:
            result = pdf_service.process_file_upload(file)
            
            return success_response(
                data=result,
                message=f"Successfully processed document: {filename}"
            )
        
        except ValueError as e:
            logger.error(f"Validation error: {str(e)}")
            return error_response(
                str(e),
                status_code=400
            )
        
        except Exception as e:
            logger.error(f"Processing error: {str(e)}", exc_info=True)
            return error_response(
                f"Failed to process document: {str(e)}",
                status_code=500
            )
    
    except RequestEntityTooLarge:
        return error_response(
            "File size exceeds maximum allowed size",
            status_code=413
        )
    
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}", exc_info=True)
        return error_response(
            "An unexpected error occurred while processing the request",
            status_code=500
        )


@pdf_bp.route('/health', methods=['GET'])
def health_check() -> tuple:
    """
    Health check endpoint.

    Returns:
        JSON response with status "ok"
    """
    return success_response(
        data={"status": "ok"},
        message="Service is healthy"
    )

