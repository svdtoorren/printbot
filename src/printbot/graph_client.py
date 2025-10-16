import requests
import msal
from typing import Dict, Any, List, Optional

GRAPH_SCOPE = ["https://graph.microsoft.com/.default"]
GRAPH_BASE = "https://graph.microsoft.com/v1.0"

class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=f"https://login.microsoftonline.com/{tenant_id}"
        )
        self._token: Optional[str] = None
        self._token_exp = 0

    def _ensure_token(self) -> str:
        import time as _t
        if self._token and _t.time() < self._token_exp - 60:
            return self._token
        result = self.app.acquire_token_silent(GRAPH_SCOPE, account=None)
        if not result:
            result = self.app.acquire_token_for_client(scopes=GRAPH_SCOPE)
        if "access_token" not in result:
            raise RuntimeError(f"MSAL auth failed: {result}")
        self._token = result["access_token"]
        self._token_exp = int(_t.time()) + int(result.get("expires_in", 3600))
        return self._token

    def _headers(self) -> Dict[str,str]:
        return {
            "Authorization": f"Bearer {self._ensure_token()}",
            "Accept": "application/json"
        }

    def get_folder_id(self, mailbox_upn: str, display_name: str) -> str:
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/mailFolders?$filter=displayName eq '{display_name}'"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get('value'):
            return data['value'][0]['id']
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/mailFolders/Inbox/childFolders?$filter=displayName eq '{display_name}'"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        data = r.json()
        if data.get('value'):
            return data['value'][0]['id']
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/mailFolders/Inbox"
        r = requests.get(url, headers=self._headers(), timeout=30)
        r.raise_for_status()
        return r.json()['id']

    def list_unread_from(self, mailbox_upn: str, folder_id: str, sender: str, top: int = 10) -> List[Dict[str,Any]]:
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/mailFolders/{folder_id}/messages"

        # Build filter: sender + unread
        if sender:
            filter_str = f"from/emailAddress/address eq '{sender}' and isRead eq false"
        else:
            filter_str = "isRead eq false"

        # Note: $orderby removed due to "InefficientFilter" error on shared mailboxes
        # Messages are returned in default order (usually receivedDateTime desc)
        params = {
            '$filter': filter_str,
            '$top': top
        }
        r = requests.get(url, headers=self._headers(), params=params, timeout=30)

        try:
            r.raise_for_status()
        except requests.exceptions.HTTPError as ex:
            # Include response body in error for debugging
            try:
                error_detail = r.json()
                raise RuntimeError(f"Graph API error: {ex}, Response: {error_detail}") from ex
            except:
                raise RuntimeError(f"Graph API error: {ex}, Status: {r.status_code}, Body: {r.text[:500]}") from ex

        return r.json().get('value', [])

    def mark_read(self, mailbox_upn: str, message_id: str) -> None:
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/messages/{message_id}"
        r = requests.patch(url, headers=self._headers(), json={"isRead": True}, timeout=30)
        r.raise_for_status()

    def get_or_create_subfolder(self, mailbox_upn: str, parent_folder_id: str, folder_name: str) -> str:
        """Get existing subfolder ID or create it if it doesn't exist."""
        # Try to find existing subfolder
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/mailFolders/{parent_folder_id}/childFolders"
        params = {'$filter': f"displayName eq '{folder_name}'"}
        r = requests.get(url, headers=self._headers(), params=params, timeout=30)
        r.raise_for_status()

        folders = r.json().get('value', [])
        if folders:
            return folders[0]['id']

        # Create new subfolder
        r = requests.post(url, headers=self._headers(), json={"displayName": folder_name}, timeout=30)
        r.raise_for_status()
        return r.json()['id']

    def move_message(self, mailbox_upn: str, message_id: str, destination_folder_id: str) -> None:
        """Move a message to a different folder."""
        url = f"{GRAPH_BASE}/users/{mailbox_upn}/messages/{message_id}/move"
        r = requests.post(url, headers=self._headers(), json={"destinationId": destination_folder_id}, timeout=30)
        r.raise_for_status()
