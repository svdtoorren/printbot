#!/usr/bin/env python3
"""Debug script to list all available mail folders for a mailbox."""

import sys
from .config import Settings
from .graph_client import GraphClient

def list_all_folders(client: GraphClient, mailbox_upn: str):
    """List all mail folders (root level and Inbox children)."""
    import requests

    print(f"\n📬 Listing folders for: {mailbox_upn}\n")

    # Get root level folders
    print("=== Root Level Folders ===")
    url = f"https://graph.microsoft.com/v1.0/users/{mailbox_upn}/mailFolders"
    r = requests.get(url, headers=client._headers(), timeout=30)
    r.raise_for_status()
    root_folders = r.json().get('value', [])

    for folder in root_folders:
        child_count = folder.get('childFolderCount', 0)
        unread = folder.get('unreadItemCount', 0)
        total = folder.get('totalItemCount', 0)
        print(f"  📁 {folder['displayName']:<30} (ID: {folder['id'][:20]}..., Unread: {unread}, Total: {total}, Children: {child_count})")

    # Get Inbox child folders
    print("\n=== Inbox Child Folders ===")
    inbox_id = None
    for folder in root_folders:
        if folder['displayName'] == 'Inbox':
            inbox_id = folder['id']
            break

    if inbox_id:
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox_upn}/mailFolders/{inbox_id}/childFolders"
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        child_folders = r.json().get('value', [])

        if child_folders:
            for folder in child_folders:
                unread = folder.get('unreadItemCount', 0)
                total = folder.get('totalItemCount', 0)
                print(f"  📂 {folder['displayName']:<30} (ID: {folder['id'][:20]}..., Unread: {unread}, Total: {total})")
        else:
            print("  (no child folders in Inbox)")
    else:
        print("  (Inbox not found)")

    print("\n" + "="*80 + "\n")

def test_folder_access(client: GraphClient, mailbox_upn: str, folder_name: str):
    """Test if we can access a specific folder."""
    print(f"🔍 Testing access to folder: {folder_name}")

    try:
        folder_id = client.get_folder_id(mailbox_upn, folder_name)
        print(f"✅ Found folder ID: {folder_id}")

        # Try to list messages (without filter first)
        import requests
        url = f"https://graph.microsoft.com/v1.0/users/{mailbox_upn}/mailFolders/{folder_id}/messages?$top=5"
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        messages = r.json().get('value', [])
        print(f"✅ Can list messages: {len(messages)} messages found")

        return folder_id
    except Exception as ex:
        print(f"❌ Error: {ex}")
        return None

def main():
    """Main debug function."""
    try:
        s = Settings()
        s.validate()

        print("🔐 Authenticating with Microsoft Graph...")
        client = GraphClient(s.tenant_id, s.client_id, s.client_secret)

        # Ensure we have a valid token
        client._ensure_token()
        print("✅ Authentication successful\n")

        # List all folders
        list_all_folders(client, s.mailbox_upn)

        # Test the configured folder
        print(f"Testing configured folder: {s.mail_folder}")
        folder_id = test_folder_access(client, s.mailbox_upn, s.mail_folder)

        if folder_id:
            print(f"\n✅ Configuration OK - folder '{s.mail_folder}' is accessible")
        else:
            print(f"\n⚠️  Folder '{s.mail_folder}' not found or not accessible")
            print(f"💡 Tip: Use 'Inbox' or one of the folders listed above")

    except Exception as ex:
        print(f"\n❌ Fatal error: {ex}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
