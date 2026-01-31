from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os
import hashlib

def derive_key(password: str):
    return hashlib.sha256(password.encode()).digest()

class AESGCMCipher:
    def __init__(self, key: bytes):
        self.aesgcm= AESGCM(key)
        
    def encrypt(self, data:bytes)-> bytes:
        nonce=os.urandom(12)
        ciphertext=self.aesgcm.encrypt(nonce, data, None)
        return nonce + ciphertext
    def decrypt(self, data: bytes)->bytes:
        nonce=data[:12]
        ciphertext=data[12:]
        return self.aesgcm.decrypt(nonce, ciphertext, None)       