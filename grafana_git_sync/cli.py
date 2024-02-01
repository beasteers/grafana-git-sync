import logging



import os
import glob
import logging
from . import EXPORT_DIR, URL, USERNAME, PASSWORD
from .util import load_dir
from .api import API
log = logging.getLogger(__name__.split('.')[0])


def apply(username=USERNAME, password=PASSWORD, url=URL, src_dir=EXPORT_DIR, only=None, force: 'bool'=False):
    """Apply to Grafana instance."""
    assert url and username and password, "missing url and/or credentials"
    log.info(f"Importing Grafana to {url}")
    log.info(f"Loading from {src_dir}\n")

    api = API(url)
    api.login(username, password)
    api.apply(src_dir)


def export(username=USERNAME, password=PASSWORD, url=URL, out_dir=EXPORT_DIR):
    '''Dump the configuration of Grafana to disk.'''
    assert url and username and password, "missing url and credentials"
    log.info(f"Exporting Grafana from {url}")
    log.info(f"Saving to {out_dir}\n")

    api = API(url)
    api.login(username, password)
    api.export(out_dir)



QUESTIONS = [
    "Are you sure you want to delete all of the flows, operations, webhooks, and roles?",
    "Really? you really sure?",
    "I mean your funeral... last chance!"
]

def wipe(username, password, url=URL):
    '''Wipe all flows, operations, webhooks, and roles from a Directus instance. Used for debugging.'''
    assert url and username and password, "missing url and credentials"
    for q in QUESTIONS:
        if input(f'{q} y/[n]: ').strip().lower() != 'y':
            log.info("Okie! probably for the best.")
            return
    else:
        log.warning("Okay let's destroy everything!")

    log.info(f"Importing Directus schema and flows to {url}")

    api = API(url)
    api.login(username, password)
    import tempfile
    with tempfile.TemporaryDirectory() as tmp_dir:
        api.apply(tmp_dir)


import ipdb
@ipdb.iex
def main(key=None):
    logging.basicConfig()
    import fire
    fire.Fire({
        "apply": apply,
        "export": export,
        "wipe": wipe,
    })
