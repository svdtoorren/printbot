# PrintBot Gateway Client

## Ansible Deployment

When running Ansible playbooks, always pass the inventory file explicitly:

```bash
cd ansible && ansible-playbook -i inventory.ini site.yml
```

The `ansible.cfg` does not specify an inventory path because the developer works with multiple Ansible projects. Never add `inventory` to `ansible.cfg`.

## Server Repo

The companion server lives at `~/Development/printgateway-server/`. Changes there are on the `main` branch. Changes in this repo are on the `websocket` branch.
