"""MongoDB Connectivity & Diagnostics Utility for SDMS.

Usage:
    python scripts/test_mongo_connection.py [optional_mongodb_uri]
"""
import os
import sys
import time
from pathlib import Path

# Load .env
root = Path(__file__).resolve().parent.parent
env_file = root / ".env"
if env_file.exists():
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v

DEFAULT_URI = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/sdms")


def mask_uri(uri: str) -> str:
    if "@" in uri:
        prefix, rest = uri.split("@", 1)
        scheme_user = prefix.split("://", 1)
        if len(scheme_user) == 2 and ":" in scheme_user[1]:
            scheme, creds = scheme_user
            user, _ = creds.split(":", 1)
            return f"{scheme}://{user}:****@{rest}"
    return uri


def main():
    target_uri = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URI
    db_name = os.environ.get("MONGODB_DB", "sdms")

    print("=" * 65)
    print("SDMS MongoDB Connection Diagnostics")
    print("=" * 65)
    print(f"Target URI: {mask_uri(target_uri)}")
    print(f"Target Database: {db_name}")
    print("Connecting...")

    try:
        from pymongo import MongoClient
        client = MongoClient(target_uri, serverSelectionTimeoutMS=4000)
        t0 = time.time()
        client.admin.command("ping")
        elapsed_ms = (time.time() - t0) * 1000

        print(f"[SUCCESS] Connected to MongoDB in {elapsed_ms:.1f}ms!")

        # Server info
        try:
            build_info = client.admin.command("buildinfo")
            print(f"  - MongoDB Version: {build_info.get('version', 'unknown')}")
        except Exception:
            pass

        db = client[db_name]
        colls = db.list_collection_names()
        print(f"  - Database '{db_name}' collections found ({len(colls)}): {colls}")
        for c in colls:
            count = db[c].count_documents({})
            print(f"      * {c}: {count} documents")

        print("=" * 65)
        print("MongoDB is healthy and ready for live SDMS donation streaming!")
        print("=" * 65)
        return 0

    except Exception as e:
        print(f"[FAILURE] Unable to connect to MongoDB:")
        print(f"  Error: {e}")
        print("\nSuggestions:")
        print("  1. If using MongoDB Atlas (Cloud), ensure your IP is whitelisted in Atlas Network Access")
        print("     and verify your username/password in .env.")
        print("  2. If using local MongoDB, ensure 'mongod' is running on port 27017.")
        print("  3. You can also connect via the SDMS Web UI in the MongoDB Settings modal.")
        print("=" * 65)
        return 1


if __name__ == "__main__":
    sys.exit(main())
