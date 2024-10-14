# grafana-git-sync
Backup/restore for grafana.

## Install
```bash
pip install git+https://github.com/beasteers/grafana-git-sync.git
```

## Usage
Assuming I want to export Grafana to this directory: `application/grafana`
```bash
# export from one version and save to disk
grafana-git-sync export \
    --path application/grafana \
    --url http://localhost:3000 \
    --username admin \
    --password admin

# compare export with other grafana version
grafana-git-sync diff \
    --path application/grafana \
    --url https://grafana.myproject.com \
    --username admin \
    --password adminnnn

# apply export to other grafana
grafana-git-sync apply \
    --path application/grafana \
    --url https://grafana.myproject.com \
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
