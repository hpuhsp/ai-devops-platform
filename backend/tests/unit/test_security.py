"""Unit tests for encrypt/decrypt."""
from app.core.security import encrypt, decrypt


def test_encrypt_decrypt_roundtrip():
    secret = "sk-test-api-key-12345"
    ciphertext = encrypt(secret)
    assert ciphertext != secret
    assert decrypt(ciphertext) == secret


def test_encrypt_empty_string():
    assert encrypt("") == ""
    assert decrypt("") == ""
