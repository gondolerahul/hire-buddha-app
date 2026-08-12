"""Shared config and API client for BI entity setup."""
import json, os, sys, time
try:
    import requests
except ImportError:
    print("pip install requests"); sys.exit(1)
try:
    from jose import jwt
    from datetime import datetime, timedelta
except ImportError:
    print("pip install python-jose[cryptography]"); sys.exit(1)

BASE_URL = "http://localhost:8000/api/v1"
USER_EMAIL = "admin@hirebuddha.com"
COMPANY_ID = "699098ce-a31c-42ef-b13b-2780c7decb9d"
SECRET_KEY = "dev_secret_key_change_in_production"

def generate_token():
    data = {"sub": USER_EMAIL, "company_id": COMPANY_ID, "exp": datetime.utcnow() + timedelta(hours=24)}
    return jwt.encode(data, SECRET_KEY, algorithm="HS256")

class APIClient:
    def __init__(self):
        self.base_url = BASE_URL
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Authorization": f"Bearer {generate_token()}",
        })

    def create_entity(self, payload):
        resp = self.session.post(f"{self.base_url}/ai/entities", json=payload)
        if resp.status_code not in (200, 201):
            print(f"  ❌ FAILED: {resp.status_code} — {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        print(f"  ✅ Created: {data['name']} → {data['id']}")
        return data

    def update_entity(self, entity_id, payload):
        resp = self.session.put(f"{self.base_url}/ai/entities/{entity_id}", json=payload)
        if resp.status_code not in (200, 201):
            print(f"  ❌ UPDATE FAILED: {resp.status_code} — {resp.text[:500]}")
            resp.raise_for_status()
        data = resp.json()
        print(f"  ✅ Updated: {data['name']} — hierarchy linked")
        return data

    def delete_entity(self, entity_id):
        resp = self.session.delete(f"{self.base_url}/ai/entities/{entity_id}")
        if resp.status_code in (200, 204):
            print(f"  🗑️  Deleted: {entity_id}")
        elif resp.status_code == 404:
            print(f"  ⚠️  Not found: {entity_id}")
        else:
            print(f"  ❌ Delete failed: {entity_id}")

    def verify_auth(self):
        resp = self.session.get(f"{self.base_url}/ai/entities")
        if resp.status_code != 200:
            print(f"  ❌ Auth failed: {resp.status_code}")
            sys.exit(1)
        print(f"  ✅ Auth OK ({len(resp.json())} existing entities)")
