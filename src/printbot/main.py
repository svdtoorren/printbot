import time, sys, traceback
from .config import Settings
from .graph_client import GraphClient
from .processor import Processor

def main():
    s = Settings()
    s.validate()
    client = GraphClient(s.tenant_id, s.client_id, s.client_secret)
    folder_id = client.get_folder_id(s.mailbox_upn, s.mail_folder)
    proc = Processor(s.state_dir, s.printer_name)

    # Get Inbox folder ID and ensure "Printed" subfolder exists
    inbox_id = client.get_folder_id(s.mailbox_upn, "Inbox")
    printed_folder_id = client.get_or_create_subfolder(s.mailbox_upn, inbox_id, "Printed")

    print(f"[PrintBot] Watching mailbox={s.mailbox_upn} folder={s.mail_folder} sender={s.filter_sender} printer={s.printer_name}")
    print(f"[PrintBot] Printed folder ready: Inbox/Printed (ID: {printed_folder_id[:20]}...)")

    while True:
        try:
            msgs = client.list_unread_from(s.mailbox_upn, folder_id, s.filter_sender, top=10)
            for m in msgs:
                try:
                    proc.handle_message(m)
                    # Move to "Printed" subfolder instead of just marking as read
                    client.move_message(s.mailbox_upn, m['id'], printed_folder_id)
                    print(f"[PrintBot] ✓ Printed and moved: {m.get('subject', 'no subject')}")
                except Exception as ex:
                    print("[PrintBot] Error processing message:", ex, file=sys.stderr)
                    traceback.print_exc()
            time.sleep(s.poll_seconds)
        except KeyboardInterrupt:
            break
        except Exception as ex:
            print("[PrintBot] Error in loop:", ex, file=sys.stderr)
            traceback.print_exc()
            time.sleep(10)

if __name__ == '__main__':
    main()
