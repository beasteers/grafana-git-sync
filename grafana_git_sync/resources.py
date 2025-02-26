from collections import OrderedDict
from datetime import datetime, timezone
import fnmatch
import os
import math
import time
import tqdm
import logging
from grafana_git_sync import EXPORT_DIR, USERNAME, PASSWORD, URL
from . import util
from .api import API
from .util import load_dir, export_dir


log = logging.getLogger(__name__.split('.')[0])

ROOT_FOLDER = 'General'


class Resources:
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
            self.login(username, password)

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

    def login(self, username, password):
        return self.api.login(username, password)

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

class Resource:
    '''
    
    export():
        - pull() from API
        - should we load() from disk and diff()?
        - write() to disk with get_fname()

    apply():
        diff():
            - pull() from API
            - load() from disk
            - diff() items with get_id()
        apply_diff():
            - create()
            - update()
            - delete()
    
    '''
    GROUP = ''
    ID = 'uid'
    TITLE = 'title'
    FNAME_KEYS = ()
    FILTER_KEYS = ()
    ORDER_BY = None
    ORDER_DESC = True
    DIFF_IGNORE_KEYS = ('created', 'updated', 'createdBy', 'updatedBy', 'version', 'id')
    EXT = 'json'

    def __init__(self, api):
        self.api = api

    # ----------------------------------- Info ----------------------------------- #

    def get_id(self, d: dict) -> str:
        """Get the unique identifier for the resource. Used to determine if a resource is new or modified."""
        return str(util.get_key(d, self.ID) if self.ID else self.get_fname(d))
    
    def get_title(self, d: dict) -> str:
        """Get the name of the resource."""
        return (util.get_key(d, self.TITLE, None) if self.TITLE else None) or self.get_fname(d)

    def get_fname(self, d: dict) -> str:
        """Get the identifier to save the resource to disk."""
        xs = [
            util.get_key(d, k, None) 
            for k in self.FNAME_KEYS or (self.TITLE,) + ((self.ID,) if self.ID != self.TITLE else ())
            if k
        ]
        return '-'.join([str(x) for x in xs if x is not None]).replace('/', '-')
    
    def _filter(self, ds, filter):
        """Filter the resource by a list of filters."""
        if not filter:
            return ds
        return [
            d for d in ds 
            if fnmatch.fnmatch(self.get_title(d), filter) 
            or fnmatch.fnmatch(f'{self.get_id(d)}', filter) 
            or any(util.get_key(d, k) == filter for k in self.FILTER_KEYS or ())
        ]
        # return [d for d in ds if fnmatch.fnmatch(self.get_title(d), filter) or any(util.get_key(d, k) == filter for k in keys)]
    
    def diff_item(self, existing, item):
        """Compare items to see if they changed."""
        missing1, missing2, mismatch = util.nested_dict_diff(existing, item, self.DIFF_IGNORE_KEYS)
        return (missing1, missing2, mismatch) if missing1 or missing2 or mismatch else False

    # ------------------------------------ API ----------------------------------- #

    def create(self, d):
        """Create a resource in the API."""
        raise NotImplemented
    
    def update(self, d, existing):
        """Update a resource in the API."""
        return self.create(d)

    def delete(self, d):
        """Delete a resource in the API."""
        print("Skipping delete", self.GROUP, self.get_title(d))

    # ----------------------------------- Load ----------------------------------- #

    def _pull(self):
        raise NotImplemented

    def pull(self, filter=None) -> list[dict]:
        """Dump the resource from the API."""
        return self._filter(self._pull(), filter)
    
    def _load(self, folder_path):
        ds = load_dir(os.path.join(folder_path, self.GROUP))
        return list(ds.values())

    def load(self, folder_path, filter=None) -> list[dict]:
        """Load the resource from disk."""
        return self._filter(self._load(folder_path), filter=filter)
    
    def write(self, folder_path: str, items: list, **kw):
        """Write the resource to disk."""
        items = {self.get_fname(d): d for d in items}
        kw.setdefault('ext', self.EXT)
        export_dir(items, folder_path, self.GROUP, **kw)

    # ---------------------------------- Commit ---------------------------------- #

    def export(self, folder_path, filter=None, **kw):
        """Export the resource to disk."""
        kw.setdefault('delete', not filter)
        self.write(folder_path, self.pull(filter=filter), **kw)

    def apply(self, folder_path, *, confirm=True, allow_delete=False, dry_run=False):
        """Apply the resource to the API."""
        new, update, missing, unchanged, items, existing = self.diff(folder_path)
        if confirm:
            util.confirm("Do you want to apply the diff?")
        print("Applying...")
        self.apply_diff(new, update, missing, unchanged, items, existing, allow_delete=allow_delete, dry_run=dry_run)

    def diff(self, folder_path, filter=None, inverse=False):
        """Diff the resource on disk with the resource from the API."""
        existing = self.pull(filter=filter)            # original comes from API
        items = self.load(folder_path, filter=filter)  # new items come from disk
        return self.get_diff(existing, items, inverse=inverse)

    def get_diff(self, existing, items, inverse=False):
        if inverse:  # flip the diff
            existing, items = items, existing
        # get items from disk and API
        items = {self.get_id(d): d for d in items}
        existing = {self.get_id(d): d for d in existing}

        # get new, updated, missing, and unchanged items
        new = set(items) - set(existing)
        missing = set(existing) - set(items)
        in_common = set(items) & set(existing)
        diffs = {k: self.diff_item(existing[k], items[k]) for k in in_common}
        update = {k: v for k, v in diffs.items() if v}
        unchanged = in_common - set(update)
        print(missing)
        return new, update, missing, unchanged, items, existing

    def apply_diff(self, new, update, missing, unchanged, items, existing, allow_delete=False, dry_run=False):
        log.info(self.simple_diff(new, update, missing, unchanged))
        if new:
            if not dry_run:
                for k in tqdm.tqdm(new, desc="Creating", leave=False):
                    log.info("Creating %s", self.get_title(items[k]))
                    self.create(items[k])
        if update:
            if not dry_run:
                for k in tqdm.tqdm(update, desc="Updating", leave=False):
                    # if existing[k]['dashboard'].get('title') != 'Event Labeling':
                    #     continue
                    # print("Updating", self.get_title(items[k]))
                    # continue
                    log.info("Updating %s", self.get_title(items[k]))
                    self.update(items[k], existing[k])
        if missing:
            if allow_delete:
                if not dry_run:
                    for k in tqdm.tqdm(missing, desc="Deleting", leave=False):
                        log.warning("Deleting %s", self.get_title(existing[k]))
                        self.delete(existing[k])
            else:
                # log.info(util.status_text("deleted", "Additional items"), ', '.join(self.get_title(existing[k]) for k in missing))
                for k in missing:
                    log.warning("Ignoring %s", self.get_title(existing[k]))
                log.warning("Use --allow-delete to delete items.")

    def wipe(self, yes=None, dry_run=False):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            new, update, missing, unchanged, items, existing = self.diff(tmpdir)
        if yes is not True:
            util.confirm(
                "Are you sure you want to delete all of the flows, operations, webhooks, and roles?",
                "Really? you really sure?",
                "I mean your funeral... last chance!"
            )
        print("Wiping...")
        print("not really.")
        # self.apply_diff(new, update, missing, unchanged, items, existing, allow_delete=True, dry_run=dry_run)

    # ----------------------------------- Print ---------------------------------- #

    def simple_diff(self, new, update, missing, unchanged, items=None, existing=None, *, allow_delete=False):
        """Simple diff: e.g. Dashboards :: 3 new. 2 modified. 1 deleted. 4 unchanged."""
        return f"{self.GROUP.title(): >24} :: " + " ".join([f'{x}.' for x in [
            util.status_text('new', i=len(new)), 
            util.status_text('modified', i=len(update)), 
            util.status_text('deleted' if allow_delete else 'trash', i=len(missing)),
            util.status_text('unchanged', i=len(unchanged)),
        ]])

    def diff_str(self, new, update, missing, unchanged, items, existing, *, title=None, allow_delete=False, show_no_changes=True):
        """Get the diff as a string."""

        '''
        diff_str:
         - _diff_items: Dashboards - unchanged, new, modified, deleted
            - _diff_item_block: Dashboard
                - _diff_item_block(_diff_item_text): title
                    - _diff_item_block(_diff_item_value): Properties - unchanged, new, modified, deleted
                        - _diff_item_format_value
                    - ...
            - ...
        '''

        # title
        lines = util.color_text('bold', title or self.GROUP.title()) + '\n'
        if not new and not update and not missing:
            if show_no_changes:
                return lines.rstrip() + util.color_text('unchanged', " :: no changes.")
            return ''

        # unchanged items
        lines += self._diff_items("unchanged", "unchanged", unchanged, items, existing, itemize=False)

        # new items
        lines += self._diff_items("new", "new", new, items)
        
        # modified items
        update_k = {k: d if isinstance(d, str) else f"modified" for k, d in update.items()}
        for k in set(update_k.values()):
            update_ki = {d: update[d] for d, ki in update_k.items() if ki == k}
            lines += self._diff_items("modified", k, update_ki, items, existing)
        
        # deleted items
        lines += self._diff_items("deleted", "deleted" if allow_delete else "trash", missing, existing)
        return lines

    def _diff_items(self, kind, kind_label, keys, items, others=None, itemize=True):
        """Diff a group of items in a category."""
        if not keys:
            return ''
        header = f"{util.status_text(kind, kind_label, i=len(keys))}\n"
        lines = ''
        if itemize:
            ks = sorted(keys, key=lambda k: util.get_key(items[k], self.ORDER_BY), reverse=self.ORDER_DESC) if self.ORDER_BY else keys
            for d in ks:
                item = items[d]
                other = (others or {}).get(d)
                diff = keys[d] if isinstance(keys, dict) else None
                txt = self._diff_item_text(kind, kind_label, item, other, diff)
                lines += self._diff_item_block(kind, '', txt, top_border=True)

                if isinstance(diff, (tuple, list)):
                    m1, m2, mm = diff
                    for kind_i, ms, di, do in (
                        ('new', m1, item, None), 
                        ('modified', mm, item, other), 
                        ('deleted', m2, other, None),
                    ):
                        for m in ms:
                            v = self._diff_item_value(kind, kind_label, m, di, do)
                            if v is not None:
                                lines += self._diff_item_block(kind_i, '.'.join(m), v, indent=2)

        lines = util.indent(lines, 4) + '\n' if lines else ''
        return header + lines
    
    def _diff_item_block(self, kind, label, value, align_value=False, **kw):
        """Get the text to display for an item in a diff."""
        l = label + " " if label else ""
        v = "" if value is None else value
        leading_spaces = len(l) - 1 if align_value else 2
        v = ('\n' + " "*leading_spaces).join(str(v).split('\n'))
        return util.symbol_block(f"{util.color_text(kind, label)}{v}", kind, **kw)

    def _diff_item_text(self, kind, kind_label, item, other, diff):
        """Get the text to display for the name of an item in a diff."""
        return util.color_text('bold', self.get_title(item))

    def _diff_item_value(self, kind, kind_label, keys, item, other=None):
        """Get the text to display for the value of an item attr in a diff."""
        v = util.get_key(item, keys, None)
        v1 = util.get_key(other, keys, None) if other is not None else None
        return (
            (f'[{kind_label or kind}]') 
            if isinstance(v, (dict, list, tuple, set)) else 
            (f"= {self._diff_item_format_value(v1, keys)} -> {self._diff_item_format_value(v, keys)}" 
             if other is not None else 
             f"= {self._diff_item_format_value(v, keys)}")
        )
    
    def _diff_item_format_value(self, value, keys=None):
        if isinstance(value, str) and value.strip():
            return util.color_text('token', value)
        return util.color_text('token', f"{value!r}")




# ---------------------------------------------------------------------------- #
#                               Primary Resources                              #
#  - Org
#  - Folder
#  - Dashboard
#  - Datasource
#  - Plugin
#  - LibraryElement
# ---------------------------------------------------------------------------- #

class Org(Resource):
    GROUP = 'organizations'
    TITLE = 'name'
    FNAME_KEYS = ('name',)
    ID = 'id'
    
    def create(self, d):
        return self.api.create_org(d)

    # def delete(self, d):
    #     return self.api.delete_org(d)

    def _pull(self):
        return [self.api.get_org(d['id']) for d in self.api.search_orgs()]


class Folder(Resource):
    GROUP = 'folders'
    TITLE = 'title'
    ID = 'uid'

    def create(self, d):
        return self.api.create_folder(d)

    def update(self, d, existing):
        return self.api.update_folder(d)

    def delete(self, d):
        return self.api.delete_folder(d)

    def _pull(self):
        ds = [self.api.get_folder(d['uid']) for d in self.api.search_folders()]
        for d in ds:
            d.pop('created', None)
            d.pop('updated', None)
        return ds

    def load(self, folder_path, **kw):
        ds = super().load(folder_path, **kw)
        ds = self._add_local_folders(ds, folder_path)
        return ds

    def _add_local_folders(self, local_items, folder_path):
        # TODO: FIXME !!! This is a hack to get folders to autocreate
        # get folders from dashboard hierarchy
        local_dirs = [f for f in os.listdir(os.path.join(folder_path, "dashboards")) if os.path.isdir(os.path.join(folder_path, "dashboards", f))]
        # filter out folders that are already in folder directory
        local_item_names = {f['title'] for f in local_items} | {ROOT_FOLDER}
        local_dirs = [f for f in local_dirs if f not in local_item_names]
        if local_dirs:
            # check if folders are already in grafana
            remote_folders = {d['title']: d for i, d in self.pull() if d['title'] in local_dirs}
            local_items = local_items.extend(
                remote_folders.get(f_name) or {'title': f_name}
                for f_name in local_dirs
            )
        return local_items


class Dashboard(Resource):
    GROUP = 'dashboards'
    TITLE = 'dashboard.title'
    ID = 'dashboard.uid'
    FNAME_KEYS = ('dashboard.title', 'dashboard.uid')
    DIFF_IGNORE_KEYS = Resource.DIFF_IGNORE_KEYS + ('meta.folderId', 'meta.folderUrl', 'meta.folderTitle')
    CLEAN = True
    EXT = 'json'

    def get_fname(self, d):
        folder = (d.get('folderTitle') or d['meta'].get('folderTitle') or self.ROOT_FOLDER).replace('/', '-')
        title = d['dashboard']['title'].replace('/', '-')
        uid = d['dashboard']['uid']
        return f"{folder}/{title}-{uid}"

    def create(self, d):
        return self.api.create_dashboard(d)
    
    def delete(self, d):
        return self.api.delete_dashboard(d)
    
    def diff_item(self, existing, item):
        newver = item.get('version')
        oldver = existing.get('version')
        # check if version is older
        if newver is not None and oldver is not None and newver < oldver:
            return 
        m1, m2, mm = util.nested_dict_diff(existing, item, self.DIFF_IGNORE_KEYS)

        # check if dashboard moved folders
        VERSION = {('dashboard', 'version'), ('meta', 'version'), ('dashboard', 'schemaVersion')}
        MOVED = {('meta', k) for k in ('folderTitle', 'folderId', 'folderUid', 'folderUrl')}
        mm = mm - VERSION
        if mm and not mm - MOVED and ('meta', 'folderUid') in mm:
            return 'moved'
        return (m1, m2, mm) if m1 or m2 or mm else False
    
    def pull(self, filter=None):
        payloads = self.api.search_dashboards()
        # payloads = [d['dashboard'] for d in self._filter([{'dashboard':d} for d in payloads], filter)]
        if filter:
            payloads = [d for d in payloads if fnmatch.fnmatch(d['title'], filter)]
        datasource_uids = {d['uid']: d['name'] for d in self.api.search_datasources()}

        ds = []
        for d in tqdm.tqdm(payloads, desc="Getting dashboards...", leave=False):
            di = self.api.get_dashboard(d['uid'])
            di['dashboard'] = self._replace_datasource(di['dashboard'], datasource_uids)
            ds.append(self._clean(di) if self.CLEAN else di)
        return ds
    
    def _clean(self, d):
        if 'meta' in d:
            d['meta'].pop('created', None)
            d['meta'].pop('updated', None)
        if 'dashboard' in d:
            d['dashboard'].pop('id', None)
            d['dashboard'].pop('folderId', None)
            d['dashboard'].pop('folderUrl', None)
            # d['dashboard'].pop('version', None)
        return d

    def load(self, folder_path, filter=None):
        ds = load_dir(os.path.join(folder_path, self.GROUP))
        ds = self._replace_folders(ds)
        # ds = self._filter(ds, filter)
        if filter:
            ds = [d for d in ds if fnmatch.fnmatch(d['dashboard']['title'], filter)]
            log.info(f"Filtering loaded dashboards by {filter}")
            log.info(f"Found {len(ds)} dashboards: {', '.join(d['dashboard']['title'] for d in ds)}")
        return ds

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
    
    def _replace_folders(self, items, available_folders=None):
        # update folder name
        new_items = {}
        for k, d in items.items():
            folder_name, fname = k.split(os.sep, 1)
            if fname in new_items:
                raise ValueError(f"Duplicate dashboard {d['meta']['title']} in both {folder_name} and {new_items['meta'].get('folderTitle')}")
            new_items[d['dashboard']['uid']] = d
            d['dashboard'].pop('id', None)
            d['dashboard'].pop('folderId', None)
            d['dashboard'].pop('folderUrl', None)

            # update folder name and uid
            current_folder = d['meta'].get('folderTitle') or ROOT_FOLDER
            if current_folder != folder_name:
                if available_folders is None:
                    available_folders = {f['title']: f for f in self.search_folders()}
                if folder_name in available_folders:
                    d['meta']['folderId'] = available_folders[folder_name]['id']
                    d['meta']['folderUid'] = available_folders[folder_name]['uid']
                    d['meta']['folderUrl'] = available_folders[folder_name]['url']
                    d['meta']['folderTitle'] = folder_name
        return list(new_items.values())
    
    # ----------------------------------- Print ---------------------------------- #
    
    def diff_str(self, new, update, missing, unchanged, items, existing, *, allow_delete=False, show_no_changes=True):
        # title
        header = util.color_text('bold', "Dashboards:") + '\n'

        # print dashboards grouped by folder
        lines = ''
        folders = {d['meta']['folderTitle'] for d in items.values()} | {d['meta']['folderTitle'] for d in existing.values()}
        for f in sorted(folders):
            # get dashboards in folder
            f_items = {k: d for k, d in items.items() if d['meta']['folderTitle'] == f}
            f_existing = {k: d for k, d in existing.items() if k in f_items}
            # format folder diff
            v = super().diff_str(
                new & set(f_items),
                {k: v for k, v in update.items() if k in f_items},
                missing & set(f_existing),
                unchanged & set(f_items),
                f_items, existing, title=f'{f}/', 
                allow_delete=allow_delete,
                show_no_changes=False,
            )
            lines += util.indent(v, 2) + '\n' if v.strip() else ''
        if not lines.strip():
            if show_no_changes:
                return header.rstrip() + util.color_text('unchanged', " :: no changes.")
            return ''
        return lines

    def _diff_item_text(self, kind, kind_label, item, other, diff):
        name = super()._diff_item_text(kind, kind_label, item, other, diff)

        # Dashboard moved folders
        diffed_keys = {x for xs in diff[2] for x in xs} if diff else set()
        if kind_label == 'moved' or ({('meta', 'folderUid'), ('meta', 'folderTitle')} & diffed_keys):
            moved = f"(moved from {util.C.BOLD}{other['meta']['folderTitle']})"
            return f"""{name} {util.color_text('yellow', moved)}"""
        return name
    
    def _diff_item_value(self, kind, kind_label, keys, item, other=None):
        if keys == ('meta', 'folderUid'):
            return None
        # Display dashboard panel differences
        if keys == ('dashboard', 'panels'):
            p1 = {p['id']: p for p in other['dashboard']['panels']}
            p2 = {p['id']: p for p in item['dashboard']['panels']}
            m1, m2, mm = util.nested_dict_diff(p1, p2, depth=1)
            mms = {i: util.nested_dict_diff(p1[i[0]], p2[i[0]])[2] for i in mm}
            moved = {i for i in mm if not {m[0] for m in mms[i]} - {'gridPos', 'collapsed', 'pluginVersion'}}
            mm2 = mm - moved

            return (' '.join((
                util.status_text('new', i=len(m1)),
                util.status_text('modified', i=len(mm2)),
                util.status_text('moved', i=len(moved)),
                util.status_text('deleted', i=len(m2)),
                util.status_text('unchanged', i=len(set(p1) & set(p2) - set(mm))),
            )) + '\n' + ''.join(
                [self._diff_item_block('new', 'panel:', p2[k[0]].get('title')) for k in m1] + 
                [self._diff_item_block(
                    'modified', 'panel:', 
                    (
                        f"{p1[k[0]].get('title')} {util.color_text('token', '->')} {p2[k[0]].get('title')}" 
                        if p2[k[0]].get('title') != p1[k[0]].get('title') else 
                        f"{p1[k[0]].get('title')}"
                    ) + (
                        util.color_text('moved', '  moved') 
                        if k in moved else 
                        '\n       ' + ', '.join(
                            util.color_text('token', '.'.join(m)) for m in mms[k] - {('pluginVersion',)}
                        )
                    ).rstrip()
                ) for k in mm] +
                [self._diff_item_block('deleted', 'panel:', p1[k[0]].get('title')) for k in m2]
            )).rstrip()
        
        # Display dashboard variable differences
        if keys == ('dashboard', 'templating', 'list'):
            p1 = {p['name']: p for p in other['dashboard']['templating']['list']}
            p2 = {p['name']: p for p in item['dashboard']['templating']['list']}
            m1, m2, mm = util.nested_dict_diff(p1, p2, depth=1)
            return ('\n' + ''.join(
                [self._diff_item_block('new', 'var:', k[0]) for k in m1] + 
                [self._diff_item_block('modified', 'var:', k[0]) for k in mm] +
                [self._diff_item_block('deleted', 'var:', k[0]) for k in m2]
            )).rstrip()
        
        # Any other differences
        return super()._diff_item_value(kind, kind_label, keys, item, other)


class Datasource(Resource):
    GROUP = 'datasources'
    TITLE = 'name'
    ID = 'uid'
    INCLUDE_READONLY = False

    def create(self, d):
        return self.api.create_datasource(d)
    
    def delete(self, d):
        return self.api.delete_datasource(d)

    def _pull(self):
        ds = self.api.search_datasources()
        ds = [d for d in ds if self.INCLUDE_READONLY or not d.get('readOnly')]
        return ds
    

class Plugin(Resource):
    GROUP = 'plugins'
    FNAME_KEYS = ['id']
    TITLE = 'name'
    ID = 'id'

    def create(self, d):
        return self.api.create_plugin(d)
    
    # def delete(self, d):
    #     return self.api.delete_plugin(d)

    def _pull(self):
        ds = self.api.get_plugins()
        ds = [d for d in ds if d.get('signature') != 'internal']  # drop built-in plugins
        return ds
    
    def load(self, folder_path, **kw):
        ds = super().load(folder_path, **kw)
        ds = [d for d in ds if d.get('signature') != 'internal']  # drop built-in plugins
        return ds


class LibraryElement(Resource):
    GROUP = 'library_elements'
    TITLE = 'name'
    ID = 'uid'

    def create(self, d):
        return self.api.create_library_element(d)
    
    def delete(self, d):
        return self.api.delete_library_element(d)

    def _pull(self):
        return self.api.search_library_elements()


class DashboardVersion(Resource):
    GROUP = 'dashboard_versions'
    TITLE = 'title'
    ID = 'uid'
    ORDER_BY = 'versions.-1.created'

    def create(self, d):
        # return self.api.create_dashboard(d)
        pass
    
    def delete(self, d):
        # return self.api.delete_dashboard(d)
        pass

    def pull(self, query=None, filter=None):
        dashboards = self._filter(self.api.search_dashboards(query), filter)
        return [
            self._process(self.api.get_dashboard_versions(d['uid']), d)
            for d in tqdm.tqdm(dashboards, desc="Getting dashboard versions...", leave=False)
        ]
    
    def _process(self, versions, d):
        # for v in versions:
        #     v.pop('data', None)
        # print(versions)
        # print(d)
        return {
            'uid': d['uid'],
            'title': d['title'],
            'versions': versions,
        }
    
    def _diff_item_value(self, kind, kind_label, keys, item, other=None):
        if keys == ('versions',):
            p1 = {p['version']: p for p in other['versions']}
            p2 = {p['version']: p for p in item['versions']}
            m1, m2, mm = util.nested_dict_diff(p1, p2, depth=1)
            unchanged = set(p1) & set(p2) - set(mm)
            newer = {k: p1[k]['created'] < p2[k]['created'] for k, in mm}
            
            # get text for each version range
            diff_text = {
                **{a: self._diff_item_block('unchanged', self._prange(a,b, "✓"), self._pdate(p2[a]['created'], p2[b]['created'], center=True), align_value=True) 
                      for a,b in self._contiguous_ranges(unchanged)},
                # **{a: self._diff_item_block('new', self._prange(a,b,"B"), self._pdate(p2[a]['created'], p2[b]['created']))
                #       for a,b in self._contiguous_ranges(k for k, in m1)},
                **{a: self._diff_item_block('new', " "*8, self._pdate(p2[a]['created'], p2[b]['created']) + " " + util.color_text('new', self._prange(a,b,"B", right=True)), right=True)
                      for a,b in self._contiguous_ranges(k for k, in m1)},
                # **{k: self._diff_item_block('modified', f'┌{f" {k} A":->7}', f"{util.color_text('red' if newer[k] else 'green', self._pdate(p1[k]['created']))} {p1[k]['message']}") + 
                #       self._diff_item_block('modified', f'└{f" B":->7}', f"{util.color_text('green' if newer[k] else 'red', self._pdate(p2[k]['created']))} {p2[k]['message']}") 
                #       for k, in mm},
                # **{a: ''.join(
                #         self._diff_item_block(
                #             'modified',
                #             # outer border
                #             f"{('┌' if k==a and not (a==b and i) else '└' if k==b else '│')}"
                #             # number/symbol
                #             f'{f" {k} {AB}":{" " if a<k and i==0 or k<b and i==1 else "─"}>7}', 
                #             # date and version message
                #             f"{util.color_text('green' if newer[k]==c else 'red', self._pdate(p[k]['created']))} {p[k]['message']}")
                #         for i, (p, c, AB) in enumerate(((p1,False,'A'), (p2,True,'B')))
                #         for k in range(a, b+1)
                #       )
                #       for a,b in self._contiguous_ranges(k for k, in mm)},
                **{a: ''.join(
                        self._diff_item_block(
                            'modified',
                            "",
                            util.color_text('modified', 
                                # outer border
                                f"{('┌' if k==a else '└' if k==b else '│')}"
                                # number/symbol
                                f'{f" {k} A":{" " if a<k else "─"}>7}'                
                            ) + 
                            # date and version message
                            f" {util.color_text('green' if not newer[k] else 'red', self._pdate(p1[k]['created']))} "
                            f" {util.color_text('green' if newer[k] else 'red', self._pdate(p2[k]['created']))} "
                            + util.color_text('modified', 
                                # number/symbol
                                f' {f"B {k} ":{" " if a<k else "─"}<7}'                
                                # outer border
                                f"{('┐' if k==a else '┘' if k==b else '│')}"
                            ) + (
                                (f"\n{p1[k]['message']}" if p1[k]['message'] else "") + 
                                (f"\n{p2[k]['message']}" if p2[k]['message'] else "")
                            ),
                            right=True
                        )
                        # for i, (p, c, AB) in enumerate(((p1,False,'A'), (p2,True,'B')))
                        for k in range(a, b+1)
                      )
                      for a,b in self._contiguous_ranges(k for k, in mm)},
                **{a: self._diff_item_block('deleted', self._prange(a,b,"A"), self._pdate(p1[a]['created'], p1[b]['created']))
                      for a,b in self._contiguous_ranges(k for k, in m2)},
            }
            # sort by version and join
            txt = (f"\n" + ''.join(diff_text[k] for k in sorted(diff_text))).rstrip()
            return txt
        return super()._diff_item_value(kind, kind_label, keys, item, other)
    
    def _prange(self, a, b, lbl='', right=False):
        r = f"{a}-{b}" if b is not None and a != b else f"{a}"
        return (
            f"""{f'{lbl or " "} {r}': <8}"""
            if right else
            f"""{f'{r} {lbl or " "}': >8}"""
        )
    
    def _pdate(self, a, b=None, center=False):
        a = datetime.strptime(a, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=timezone.utc).astimezone().strftime('%m/%d/%y %H:%M')
        b = datetime.strptime(b, "%Y-%m-%dT%H:%M:%S%z").replace(tzinfo=timezone.utc).astimezone().strftime('%m/%d/%y %H:%M') if b else ''
        if center:
            a = f"         {a} "
            b = f"       - {b} "
            return f'{a}\n{b}'
        else:
            r = f" {a} - {b} " if b and a != b else f" {a}"
        return r

    def _contiguous_ranges(self, xs):
        xs = sorted(xs)
        if not xs:
            return []
        ranges = [xs[0]]
        for i in range(1, len(xs)):
            if xs[i] > xs[i-1]+1:
                ranges.append(xs[i-1])
                ranges.append(xs[i])
        ranges.append(xs[-1])
        return list(zip(ranges[::2], ranges[1::2]))


# ---------------------------------------------------------------------------- #
#                                   Alerting                                   #
#  - AlertRule
#  - AlertChannel
#  - ContactPoint
#  - AlertNotifications
#  - NotificationPolicy
#  - NotificationTemplate
# ---------------------------------------------------------------------------- #


class AlertRule(Resource):
    GROUP = 'alert_rules'
    TITLE = 'title'
    ID = 'uid'

    def create(self, d):
        return self.api.create_alert_rule(d)
    
    def delete(self, d):
        return self.api.delete_alert_rule(d)

    def _pull(self):
        return self.api.search_alert_rules()


# class AlertRuleGroup(Resource):
#     GROUP = 'alert_rule_groups'
#     TITLE = 'name'
#     ID = 'id'

#     def create(self, d):
#         return #self.api.create_alert_rule_group(d)
    
#     # def delete(self, d):
#     #     return self.api.delete_alert_rule_group(d)

#     def _pull(self):
#         return self.api.search_alert_rule_groups()


class AlertNotifications(Resource):
    GROUP = 'alert_notifications'
    TITLE = 'name'
    ID = 'uid'

    def get_id(self, d):
        return d.get('uid', d['id'])

    def get_fname(self, d):
        return self.get_id(d)

    def create(self, d):
        return self.api.create_alert_notification(d)
    
    def delete(self, d):
        return self.api.delete_alert_notification(d)

    def _pull(self):
        return self.api.search_alert_notifications()


class ContactPoint(Resource):
    GROUP = 'contact_points'
    TITLE = 'name'
    ID = 'uid'

    def create(self, d):
        return self.api.create_contact_point(d)

    # def delete(self, d):
    #     return self.api.delete_contact_point(d)

    def _pull(self):
        return self.api.search_contact_points()


class NotificationPolicy(Resource):
    GROUP = 'notification_policies'
    TITLE = ID = None
    EXT = 'yaml'

    def get_fname(self, d):
        return "policies"

    def create(self, d):
        return self.api.update_notification_policy(d)
    
    # def delete(self, d):
    #     return self.api.delete_notification_policy(d)

    def _pull(self):
        return self.api.search_notification_policies()


class NotificationTemplate(Resource):
    GROUP = 'notification_templates'
    TITLE = 'name'
    ID = 'name'
    EXT = 'yaml'

    def create(self, d):
        return self.api.create_notification_template(d)
    
    # def delete(self, d):
    #     return self.api.delete_notification_template(d)

    def _pull(self):
        return self.api.search_notification_templates()

    def _diff_item_value(self, kind, kind_label, keys, item, other=None):
        if keys == ('template',):
            return "\n" + util.str_diff(item['template'], other.get('template') or '')
        return super()._diff_item_value(kind, kind_label, keys, item, other)


# ---------------------------------------------------------------------------- #
#                                     Users                                    #
#  - User
#  - Team
#  - TeamMember
#  - FolderPermission
# ---------------------------------------------------------------------------- #

class User(Resource):
    GROUP = 'users'
    TITLE = 'login'
    ID = 'login'
    FNAME_KEYS = ['login']
    DIFF_IGNORE_KEYS = Resource.DIFF_IGNORE_KEYS + ('createdAt', 'updatedAt', 'orgs')

    def create(self, d):
        return self.api.create_user(d)
    
    # def delete(self, d):
    #     return self.api.delete_user(d)

    def _pull(self):
        return [self.api.get_user(d['id']) for d in self.api.search_users()]


class Team(Resource):
    GROUP = 'teams'
    TITLE = 'name'
    ID = 'id'
    FNAME_KEYS = ['name']

    def create(self, d):
        return self.api.create_team(d)
    
    # def delete(self, d):
    #     return self.api.delete_team(d)

    def _pull(self):
        return [self.get_team(d['id']) for d in self.api.search_teams()]


class TeamMember(Resource):
    GROUP = 'team_members'
    FNAME_KEYS = ['teamId', 'login']
    TITLE = ID = None

    def create(self, d):
        return self.api.create_team_member(d)
    
    # def delete(self, d):
    #     return self.api.delete_team_member(d)

    def _pull(self):
        return [
            d for team in self.api.search_teams()
            for d in self.api.search_team_members(team['id'])
        ]


class FolderPermission(Resource):
    GROUP = 'folder_permissions'
    TITLE = None
    ID = 'uid'
    FNAME_KEYS = ['title', 'userLogin', 'role', 'uid']

    # def create(self, d):
    #     return self.api.create_folder_permission(d)
    
    # def delete(self, d):
    #     return self.api.delete_folder_permission(d)

    def _clean(self, d):
        d.pop('created', None)
        d.pop('updated', None)
        return d

    def _pull(self):
        return [
            self._clean(d) 
            for f in self.api.search_folders()
            for d in self.api.get_folder_permissions(f['uid'])
        ]


class ServiceAccount(Resource):
    GROUP = 'service_accounts'
    TITLE = 'name'
    ID = 'id'
    FNAME_KEYS = ['name']

    def create(self, d):
        return self.api.create_service_account(d)
    
    def update(self, d):
        return self.api.update_service_account(d)
    
    # def delete(self, d):
    #     return self.api.delete_service_account(d)

    def _pull(self):
        return self.api.search_service_accounts()


# ---------------------------------------------------------------------------- #
#                                     Data                                     #
# ---------------------------------------------------------------------------- #


class Alert(Resource):
    GROUP = 'alerts'
    TITLE = 'name'
    ID = 'id'
    FNAME_KEYS = ['name']

    def create(self, d):
        return 
    
    def delete(self, d):
        return 

    def _pull(self):
        return self.api.search_alerts()


class MuteTiming(Resource):
    GROUP = 'mute_timings'
    TITLE = None
    ID = 'id'
    FNAME_KEYS = ['id']

    def create(self, d):
        return self.api.create_mute_timing(d)
    
    def delete(self, d):
        return self.api.delete_mute_timing(d)

    def _pull(self):
        return self.api.search_mute_timings()


class Snapshot(Resource):
    GROUP = 'snapshots'
    TITLE = 'name'
    ID = 'uid'
    FNAME_KEYS = ['name', 'created']

    def create(self, d):
        return self.api.create_snapshot(d)
    
    # def delete(self, d):
    #     return self.api.delete_snapshot(d)

    def _pull(self):
        # ??? do you have to merge d with get_snapshot() ???
        return [self.api.get_snapshot(d['key']) for d in self.api.search_snapshots()]


class Annotation(Resource):
    GROUP = 'annotations'
    TITLE = ID = None
    FNAME_KEYS = ['dashboardUID', 'panelId', 'time', 'timeEnd']

    def create(self, d):
        return self.api.create_annotation(d)
    
    # def delete(self, d):
    #     return self.api.delete_annotation(d)

    def _pull(self):
        now = int(round(time.time() * 1000))
        one_month_in_ms = 31 * 24 * 60 * 60 * 1000
        thirteen_months_retention = (now - (13 * one_month_in_ms))
        return self.api.search_annotations(thirteen_months_retention, now)



# import ipdb
# @ipdb.iex
def cli():
    import logging
    logging.basicConfig()
    import fire
    fire.Fire(Resources)

if __name__ == '__main__':
    cli()
