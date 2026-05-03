from __future__ import annotations

import argparse

from app.config import get_settings
from app.database import create_or_promote_admin, get_database_path, init_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Create or promote a Wonky Studio admin user.")
    parser.add_argument("email", help="Email address that will be allowed to sign in as admin.")
    parser.add_argument("--name", help="Display name for the admin user.")
    args = parser.parse_args()

    settings = get_settings()
    db_path = get_database_path()
    init_database(
        db_path,
        organization_id=settings.organization_id,
        organization_name=settings.organization_name,
    )
    user = create_or_promote_admin(
        db_path,
        organization_id=settings.organization_id,
        email=args.email,
        display_name=args.name,
    )
    print(f"Admin ready: {user['email']} ({user['organization_id']})")


if __name__ == "__main__":
    main()

