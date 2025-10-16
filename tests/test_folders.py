#!/usr/bin/env python3
"""Test folder creation and message moving."""

from src.printbot.config import Settings
from src.printbot.graph_client import GraphClient

def main():
    s = Settings()
    s.validate()

    print("🔐 Authenticating...")
    client = GraphClient(s.tenant_id, s.client_id, s.client_secret)

    # Get Inbox
    print("\n📬 Getting Inbox folder ID...")
    inbox_id = client.get_folder_id(s.mailbox_upn, "Inbox")
    print(f"✅ Inbox ID: {inbox_id}")

    # Create or get "Printed" subfolder
    print("\n📂 Creating/getting 'Printed' subfolder in Inbox...")
    printed_folder_id = client.get_or_create_subfolder(s.mailbox_upn, inbox_id, "Printed")
    print(f"✅ Printed folder ID: {printed_folder_id}")

    # List child folders to verify
    print("\n📋 Listing Inbox child folders...")
    import requests
    url = f"https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{inbox_id}/childFolders"
    r = requests.get(url, headers=client._headers(), timeout=30)
    r.raise_for_status()
    child_folders = r.json().get('value', [])

    if child_folders:
        for folder in child_folders:
            unread = folder.get('unreadItemCount', 0)
            total = folder.get('totalItemCount', 0)
            print(f"  📁 {folder['displayName']:<20} (Unread: {unread}, Total: {total})")
    else:
        print("  (no child folders)")

    print("\n✅ Folder creation test successful!")
    print(f"\n💡 The 'Printed' subfolder is ready at: Inbox/Printed")
    print(f"   ID: {printed_folder_id}")

if __name__ == '__main__':
    main()
