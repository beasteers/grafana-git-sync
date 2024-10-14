import os
from grafana_git_sync import USERNAME, PASSWORD, URL
from .resources import Resources



class Compare:
    def __init__(self, url, username=USERNAME, password=PASSWORD, ref_url=URL):
        assert isinstance(url, str), "url must be a string"
        assert isinstance(username, str), "username must be a string"
        assert isinstance(password, str), "password must be a string"
        assert isinstance(ref_url, str), "ref_url must be a string"
        url = os.getenv(url) or url
        self.rs1 = Resources(username, password, ref_url, clean=False)
        self.rs2 = Resources(username, password, url, clean=False)

    def diff(self, key, filter=None, inverse=False, **kw):
        d1=self.rs1[key]
        d2=self.rs2[key]

        items = d1.pull(filter=filter)    # latest items from source A
        existing = d2.pull(filter=filter) # existing items from source B
        diffs = d1.get_diff(existing, items, inverse=inverse, **kw)
        print(d1.diff_str(*diffs))

        print("Source:     ", self.rs1.api.url if not inverse else self.rs2.api.url)
        print("Destination:", self.rs2.api.url if not inverse else self.rs1.api.url)


import ipdb
@ipdb.iex
def cli():
    import logging
    logging.basicConfig(level=logging.INFO)
    import fire
    fire.Fire(Compare)


if __name__ == '__main__':
    cli()