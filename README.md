# PDF Processor Bridge - Flask Microservice

A lightweight Flask microservice that processes PDF and document files using the `docling` library and returns parsed results in Markdown format.

## Features

- **Document Processing**: Supports PDF, DOCX, DOC, PPTX, PPT, XLSX, XLS, HTML, TXT, and MD files
- **Markdown Output**: Converts documents to clean Markdown format
- **Metadata Extraction**: Extracts title, author, date, and page count
- **Noise Removal**: Automatically removes headers, footers, and watermarks
- **RESTful API**: Clean JSON responses with consistent structure
- **Error Handling**: Comprehensive error handling with meaningful messages
- **Health Check**: `/health` endpoint for service monitoring

## Requirements

- Python 3.10+
- Flask 3.x
- docling
- python-dotenv
- pytest (for testing)

## Installation

1. **Clone or navigate to the project directory:**
   ```bash
   cd py-file-processor
   ```

2. **Create a virtual environment (recommended):**
   ```bash
   python -m venv venv
   ```
   
   **Activate it:**
   - On Windows: `venv\Scripts\activate`
   - On macOS/Linux: `source venv/bin/activate`

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Copy `.env.example` to `.env` and modify as needed:

```env
HOST=0.0.0.0
PORT=5001
DEBUG=False
UPLOAD_FOLDER=/tmp
```

## Running the Service

Start the Flask server:

```bash
python app.py
```

The server will run at `http://localhost:5001` by default.

## API Endpoints

### POST /process-pdf

Process a document file and get parsed Markdown content.

**Request:**
- Method: `POST`
- Content-Type: `multipart/form-data`
- Body: Form data with field name `file` containing the document file

**Response (Success):**
```json
{
  "status": "success",
  "data": {
    "metadata": {
      "filename": "document.pdf",
      "title": "Document Title",
      "author": "Author Name",
      "date": "2024-01-01",
      "pages": 10
    },
    "content": "# Document Title\n\nContent in markdown format...",
    "sections": [
      {
        "title": "Section 1",
        "content": "Section content",
        "level": 1
      }
    ]
  },
  "message": "Successfully processed document: document.pdf"
}
```

**Response (Error):**
```json
{
  "status": "error",
  "message": "Error message here"
}
```

**Example using curl:**
```bash
curl -X POST http://localhost:5001/process-pdf \
  -F "file=@path/to/your/document.pdf"
```

**Example using Python requests:**
```python
import requests

url = "http://localhost:5001/process-pdf"
files = {"file": open("document.pdf", "rb")}
response = requests.post(url, files=files)
print(response.json())
```

### GET /health

Health check endpoint.

**Response:**
```json
{
  "status": "success",
  "data": {
    "status": "ok"
  },
  "message": "Service is healthy"
}
```

## Testing

Run the test suite:

```bash
pytest test_app.py -v
```

## Project Structure

```
py-file-processor/
├── app.py                 # Main Flask application
├── requirements.txt       # Python dependencies
├── test_app.py           # Test suite
├── .env                  # Environment configuration
├── .env.example          # Example environment file
├── services/
│   ├── __init__.py
│   └── pdf_service.py    # PDF processing logic
├── routes/
│   ├── __init__.py
│   └── pdf_routes.py     # API routes
└── utils/
    ├── __init__.py
    └── response_formatter.py  # Response formatting utilities
```

## Architecture

- **Flask Blueprints**: Routes organized in blueprints for modularity
- **Service Layer**: Business logic separated in `services/pdf_service.py`
- **Utility Layer**: Common utilities in `utils/`
- **Error Handling**: Centralized error handlers in `app.py`
- **Logging**: Structured logging with timestamps and log levels

## Error Codes

- `200`: Success
- `400`: Bad Request (invalid input, missing file, invalid file type)
- `413`: Request Entity Too Large (file exceeds size limit)
- `500`: Internal Server Error

## Integration with NestJS

This microservice is designed to be called from a NestJS backend. The service:

- Returns clean JSON responses
- Supports CORS (enabled via flask-cors)
- Uses consistent response format
- Handles errors gracefully

## Development

### Code Standards

- Type hints in all function definitions
- Docstrings for all functions
- Code formatted with Black
- Logging instead of print statements

### Formatting Code

```bash
black .
```

## License

This project is part of a document processing system.

