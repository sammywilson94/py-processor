"""Routes for PDF processing endpoints."""

import logging
import os
import subprocess
import uuid
from flask import Blueprint, request, current_app, Response
from werkzeug.utils import secure_filename
from werkzeug.exceptions import RequestEntityTooLarge

from services.pdf_service import PDFService
from utils.response_formatter import success_response, error_response
from services.parser_service import repo_to_json, generate_pkg
from services.agent_orchestrator import AgentOrchestrator

try:
    from agents import storing_agent
    STORING_AGENT_AVAILABLE = True
except ImportError:
    storing_agent = None
    STORING_AGENT_AVAILABLE = False

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
        - Optional query parameters:
            - enable_ocr: Enable OCR for scanned documents (true/false, default: false)
            - output_format: Output format - "markdown", "json", or "html" (default: "markdown")
            - extract_tables: Extract tables (true/false, default: true)
            - extract_images: Extract images (true/false, default: true)
            - chunk_size: Chunk document into pieces of this size (integer, optional)
            - chunk_overlap: Overlap between chunks (integer, default: 200)

    Returns:
        JSON response with:
            - status: "success" | "error"
            - data: { metadata, content, sections, tables, images, chunks }
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
        
        # Parse optional parameters from query string or form data
        enable_ocr = request.args.get('enable_ocr', 'false').lower() == 'true' or \
                     request.form.get('enable_ocr', 'false').lower() == 'true'
        
        output_format = request.args.get('output_format', request.form.get('output_format', 'markdown')).lower()
        if output_format not in ['markdown', 'json', 'html']:
            output_format = 'markdown'
        
        extract_tables = request.args.get('extract_tables', request.form.get('extract_tables', 'true')).lower() != 'false'
        extract_images = request.args.get('extract_images', request.form.get('extract_images', 'true')).lower() != 'false'
        
        chunk_size = None
        chunk_size_param = request.args.get('chunk_size', request.form.get('chunk_size'))
        if chunk_size_param:
            try:
                chunk_size = int(chunk_size_param)
                if chunk_size <= 0:
                    return error_response(
                        "chunk_size must be a positive integer",
                        status_code=400
                    )
            except ValueError:
                return error_response(
                    "chunk_size must be a valid integer",
                    status_code=400
                )
        
        chunk_overlap = 200
        chunk_overlap_param = request.args.get('chunk_overlap', request.form.get('chunk_overlap'))
        if chunk_overlap_param:
            try:
                chunk_overlap = int(chunk_overlap_param)
                if chunk_overlap < 0:
                    return error_response(
                        "chunk_overlap must be a non-negative integer",
                        status_code=400
                    )
            except ValueError:
                return error_response(
                    "chunk_overlap must be a valid integer",
                    status_code=400
                )
        
        logger.info(
            f"Processing file: {filename} "
            f"(OCR={enable_ocr}, format={output_format}, "
            f"tables={extract_tables}, images={extract_images}, "
            f"chunk_size={chunk_size})"
        )
        
        # Process the document
        try:
            result = pdf_service.process_file_upload(
                file,
                enable_ocr=enable_ocr,
                output_format=output_format,
                extract_tables=extract_tables,
                extract_images=extract_images,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap
            )
            
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


@pdf_bp.route('/chunks', methods=['GET'])
def get_stored_chunks():
    query = request.args.get("q", None)
    
    if not STORING_AGENT_AVAILABLE:
        return error_response(
            "LangChain agents not available. Please install langchain: pip install langchain langchain-openai",
            status_code=503
        )
    
    try:
        result = storing_agent.search_vectors.invoke({"query": query})
        return {"result": result}
    
    except Exception as e:
        return error_response(
            f"Failed to search chunks: {str(e)}",
            status_code=500
        )
    

@pdf_bp.route('/clone-and-generate', methods=['OPTIONS'])
def clone_and_generate_options():
    """Handle CORS preflight requests for clone-and-generate endpoint."""
    response = Response()
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type, Authorization, X-Requested-With')
    response.headers.add('Access-Control-Allow-Methods', 'POST, OPTIONS')
    return response


@pdf_bp.route('/clone-and-generate', methods=['POST'])
def clone_and_generate():
    """
    Clone a repository into cloned_repos using the original repo name,
    then generate PKG JSON using generate_pkg.
    Expects JSON body: { "repo_url": "https://github.com/user/repo.git" }
    
    Optional query parameters:
        - generate_summaries: bool (default: false) - Generate LLM summaries
        - fan_threshold: int (default: 3) - Fan-in threshold for filtering
        - include_features: bool (default: true) - Include feature groupings
        - format: str (default: "pkg") - Output format: "pkg" or "legacy"
    """
    try:
        data = request.get_json()
        repo_url = data.get('repo_url')

        if not repo_url:
            logger.error("Missing repo_url in request body")
            return error_response("repo_url is required", 400)

        # Store original URL before potential fork
        original_repo_url = repo_url
        fork_info = None
        
        # Check if auto-forking is needed (BEFORE clone operation)
        logger.info(f"🔍 CHECKING FORK STATUS | URL: {repo_url}")
        orchestrator = AgentOrchestrator()
        owner, repo_name_parsed = orchestrator._parse_repo_url(repo_url)
        
        if owner and repo_name_parsed:
            try:
                # Initialize PRCreator to access GitHub API
                # Use a temporary path for PRCreator initialization (it needs a repo path)
                temp_repo_path = os.path.join(os.getcwd(), "cloned_repos", ".temp")
                os.makedirs(temp_repo_path, exist_ok=True)
                
                from agents.pr_creator import PRCreator
                pr_creator = PRCreator(temp_repo_path)
                
                if pr_creator.github:
                    logger.info(f"🔐 AUTHENTICATED GITHUB USER AVAILABLE | Checking ownership...")
                    
                    # Fork repository if needed
                    fork_info = pr_creator.fork_repository(owner, repo_name_parsed)
                    
                    if fork_info.get('success'):
                        if fork_info.get('already_owned'):
                            logger.info(f"✅ REPO OWNED BY USER | No fork needed")
                        else:
                            logger.info(f"🍴 FORK OPERATION SUCCESSFUL | Fork URL: {fork_info.get('fork_url')}")
                            repo_url = fork_info.get('fork_url')
                    else:
                        logger.warning(f"⚠️  FORK OPERATION FAILED | Error: {fork_info.get('error')} | Falling back to original URL")
                        # Continue with original URL
                else:
                    logger.warning(f"⚠️  GITHUB TOKEN NOT AVAILABLE | Skipping fork, using original URL")
            except Exception as e:
                logger.error(f"❌ ERROR DURING FORK CHECK | Error: {e}", exc_info=True)
                # Continue with original URL
        else:
            logger.warning(f"⚠️  COULD NOT PARSE REPO URL | URL: {repo_url} | Skipping fork check")

        # Parse optional parameters
        generate_summaries = request.args.get('generate_summaries', 'false').lower() == 'true'
        fan_threshold = int(request.args.get('fan_threshold', '3'))
        include_features = request.args.get('include_features', 'true').lower() != 'false'
        output_format = request.args.get('format', 'pkg').lower()

        # Ensure cloned_repos folder exists
        base_dir = os.path.join(os.getcwd(), "cloned_repos")
        os.makedirs(base_dir, exist_ok=True)

        # Extract repo name from URL (strip .git if present)
        repo_name = os.path.splitext(os.path.basename(repo_url))[0]
        folder_path = os.path.join(base_dir, repo_name)

         # Check if repo already exists
        if os.path.exists(folder_path):
            logger.info(f"Repository already present at {folder_path}, skipping clone.")
        else:
            # Clone repo
            try:
                # Try to use git from PATH first, then fallback to Windows path
                git_cmd = "git"
                try:
                    subprocess.run([git_cmd, "--version"], check=True, capture_output=True)
                except (FileNotFoundError, subprocess.CalledProcessError):
                    git_cmd = r"C:\Program Files\Git\cmd\git.exe"
                
                subprocess.run([git_cmd, "clone", repo_url, folder_path], check=True)
                logger.info(f"Repository cloned successfully into {folder_path}")
            except FileNotFoundError:
                logger.exception("Git executable not found")
                return error_response("Git is not installed or not found in PATH.", 500)
            except subprocess.CalledProcessError as e:
                logger.exception("Failed to clone repository")
                return error_response(f"Failed to clone repo: {str(e)}", 500)

        # Generate JSON from cloned repo
        try:
            if output_format == "legacy":
                # Use legacy format for backward compatibility
                json_output = repo_to_json(folder_path)
                return success_response(
                    data={"repo": repo_name, **json_output},
                    message="Repository parsed successfully (legacy format)"
                )
            else:
                # Use new PKG format
                pkg_output = generate_pkg(
                    repo_path=folder_path,
                    fan_threshold=fan_threshold,
                    include_features=include_features
                )
                
                # Optionally generate summaries if requested
                if generate_summaries:
                    try:
                        from services.summary_generator import generate_summaries
                        pkg_output = generate_summaries(pkg_output)
                    except ImportError:
                        logger.warning("Summary generator not available, skipping summaries")
                
                return success_response(
                    data=pkg_output,
                    message=f"PKG generated successfully for {repo_name}"
                )
        except Exception as e:
            logger.exception("Error generating PKG from repo")
            return error_response(f"Failed to generate PKG: {str(e)}", 500)

    except subprocess.CalledProcessError as e:
        logger.exception("Failed to clone repository")
        return error_response(f"Failed to clone repo: {str(e)}", 500)

    except Exception as e:
        logger.exception("Unexpected error during clone+generate")
        return error_response(str(e), 500)
