#!/usr/bin/env python3
"""Display a tree view of the mailbox with all folders and messages."""

from src.printbot.config import Settings
from src.printbot.graph_client import GraphClient
import requests
from typing import List, Dict, Any
from datetime import datetime

def format_datetime(dt_str: str) -> str:
    """Format ISO datetime string to readable format."""
    try:
        dt = datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except:
        return dt_str

def get_all_folders(client: GraphClient, mailbox_upn: str) -> List[Dict[str, Any]]:
    """Get all mail folders for the mailbox."""
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_upn}/mailFolders"
    folders = []

    while url:
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        folders.extend(data.get('value', []))
        url = data.get('@odata.nextLink')

    return folders

def get_folder_messages(client: GraphClient, mailbox_upn: str, folder_id: str, top: int = 20) -> List[Dict[str, Any]]:
    """Get messages from a specific folder."""
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_upn}/mailFolders/{folder_id}/messages"
    params = {'$top': top}

    try:
        r = requests.get(url, headers=client._headers(), params=params, timeout=30)
        r.raise_for_status()
        return r.json().get('value', [])
    except requests.exceptions.HTTPError as ex:
        print(f"    Error fetching messages: {ex}")
        return []

def get_child_folders(client: GraphClient, mailbox_upn: str, parent_id: str) -> List[Dict[str, Any]]:
    """Get child folders of a specific folder."""
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_upn}/mailFolders/{parent_id}/childFolders"

    try:
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        return r.json().get('value', [])
    except requests.exceptions.HTTPError:
        return []

def print_folder_tree(client: GraphClient, mailbox_upn: str, folder: Dict[str, Any], indent: int = 0, show_messages: bool = True):
    """Recursively print folder tree with messages."""
    prefix = "  " * indent
    folder_name = folder.get('displayName', 'Unknown')
    folder_id = folder.get('id')
    total_count = folder.get('totalItemCount', 0)
    unread_count = folder.get('unreadItemCount', 0)

    # Print folder header
    print(f"{prefix}📁 {folder_name} ({unread_count}/{total_count})")

    # Get and print messages if requested
    if show_messages and total_count > 0:
        messages = get_folder_messages(client, mailbox_upn, folder_id)
        for msg in messages:
            msg_prefix = prefix + "  "
            read_status = '✓' if msg.get('isRead') else '✉'
            subject = msg.get('subject', 'no subject')
            sender = msg.get('from', {}).get('emailAddress', {}).get('address', 'unknown')
            received = format_datetime(msg.get('receivedDateTime', ''))

            print(f"{msg_prefix}{read_status} {subject}")
            print(f"{msg_prefix}  From: {sender}")
            print(f"{msg_prefix}  Date: {received}")

    # Get and print child folders recursively
    child_folders = get_child_folders(client, mailbox_upn, folder_id)
    for child in child_folders:
        print_folder_tree(client, mailbox_upn, child, indent + 1, show_messages)

def main():
    print("=" * 80)
    print("📬 MAILBOX TREE VIEW")
    print("=" * 80)

    # Load settings and authenticate
    s = Settings()
    s.validate()

    print(f"\n🔐 Authenticating...")
    client = GraphClient(s.tenant_id, s.client_id, s.client_secret)

    print(f"📧 Mailbox: {s.mailbox_upn}\n")

    # Get all top-level folders
    print("Fetching folder structure...")
    folders = get_all_folders(client, s.mailbox_upn)

    print(f"\nFound {len(folders)} top-level folders\n")
    print("=" * 80)

    # Print tree for each top-level folder
    for folder in folders:
        print_folder_tree(client, s.mailbox_upn, folder)
        print()

    print("=" * 80)
    print(f"✅ Tree view complete")

    # Print summary
    total_messages = sum(f.get('totalItemCount', 0) for f in folders)
    total_unread = sum(f.get('unreadItemCount', 0) for f in folders)
    print(f"\nSummary: {total_unread} unread / {total_messages} total messages")

if __name__ == '__main__':
    main()