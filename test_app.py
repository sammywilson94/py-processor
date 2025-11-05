"""Tests for the PDF processor Flask application."""

import pytest
import os
import tempfile
from io import BytesIO
from app import create_app


@pytest.fixture
def client():
    """Create a test client for the Flask application."""
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client


def test_health_endpoint(client):
    """Test the health check endpoint."""
    response = client.get('/health')
    assert response.status_code == 200
    
    data = response.get_json()
    assert data['status'] == 'success'
    assert data['data']['status'] == 'ok'


def test_process_pdf_no_file(client):
    """Test processing PDF without providing a file."""
    response = client.post('/process-pdf')
    assert response.status_code == 400
    
    data = response.get_json()
    assert data['status'] == 'error'
    assert 'file' in data['message'].lower()


def test_process_pdf_empty_file(client):
    """Test processing PDF with empty file selection."""
    response = client.post(
        '/process-pdf',
        data={'file': (BytesIO(b''), '')},
        content_type='multipart/form-data'
    )
    assert response.status_code == 400
    
    data = response.get_json()
    assert data['status'] == 'error'


def test_process_pdf_invalid_file_type(client):
    """Test processing with invalid file type."""
    file_content = b'This is a test file'
    response = client.post(
        '/process-pdf',
        data={'file': (BytesIO(file_content), 'test.exe')},
        content_type='multipart/form-data'
    )
    assert response.status_code == 400
    
    data = response.get_json()
    assert data['status'] == 'error'
    assert 'invalid' in data['message'].lower() or 'type' in data['message'].lower()


def test_process_pdf_valid_structure(client):
    """Test that the response structure is correct for valid requests."""
    # Create a minimal PDF-like file for testing
    # Note: This will fail processing but should return proper error structure
    file_content = b'%PDF-1.4\ninvalid pdf content'
    response = client.post(
        '/process-pdf',
        data={'file': (BytesIO(file_content), 'test.pdf')},
        content_type='multipart/form-data'
    )
    
    # Even if processing fails, the response should have the correct structure
    data = response.get_json()
    assert 'status' in data
    assert data['status'] in ['success', 'error']
    
    if data['status'] == 'error':
        assert 'message' in data
    elif data['status'] == 'success':
        assert 'data' in data
        assert 'metadata' in data['data']
        assert 'content' in data['data']


def test_404_endpoint(client):
    """Test that non-existent endpoints return 404."""
    response = client.get('/nonexistent')
    assert response.status_code == 404
    
    data = response.get_json()
    assert data['status'] == 'error'

