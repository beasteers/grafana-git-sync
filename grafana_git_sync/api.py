#!/usr/bin/env python3

import re
import tqdm
import json
import base64
import logging
import requests
from packaging import version

log = logging.getLogger(__name__.split('.')[0])
# log.setLevel(logging.DEBUG)

ROOT_FOLDER = 'General'

class API:
    '''Query tool for grafana.'''
    def __init__(self, url, username=None, password=None, api_key=None):
        self.url = url
        self.headers = {"Content-type": "application/json"}
        self.api_key = api_key
        self.basicauth = None
        self.org = None
        if username and password:
            self.login(username, password)

    def login(self, username, password):
        self.basicauth = base64.b64encode(f"{username}:{password}".encode()).decode()

    #region --------------------------- Requests --------------------------------- #

    def _req(self, method, path, basic=False, params=None, org=None, provenance=True, **kw):
        log.debug('%s: %s', method, path)
        params = {k: v for k, v in (params or {}).items() if v is not None}
        headers = dict(self.headers)
        if not basic and self.api_key:
            headers['Authorization'] = f"Bearer {self.api_key}"
        else:
            headers['Authorization'] = f'Basic {self.basicauth}'
        org = org or self.org
        if org:
            headers['X-Grafana-Org-Id'] = org
        if not provenance:
            headers['X-Disable-Provenance'] = 'true'
        response = requests.request(method, f"{self.url}{path}", headers=headers, params=params, **kw)
        # log.debug('%s', response.status_code)
        try:
            response.raise_for_status()
            if not response.content:
                return 
            return response.json()
        except requests.exceptions.JSONDecodeError as e:
            log.error('%s: %s', response.status_code, response.content.decode())
            raise
        except requests.exceptions.HTTPError as e:
            try:
                data = response.json()
                if data.get('status') == 'version-mismatch':
                    log.warning('%s: %s', response.status_code, response.content.decode())
                    return
            except Exception:
                pass
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
        return self.get('/api/serviceaccounts/search', params={'query': name})['serviceAccounts']
    
    def get_service_account(self, id):
        return self.get(f'/api/serviceaccounts/{id}')
    
    def create_service_account(self, payload):
        try:
            existing = self.search_service_accounts(payload['name'])[0]
            return self.update_service_account(existing['id'], payload)
        except Exception:
            return self.post('/api/serviceaccounts', payload)
    
    def update_service_account(self, payload):
        # payload: {'name': name, 'role': role}
        return self.put('/api/serviceaccounts', payload)

    #endregion
    #region -------------------------- Dashboards -------------------------------- #

    def search(self, query=None, _maxiter=1000, **params):
        """Search folders and dashboards

        query (str): Search Query e.g. dashboard title
        tag (list[str]): List of tags to search for
        type (str): Type to search for, dash-folder or dash-db
        dashboardIds (list[int]): List of dashboard id's to search for
        dashboardUIDs (list[str]): List of dashboard uid's to search for
        folderUIDs (list[str]): List of folder UIDs to search in
        starred (bool): Flag indicating if only starred Dashboards should be returned
        limit (int): Limit the number of returned results (max is 5000; default is 1000)
        page (int): Use this parameter to access hits beyond limit. Numbering starts at 1. limit param acts as page size. Only available in Grafana v6.2+.
        """
        results = []
        for i in range(_maxiter):
            x = self.get('/api/search', params={**params, 'query': query, 'page': i+1})
            if not x:
                break
            results.extend(x)
        return results

    def search_dashboards(self, query=None, **params):
        return self.search(query=query, type='dash-db', **params)

    def create_dashboard(self, payload, fname=None):
        try:
            return self.post('/api/dashboards/db', {
                "dashboard": payload['dashboard'],
                "folderUid": payload.get('folderUid') or payload.get('meta', {}).get('folderUid', ''),
                "overwrite": True,
            })
        except requests.HTTPError as e:
            if e.response.json().get('message') == 'Cannot save provisioned dashboard':
                log.warning(e.response.content)
                return
            raise

    def get_dashboard(self, uid):
        return self.get(f'/api/dashboards/uid/{uid}')
    
    def delete_dashboard_by_uid(self, uid):
        return self.delete(f'/api/dashboards/uid/{uid}')

    def delete_dashboard_by_slug(self, slug):
        return self.delete(f'/api/dashboards/db/{slug}')
    
    def delete_dashboard(self, payload):
        return self.delete_dashboard_by_uid(payload['dashboard']['uid'])

    # ----------------------------- Public Dashboards ---------------------------- #

    def search_public_dashboards(self):
        return self.get('/api/dashboards/public-dashboards')
    
    def get_public_dashboard(self, uid):
        return self.get(f'/api/dashboards/uid/{uid}/public-dashboards/')['publicDashboards']
    
    def create_public_dashboard(self, uid, payload):
        try:
            return self.post(f"/api/dashboards/uid/{uid}/public-dashboards/{payload['uid']}", payload)
        except requests.HTTPError as e:
            return self.post(f"/api/dashboards/uid/{uid}/public-dashboards/", payload)
        
    def update_public_dashboard(self, uid, payload):
        return self.post(f"/api/dashboards/uid/{uid}/public-dashboards/{payload['uid']}", payload)

    def delete_public_dashboard(self, uid, pd_uid):
        return self.delete(f'/api/dashboards/uid/{uid}/public-dashboards/{pd_uid}')

    # ----------------------------- Dashboard Versions --------------------------- #

    def get_dashboard_versions(self, uid):
        return self.get(f'/api/dashboards/uid/{uid}/versions')
    
    def get_dashboard_version(self, uid, version):
        return self.get(f'/api/dashboards/uid/{uid}/versions/{version}')
    
    def restore_dashboard_version(self, uid, version):
        return self.post(f'/api/dashboards/uid/{uid}/restore', {"version": version})
    
    def compare_dashboard_versions(self, uid, version1, version2):
        return self.post(f'/api/dashboards/calculate-diff', {
            "old": {"uid": uid, "version": version1},
            "new": {"uid": uid, "version": version2},
            "diffType": "json",
        })
    
    # ----------------------------- Dashboard Permissions ------------------------ #
    
    def get_dashboard_permissions(self, uid):
        return self.get(f'/api/dashboards/uid/{uid}/permissions')
    
    def update_dashboard_permissions(self, uid, payload):
        return self.post(f'/api/dashboards/uid/{uid}/permissions', items=json.dumps({'items': payload}))
    
    # --------------------------------- Playlists -------------------------------- #

    def search_playlists(self):
        return self.get('/api/playlists')
    
    def get_playlist(self, uid):
        return self.get(f'/api/playlists/{uid}')
    
    def get_playlist_items(self, uid):
        return self.get(f'/api/playlists/{uid}/items')
    
    def create_playlist(self, payload):
        return self.post('/api/playlists', payload)
    
    def delete_playlist_by_uid(self, uid):
        return self.delete(f'/api/playlists/{uid}')
    
    def delete_playlist(self, payload):
        return self.delete_playlist_by_uid(payload['uid'])

    #endregion
    #region -------------------------- Datasources ------------------------------- #

    def search_datasources(self):
        return self.get('/api/datasources')
    
    def get_datasource(self, uid):
        return self.get(f'/api/datasources/uid/{uid}')
    
    def create_datasource(self, payload):
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
        if 'uid' in payload:
            return self.delete_datasource_by_uid(payload['uid'])
        return self.delete_datasource_by_id(payload['id'])

    #endregion
    #region ---------------------------- Folders --------------------------------- #

    _folders = None
    @property
    def folders(self):
        if self._folders is None:
            self._folders = self.search_folders()
        return self._folders

    def search_folders(self, query=None, **params):
        x = self.search(query, type='dash-folder', **params)
        if not params and not query:
            self._folders = x
        return x

    def get_folder(self, uid):
        return self.get(f'/api/folders/{uid}')

    def create_folder(self, payload):
        payload.pop('id', None)
        try:
            try:
                existing = self.get_folder(payload['uid'])
                if existing.get('version') and payload.get('version') and existing['version'] >= payload['version']:
                    return
            except Exception as e:
                existing = self.search_folders(payload['title'])
                if existing:
                    return 
                payload['uid'] = existing[0]['uid']
            return self.update_folder(payload)
        except Exception as e:
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

    #endregion
    #region ----------------------- Library elements ----------------------------- #

    def search_library_elements(self):
        return self.get('/api/library-elements?perPage=5000')['result']['elements']

    def create_library_element(self, library_element):
        folder_uid = library_element["meta"]["folderUid"]
        fd = self.get_folder(folder_uid)
        fd = fd[0] if isinstance(fd, list) else fd
        library_element["folderUid"] = fd['uid']
        return self.post('/api/library-elements', library_element)

    def delete_library_element_by_uid(self, uid):
        return self.delete(f'/api/library-elements/{uid}')
    
    def delete_library_element(self, library_element):
        return self.delete_library_element_by_id(library_element['uid'])

    #endregion
    #region -------------------------- Annotations ------------------------------- #

    def search_annotations(self, ts_from, ts_to):
        return self.get(f'/api/annotations?type=annotation&limit=5000&from={ts_from}&to={ts_to}')

    def create_annotation(self, annotation):
        return self.post('/api/annotations', annotation)

    def delete_annotation_by_id(self, id_):
        return self.delete(f'/api/annotations/{id_}')
    
    def delete_annotation(self, payload):
        return self.delete_annotation_by_id(payload['id'])

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
    # https://grafana.com/docs/grafana/latest/developers/http_api/alerting_provisioning/#alert-rules

    def search_alert_rules(self):
        # if not self.compare_version('9.4.0'):
        #     return self.get('/api/ruler/grafana/api/v1/rules')
        if not self.compare_version('9.4.0') or not self.basicauth:
            return []
        return self.get('/api/v1/provisioning/alert-rules', basic=True)

    def get_alert_rule(self, uid, export=False):
        if export:
            return self.get(f'/api/v1/provisioning/alert-rules/{uid}/export', basic=True)
        return self.get(f'/api/v1/provisioning/alert-rules/{uid}', basic=True)

    def create_alert_rule(self, alert, provenance=False):
        if not self.compare_version('9.4.0'):
            return
        del alert['id']
        uid = alert['uid']
        try:
            existing = self.get_alert_rule(uid)
            try:
                return self.update_alert_rule(uid, alert)
            except Exception as e:
                self.delete_alert_rule_by_uid(uid)
                raise
        except Exception as e:
            return self.post('/api/v1/provisioning/alert-rules', alert, basic=True, provenance=provenance)

    def update_alert_rule(self, uid, alert, provenance=False):
        return self.put(f'/api/v1/provisioning/alert-rules/{uid}', alert, basic=True, provenance=provenance)

    def delete_alert_rule_by_uid(self, uid):
        return self.delete(f'/api/v1/provisioning/alert-rules/{uid}', basic=True)
    
    def delete_alert_rule(self, payload):
        return self.delete_alert_rule_by_uid(payload['uid'])

    #endregion
    #region ------------------------ Alert rule groups --------------------------- #

    def get_alert_rule_group(self, folderUid, group, export=False):
        if export:
            return self.get(f'/api/v1/provisioning/folder/{folderUid}/rule-groups/{group}/export')
        return self.get(f'/api/v1/provisioning/folder/{folderUid}/rule-groups/{group}')

    #endregion
    #region ------------------------ Alert channels ------------------------------ #

    def search_alert_notifications(self):
        return self.get('/api/alert-notifications')

    def create_alert_notification(self, payload):
        return self.post('/api/alert-notifications', payload)

    def delete_alert_notification_by_uid(self, uid):
        return self.delete(f'/api/alert-notifications/uid/{uid}')

    def delete_alert_notification_by_id(self, id_):
        return self.delete(f'/api/alert-notifications/{id_}')
    
    def delete_alert_notification(self, payload):
        if 'uid' in payload:
            return self.delete_alert_notification_by_uid(payload['uid'])
        return self.delete_alert_notification_by_id(payload['id'])

    search_alert_channels = search_alert_notifications
    create_alert_channel = create_alert_notification
    delete_alert_channel_by_uid = delete_alert_notification_by_uid
    delete_alert_channel_by_id = delete_alert_notification_by_id
    delete_alert_channel = delete_alert_notification

    #endregion
    #region ----------------------- Notification templates ----------------------- #
    # https://grafana.com/docs/grafana/latest/developers/http_api/alerting_provisioning/#templates

    def search_notification_templates(self):
        return self.get('/api/v1/provisioning/templates')
    
    def get_notification_template(self, name):
        return self.get(f'/api/v1/provisioning/templates/{name}')

    def create_notification_template(self, payload, provenance=False):
        try:
            return self.put(f"/api/v1/provisioning/templates/{payload['name']}", payload, provenance=provenance)
        except Exception as e:
            self.delete_notification_template_by_name(payload['name'])
            return self.put(f"/api/v1/provisioning/templates/{payload['name']}", payload, provenance=provenance)
    
    def delete_notification_template_by_name(self, name):
        return self.delete(f'/api/v1/provisioning/templates/{name}')

    def delete_notification_template(self, payload):
        return self.delete_notification_template_by_name(payload['name'])

    #endregion
    #region ------------------------ Contact points ------------------------------ #
    # https://grafana.com/docs/grafana/latest/developers/http_api/alerting_provisioning/#contact-points

    _contact_points = None
    @property
    def contact_points(self):
        if self._contact_points is None:
            self._contact_points = self.search_contact_points()
        return self._contact_points

    def search_contact_points(self):
        self._contact_points = x = self.get('/api/v1/provisioning/contact-points')
        return x
    
    def get_contact_point(self, uid):
        for cp in self.contact_points:
            if cp['uid'] == uid:
                return cp
        raise RuntimeError(f"Could not find contact point with uid: {uid}")

    def create_contact_point(self, payload, fname=None, preserve_addresses=True, provenance=False):
        if not self.compare_version('9.4.0'):
            return
        try:
            uid = payload['uid']
            existing = self.get_contact_point(uid)
            if preserve_addresses:
                if payload['type'] == 'email':
                    log.info('Preserving email addresses for %s: \n  using: %s\n  instead of: %s', 
                             uid, existing['settings']['addresses'], payload['settings']['addresses'])
                    payload['settings']['addresses'] = existing['settings']['addresses']
            try:
                return self.put(f'/api/v1/provisioning/contact-points/{uid}', payload, provenance=provenance)
            except Exception as e:
                notification_policy = self.get_notification_policy()
                self.delete_notification_policy()
                self.delete_contact_point_by_uid(uid)
                self.update_notification_policy(notification_policy)
                raise
        except KeyError:
            raise
        except Exception:
            if preserve_addresses:
                if payload['type'] == 'email':
                    log.info('Dropping email addresses for %s: %s', uid, payload['settings']['addresses'])
                    payload['settings']['addresses'] = " "
            return self.post('/api/v1/provisioning/contact-points', payload, provenance=provenance)

    def delete_contact_point_by_uid(self, uid):
        return self.delete(f'/api/v1/provisioning/contact-points/{uid}')

    def delete_contact_point(self, payload):
        return self.delete_contact_point_by_uid(payload['uid'])

    #endregion
    #region --------------------- Notification policies -------------------------- #
    # https://grafana.com/docs/grafana/latest/developers/http_api/alerting_provisioning/#notification-policies

    def search_notification_policies(self):
        if not self.compare_version('9.4.0'):
            return []
        p = self.get('/api/v1/provisioning/policies')
        return [p] if p else []

    def get_notification_policy(self, export=False):
        if export:
            return self.get('/api/v1/provisioning/policies/export')
        return self.get('/api/v1/provisioning/policies')

    def update_notification_policy(self, json_payload, provenance=False):
        return self.put('/api/v1/provisioning/policies', json_payload, provenance=provenance)

    def delete_notification_policy(self):
        return self.delete('/api/v1/provisioning/policies')

    #endregion
    #region --------------------------- Snapshots -------------------------------- #

    def search_snapshots(self):
        return self.get('/api/dashboard/snapshots')

    def get_snapshot(self, key):
        return self.get(f'/api/snapshots/{key}')

    def create_snapshot(self, payload):
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

    #endregion
    #region ------------------------- Mute Timings ------------------------------- #
    # https://grafana.com/docs/grafana/latest/developers/http_api/alerting_provisioning/#mute-timings

    def search_mute_timings(self):
        return self.get('/api/v1/provisioning/mute-timings')
    
    def get_mute_timing(self, name):
        return self.get(f'/api/v1/provisioning/mute-timings/{name}')
    
    def create_mute_timing(self, payload):
        return self.post('/api/v1/provisioning/mute-timings', payload)
    
    def delete_mute_timing(self, payload):
        return self.delete(f'/api/v1/provisioning/mute-timings/{payload["name"]}')

    #endregion
    #region ----------------------------- Users ---------------------------------- #

    def search_users(self, page=0, limit=5000):
        if not self.basicauth:
            return []
        return self.get(f'/api/users?perpage={limit}&page={page}', basic=True)

    def get_users(self):
        return self.get('/api/org/users', basic=True)

    def get_user(self, id):
        return self.get(f'/api/users/{id}', basic=True)

    def create_user(self, payload):
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

    #endregion
    #region ----------------------------- Teams ---------------------------------- #

    def search_teams(self, name=None):
        return self.get('/api/teams/search?perPage=5000', params={'name': name})['teams']

    def get_team(self, id_):
        return self.get(f'/api/teams/{id_}')

    def create_team(self, payload):
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

    def search_team_members(self, team_id):
        return self.get(f'/api/teams/{team_id}/members')

    def create_team_member(self, user, team_id):
        return self.post(f'/api/teams/{team_id}/members', {
            'userId': self.get_user_by_login(user['email'], user['name'])
        })

    def delete_team_member(self, user_id, team_id):
        return self.delete(f'/api/teams/{team_id}/members/{user_id}')

    #endregion
    #region ----------------------------- Orgs ----------------------------------- #

    def search_orgs(self):
        if not self.basicauth:
            return []
        return self.get('/api/orgs', basic=True)

    def get_org(self, id):
        return self.get(f'/api/orgs/{id}', basic=True)

    def create_org(self, payload):
        try:
            # del payload['id']
            uid = payload['id']
            existing = self.get_org(uid)
            return self.update_org(uid, payload)
        except Exception:
            return self.post('/api/orgs', payload, basic=True)

    def update_org(self, id, payload):
        return self.put(f'/api/orgs/{id}', payload, basic=True)
    
    #endregion
    #region ---------------------------- Plugins --------------------------------- #
    # https://github.com/grafana/grafana/blob/f761ae1f026a45210b82bf7c531ff3c80dbbab36/pkg/api/api.go#L385

    def get_plugins(self):
        return self.get(f'/api/plugins', basic=True)
    
    def get_plugin(self, name):
        return self.get(f'/api/plugins/{name}/settings', basic=True)
    
    def create_plugin(self, payload):
        uid = payload['id']
        try:
            existing = self.get_plugin(uid)
        except Exception:
            try:
                print(self.install_plugin(uid))
            except requests.HTTPError as e:
                if e.response.status_code == 409 and e.response.json().get('message').lower().strip('.', '') == 'plugin already installed':
                    log.warning(e.response.content)
                    return
                raise
        # d = self.update_plugin(uid, payload)
        # if input(): embed()
        return 
    
    def update_plugin(self, name, payload):
        return self.post(f'/api/plugins/{name}/settings', payload, basic=True)

    def install_plugin(self, name):
        return self.post(f'/api/plugins/{name}/install', basic=True)
    
    def uninstall_plugin(self, name):
        return self.post(f'/api/plugins/{name}/uninstall', basic=True)

    #endregion
    #region ---------------------- Dashboard Versions ------------------------------ #

    #endregion


def cli():
    logging.basicConfig()
    import fire
    fire.Fire(API)

if __name__ == '__main__':
    cli()