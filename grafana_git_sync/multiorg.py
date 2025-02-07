import os
from pathlib import Path
from .resources import *
from .api import API
from .util import dump_data, load_data


class CleanWriter:
    def __init__(self, root_dir):
        self.root_dir = Path(root_dir)
        self.files_initial = set(self.root_dir.rglob('*'))
        self.files_written = set()

    def write(self, data, *path):
        path = self.root_dir / os.path.join(*path)
        dump_data(data, path)
        self.files_written.add(path)

    def cleanup(self):
        for path in self.files_initial - self.files_written:
            if os.path.isfile(path):
                print('unlink', path)
                # path.unlink()


def pull(root_dir='export'):
    root_dir = Path(root_dir)
    # api = API()
    # r_orgs = Org(api)
    # r_folders = Folder(api)
    # r_dashboards = Dashboard(api)
    rs = Resources()
    api = rs.api

    writer = CleanWriter(root_dir)
    
    orgs = rs['organizations'].pull()
    if 0 not in [org['id'] for org in orgs]:
        orgs.append({'id': 0, 'name': '__global__', 'fake': True})

    for org in orgs:
        org_id = org['id']
        api.org = str(org_id)

        if not org.get('fake'):
            writer.write(org, org['name'], '__org__.yaml')

        folders = rs['folders'].pull()
        dashboards = rs['dashboards'].pull()
        if org_id:
            folders.append({'uid': '', 'title': 'General', 'orgId': org_id})
        for folder in folders:
            if folder['orgId'] != org_id:
                continue

            folder_uid = folder['uid']
            if folder_uid:
                writer.write(folder, org['name'], 'dashboards', folder['title'], '__folder__.yaml')

            for dashboard in dashboards:
                if dashboard['meta']['folderUid'] != folder_uid:
                    continue
                writer.write(dashboard['dashboard'], org['name'], 'dashboards', folder['title'], f'{dashboard["dashboard"]["title"]}.json')

        datasources = rs['datasources'].pull()
        for datasource in datasources:
            if datasource['orgId'] != org_id:
                continue
            writer.write(datasource, org['name'], 'datasources', f'{datasource["name"]}.yaml')

        if org_id == 0:
            alert_rules = rs['alert_rules'].pull()
            for alert_rule in alert_rules:
                if alert_rule.get('orgID', 0) != org_id:
                    continue
                writer.write(alert_rule, org['name'], 'alerts/rules', f'{alert_rule["title"]}.yaml')

            # notification_templates = rs['notification_templates'].pull()
            # for notification_template in notification_templates:
            #     # if notification_template['orgID'] != org_id:
            #     #     continue
            #     writer.write(notification_template, org['name'], 'alerts/templates', f'{notification_template["title"]}.yaml')
            
            notification_policies = rs['notification_policies'].pull()
            for notification_policy in notification_policies:
                if notification_policy.get('orgID', 0) != org_id:
                    continue
                writer.write(notification_policy, org['name'], 'alerts/policies', f'{notification_policy["receiver"]}.yaml')

            contact_points = rs['contact_points'].pull()
            for contact_point in contact_points:
                if contact_point.get('orgID', 0) != org_id:
                    continue
                if not contact_point['uid']:
                    continue
                writer.write(contact_point, org['name'], 'alerts/contacts', f'{contact_point["name"]}.yaml')

            plugins = rs['plugins'].pull()
            for plugin in plugins:
                writer.write(plugin, org['name'], 'plugins', f'{plugin["id"]}.yaml')

    writer.cleanup()


def push(root_dir='export'):
    root_dir = Path(root_dir)
    org_files = list(root_dir.glob('*/__org__.yaml'))

    orgs = []
    for f in org_files:
        org = load_data(f)
        org['name'] = f.parent.name
    org_ids = {org['name']: org['id'] for org in orgs}
    org_ids['__global__'] = 0

    folders = []
    dashboards = []
    datasources = []
    plugins = []
    alert_rules = []
    contact_points = []
    notification_policies = []
    notification_templates = []

    org_dirs = list(root_dir.glob('*'))
    for org_dir in org_dirs:

        folder_root = org_dir / 'dashboards'
        folder_files = list(folder_root.glob('**/__folder__.yaml'))
        dashboard_files = list(folder_root.glob('**/*.json'))
        datasource_files = list(root_dir.glob('datasources/*.yaml'))
        plugin_files = list(root_dir.glob('plugins/*.yaml'))

        for f in folder_files:
            folder = load_data(f)
            parts = f.relative_to(folder_root).parent.parts
            parents = parts[:-1]
            if parents:
                folder['parents'] = parents
            folder['title'] = f.parent.name
            folder['orgId'] = org_ids[folder['org']]
            folders.append(folder)
        folder_ids = {folder['title']: folder['uid'] for folder in folders}
        for d in folders:
            if d.get('parents'):
                d['parents'] = [folder_ids[p] for p in d['parents']]
                d['parentUid'] = folder_ids[d['parents'][-1]]

        for f in dashboard_files:
            dash = load_data(f)
            dashboard = {'dashboard': dash}
            parts = f.relative_to(folder_root).parts
            folder = parts[-2]
            dashboard['folderUid'] = folder_ids[folder]
            dashboards.append(dashboard)

        for f in plugin_files:
            plugin = load_data(f)
            plugins.append(plugin)

        for f in datasource_files:
            datasource = load_data(f)
            datasource['orgId'] = org_ids[datasource['org']]
            datasources.append(datasource)

        alert_rule_files = list(root_dir.glob('alerts/rules/*.yaml'))
        contact_point_files = list(root_dir.glob('alerts/contacts/*.yaml'))
        notification_policy_files = list(root_dir.glob('alerts/policies/*.yaml'))
        notification_template_files = list(root_dir.glob('alerts/templates/*.yaml'))

        for f in alert_rule_files:
            alert_rule = load_data(f)
            # alert_rule['orgID'] = org_ids[alert_rule['org']]
            alert_rules.append(alert_rule)

        for f in notification_policy_files:
            notification_policy = load_data(f)
            # notification_policy['orgID'] = org_ids[notification_policy['org']]
            notification_policies.append(notification_policy)

        for f in contact_point_files:
            contact_point = load_data(f)
            # contact_point['orgID'] = org_ids[contact_point['org']]
            contact_points.append(contact_point)

        for f in notification_template_files:
            notification_template = load_data(f)
            # notification_template['orgID'] = org_ids[notification_template['org']]
            notification_templates.append(notification_template)

    


    



if __name__ == '__main__':
    import fire
    fire.Fire()


    # DEFAULT_EXCLUDE = (
    #     'users', 'teams', 'team_members', 'folder_permissions', 
    #     'alert', 'mute_timing', 'snapshot', 'annotation',
    #     'dashboard_versions', 
    # )



    # r_orgs = Org(api)
    # r_plugins = Plugin(api)
    # r_folders = Folder(api)
    # r_dashboards = Dashboard(api)
    # resc = [
    #     # # Admin
    #     # Org(api),
    #     # User(api),
    #     # Team(api),
    #     # TeamMember(api),
    #     # ServiceAccount(api),

    #     # Primary Resources
    #     # Folder(api),
    #     Plugin(api),
    #     Datasource(api),
    #     LibraryElement(api),
    #     Dashboard(api),

    #     # Alerting
    #     AlertRule(api),
    #     ContactPoint(api),
    #     NotificationPolicy(api),
    #     NotificationTemplate(api),
    # ]

    # resources = ResourceGroup(api, resc)
