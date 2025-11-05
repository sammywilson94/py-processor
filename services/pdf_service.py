"""Service for processing PDF documents using docling."""

import logging
from typing import Dict, Any, Optional
from pathlib import Path
import tempfile
import os

try:
    from docling.document_converter import DocumentConverter
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.datamodel.base_models import InputFormat
except ImportError:
    DocumentConverter = None
    PdfPipelineOptions = None
    InputFormat = None

logger = logging.getLogger(__name__)


class PDFService:
    """Service class for processing PDF and document files using docling."""
    
    def __init__(self) -> None:
        """Initialize the PDF service with docling converter."""
        if DocumentConverter is None:
            raise ImportError(
                "docling library is not installed. "
                "Please install it using: pip install docling"
            )
        
        # Initialize docling converter with pipeline options
        # This will remove noise like headers, footers, watermarks
        pipeline_options = None
        if PdfPipelineOptions:
            pipeline_options = PdfPipelineOptions(
                do_ocr=False,  # Set to True if OCR is needed
                do_cleanup=True
            )
        
        self.converter = DocumentConverter(
            pipeline_options=pipeline_options
        )
        logger.info("PDFService initialized with docling converter")
    
    def process_document(
        self,
        file_path: str,
        filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a document file and extract content, metadata, and sections.

        Args:
            file_path: Path to the document file
            filename: Original filename (optional)

        Returns:
            Dictionary containing:
                - metadata: Document metadata (title, author, date, pages)
                - content: Full text content in markdown format
                - sections: Structured sections if available
                - filename: Original filename

        Raises:
            ValueError: If file doesn't exist or is invalid
            Exception: If processing fails
        """
        if not os.path.exists(file_path):
            raise ValueError(f"File not found: {file_path}")
        
        try:
            logger.info(f"Processing document: {file_path}")
            
            # Convert document using docling
            result = self.converter.convert(file_path)
            
            # Extract metadata
            metadata: Dict[str, Any] = {
                "filename": filename or os.path.basename(file_path),
            }
            
            # Extract content as markdown
            content = ""
            sections = []
            
            # Try to get the document from the result
            doc = result.document if hasattr(result, 'document') else result
            
            # Extract metadata if available
            if hasattr(doc, 'meta') and doc.meta:
                meta = doc.meta
                if hasattr(meta, 'title') and meta.title:
                    metadata["title"] = meta.title
                if hasattr(meta, 'author') and meta.author:
                    metadata["author"] = meta.author
                if hasattr(meta, 'creation_date') and meta.creation_date:
                    metadata["date"] = str(meta.creation_date)
            
            # Get page count if available
            if hasattr(doc, 'pages') and doc.pages:
                metadata["pages"] = len(doc.pages)
            
            # Extract content as markdown
            if hasattr(doc, 'export_to_markdown'):
                content = doc.export_to_markdown()
            elif hasattr(doc, 'to_markdown'):
                content = doc.to_markdown()
            elif hasattr(doc, 'export'):
                content = doc.export(format='markdown')
            else:
                # Fallback: convert to string
                content = str(doc)
            
            # Extract sections if available
            if hasattr(doc, 'sections') and doc.sections:
                for section in doc.sections:
                    section_data: Dict[str, Any] = {}
                    if hasattr(section, 'title'):
                        section_data["title"] = section.title
                    if hasattr(section, 'content'):
                        section_data["content"] = section.content
                    if hasattr(section, 'level'):
                        section_data["level"] = section.level
                    if section_data:
                        sections.append(section_data)
            
            logger.info(f"Successfully processed document: {filename or file_path}")
            
            return {
                "metadata": metadata,
                "content": content,
                "sections": sections if sections else None
            }
            
        except Exception as e:
            logger.error(f"Error processing document {file_path}: {str(e)}", exc_info=True)
            raise Exception(f"Failed to process document: {str(e)}")
    
    def process_file_upload(
        self,
        file_storage
    ) -> Dict[str, Any]:
        """
        Process an uploaded file from Flask request.

        Args:
            file_storage: FileStorage object from Flask request

        Returns:
            Dictionary with processed document data

        Raises:
            ValueError: If file is invalid or missing
            Exception: If processing fails
        """
        if not file_storage or not file_storage.filename:
            raise ValueError("No file provided")
        
        # Save uploaded file to temporary location
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file_storage.filename)[1]) as tmp_file:
            file_storage.save(tmp_file.name)
            tmp_path = tmp_file.name
        
        try:
            # Process the document
            result = self.process_document(tmp_path, file_storage.filename)
            return result
        finally:
            # Clean up temporary file
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
                logger.debug(f"Cleaned up temporary file: {tmp_path}")

