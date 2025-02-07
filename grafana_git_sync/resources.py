from .resource import *

from collections import OrderedDict
import logging
from grafana_git_sync import EXPORT_DIR, USERNAME, PASSWORD, URL
from . import util
from .api import API
from .util import load_dir, export_dir


log = logging.getLogger(__name__.split('.')[0])

ROOT_FOLDER = 'General'


class ResourceGroup:
    def __init__(self, api, resources_dict, active=None):
        self.api = api
        if isinstance(resources_dict, list):
            resources_dict = OrderedDict((r.GROUP, r) for r in resources_dict)
        self.resources_dict = resources_dict
        self.active = list(resources_dict) if active is None else active

    def __getitem__(self, key):
        if key is None:
            return self
        if isinstance(key, int):
            return self.resources_dict[self.active[key]]
        if isinstance(key, (list, tuple)):
            return Resources(resources_dict=self.resources_dict, active=key)
        return self.resources_dict[key]
    
    def resources(self, active=None):
        active = active.split(',') if isinstance(active, str) else active
        return [self.resources_dict[k] for k in active or self.active]

    def get_diff(self, key=None, path=EXPORT_DIR, print_diff=True, **kw):
        diffs = {}
        resources = self.resources(key)
        for r in resources:
            diffs[r.GROUP] = r.diff(path, **kw)
            if print_diff:
                s = r.diff_str(*diffs[r.GROUP])
                if s:
                    print(s)
        return diffs

    def diff(self, key=None, path=EXPORT_DIR, **kw):
        """Diff the resources on disk with the resources from the API."""
        self.get_diff(key, path, **kw)

    def apply(self, key=None, path=EXPORT_DIR, allow_delete=False, dry_run=False):
        """Apply the resources to the API."""
        diffs = self.get_diff(key, path)
        for r in self.resources(key):
            r.apply_diff(*diffs[r.GROUP], allow_delete=allow_delete, dry_run=dry_run)

    def export(self, resource=None, *, path=EXPORT_DIR, filter=None, **kw):
        """Export the resources to disk."""
        assert bool(resource) == bool(filter), f"If a filter is provided ({filter}), you must pick a specific resource (e.g. 'dashboards')."
        for r in self.resources(resource):
            r.export(path, filter=filter, **kw)

    pull = export



class Resources(ResourceGroup):
    DEFAULT_EXCLUDE = (
        'users', 'teams', 'team_members', 'folder_permissions', 
        'alert', 'mute_timing', 'snapshot', 'annotation',
        'dashboard_versions', 
    )
    def __init__(self, username=USERNAME, password=PASSWORD, url=URL, *, allowed=None, include=None, exclude=None, active=None, api=None, resources_dict=None, clean=True):
        self.api = api = api or API(url)
        log.info(f"Connecting to {api.url}")
        self.resources_dict = resources_dict or OrderedDict((r.GROUP, r) for r in [
            # Admin
            Org(api),
            User(api),
            Team(api),
            TeamMember(api),
            ServiceAccount(api),

            # Primary Resources
            Folder(api),
            Plugin(api),
            Datasource(api),
            LibraryElement(api),
            DashboardVersion(api),
            FolderPermission(api),
            Dashboard(api),

            # Alerting
            AlertRule(api),
            ContactPoint(api),
            NotificationPolicy(api),
            NotificationTemplate(api),

            # Data
            # Alert(api),
            # AlertNotifications(api),
            # MuteTiming(api),
            # Snapshot(api),
            # Annotation(api),
        ])
        for r in self.resources_dict.values():
            r.CLEAN = clean

        # filter resources
        if active is None:
            available = set(self.resources_dict)
            default_exclude = set(self.DEFAULT_EXCLUDE)
            allowed = set(allowed.split(',') if isinstance(allowed, str) else allowed or [])  # deprecate
            include = set(include.split(',') if isinstance(include, str) else include or []) | allowed
            exclude = set(exclude.split(',') if isinstance(exclude, str) else exclude or [])
            active = (available & (include or available) - exclude - (default_exclude - include))
            if include - available:
                raise ValueError(f"Invalid included resources: {include - available}")
            if not active:
                raise ValueError(f"No resources chosen from {available} with include={include} and exclude={exclude}")
            assert not (active & exclude), f"Chosen resources {active & exclude} should not be included. weird!"

        self.active = [k for k in self.resources_dict if k in active]
        if username and password:
            self.api.login(username, password)
