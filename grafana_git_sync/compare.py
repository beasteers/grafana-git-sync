import os
from grafana_git_sync import USERNAME, PASSWORD, URL
from .resources import Resources
from .util import nested_dict_diff


class Compare:
    def __init__(self, url, username=USERNAME, password=PASSWORD, ref_url=URL):
        assert isinstance(url, str), "url must be a string"
        assert isinstance(username, str), "username must be a string"
        assert isinstance(password, str), "password must be a string"
        assert isinstance(ref_url, str), "ref_url must be a string"
        url = os.getenv(url) or url
        self.rs1 = Resources(username, password, ref_url, clean=False)
        self.rs2 = Resources(username, password, url, clean=False)

    def pull(self, key, filter=None, **kw):
        d1=self.rs1[key]
        d2=self.rs2[key]

        items = d1.pull(filter=filter)    # latest items from source A
        existing = d2.pull(filter=filter)
        return items, existing, d1, d2

    def diff(self, key, filter=None, inverse=False, **kw):
        items, existing, d1, d2 = self.pull(key, filter=filter, **kw)
        diffs = d1.get_diff(existing, items, inverse=inverse, **kw)
        print(d1.diff_str(*diffs))

        print("Source:     ", self.rs1.api.url if not inverse else self.rs2.api.url)
        print("Destination:", self.rs2.api.url if not inverse else self.rs1.api.url)

    def diffv(self, filter=None, inverse=False, **kw):
        # dash1 = self.rs1['dashboards']
        items, existing, d1, d2 = self.pull("dashboard_versions", filter=filter, **kw)
        new, update, missing, unchanged, items, existing = d1.get_diff(existing, items, inverse=inverse, **kw)
        print("Unchanged:", len(unchanged))
        print("New:", len(new))
        for k in new:
            print(k)
        print()

        print("Deleted:", len(missing))
        for k in missing:
            print(k)
        print()

        print("Updated:", len(update))
        for k in update:
            a = existing[k]
            b = items[k]
            i, j = common_version(a, b)
            print(k)
            print("A", existing[k]['title'], existing[k]['versions'][i]['version'], f'{d1.api.url}/d/{a["uid"]}')
            for ii, d in enumerate(a['versions']):
                print('~' if ii==i else '', d['created'], d['version'], d['message'])
            print("B", items[k]['title'], items[k]['versions'][j]['version'], f'{d2.api.url}/d/{b["uid"]}')
            for ii, d in enumerate(b['versions']):
                print('~' if ii==j else '', d['created'], d['version'], d['message'])

            print(d1.diff_str(*d1.get_diff([a], [b], inverse=inverse, **kw)))
            print()
            
            if input('>?'):from IPython import embed;embed()



def common_version(a, b):
    for i, ai in enumerate(a['versions']):
        for j, bi in enumerate(b['versions']):
            m1, m2, mm = nested_dict_diff(ai['data'], bi['data'])
            if not m1 and not m2 and not mm:
                return i, j
    return -1, -1
            


import ipdb
@ipdb.iex
def cli():
    import logging
    logging.basicConfig(level=logging.INFO)
    import fire
    fire.Fire(Compare)


if __name__ == '__main__':
    cli()