#!/usr/bin/env python3

import os
import re
import csv
import glob
import json
import yaml
from datetime import datetime
# try:
#     from yaml import CLoader as Loader, CDumper as Dumper
# except ImportError:
#     from yaml import Loader, Dumper

import logging
log = logging.getLogger(__name__.split('.')[0])

EXT = 'json'

def export_one(data, out_dir, name, ext=EXT):
    state = _export_one(data, out_dir, name, ext)
    log.info("%-16s :: %s.", name.title(), status_text(state))
    return 

def _export_one(data, out_dir, name, ext=EXT, dry_run=False):
    existing = glob.glob(get_fname(out_dir, name, ext))  # TODO: search for other exts
    if existing:
        assert len(existing) == 1
        existing_data = load_data(existing[0])
        if existing_data == data:
            return 'unchanged'
        state = 'modified'
    else:
        state = 'new'
    if not dry_run:
        dump_data(data, get_fname(out_dir, name, ext))
    return state


def export_dir(data, out_dir, name, ext=EXT, deleted_dir=None, dry_run=False):
    counts = {'unchanged': 0, 'modified': 0, 'new': 0, 'deleted': 0}

    # write out files
    current = set()
    existing = {_path_to_stem(f, f'{out_dir}/{name}') for f in _get_file_list(f'{out_dir}/{name}')}

    for name_i, d in data.items():
        state = _export_one(d, f'{out_dir}/{name}', name_i, ext, dry_run=dry_run)
        counts[state] += 1
        current.add(name_i)
    
    # check for files that weren't written to
    if deleted_dir is True:
        deleted_dir = os.path.join(out_dir, '.deleted', datetime.now().strftime('%Y-%m-%dT%H:%M:%S'))
    for name_i in existing - current:
        f = get_fname(f'{out_dir}/{name}', name_i, ext)
        if deleted_dir:
            f2 = get_fname(f'{deleted_dir}/{name}', name_i, ext)
            log.warn('Deleting %s. Backing up to %s', f, f2)
            if not dry_run:
                os.makedirs(os.path.dirname(f2), exist_ok=True)
                os.rename(f, f2)
        else:
            log.warn("%s :: Deleting %s", name, name_i)
            if not dry_run:
                os.remove(f)
        # log.warn("%s :: Removing %s", name, name_i)
        # os.remove(get_fname(out_dir, name, ext))
        counts['deleted'] += 1

    if not any(counts.values()):
        log.info("%s%-16s :: 🫥  none.", "[Dry Run]" if dry_run else "", name.title())
    else:
        log.info(
            "%s%-16s :: %s. %s. %s. %s.", 
            "[Dry Run]" if dry_run else "",
            name.title(), *(
                status_text(k, i=counts[k]) 
                for k in ['new', 'modified', 'deleted', 'unchanged']
            ),
        )

def _get_file_list(src_dir):
    fs = glob.glob(os.path.join(src_dir, '**/*'), recursive=True)
    return [f for f in fs if os.path.isfile(f)]

def _path_to_stem(path, rel_dir):
    return os.path.splitext(os.path.relpath(path, rel_dir))[0]


def load_dir(src_dir):
    return {_path_to_stem(f, src_dir): load_data(f) for f in _get_file_list(src_dir)}


# def load_dir(src_dir):
#     if os.path.isfile(src_dir):
#         return load_data(src_dir)
#     return [load_data(f) for f in glob.glob(f'{src_dir}/*')]


def get_fname(out_dir, fname, ext):
    return os.path.join(out_dir, f'{fname}.{ext.lstrip(".")}')

def clean(fname):
    return re.sub(r'\s*[^-\s_A-Za-z0-9.]+\s*', ' ', fname)



def dump_data(data, file_path):
    """
    Write data to a file in CSV, JSON, or YAML format based on the file extension.

    Parameters:
    - data: The data to be written (list of dictionaries).
    - file_path: The path to the file.

    Returns:
    - None
    """
    file_extension = file_path.split('.')[-1].lower()
    # log.info(f"💾↓ pretend write to {file_path}")
    # return

    os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
    if file_extension == 'csv':
        with open(file_path, 'w', newline='') as csv_file:
            # iterator so you can write large csv files
            data = iter(data)
            first = next(data, None)
            if first is not None:
                csv_writer = csv.DictWriter(csv_file, fieldnames=list(first))
                csv_writer.writeheader()
                csv_writer.writerow(first)
                csv_writer.writerows(data)
        log.info(f"💾↓ Wrote csv to {file_path}")
    elif file_extension == 'json':
        with open(file_path, 'w') as json_file:
            json.dump(data, json_file, indent=2)
        log.info(f"💾↓ Wrote json to {file_path}")
    elif file_extension in ['yaml', 'yml']:
        with open(file_path, 'w') as yaml_file:
            yaml.dump(data, yaml_file, default_flow_style=False)
        log.info(f"💾↓ Wrote yaml to {file_path}")
    elif file_extension in ['txt']:
        with open(file_path, 'w') as f:
            f.write(str(data))
        log.info(f"💾↓ Wrote text to {file_path}")
    else:
        raise ValueError("Unsupported file format. Supported formats: csv, json, yaml/yml")

def load_data(file_path):
    """
    Load data from a file in CSV, JSON, or YAML format based on the file extension.

    Parameters:
    - file_path: The path to the file.

    Returns:
    - Loaded data (list of dictionaries).
    """
    file_extension = file_path.split('.')[-1].lower()

    if file_extension == 'csv':
        log.debug(f"📖 Reading csv {file_path}")
        with open(file_path, 'r') as csv_file:
            csv_reader = csv.DictReader(csv_file)
            return [dict(row) for row in csv_reader]
    elif file_extension == 'json':
        log.debug(f"📖 Reading json {file_path}")
        with open(file_path, 'r') as json_file:
            return json.load(json_file)
    elif file_extension in ['yaml', 'yml']:
        log.debug(f"📖 Reading yaml {file_path}")
        with open(file_path, 'r') as yaml_file:
            return yaml.safe_load(yaml_file)
    elif file_extension in ['txt']:
        log.debug(f"📖 Reading text {file_path}")
        with open(file_path, 'w') as f:
            return f.read()
    else:
        raise ValueError("Unsupported file format. Supported formats: csv, json, yaml/yml")



def dict_diff(d1, d2):
    missing1 = d2.keys() - d1
    missing2 = d1.keys() - d2
    mismatch = {k for k in d1.keys() & d2 if d1[k] != d2[k]}
    return missing1, missing2, mismatch



def norm_cm_key(name):
    name = re.sub('[^-._a-zA-Z0-9]+', '-', name)
    return name


class C:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

COLORS = {'new': C.CYAN, 'modified': C.YELLOW, 'deleted': C.RED, 'additional': C.RED, 'unchanged': C.GREEN, 'none': C.BLUE}
ICONS = {'new': '🌱', 'modified': '🍂', 'deleted': '🪵 ', 'additional': '🪵 ', 'unchanged': '🌲', 'none': '🫥'}


def color_text(color, x, i=True):
    return f'{color}{x}{C.END}'


def status_text(status, fmt=None, i=True):
    color = COLORS.get(status, status)
    icon = ICONS.get(status,"")
    fmt = fmt or status
    fmt = f'{icon} {i} {fmt}' if i is not True else f'{icon} {fmt}'
    return f'{color}{fmt}{C.END}' if i else fmt