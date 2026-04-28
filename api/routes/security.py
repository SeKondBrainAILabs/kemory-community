"""
S9N Memory Vault — Security API Routes

Endpoints:
- POST /api/v1/security/scan          — Full security scan on content
- POST /api/v1/security/encrypt       — Encrypt a field value
- POST /api/v1/security/decrypt       — Decrypt a field value
- POST /api/v1/security/pii-scan      — Scan for PII only
- POST /api/v1/security/injection-scan — Scan for injection only

Spec reference: Section 12 (Security Architecture)
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from backend.core.auth import AuthContext, require_auth
from backend.services.security_service import (
    EncryptedPayload,
    decrypt_field,
    encrypt_field,
    full_security_scan,
    generate_master_key,
    scan_for_injection,
    scan_for_pii,
)

router = APIRouter(prefix="/api/v1/security", tags=["Security"])


class EncryptRequest(BaseModel):
    plaintext: str
    master_key: str


class DecryptRequest(BaseModel):
    payload: EncryptedPayload
    master_key: str


class ScanRequest(BaseModel):
    content: str


@router.post("/scan", summary="Full security scan")
async def security_scan(
    request: ScanRequest,
    auth: AuthContext = Depends(require_auth),
):
    """Run the full security pipeline on content."""
    result = full_security_scan(request.content)
    return result.model_dump()


@router.post("/encrypt", summary="Encrypt a field value")
async def encrypt_endpoint(
    request: EncryptRequest,
    auth: AuthContext = Depends(require_auth),
):
    """Encrypt a field value using AES-256-GCM."""
    payload = encrypt_field(request.plaintext, request.master_key)
    return payload.model_dump()


@router.post("/decrypt", summary="Decrypt a field value")
async def decrypt_endpoint(
    request: DecryptRequest,
    auth: AuthContext = Depends(require_auth),
):
    """Decrypt a field value using AES-256-GCM."""
    try:
        plaintext = decrypt_field(request.payload, request.master_key)
        return {"plaintext": plaintext}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Decryption failed: {str(e)}",
        )


@router.post("/pii-scan", summary="Scan for PII")
async def pii_scan_endpoint(
    request: ScanRequest,
    auth: AuthContext = Depends(require_auth),
):
    """Scan content for personally identifiable information."""
    result = scan_for_pii(request.content)
    return result.model_dump()


@router.post("/injection-scan", summary="Scan for injection attacks")
async def injection_scan_endpoint(
    request: ScanRequest,
    auth: AuthContext = Depends(require_auth),
):
    """Scan content for injection attacks."""
    result = scan_for_injection(request.content)
    return result.model_dump()


@router.post("/generate-key", summary="Generate a master key")
async def generate_key_endpoint(
    auth: AuthContext = Depends(require_auth),
):
    """Generate a new cryptographically secure master key."""
    key = generate_master_key()
    return {"master_key": key, "algorithm": "AES-256-GCM", "key_size_bits": 256}
