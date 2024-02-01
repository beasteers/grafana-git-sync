# grafana-git-sync
Backup/restore for grafana.

## Install
```bash
pip install git+https://github.com/beasteers/grafana-git-sync.git
```

## Usage
```bash
grafana-git-sync export \
    --url localhost:3000 \
    --username admin \
    --password admin

grafana-git-sync apply \
    --url grafana.myproject.com \
    --username admin \
    --password adminnnn
```



TODO:

unimplemented methods:
 - create_folder_permission
 - delete_folder_permission
 - delete_contact_point
 - create_notification_policy
 - delete_notification_policy
 - delete_snapshot
 - delete_user
 - delete_org
 - delete_plugin
