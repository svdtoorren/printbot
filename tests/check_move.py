#!/usr/bin/env python3
"""Check if mail was moved to Printed folder."""

from src.printbot.config import Settings
from src.printbot.graph_client import GraphClient
import requests

s = Settings()
client = GraphClient(s.tenant_id, s.client_id, s.client_secret)

inbox_id = client.get_folder_id(s.mailbox_upn, 'Inbox')
printed_id = client.get_or_create_subfolder(s.mailbox_upn, inbox_id, 'Printed')

# Check Inbox
url_inbox = f'https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{inbox_id}/messages'
r = requests.get(url_inbox, headers=client._headers(), params={'$top': 10}, timeout=30)
inbox_msgs = r.json().get('value', [])

# Check Printed folder
url_printed = f'https://graph.microsoft.com/v1.0/users/{s.mailbox_upn}/mailFolders/{printed_id}/messages'
r = requests.get(url_printed, headers=client._headers(), params={'$top': 10}, timeout=30)
printed_msgs = r.json().get('value', [])

print('📬 Inbox messages:', len(inbox_msgs))
for m in inbox_msgs:
    read_status = '✓ read' if m.get('isRead') else '✉ unread'
    print(f'  - [{read_status}] {m.get("subject", "no subject")}')

print('\n✅ Printed folder messages:', len(printed_msgs))
for m in printed_msgs:
    read_status = '✓ read' if m.get('isRead') else '✉ unread'
    print(f'  - [{read_status}] {m.get("subject", "no subject")}')
