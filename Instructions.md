# Project Instructions: PDF Processor Bridge (Flask + Docling)

## Overview
Build a lightweight Flask microservice that receives PDF or any document files from a NestJS backend, processes them using the `docling` Python library, and returns parsed results as MD format.

## Functional Requirements

1. **API Endpoint**
   - Endpoint: `POST /process-pdf`
   - Accepts: `multipart/form-data` containing a PDF file (field name: `file`)
   - Validates that the file exists and is a PDF.
   - Returns: { metadata, content, sections } structured data from `docling`.

2. **PDF Processing**
   - Use `docling` to extract:
     - Full text
     - Metadata (title, author, date, pages count if possible)
     - Removes noise (headers/footers, watermarks)
     - Any structured info docling supports
   - Wrap this logic in a `pdf_service.py` file for modularity.

3. **Error Handling**
   - Return proper HTTP error codes:
     - `400` for invalid input or missing file
     - `500` for internal parsing errors
   - Include meaningful error messages in JSON.

4. **Testing**
   - Include a simple `test_app.py` with a sample test using `pytest` or `unittest`.
   - Mock file upload and validate response JSON structure.

5. **Environment**
   - Python 3.10+
   - Dependencies: Flask, docling, python-dotenv, pytest
   - Use `requirements.txt` for dependency management.

6. **Run Instructions**
   - Start the Flask server with `python app.py`.
   - Server should run at `http://localhost:5001` by default.
   - Provide `.env` for configurable port and debug settings.

7. **NestJS Communication**
   - This Flask app will be called from a NestJS service.
   - Keep responses clean JSON and use CORS if necessary.

8. **Optional (Nice-to-Have)**
   - Add `/health` endpoint returning `{ status: "ok" }`
   - Add Dockerfile for containerized deployment.

## Example Request
