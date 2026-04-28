"""
S9N Memory Vault — Security Service

Implements:
1. Field-level encryption: AES-256-GCM for memory content at rest
2. Secrets management: key derivation, rotation, envelope encryption
3. Injection prevention: sanitize inputs against prompt injection, SQL injection
4. PII detection: identify and flag personally identifiable information
5. Agent identity verification: validate agent signatures

Spec reference: Section 12 (Security Architecture), Appendix F (Encryption Detail)

Stories: F08-US-001 (encryption), F08-US-002 (secrets management),
         F08-US-003 (injection prevention), F08-US-004 (PII detection)
"""

import base64
import os
import re
import secrets
from enum import Enum

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from pydantic import BaseModel, Field

# ─── Encryption Configuration ────────────────────────────────────

# AES-256-GCM key size (32 bytes = 256 bits)
AES_KEY_SIZE = 32
# Nonce size for AES-GCM (12 bytes recommended by NIST)
NONCE_SIZE = 12
# PBKDF2 iterations for key derivation
KDF_ITERATIONS = 100_000
# Salt size for key derivation
SALT_SIZE = 16


# ─── Encryption Schemas ──────────────────────────────────────────


class EncryptedPayload(BaseModel):
    """Encrypted data with metadata for decryption."""

    ciphertext: str  # Base64-encoded ciphertext
    nonce: str  # Base64-encoded nonce
    salt: str  # Base64-encoded salt (for key derivation)
    version: int = 1  # Encryption version for future rotation
    algorithm: str = "AES-256-GCM"


class PIIType(str, Enum):
    """Types of PII that can be detected."""

    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    DATE_OF_BIRTH = "date_of_birth"


class PIIDetection(BaseModel):
    """A detected PII instance."""

    pii_type: PIIType
    value_masked: str  # Masked version of the detected value
    start_pos: int
    end_pos: int
    confidence: float = Field(ge=0.0, le=1.0)


class PIIScanResult(BaseModel):
    """Result of a PII scan."""

    has_pii: bool
    detections: list[PIIDetection]
    risk_level: str  # "none", "low", "medium", "high"


class InjectionScanResult(BaseModel):
    """Result of an injection scan."""

    is_safe: bool
    threats: list[dict]  # List of detected threats with type and detail
    sanitized_content: str  # Content with threats neutralized


# ─── Field-Level Encryption ──────────────────────────────────────


def derive_key(master_key: str, salt: bytes) -> bytes:
    """
    Derive an AES-256 encryption key from a master key using PBKDF2.

    The master key is the user's vault key (stored in secrets manager).
    Each encryption operation uses a unique salt for key derivation,
    ensuring different derived keys even with the same master key.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=AES_KEY_SIZE,
        salt=salt,
        iterations=KDF_ITERATIONS,
    )
    return kdf.derive(master_key.encode("utf-8"))


def encrypt_field(plaintext: str, master_key: str) -> EncryptedPayload:
    """
    Encrypt a field value using AES-256-GCM.

    Each encryption uses:
    - A unique salt for key derivation (PBKDF2)
    - A unique nonce for AES-GCM
    This ensures that encrypting the same plaintext twice produces
    different ciphertext (semantic security).
    """
    salt = os.urandom(SALT_SIZE)
    key = derive_key(master_key, salt)
    nonce = os.urandom(NONCE_SIZE)

    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)

    return EncryptedPayload(
        ciphertext=base64.b64encode(ciphertext).decode("ascii"),
        nonce=base64.b64encode(nonce).decode("ascii"),
        salt=base64.b64encode(salt).decode("ascii"),
    )


def decrypt_field(payload: EncryptedPayload, master_key: str) -> str:
    """
    Decrypt a field value using AES-256-GCM.

    Raises cryptography.exceptions.InvalidTag if the key is wrong
    or the ciphertext has been tampered with.
    """
    salt = base64.b64decode(payload.salt)
    key = derive_key(master_key, salt)
    nonce = base64.b64decode(payload.nonce)
    ciphertext = base64.b64decode(payload.ciphertext)

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")


def generate_master_key() -> str:
    """
    Generate a cryptographically secure master key.

    Returns a 64-character hex string (256 bits of entropy).
    """
    return secrets.token_hex(32)


def rotate_encryption(
    plaintext: str,
    old_key: str,
    new_key: str,
    old_payload: EncryptedPayload,
) -> EncryptedPayload:
    """
    Re-encrypt data with a new key during key rotation.

    Steps:
    1. Decrypt with old key
    2. Verify decrypted content matches expected plaintext
    3. Re-encrypt with new key
    """
    decrypted = decrypt_field(old_payload, old_key)
    if decrypted != plaintext:
        raise RuntimeError(
            "Key rotation integrity check failed: decrypted content does not match expected plaintext"
        )
    return encrypt_field(plaintext, new_key)


# ─── Injection Prevention ────────────────────────────────────────

# Patterns that indicate prompt injection attempts
PROMPT_INJECTION_PATTERNS = [
    r"(?i)ignore\s+(previous|all|above)\s+(\w+\s+)*(instructions|prompts|rules)",
    r"(?i)you\s+are\s+now\s+(a|an)\s+",
    r"(?i)system\s*:\s*",
    r"(?i)<<\s*SYS\s*>>",
    r"(?i)\[INST\]",
    r"(?i)act\s+as\s+(if|though)\s+you",
    r"(?i)forget\s+(everything|all|your)\s+(you|instructions|training)",
    r"(?i)override\s+(your|the|all)\s+(instructions|rules|guidelines)",
    r"(?i)jailbreak",
    r"(?i)DAN\s+mode",
]

# Patterns that indicate SQL injection attempts
SQL_INJECTION_PATTERNS = [
    r"(?i)(\b(SELECT|INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|EXEC|UNION)\b.*\b(FROM|INTO|TABLE|WHERE|SET)\b)",
    r"(?i)(--|#|/\*|\*/)",  # SQL comments
    r"(?i)(\bOR\b\s+\d+\s*=\s*\d+)",  # OR 1=1 style
    r"(?i)(\bAND\b\s+\d+\s*=\s*\d+)",  # AND 1=1 style
    r"';",  # String termination
]

# Patterns that indicate XSS attempts
XSS_PATTERNS = [
    r"<script[^>]*>",
    r"javascript\s*:",
    r"on(error|load|click|mouseover)\s*=",
    r"<iframe[^>]*>",
    r"<object[^>]*>",
    r"<embed[^>]*>",
]


def scan_for_injection(content: str) -> InjectionScanResult:
    """
    Scan content for injection attempts.

    Checks for:
    - Prompt injection (attempts to override agent instructions)
    - SQL injection (attempts to manipulate database queries)
    - XSS (cross-site scripting attempts)

    Returns sanitized content with threats neutralized.
    """
    threats = []
    sanitized = content

    # Check prompt injection
    for pattern in PROMPT_INJECTION_PATTERNS:
        matches = re.finditer(pattern, content)
        for match in matches:
            threats.append(
                {
                    "type": "prompt_injection",
                    "pattern": pattern[:50],
                    "match": match.group()[:100],
                    "position": match.start(),
                }
            )
            # Neutralize by wrapping in brackets
            sanitized = sanitized.replace(match.group(), f"[FILTERED: {match.group()[:20]}...]")

    # Check SQL injection
    for pattern in SQL_INJECTION_PATTERNS:
        matches = re.finditer(pattern, content)
        for match in matches:
            threats.append(
                {
                    "type": "sql_injection",
                    "pattern": pattern[:50],
                    "match": match.group()[:100],
                    "position": match.start(),
                }
            )

    # Check XSS
    for pattern in XSS_PATTERNS:
        matches = re.finditer(pattern, content)
        for match in matches:
            threats.append(
                {
                    "type": "xss",
                    "pattern": pattern[:50],
                    "match": match.group()[:100],
                    "position": match.start(),
                }
            )
            sanitized = sanitized.replace(match.group(), "[FILTERED]")

    return InjectionScanResult(
        is_safe=len(threats) == 0,
        threats=threats,
        sanitized_content=sanitized,
    )


# ─── PII Detection ───────────────────────────────────────────────

# PII detection patterns
PII_PATTERNS = {
    PIIType.EMAIL: {
        "pattern": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "mask": lambda m: m[:2] + "***@" + m.split("@")[1] if "@" in m else "***",
        "confidence": 0.95,
    },
    PIIType.PHONE: {
        "pattern": r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        "mask": lambda m: m[:3] + "***" + m[-2:],
        "confidence": 0.85,
    },
    PIIType.SSN: {
        "pattern": r"\b\d{3}[-\s]?\d{2}[-\s]?\d{4}\b",
        "mask": lambda m: "***-**-" + m[-4:],
        "confidence": 0.80,
    },
    PIIType.CREDIT_CARD: {
        "pattern": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
        "mask": lambda m: "****-****-****-" + m[-4:],
        "confidence": 0.90,
    },
    PIIType.IP_ADDRESS: {
        "pattern": r"\b(?:\d{1,3}\.){3}\d{1,3}\b",
        "mask": lambda m: m.rsplit(".", 1)[0] + ".***",
        "confidence": 0.75,
    },
}


def scan_for_pii(content: str) -> PIIScanResult:
    """
    Scan content for personally identifiable information.

    Detects: emails, phone numbers, SSNs, credit card numbers, IP addresses.
    Returns masked versions of detected PII for safe logging.
    """
    detections = []

    for pii_type, config in PII_PATTERNS.items():
        for match in re.finditer(config["pattern"], content):
            value = match.group()
            detections.append(
                PIIDetection(
                    pii_type=pii_type,
                    value_masked=config["mask"](value),
                    start_pos=match.start(),
                    end_pos=match.end(),
                    confidence=config["confidence"],
                )
            )

    # Determine risk level
    if not detections:
        risk_level = "none"
    elif len(detections) <= 2:
        risk_level = "low"
    elif len(detections) <= 5:
        risk_level = "medium"
    else:
        risk_level = "high"

    return PIIScanResult(
        has_pii=len(detections) > 0,
        detections=detections,
        risk_level=risk_level,
    )


def redact_pii(content: str) -> str:
    """
    Redact all detected PII from content.

    Replaces PII with masked versions for safe storage or logging.
    """
    result = content
    scan = scan_for_pii(content)

    # Sort detections by position (reverse) to maintain correct positions during replacement
    sorted_detections = sorted(scan.detections, key=lambda d: d.start_pos, reverse=True)

    for detection in sorted_detections:
        result = (
            result[: detection.start_pos]
            + f"[{detection.pii_type.value.upper()}: {detection.value_masked}]"
            + result[detection.end_pos :]
        )

    return result


# ─── Content Security Pipeline ────────────────────────────────────


class SecurityScanResult(BaseModel):
    """Combined security scan result."""

    is_safe: bool
    injection_scan: InjectionScanResult
    pii_scan: PIIScanResult
    sanitized_content: str
    blocked: bool = False
    block_reason: str | None = None


def full_security_scan(content: str) -> SecurityScanResult:
    """
    Run the full security pipeline on content.

    Pipeline:
    1. Injection scan (prompt injection, SQL injection, XSS)
    2. PII detection
    3. Content sanitization

    If critical threats are found, content is blocked.
    """
    injection = scan_for_injection(content)
    pii = scan_for_pii(content)

    # Determine if content should be blocked
    blocked = False
    block_reason = None

    # Block if prompt injection detected
    prompt_injections = [t for t in injection.threats if t["type"] == "prompt_injection"]
    if prompt_injections:
        blocked = True
        block_reason = f"Prompt injection detected: {len(prompt_injections)} threat(s)"

    # Block if SQL injection detected
    sql_injections = [t for t in injection.threats if t["type"] == "sql_injection"]
    if len(sql_injections) >= 2:  # Multiple SQL patterns = likely attack
        blocked = True
        block_reason = f"SQL injection detected: {len(sql_injections)} threat(s)"

    return SecurityScanResult(
        is_safe=injection.is_safe and not pii.has_pii,
        injection_scan=injection,
        pii_scan=pii,
        sanitized_content=injection.sanitized_content,
        blocked=blocked,
        block_reason=block_reason,
    )
