"""Utility functions for formatting API responses consistently."""

from typing import Any, Dict, Optional
from flask import jsonify


def success_response(
    data: Optional[Any] = None,
    message: Optional[str] = None,
    status_code: int = 200
) -> tuple:
    """
    Format a success response.

    Args:
        data: Optional data to include in the response
        message: Optional success message
        status_code: HTTP status code (default: 200)

    Returns:
        Tuple of (JSON response, status code)
    """
    response: Dict[str, Any] = {
        "status": "success"
    }
    
    if data is not None:
        response["data"] = data
    
    if message:
        response["message"] = message
    
    return jsonify(response), status_code


def error_response(
    message: str,
    status_code: int = 400,
    data: Optional[Any] = None
) -> tuple:
    """
    Format an error response.

    Args:
        message: Error message to include
        status_code: HTTP status code (default: 400)
        data: Optional additional error data

    Returns:
        Tuple of (JSON response, status code)
    """
    response: Dict[str, Any] = {
        "status": "error",
        "message": message
    }
    
    if data is not None:
        response["data"] = data
    
    return jsonify(response), status_code

