from datetime import datetime, timezone
from . import util




class ResourceDiff:
    def __init__(self, resource):
        self.GROUP = resource.GROUP
        self.ORDER_BY = resource.ORDER_BY
        self.ORDER_DESC = resource.ORDER_DESC
        self.DIFF_IGNORE_KEYS = resource.DIFF_IGNORE_KEYS
        self.get_title = resource.get_title
        
        
    def diff_item(self, existing, item):
        """Compare items to see if they changed."""
        missing1, missing2, mismatch = util.nested_dict_diff(existing, item, self.DIFF_IGNORE_KEYS)
        return (missing1, missing2, mismatch) if missing1 or missing2 or mismatch else False

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
        
        # deleted items
        lines += self._diff_items("deleted", "deleted" if allow_delete else "trash", missing, existing)
        
        # modified items
        update_k = {k: d if isinstance(d, str) else f"modified" for k, d in update.items()}
        for k in set(update_k.values()):
            update_ki = {d: update[d] for d, ki in update_k.items() if ki == k}
            lines += self._diff_items("modified", k, update_ki, items, existing)
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




class DashboardDiff(ResourceDiff):
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
            f_existing = {k: d for k, d in existing.items() if d['meta']['folderTitle'] == f}
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
        if keys == ('dashboard', 'panels') and other is not None:
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


class DashboardVersionDiff(ResourceDiff):

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


class NotificationTemplateDiff(ResourceDiff):

    def _diff_item_value(self, kind, kind_label, keys, item, other=None):
        if keys == ('template',):
            return "\n" + util.str_diff(item['template'], other.get('template') or '')
        return super()._diff_item_value(kind, kind_label, keys, item, other)
