#!/usr/bin/env python3
"""Inspect the PrintBot state database to see which messages have been marked as printed."""

import sqlite3
import sys
from datetime import datetime
from pathlib import Path

def inspect_database(db_path: str):
    """Inspect the state database and display all printed messages."""
    if not Path(db_path).exists():
        print(f"❌ Database not found at: {db_path}")
        print("   Make sure PrintBot has run at least once to create the database.")
        return

    print("=" * 80)
    print("📊 PRINTBOT STATE DATABASE INSPECTION")
    print("=" * 80)
    print(f"\nDatabase: {db_path}\n")

    con = sqlite3.connect(db_path)
    try:
        # Get schema info
        cursor = con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='printed'")
        schema = cursor.fetchone()
        if schema:
            print("Table Schema:")
            print(schema[0])
            print()

        # Get all printed messages
        cursor = con.execute("SELECT id, printed_utc FROM printed ORDER BY printed_utc DESC")
        rows = cursor.fetchall()

        print(f"Total messages marked as printed: {len(rows)}\n")

        if rows:
            print("Printed Messages (most recent first):")
            print("-" * 80)
            for idx, (msg_id, printed_utc) in enumerate(rows, 1):
                try:
                    dt = datetime.fromisoformat(printed_utc.replace('Z', '+00:00'))
                    formatted_date = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                except:
                    formatted_date = printed_utc

                # Truncate long IDs for display
                display_id = msg_id[:60] + "..." if len(msg_id) > 60 else msg_id

                print(f"{idx:3}. {formatted_date}")
                print(f"     ID: {display_id}")
                print()
        else:
            print("No messages have been marked as printed yet.")

        print("=" * 80)

    finally:
        con.close()

def search_message(db_path: str, search_term: str):
    """Search for a specific message ID in the database."""
    if not Path(db_path).exists():
        print(f"❌ Database not found at: {db_path}")
        return

    print(f"🔍 Searching for: {search_term}\n")

    con = sqlite3.connect(db_path)
    try:
        cursor = con.execute("SELECT id, printed_utc FROM printed WHERE id LIKE ?", (f"%{search_term}%",))
        rows = cursor.fetchall()

        if rows:
            print(f"✅ Found {len(rows)} matching message(s):\n")
            for msg_id, printed_utc in rows:
                try:
                    dt = datetime.fromisoformat(printed_utc.replace('Z', '+00:00'))
                    formatted_date = dt.strftime('%Y-%m-%d %H:%M:%S UTC')
                except:
                    formatted_date = printed_utc

                print(f"Message ID: {msg_id}")
                print(f"Printed at: {formatted_date}")
                print()
        else:
            print("❌ No matching messages found.")

    finally:
        con.close()

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Inspect PrintBot state database')
    parser.add_argument('--db', default='/var/lib/printbot/state.db',
                        help='Path to state database (default: /var/lib/printbot/state.db)')
    parser.add_argument('--search', metavar='TERM',
                        help='Search for messages containing TERM in their ID')

    args = parser.parse_args()

    if args.search:
        search_message(args.db, args.search)
    else:
        inspect_database(args.db)

if __name__ == '__main__':
    main()
