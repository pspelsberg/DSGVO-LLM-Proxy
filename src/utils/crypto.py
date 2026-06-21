import os
import logging
import threading
from pathlib import Path
from cryptography.fernet import Fernet

# Project root directory
BASE_DIR = Path(__file__).resolve().parent.parent.parent
KEY_FILE = BASE_DIR / ".gateway_secret.key"

logger = logging.getLogger(__name__)

_fernet = None
_fernet_lock = threading.Lock()

def get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet
    
    with _fernet_lock:
        if _fernet is not None:
            return _fernet
            
        # 1. Try loading key from environment variable
        env_key = os.getenv("GATEWAY_ENCRYPTION_KEY")
        if env_key:
            try:
                # Ensure key is valid Fernet key
                _fernet = Fernet(env_key.encode("utf-8"))
                logger.info("Using encryption key from environment variable GATEWAY_ENCRYPTION_KEY.")
                return _fernet
            except Exception as e:
                logger.error(f"Invalid encryption key in GATEWAY_ENCRYPTION_KEY environment variable: {str(e)}. Falling back to key file.")

        # 2. Fallback to local key file
        # Generate key if it does not exist
        if not KEY_FILE.exists():
            key = Fernet.generate_key()
            try:
                with open(KEY_FILE, "wb") as f:
                    f.write(key)
            except Exception as e:
                # Abort startup: a transient key would make all persisted data unrecoverable after restart
                raise RuntimeError(
                    f"CRITICAL: Cannot persist encryption key to {KEY_FILE}. "
                    f"Set GATEWAY_ENCRYPTION_KEY env var or fix file permissions. Error: {e}"
                ) from e
        else:
            try:
                with open(KEY_FILE, "rb") as f:
                    key = f.read()
            except Exception as e:
                raise RuntimeError(
                    f"CRITICAL: Cannot read encryption key from {KEY_FILE}. "
                    f"Set GATEWAY_ENCRYPTION_KEY env var or fix file permissions. Error: {e}"
                ) from e
                
        try:
            _fernet = Fernet(key)
        except Exception as e:
            raise RuntimeError(
                f"CRITICAL: Invalid key format in {KEY_FILE}. "
                f"Delete the file to regenerate or set GATEWAY_ENCRYPTION_KEY env var. Error: {e}"
            ) from e
            
        return _fernet

def encrypt_key(plain_text: str) -> str:
    """Encrypt a plain text API key using Fernet."""
    if not plain_text:
        return ""
    try:
        f = get_fernet()
        encrypted = f.encrypt(plain_text.encode("utf-8"))
        return encrypted.decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption failed: {type(e).__name__}: {e}")
        raise

def decrypt_key(encrypted_text: str) -> str:
    """Decrypt an encrypted API key using Fernet."""
    if not encrypted_text:
        return ""
    try:
        f = get_fernet()
        decrypted = f.decrypt(encrypted_text.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception as e:
        logger.warning(f"Decryption failed (data may be unencrypted or key mismatch): {type(e).__name__}: {e}")
        return ""
