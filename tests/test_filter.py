#!/usr/bin/env python3
"""Test the exact filter query that's failing."""

from src.printbot.config import Settings
from src.printbot.graph_client import GraphClient

def main():
    s = Settings()
    s.validate()

    print(f"🔐 Authenticating...")
    client = GraphClient(s.tenant_id, s.client_id, s.client_secret)

    print(f"📬 Getting folder ID for: {s.mail_folder}")
    folder_id = client.get_folder_id(s.mailbox_upn, s.mail_folder)
    print(f"✅ Folder ID: {folder_id}\n")

    print("=" * 80)
    print("TEST 1: List ALL unread messages (no sender filter)")
    print("=" * 80)
    try:
        import requests
        url = f"https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{folder_id}/messages?$filter=isRead eq false&$top=10"
        print(f"URL: {url}\n")
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        messages = r.json().get('value', [])
        print(f"✅ SUCCESS: Found {len(messages)} unread messages")
        for msg in messages:
            sender = msg.get('from', {}).get('emailAddress', {}).get('address', 'unknown')
            subject = msg.get('subject', 'no subject')
            print(f"  📧 From: {sender}, Subject: {subject}")
    except Exception as ex:
        print(f"❌ FAILED: {ex}\n")

    print("\n" + "=" * 80)
    print(f"TEST 2: List unread messages FROM '{s.filter_sender}' (with single quotes)")
    print("=" * 80)
    try:
        import requests
        filt = f"from/emailAddress/address eq '{s.filter_sender}' and isRead eq false"
        url = f"https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{folder_id}/messages?$filter={filt}&$top=10"
        print(f"Filter: {filt}")
        print(f"URL: {url}\n")
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        messages = r.json().get('value', [])
        print(f"✅ SUCCESS: Found {len(messages)} messages")
        for msg in messages:
            sender = msg.get('from', {}).get('emailAddress', {}).get('address', 'unknown')
            subject = msg.get('subject', 'no subject')
            print(f"  📧 From: {sender}, Subject: {subject}")
    except Exception as ex:
        print(f"❌ FAILED: {ex}")
        print(f"   This is the error PrintBot is hitting!\n")

    print("\n" + "=" * 80)
    print(f"TEST 3: Try URL encoding the filter")
    print("=" * 80)
    try:
        import requests
        from urllib.parse import quote
        filt = f"from/emailAddress/address eq '{s.filter_sender}' and isRead eq false"
        filt_encoded = quote(filt, safe='')
        url = f"https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{folder_id}/messages?$filter={filt_encoded}&$top=10"
        print(f"Filter (encoded): {filt_encoded}")
        print(f"URL: {url}\n")
        r = requests.get(url, headers=client._headers(), timeout=30)
        r.raise_for_status()
        messages = r.json().get('value', [])
        print(f"✅ SUCCESS: Found {len(messages)} messages")
    except Exception as ex:
        print(f"❌ FAILED: {ex}\n")

    print("\n" + "=" * 80)
    print("TEST 4: Use params dict (automatic encoding)")
    print("=" * 80)
    try:
        import requests
        url = f"https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{folder_id}/messages"
        filt = f"from/emailAddress/address eq '{s.filter_sender}' and isRead eq false"
        params = {
            '$filter': filt,
            '$top': 10
        }
        print(f"Filter: {filt}\n")
        r = requests.get(url, headers=client._headers(), params=params, timeout=30)
        r.raise_for_status()
        messages = r.json().get('value', [])
        print(f"✅ SUCCESS: Found {len(messages)} messages")
        for msg in messages:
            sender = msg.get('from', {}).get('emailAddress', {}).get('address', 'unknown')
            subject = msg.get('subject', 'no subject')
            print(f"  📧 From: {sender}, Subject: {subject}")
    except Exception as ex:
        print(f"❌ FAILED: {ex}\n")

if __name__ == '__main__':
    main()
