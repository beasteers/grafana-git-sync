#!/usr/bin/env python3

from datetime import datetime
import os
import re
import glob
import argparse
import contextlib
import collections
import logging
import time
import requests
import json
import yaml
import base64
from grafana_git_sync.util import export_dir
from packaging import version
import simplejson
from .util import load_dir, status_text, dict_diff, norm_cm_key

from IPython import embed

log = logging.getLogger(__name__.split('.')[0])
# log.setLevel(logging.DEBUG)

DEFAULT_FOLDER_PATH = 'grafana'
ROOT_FOLDER = 'General'

class API:
    '''Query tool for grafana.'''
    ROOT_FOLDER = ROOT_FOLDER
    def __init__(self, url, username=None, password=None, api_key=None):
        self.url = url
        self.headers = {"Content-type": "application/json"}
        self.api_key = api_key
        self.basicauth = None
        if username and password:
            self.login(username, password)

        backup_functions = collections.OrderedDict()
        backup_functions['dashboards'] = self.dump_dashboards
        backup_functions['datasources'] = self.dump_datasources
        backup_functions['folders'] = self.dump_folders
        backup_functions['alert_channels'] = self.dump_alert_channels
        backup_functions['organizations'] = self.dump_orgs
        backup_functions['users'] = self.dump_users
        backup_functions['snapshots'] = self.dump_snapshots
        # backup_functions['dashboard-versions'] = self.dump_dashboard_versions
        backup_functions['annotations'] = self.dump_annotations
        backup_functions['library_elements'] = self.dump_library_elements
        backup_functions['teams'] = self.dump_teams
        backup_functions['team_members'] = self.dump_team_members
        backup_functions['alert_rules'] = self.dump_alert_rules
        backup_functions['contact_points'] = self.dump_contact_points
        backup_functions['notification_policy'] = self.dump_notification_policies
        backup_functions['plugins'] = self.dump_plugins
        self.backup_functions = backup_functions

        restore_functions = collections.OrderedDict()
        # Folders must be restored before Library-Elements
        restore_functions['plugins'] = self.apply_plugins
        restore_functions['folders'] = self.apply_folders
        restore_functions['datasources'] = self.apply_datasources
        restore_functions['library_elements'] = self.apply_library_elements
        restore_functions['dashboards'] = self.apply_dashboards
        restore_functions['alert_channels'] = self.apply_alert_channels
        restore_functions['organizations'] = self.apply_orgs
        # restore_functions['users'] = self.apply_users
        restore_functions['snapshots'] = self.apply_snapshots
        restore_functions['annotations'] = self.apply_annotations
        restore_functions['teams'] = self.apply_teams
        restore_functions['team_members'] = self.apply_team_members
        # restore_functions['folder_permissions'] = self.apply_folder_permissions
        restore_functions['alert_rules'] = self.apply_alert_rules
        restore_functions['contact_points'] = self.apply_contact_points
        self.restore_functions = restore_functions

    def login(self, username, password):
        self.basicauth = base64.b64encode(f"{username}:{password}".encode()).decode()

    #region --------------------------- Requests --------------------------------- #

    def _req(self, method, path, basic=False, params=None, **kw):
        log.debug('%s: %s', method, path)
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = dict(self.headers)
        if not basic and self.api_key:
            headers['Authorization'] = f"Bearer {self.api_key}"
        else:
            headers['Authorization'] = f'Basic {self.basicauth}'
        response = requests.request(method, f"{self.url}{path}", headers=headers, params=params, **kw)
        # log.debug('%s', response.status_code)
        try:
            response.raise_for_status()
            return response.json()
        except simplejson.decoder.JSONDecodeError as e:
            log.error('%s: %s', response.status_code, response.content.decode())
            raise
        except requests.exceptions.HTTPError as e:
            log.error('%s: %s', response.status_code, response.content.decode())
            raise
    
    def get(self, path, **kw):
        return self._req('GET', path, **kw)
    
    def post(self, path, data=None, **kw):
        return self._req('POST', path, json=data, **kw)
    
    def put(self, path, data=None, **kw):
        return self._req('PUT', path, json=data, **kw)
    
    def delete(self, path, **kw):
        return self._req('DELETE', path, **kw)

    #endregion
    #region -------------------------- Basic utils ------------------------------- #

    def health(self):
        return self.get('/api/health')

    def auth_check(self):
        return self.get('/api/auth/keys')
    
    def get_version(self):
        d = self.health()
        match = re.search(r'\b(\d+\.\d+\.\d+)', d['version'])
        ver = match.group(1) if match else None
        return version.parse(ver) if ver else None

    def compare_version(self, min_version=None, max_version=None):
        ver = self.get_version()
        return (
            not ver or
            (not min_version or version.parse(min_version) <= ver) and
            (not max_version or version.parse(max_version) >= ver)
        )

    def dashboard_uid_feature_check(self):
        ds = self.search_dashboards(1, 1)
        return ds and 'uid' in ds[0]
    
    def datasource_uid_feature_check(self):
        ds = self.search_datasources()
        return ds and 'uid' in ds[0]
    
    def paging_feature_check(self):
        try:
            ds1 = self.search_dashboards(1, 1)[0]
            ds2 = self.search_dashboards(2, 1)[0]
            return ds1 != ds2
        except Exception:
            return False

    def contact_point_feature_check(self):
        try:
            self.search_contact_points()
            return True
        except Exception:
            return False
        
    #endregion
    #region ----------------------- Service Accounts ----------------------------- #

    def search_service_accounts(self, name=None, page=1):
        return self.get('/api/serviceaccounts/search', params={'query': name})
    
    def get_service_account(self, id):
        return self.get(f'/api/serviceaccounts/{id}')
    
    def create_service_account(self, payload, fname=None):
        try:
            existing = self.search_service_accounts(payload['name'])[0]
            return self.update_service_account(existing['id'], payload)
        except Exception:
            return self.post('/api/serviceaccounts', payload)
    
    def update_service_account(self, name, role):
        return self.put('/api/serviceaccounts', {'name': name, 'role': role})

    #endregion
    #region -------------------------- Dashboards -------------------------------- #

    def search_dashboards(self, page=0, limit=5000):
        return self.get(f'/api/search/?type=dash-db', params={'page': page, 'limit': limit})

    def get_dashboard(self, uid):
        return self.get(f'/api/dashboards/uid/{uid}')
    
    def delete_dashboard_by_uid(self, uid):
        return self.delete(f'/api/dashboards/uid/{uid}')

    def delete_dashboard_by_slug(self, slug):
        return self.delete(f'/api/dashboards/db/{slug}')
    
    def delete_dashboard(self, payload):
        return self.delete_dashboard_by_uid(payload['dashboard']['uid'])

    def create_dashboard(self, payload, fname=None):
        payload = self._replace_folder(payload, fname)
        payload['dashboard']['id'] = None
        return self.post('/api/dashboards/db', payload)
    
    # def get_dashboard_versions(self, dashboard_id):
    #     return self.get(f'/api/dashboards/id/{dashboard_id}/versions')

    # def get_dashboard_version(self, dashboard_id, version_number):
    #     return self.get(f'/api/dashboards/id/{dashboard_id}/versions/{version_number}')

    def _replace_folder(self, payload, fname=None):
        fuid = 0
        if fname:
            folder_name = fname.split('/')[-2]
            if folder_name != ROOT_FOLDER:
                folders = self.search_folders(query=folder_name)
                if folders:
                    fuid = folders[0].get('id', 0)
                else:
                    fuid = self.create_folder({'title': folder_name}).get('id', 0)
        else:
            fuid = payload.get('meta', {}).get('folderUid', '')
            fuid = self.get_folder(fuid).get('id', 0) if fuid else 0

        return {
            'dashboard': payload['dashboard'],
            'folderId': fuid or 0,
            'overwrite': True
        }

    def _replace_datasource(self, dash, uid_map):
        if isinstance(dash, dict):
            # find datasource and replace it with the datasource name instead
            if dash.get('datasource') and 'uid' in dash['datasource'] and dash['datasource']['uid'] in uid_map:
                dash['datasource']['uid'] = uid_map[dash['datasource']['uid']]
            for k, v in dash.items():
                dash[k] = self._replace_datasource(v, uid_map)
        if isinstance(dash, list):
            for i, x in enumerate(dash):
                dash[i] = self._replace_datasource(x, uid_map)
        return dash

    # export/apply interface
    
    def dump_dashboards(self):
        payloads = self.search_dashboards()
        datasources = self.search_datasources()
        datasource_uids = {
            d['uid']: d['name']
            for d in datasources
        }
        for d in payloads:
            folder = (d.get('folderTitle') or self.ROOT_FOLDER).replace('/', '-')
            di = self.get_dashboard(d['uid'])
            di['dashboard'] = self._replace_datasource(di['dashboard'], datasource_uids)
            title = d['title'].replace('/', '-')
            yield f"{folder}/{title}-{d['uid']}", di

    def apply_dashboards(self, items, **kw):
        return self._apply(
            'dashboards', items,
            dump_fn=self.dump_dashboards,
            create_fn=self.create_dashboard,
            update_fn=self.create_dashboard,
            delete_fn=self.delete_dashboard,
            **kw,
        )

    #endregion
    #region -------------------------- Datasources ------------------------------- #

    def search_datasources(self):
        return self.get('/api/datasources')
    
    def get_datasource(self, uid):
        return self.get(f'/api/datasources/uid/{uid}')
    
    def create_datasource(self, payload, fname=None):
        # del payload['id']
        uid = payload['uid']
        try:
            existing = self.get_datasource(uid)
        except Exception:
            return self.post('/api/datasources', payload)
        else:
            return self.put(f'/api/datasources/uid/{uid}', payload)

    def delete_datasource_by_uid(self, uid):
        return self.delete(f'/api/datasources/uid/{uid}')

    def delete_datasource_by_id(self, id_):
        return self.delete(f'/api/datasources/{id_}')
    
    def delete_datasource(self, payload):
        return self.delete_datasource_by_uid(payload['uid'])
    
    # export/apply interface
    
    def dump_datasources(self, include_readonly=False):
        payloads = self.search_datasources()
        for d in payloads:
            if not include_readonly and d.get('readOnly'):
                continue
            yield f"{d['name']}-{d['uid']}", d

    def apply_datasources(self, items, **kw):
        return self._apply(
            'datasources', items,
            dump_fn=self.dump_datasources,
            create_fn=self.create_datasource,
            update_fn=self.create_datasource,
            delete_fn=self.delete_datasource,
            **kw,
        )

    #endregion
    #region ---------------------------- Folders --------------------------------- #

    def search_folders(self, **params):
        return self.get('/api/search/?type=dash-folder', params=params)

    def get_folder(self, uid):
        return self.get(f'/api/folders/{uid}')

    def create_folder(self, payload, fname=None):
        payload.pop('id', None)
        try:
            existing = self.get_folder(payload['uid'])
            if existing['version'] >= payload.get('version'):
                return
            return self.update_folder(payload)
        except Exception:
            return self.post('/api/folders', payload)

    def update_folder(self, payload):
        return self.put(f'/api/folders/{payload["uid"]}', payload)

    def delete_folder_by_uid(self, uid):
        return self.delete(f'/api/folders/{uid}')
    
    def delete_folder(self, payload):
        return self.delete_folder_by_uid(payload['uid'])

    def get_folder_permissions(self, uid):
        return self.get(f'/api/folders/{uid}/permissions')

    def update_folder_permissions(self, payload):
        return self.post(f'/api/folders/{payload[0]["uid"]}/permissions', items=json.dumps({'items': payload}))

    def dump_folders(self):
        payloads = self.search_folders()
        for d in payloads:
            d = self.get_folder(d['uid'])
            title = d['title'].replace('/', '-')
            yield f"{title}-{d['uid']}", d

    def dump_folder_permissions(self):
        payloads = self.search_folders()
        for d in payloads:
            d = self.get_folder_permissions(d['uid'])
            yield d.get('name', d.get('uid')), d

    def apply_folders(self, items, **kw):
        return self._apply(
            'folders', items,
            dump_fn=self.dump_folders,
            create_fn=self.create_folder,
            update_fn=self.update_folder,
            delete_fn=self.delete_folder,
            **kw,
        )

    def apply_folder_permissions(self, items, **kw):
        return self._apply(
            'folder_permissions', items,
            dump_fn=self.dump_folder_permissions,
            # create_fn=self.create_folder_permission,
            # update_fn=self.create_folder_permission,
            # delete_fn=self.delete_folder_permission,
            **kw,
        )

    #endregion
    #region ----------------------- Library elements ----------------------------- #

    def search_library_elements(self):
        return self.get('/api/library-elements?perPage=5000')['result']['elements']

    def create_library_element(self, library_element, fname=None):
        folder_uid = library_element["meta"]["folderUid"]
        fd = self.get_folder(folder_uid)
        fd = fd[0] if isinstance(fd, list) else fd
        library_element["folderUid"] = fd['uid']
        return self.post('/api/library-elements', library_element)

    def delete_library_element_by_uid(self, uid):
        return self.delete(f'/api/library-elements/{uid}')
    
    def delete_library_element(self, library_element):
        return self.delete_library_element_by_id(library_element['uid'])
    
    def dump_library_elements(self):
        payloads = self.search_library_elements()
        for d in payloads:
            yield f"{d['name']}-{d['uid']}", d

    def apply_library_elements(self, items, **kw):
        return self._apply(
            'library_elements', items,
            dump_fn=self.dump_library_elements,
            create_fn=self.create_library_element,
            update_fn=self.create_library_element,
            delete_fn=self.delete_library_element,
            **kw,
        )
    
    #endregion
    #region -------------------------- Annotations ------------------------------- #

    def search_annotations(self, ts_from, ts_to):
        return self.get(f'/api/annotations?type=annotation&limit=5000&from={ts_from}&to={ts_to}')

    def create_annotation(self, annotation, fname=None):
        return self.post('/api/annotations', annotation)

    def delete_annotation_by_id(self, id_):
        return self.delete(f'/api/annotations/{id_}')
    
    def delete_annotation(self, payload):
        return self.delete_annotation_by_id(payload['id'])
    
    def dump_annotations(self):
        now = int(round(time.time() * 1000))
        one_month_in_ms = 31 * 24 * 60 * 60 * 1000

        ts_to = now
        ts_from = now - one_month_in_ms
        thirteen_months_retention = (now - (13 * one_month_in_ms))

        while ts_from > thirteen_months_retention:
            anns = self.search_annotations(ts_from, ts_to)
            for d in anns:
                yield f"{d['dashboardUID']}-{d['panelId']}-{d['time']}-{d['timeEnd']}", d
            ts_to = ts_from
            ts_from = ts_from - one_month_in_ms

    def apply_annotations(self, items, **kw):
        return self._apply(
            'annotations', items,
            dump_fn=self.dump_annotations,
            create_fn=self.create_annotation,
            update_fn=self.create_annotation,
            delete_fn=self.delete_annotation,
            **kw,
        )

    #endregion
    #region ---------------------------- Alerts ---------------------------------- #

    def search_alerts(self):
        return self.get('/api/alerts')

    def pause_alert(self, id_):
        return self.post(f'/api/alerts/{id_}/pause', {"paused": True})

    def unpause_alert(self, id_):
        return self.post(f'/api/alerts/{id_}/pause', {"paused": False})
    
    #endregion
    #region -------------------------- Alert rules ------------------------------- #

    def search_alert_rules(self):
        # if not self.compare_version('9.4.0'):
        #     return self.get('/api/ruler/grafana/api/v1/rules')
        return self.get('/api/v1/provisioning/alert-rules', basic=True)

    def get_alert_rule(self, uid):
        return self.get(f'/api/v1/provisioning/alert-rules/{uid}', basic=True)

    def create_alert_rule(self, alert, fname=None):
        if not self.compare_version('9.4.0'):
            return
        del alert['id']
        uid = alert['uid']
        try:
            existing = self.get_alert_rule(uid)
            return self.update_alert_rule(uid, alert)
        except Exception:
            return self.post('/api/v1/provisioning/alert-rules', alert, basic=True)

    def delete_alert_rule_by_uid(self, uid):
        return self.delete(f'/api/v1/provisioning/alert-rules/{uid}', basic=True)
    
    def delete_alert_rule(self, payload):
        return self.delete_alert_rule_by_uid(payload['uid'])

    def update_alert_rule(self, uid, alert):
        return self.put(f'/api/v1/provisioning/alert-rules/{uid}', alert, basic=True)
    
    def dump_alert_rules(self):
        if not self.compare_version('9.4.0') or not self.basicauth:
            return
        payloads = self.search_alert_rules()
        for d in payloads:
            yield d['uid'], d
    
    def apply_alert_rules(self, items, **kw):
        return self._apply(
            'alert_rules', items,
            dump_fn=self.dump_alert_rules,
            create_fn=self.create_alert_rule,
            update_fn=self.create_alert_rule,
            delete_fn=self.delete_alert_rule,
            **kw,
        )

    #endregion
    #region ------------------------ Alert channels ------------------------------ #

    def search_alert_channels(self):
        return self.get('/api/alert-notifications')

    def create_alert_channel(self, payload, fname=None):
        return self.post('/api/alert-notifications', payload)

    def delete_alert_channel_by_uid(self, uid):
        return self.delete(f'/api/alert-notifications/uid/{uid}')

    def delete_alert_channel_by_id(self, id_):
        return self.delete(f'/api/alert-notifications/{id_}')
    
    def delete_alert_channel(self, payload):
        return self.delete_alert_channel_by_uid(payload['uid'])

    def dump_alert_channels(self):
        payloads = self.search_alert_channels()
        for d in payloads:
            yield d.get('uid', d['id']), d

    def apply_alert_channels(self, items, **kw):
        return self._apply(
            'alert_channels', items,
            dump_fn=self.dump_alert_channels,
            create_fn=self.create_alert_channel,
            update_fn=self.create_alert_channel,
            delete_fn=self.delete_alert_channel,
            **kw,
        )

    #endregion
    #region ------------------------ Contact points ------------------------------ #

    def search_contact_points(self):
        return self.get('/api/v1/provisioning/contact-points')

    def create_contact_point(self, payload, fname=None):
        if not self.compare_version('9.4.0'):
            return
        try:
            uid = payload['uid']
            existing = self.get_contact_point(uid)
            return self.update_contact_point(uid, payload)
        except Exception:
            return self.post('/api/v1/provisioning/contact-points', payload)

    def update_contact_point(self, uid, json_payload):
        return self.put(f'/api/v1/provisioning/contact-points/{uid}', json_payload)
    
    def dump_contact_points(self):
        payloads = self.search_contact_points()
        for d in payloads:
            yield f"{d['name']}-{d['uid']}", d

    def apply_contact_points(self, items, **kw):
        return self._apply(
            'contact_points', items,
            dump_fn=self.dump_contact_points,
            create_fn=self.create_contact_point,
            update_fn=self.create_contact_point,
            # delete_fn=self.delete_contact_point,
            **kw,
        )
    
    #endregion
    #region --------------------- Notification policies -------------------------- #

    def search_notification_policies(self):
        return self.get('/api/v1/provisioning/policies')

    def update_notification_policy(self, json_payload):
        return self.put('/api/v1/provisioning/policies', json_payload)
    
    def dump_notification_policies(self):
        if not self.compare_version('9.4.0'):
            return
        d = self.search_notification_policies()
        yield 'policies', d
        # for d in payloads:
        #     yield d.get('uid', d['id']), d

    def apply_notification_policies(self, items, **kw):
        return self._apply(
            'notification_policies', items,
            dump_fn=self.dump_notification_policies,
            create_fn=self.create_notification_policy,
            update_fn=self.create_notification_policy,
            # delete_fn=self.delete_notification_policy,
            **kw,
        )

    #endregion
    #region --------------------------- Snapshots -------------------------------- #

    def search_snapshots(self):
        return self.get('/api/dashboard/snapshots')

    def get_snapshot(self, key):
        return self.get(f'/api/snapshots/{key}')

    def create_snapshot(self, payload, fname=None):
        if 'name' not in payload:
            try:
                payload['name'] = payload['dashboard']['title']
            except KeyError:
                payload['name'] = "Untitled Snapshot"
        return self.post('/api/snapshots', payload)

    def delete_snapshot_by_key(self, key):
        return self.delete(f'/api/snapshots/{key}')
    
    # def delete_snapshot(self, payload):
    #     return self.delete_snapshot_by_key(payload['key'])
    
    def dump_snapshots(self):
        payloads = self.search_snapshots()
        for d1 in payloads:
            name = d1['name']
            d = self.get_snapshot(d1['key'])
            # random_suffix = "".join(random.choice(string.ascii_letters) for _ in range(6))
            yield f"{name}-{d1['created']}", d

    def apply_snapshots(self, items, **kw):
        return self._apply(
            'snapshots', items,
            dump_fn=self.dump_snapshots,
            create_fn=self.create_snapshot,
            update_fn=self.create_snapshot,
            # delete_fn=self.delete_snapshot,
            **kw,
        )

    #endregion
    #region ----------------------------- Users ---------------------------------- #

    def search_users(self, page=0, limit=5000):
        return self.get(f'/api/users?perpage={limit}&page={page}', basic=True)

    def get_users(self):
        return self.get('/api/org/users', basic=True)

    def get_user(self, id):
        return self.get(f'/api/users/{id}', basic=True)

    def create_user(self, payload, fname=None):
        user = self.post('/api/admin/users', payload)
        for org in payload.get('orgs', []):
            self.post(f'/api/orgs/{org["orgId"]}/users', {
                "loginOrEmail": payload.get('login', 'email'),
                "role": org.get('role', 'Viewer')
            }, basic=True)
        return user
    
    # def delete_user(self, payload):
    #     pass

    def set_user_role(self, user_id, role):
        return self.patch(f'/api/org/users/{user_id}', json_payload=json.dumps({'role': role}))

    def get_user_by_login(self, *logins):
        for email in logins:
            try:
                return self.get(f'/api/users/lookup?loginOrEmail={email}')
            except Exception:
                pass
        raise RuntimeError(f"Could not find user using: {logins}")

    def get_user_org(self, id):
        return self.get(f'/api/users/{id}/orgs', basic=True)
    
    def dump_users(self):
        if not self.basicauth:
            return
        payloads = self.search_users()
        for d in payloads:
            d = self.get_user(d['id'])
            d['orgs'] = self.get_user_org(d['id'])
            yield d['login'], d

    def apply_users(self, items, **kw):
        return self._apply(
            'users', items,
            dump_fn=self.dump_users,
            create_fn=self.create_user,
            update_fn=self.create_user,
            # delete_fn=self.delete_user,
            **kw,
        )

    #endregion
    #region ----------------------------- Teams ---------------------------------- #

    def search_teams(self, name=None):
        return self.get('/api/teams/search?perPage=5000', params={'name': name})['teams']

    def get_team(self, id_):
        return self.get(f'/api/teams/{id_}')

    def search_team_members(self, team_id):
        return self.get(f'/api/teams/{team_id}/members')

    def create_team(self, payload, fname=None):
        uid = payload['id']
        try:
            # existing = self.get_team(uid)
            existing = self.search_teams(payload['name'])[0]
        except Exception:
            return self.post('/api/teams', payload)
        else:
            return self.put(f'/api/teams/{existing["id"]}', payload)

    def delete_team(self, id_):
        return self.delete(f'/api/teams/{id_}')

    def create_team_member(self, user, team_id):
        return self.post(f'/api/teams/{team_id}/members', {
            'userId': self.get_user_by_login(user['email'], user['name'])
        })

    def delete_team_member(self, user_id, team_id):
        return self.delete(f'/api/teams/{team_id}/members/{user_id}')
    
    def dump_teams(self):
        payloads = self.search_teams()
        for d in payloads:
            d = self.get_team(d['id'])
            yield d['name'], d

    def dump_team_members(self):
        payloads = self.search_teams()
        for t in payloads:
            for d in self.search_team_members(t['id']):
                yield f"{d['teamId']}_{d['login']}", d
        
    def apply_teams(self, items, **kw):
        return self._apply(
            'teams', items,
            dump_fn=self.dump_teams,
            create_fn=self.create_team,
            update_fn=self.create_team,
            delete_fn=self.delete_team,
            **kw,
        )
    
    def apply_team_members(self, items, **kw):
        return self._apply(
            'team_members', items,
            dump_fn=self.dump_team_members,
            create_fn=self.create_team_member,
            update_fn=self.create_team_member,
            delete_fn=self.delete_team_member,
            **kw,
        )

    #endregion
    #region ----------------------------- Orgs ----------------------------------- #

    def search_orgs(self):
        return self.get('/api/orgs', basic=True)

    def get_org(self, id):
        return self.get(f'/api/orgs/{id}', basic=True)

    def create_org(self, payload, fname=None):
        try:
            # del payload['id']
            uid = payload['id']
            existing = self.get_org(uid)
            return self.update_org(uid, payload)
        except Exception:
            return self.post('/api/orgs', payload, basic=True)

    def update_org(self, id, payload):
        return self.put(f'/api/orgs/{id}', payload, basic=True)
    
    def dump_orgs(self):
        if not self.basicauth:
            return
        payloads = self.search_orgs()
        for d in payloads:
            d = self.get_org(d['id'])
            yield d['name'], d

    def apply_orgs(self, items, **kw):
        return self._apply(
            'orgs', items,
            dump_fn=self.dump_orgs,
            create_fn=self.create_org,
            update_fn=self.create_org,
            # delete_fn=self.delete_org,
            **kw,
        )

    #endregion
    #region ---------------------------- Plugins --------------------------------- #
    # https://github.com/grafana/grafana/blob/f761ae1f026a45210b82bf7c531ff3c80dbbab36/pkg/api/api.go#L385

    def get_plugins(self):
        return self.get(f'/api/plugins', basic=True)
    
    def get_plugin(self, name):
        return self.get(f'/api/plugins/{name}/settings', basic=True)
    
    def create_plugin(self, payload, fname=None):
        uid = payload['id']
        try:
            existing = self.get_plugin(uid)
        except Exception:
            print(self.install_plugin(uid))
        # d = self.update_plugin(uid, payload)
        # if input(): embed()
        return 
    
    def update_plugin(self, name, payload):
        return self.post(f'/api/plugins/{name}/settings', payload, basic=True)

    def install_plugin(self, name):
        return self.post(f'/api/plugins/{name}/install', basic=True)
    
    def uninstall_plugin(self, name):
        return self.post(f'/api/plugins/{name}/uninstall', basic=True)

    def dump_plugins(self):
        payloads = self.get_plugins()
        for d in payloads:
            yield f"{d['name']}-{d['id']}", d
    
    def apply_plugins(self, items, **kw):
        return self._apply(
            'plugins', items,
            dump_fn=self.dump_plugins,
            create_fn=self.create_plugin,
            update_fn=self.create_plugin,
            # delete_fn=self.delete_plugin,
            **kw,
        )

    #endregion
    #region ------------------------ Export / Apply ------------------------------ #

    def _apply(self, route, items: dict, dump_fn, create_fn, update_fn, delete_fn=None, existing=None, allow_delete=False, dry_run=False):
        existing = dict(dump_fn()) if existing is None else existing

        # check for new
        new = set(items) - set(existing)
        log.debug(f'new {route} {new}')
        if new:
            log.info(f"🌱 Creating {route}: {new}")
            if not dry_run:
                for k in new:
                    create_fn(items[k])

        # check for changes
        in_common = set(items) & set(existing)
        diffs = {k: dict_diff(existing[k], items[k]) for k in in_common}
        update = {k for k in in_common if any(diffs[k])}
        unchanged = in_common - update
        # log.debug(f'diffs {route} {diffs}')
        # log.debug(f'update {route} {update}')

        if update:
            log.info(f"🔧 Updating {route}: {update}")
            if not dry_run:
                for k in update:
                    newver = items[k].get('version')
                    oldver = existing[k].get('version')
                    if newver is not None and oldver is not None and newver < oldver:
                        # log.warning(f"{route} {k} version {newver} < {oldver} currently deployed. Skipping.")
                        # continue
                        items[k]['version'] = oldver
                    update_fn(items[k])
        
        # check for deleted
        missing = set(existing) - set(items)
        delete = missing if allow_delete and delete_fn is not None else set()
        log.debug(f'missing {route} {missing}')
        log.debug(f'delete {route} {delete}')
        if delete:
            log.warning(f"🗑 Deleting {route}: {delete}")
            if not dry_run:
                for k in delete:
                    delete_fn(existing[k])
        elif missing:
            log.warning(f"Missing (skipping delete) {route}: {missing}")

        # summary
        log.info(
            "%s%-16s :: %s. %s. %s. %s.", 
            "[Dry Run]" if dry_run else "",
            route.strip('/').replace('/', '|').title(),
            status_text('new', i=len(new)), 
            status_text('modified', i=len(update)), 
            status_text('deleted' if allow_delete else 'additional', i=len(delete)),
            status_text('unchanged', i=len(unchanged)),
        )
        return new, update, delete, unchanged


    def export(self, folder_path=DEFAULT_FOLDER_PATH, deleted_dir=None, allowed=None, exclude=None, dry_run=False):
        allowed = (allowed.split(',') if isinstance(allowed, str) else allowed) or list(self.backup_functions)
        if exclude:
            allowed = [k for k in allowed if k not in exclude]
        for group in allowed:
            export_dir(dict(self.backup_functions[group]()), folder_path, group, deleted_dir=deleted_dir, dry_run=dry_run)

    def apply(self, folder_path=DEFAULT_FOLDER_PATH, allowed=None, exclude=None, allow_delete=False, dry_run=False):
        allowed = (allowed.split(',') if isinstance(allowed, str) else allowed) or list(self.restore_functions)
        if exclude:
            allowed = [k for k in allowed if k not in exclude]
        for group in allowed:
            self.restore_functions[group](load_dir(os.path.join(folder_path, group)), allow_delete=allow_delete, dry_run=dry_run)

    #endregion



def cli():
    logging.basicConfig()
    import fire
    fire.Fire(API)

if __name__ == '__main__':
    cli()