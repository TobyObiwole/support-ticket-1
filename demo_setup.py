"""Create a new, synthetic rehearsal database. Never overwrite an existing file."""

import argparse
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(__file__).parent / ".demo" / "tickets.db")
    args = parser.parse_args()
    target = args.database.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental replacement, even if the DB is empty.
    try:
        with target.open("xb"):
            pass
    except FileExistsError:
        parser.error("Database already exists. Choose a new --database path; saved data was not changed.")
    os.environ["SUPPORT_TICKET_DB"] = str(target)
    import app as ticket_app

    # Exercise the same CSRF, validation, SQLite and redirect path as a browser.
    client = ticket_app.app.test_client()
    for index in range(1, 13):
        client.get("/")
        with client.session_transaction() as session:
            token = session["csrf_token"]
        fields = {
            "csrf_token": token,
            "name": f"Demo Customer {index:02d}",
            "email": f"demo{index:02d}@example.invalid",
            "problem": "DEMO: Printer is offline." if index == 1 else f"DEMO: Training request {index:02d}.",
        }
        if index == 1:
            from io import BytesIO
            from PIL import Image
            picture = BytesIO()
            Image.new("RGB", (160, 80), "#dce6f1").save(picture, format="PNG")
            picture.seek(0)
            fields["image"] = (picture, "demo-printer.png")
        response = client.post("/submit", data=fields)
        if response.status_code != 303:
            raise RuntimeError("A demo submission failed; use a new database path to retry.")
    print(f"Created 12 synthetic tickets and one generated image in {target}")
    print("No staff account or password was created. Use the interactive create-staff command next.")


if __name__ == "__main__":
    main()
