"""Secure one-time administrator bootstrap and explicit workspace sharing."""

import argparse
from getpass import getpass
import re
import sys

from app.environment import load_backend_environment

load_backend_environment()

from sqlalchemy import select
from app.auth import hash_password, normalize_email, verify_password
from app.database import SessionLocal, initialize_database
from app.models import User, Workspace


def main() -> int:
    parser = argparse.ArgumentParser(description="BedSynth AI account administration")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="Create the first administrator account")
    create.add_argument("--email")
    share = sub.add_parser("share-workspace", help="Explicitly allow standard users to access a workspace")
    share.add_argument("workspace_id", type=int)
    share.add_argument("--unshare", action="store_true")
    args = parser.parse_args()
    initialize_database()
    db = SessionLocal()
    try:
        if args.command == "create-admin":
            email = normalize_email(args.email or input("Administrator email: "))
            existing = db.scalar(select(User).where(User.email == email))
            if existing:
                password = getpass("Existing account password to authorize administrator bootstrap: ")
                if not verify_password(password, existing.password_hash):
                    print("The account could not be verified.")
                    return 1
                existing.role = "admin"
                existing.is_active = True
                db.commit()
                print("Administrator access enabled for the verified account.")
                return 0
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
                print("Enter a valid email address.")
                return 2
            password = getpass("Administrator password (12+ characters): ")
            confirmation = getpass("Confirm password: ")
            if len(password) < 12 or len(password) > 128 or password != confirmation:
                print("Passwords must match and contain 12 to 128 characters.")
                return 2
            db.add(User(email=email, password_hash=hash_password(password), role="admin", is_active=True))
            db.commit()
            print("Administrator account created. Sign in through the BedSynth AI login page.")
            return 0
        workspace = db.get(Workspace, args.workspace_id)
        if not workspace:
            print("Workspace not found.")
            return 1
        workspace.is_shared = not args.unshare
        db.commit()
        print(f"Workspace {workspace.id} sharing set to {workspace.is_shared}.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
