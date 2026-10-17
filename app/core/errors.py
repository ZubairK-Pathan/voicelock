"""
app/core/errors.py — Reusable HTTP exception helpers and sanitized error responses.
"""

from fastapi import HTTPException


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=400, detail=detail)


def not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def payload_too_large(detail: str) -> HTTPException:
    return HTTPException(status_code=413, detail=detail)


def service_unavailable(detail: str) -> HTTPException:
    return HTTPException(status_code=503, detail=detail)


def internal_error(detail: str = "Biometric processing error.") -> HTTPException:
    return HTTPException(status_code=500, detail=detail)
