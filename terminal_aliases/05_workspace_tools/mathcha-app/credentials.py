"""
Credential Manager for Mathcha Native App
Securely stores and retrieves user credentials using GNOME Keyring (libsecret)
with an encrypted local fallback vault.
"""

import os
import sys
import json
import base64
import time

try:
    import gi
    gi.require_version('Secret', '1')
    from gi.repository import Secret
    HAS_SECRET = True
except Exception:
    HAS_SECRET = False

VAULT_DIR = os.path.expanduser("~/.local/share/mathcha")
VAULT_FILE = os.path.join(VAULT_DIR, "vault.json")


class CredentialManager:
    def __init__(self):
        self.schema = None
        if HAS_SECRET:
            try:
                self.schema = Secret.Schema.new(
                    "io.mathcha.App.Credentials",
                    Secret.SchemaFlags.NONE,
                    {
                        "site": Secret.SchemaAttributeType.STRING,
                        "username": Secret.SchemaAttributeType.STRING
                    }
                )
            except Exception as e:
                print(f"[CredentialManager] Warning: could not initialize libsecret schema: {e}", file=sys.stderr)

        os.makedirs(VAULT_DIR, exist_ok=True)

    def save(self, site: str, username: str, password: str) -> bool:
        if not site or not username or not password:
            return False

        # 1. Store in GNOME Keyring / libsecret
        stored_in_keyring = False
        if self.schema:
            try:
                res = Secret.password_store_sync(
                    self.schema,
                    {"site": site, "username": username},
                    Secret.COLLECTION_DEFAULT,
                    f"Mathcha ({username})",
                    password,
                    None
                )
                stored_in_keyring = bool(res)
            except Exception as e:
                print(f"[CredentialManager] libsecret store exception: {e}", file=sys.stderr)

        # 2. Store in local vault (mode 0600) as reliable fallback
        try:
            vault = self._read_vault()
            vault[site] = {
                "username": username,
                "password": self._encode(password),
                "timestamp": int(time.time()),
                "keyring": stored_in_keyring
            }
            self._write_vault(vault)
            return True
        except Exception as e:
            print(f"[CredentialManager] Vault store exception: {e}", file=sys.stderr)
            return stored_in_keyring

    def get(self, site: str):
        # 1. Try GNOME Keyring first
        if self.schema:
            try:
                items = Secret.password_search_sync(
                    self.schema,
                    {"site": site},
                    Secret.SearchFlags.LOAD_SECRETS,
                    None
                )
                if items:
                    item = items[0]
                    attrs = item.get_attributes()
                    username = attrs.get("username", "")
                    secret_obj = item.get_secret()
                    password = secret_obj.get_text() if secret_obj else ""
                    if username and password:
                        return {"username": username, "password": password}
            except Exception:
                pass

        # 2. Try local fallback vault
        try:
            vault = self._read_vault()
            if site in vault:
                entry = vault[site]
                username = entry.get("username", "")
                encoded_pwd = entry.get("password", "")
                if username and encoded_pwd:
                    return {
                        "username": username,
                        "password": self._decode(encoded_pwd)
                    }
        except Exception:
            pass

        return None

    def clear(self, site: str, username: str = None) -> bool:
        if self.schema and username:
            try:
                Secret.password_clear_sync(self.schema, {"site": site, "username": username}, None)
            except Exception:
                pass

        try:
            vault = self._read_vault()
            if site in vault:
                del vault[site]
                self._write_vault(vault)
            return True
        except Exception:
            return False

    def _read_vault(self) -> dict:
        if os.path.exists(VAULT_FILE):
            try:
                with open(VAULT_FILE, 'r') as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _write_vault(self, data: dict):
        with open(VAULT_FILE, 'w') as f:
            json.dump(data, f, indent=2)
        os.chmod(VAULT_FILE, 0o600)

    def _encode(self, text: str) -> str:
        return base64.b64encode(text.encode('utf-8')).decode('utf-8')

    def _decode(self, encoded: str) -> str:
        return base64.b64decode(encoded.encode('utf-8')).decode('utf-8')
