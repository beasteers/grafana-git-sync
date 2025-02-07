#!/usr/bin/env python3

import os
import re
import csv
import glob
import json
import difflib
import ruamel.yaml
import ruamel.yaml.scalarstring
from datetime import datetime
import logging
log = logging.getLogger(__name__.split('.')[0])

EXT = 'yaml'
yaml=ruamel.yaml.YAML(typ='rt')

CACHE_DIR = os.path.join(os.path.dirname(__file__), '.cache')

def disk_cache_fn_json(fn, *args, key=None, cache_dir=CACHE_DIR, **kwargs):
    '''Cache the results of a function to disk as json'''
    os.makedirs(cache_dir, exist_ok=True)
    cache_file = os.path.join(cache_dir, f'{key or fn.__name__}.json')
    if os.path.isfile(cache_file):
        with open(cache_file, 'r') as f:
            return json.load(f)
    result = fn(*args, **kwargs)
    with open(cache_file, 'w') as f:
        json.dump(result, f)
    return result


def confirm(*questions, default_yes=False, bye="Okie bye <3"):
    for q in questions:
        if (
            input(f'{q} y/[n]: ').strip().lower() != 'y' 
            if not default_yes else
            input(f'{q} [y]/n: ').strip().lower() not in {'y', ''}
        ):
            log.info(bye)
            raise SystemExit(0)

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


def export_dir(data, out_dir, name, ext=EXT, delete=True, deleted_dir=None, dry_run=False):
    counts = {'unchanged': 0, 'modified': 0, 'new': 0, 'deleted': 0}

    # write out files
    current = set()
    existing = {_path_to_stem(f, f'{out_dir}/{name}') for f in _get_file_list(f'{out_dir}/{name}')}

    for name_i, d in data.items():
        state = _export_one(d, f'{out_dir}/{name}', name_i, ext, dry_run=dry_run)
        counts[state] += 1
        current.add(name_i)
    
    # check for files that weren't written to
    if delete:
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

def _get_file_list(src_dir, exts=None, ignored_dirs=['.trash']):
    fs = glob.glob(os.path.join(src_dir, '**/*'), recursive=True)
    return [
        f for f in fs if os.path.isfile(f) and 
        (exts is None or os.path.splitext(f)[1].lstrip('.') in exts) and
        (ignored_dirs is None or not any(d in f.split(os.sep) for d in ignored_dirs))
    ]

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
    file_path = os.path.expanduser(file_path)
    file_extension = file_path.split('.')[-1].lower()
    # log.info(f"💾↓ pretend write to {file_path}")
    # return

    os.makedirs(os.path.dirname(file_path) or '.', exist_ok=True)
    for f in alt_ext(file_path):
        if input(f"Replace {f} with {file_extension} file? [y]/n: ").strip().lower() not in {'y', ''}:
            os.remove(f)
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
            ruamel.yaml.scalarstring.walk_tree(data)
            yaml.dump(data, yaml_file)
        log.info(f"💾↓ Wrote yaml to {file_path}")
    elif file_extension in ['txt']:
        with open(file_path, 'w') as f:
            f.write(str(data))
        log.info(f"💾↓ Wrote text to {file_path}")
    else:
        raise ValueError("Unsupported file format. Supported formats: csv, json, yaml/yml")


def alt_ext(fname):
    base, ext = os.path.splitext(fname)
    fs = [f for f in glob.glob(f'{base}.*') if f != fname and os.path.splitext(f)[0] == base]
    return fs


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
            return yaml.load(yaml_file)
    elif file_extension in ['txt']:
        log.debug(f"📖 Reading text {file_path}")
        with open(file_path, 'w') as f:
            return f.read()
    else:
        raise ValueError("Unsupported file format. Supported formats: csv, json, yaml/yml")



# def dict_diff(d1, d2, ignore=None):
#     missing1 = d2.keys() - d1
#     missing2 = d1.keys() - d2
#     mismatch = {k for k in d1.keys() & d2 if _filter_dict(d1[k], ignore) != _filter_dict(d2[k], ignore)}
#     return missing1, missing2, mismatch

def nested_dict_diff(d1, d2, ignore=None, _keys=(), _ignore=None, depth=-1):
    _ignore = _ignore or {tuple(k.split('.') if isinstance(k, str) else k) for k in ignore or []}
    if _keys in _ignore:
        return set(), set(), set()
    if depth == 0 or not isinstance(d1, dict) or not isinstance(d2, dict):
        d1 = _filter_dict(d1, _ignore, _keys)
        d2 = _filter_dict(d2, _ignore, _keys)
        return set(),set(),{_keys} if d1 != d2 else set()

    missing1 = {(*_keys, k) for k in d2.keys() - d1} - _ignore
    missing2 = {(*_keys, k) for k in d1.keys() - d2} - _ignore
    mismatch = set()
    for k in d1.keys() & d2:
        m1, m2, mm = nested_dict_diff(d1[k], d2[k], _keys=(*_keys, k), _ignore=_ignore, depth=depth-1)
        missing1 |= m1
        missing2 |= m2
        mismatch |= mm

    return missing1, missing2, mismatch

def _filter_dict(d, ignore, _current=()):
    '''Drop nested keys from a dictionary'''
    return {
        k: _filter_dict(d[k], ignore, (*_current, k)) 
        for k in d if (*_current, k) not in ignore
    } if isinstance(d, dict) and ignore else d

def _filter_dict_keep(d, keep, _current=()):
    '''Keep nested keys from a dictionary'''
    return {
        k: _filter_dict_keep(d[k], keep, (*_current, k)) 
        for k in d if (*_current, k) in {k[:len(_current)+1] for k in keep}
    } if isinstance(d, dict) and keep else d


def dict_prune(d):
    if not isinstance(d, dict):
        return d
    return {k: dict_prune(v) for k, v in d.items() if v}


def get_key(d, key, default=...):
    keys = key.split('.') if isinstance(key, str) else key
    try:
        for k in keys:
            if isinstance(d, (list, tuple)):
                k = int(k)
            d = d[k]
    except (KeyError, IndexError):
        if default is ...:
            raise
        return default
    return d


def norm_cm_key(name):
    name = re.sub('[^-._a-zA-Z0-9]+', '-', name)
    return name


def indent(text, spaces=4):
    return '\n'.join(' '*spaces + l for l in text.splitlines())

def symbol_block(txt='', color=None, *, indent=0, maxlen=None, top_border=False, right=False):
    lines = ''
    s = SYMBOLS.get(color, '|')
    txt = txt.splitlines() if txt else []
    for i, l in enumerate(txt):
        # '┌' if len(txt) > 1 else s
        ii = s+' '*(indent+1) if i or not top_border else s+'─'*(indent+1)
        lines += f"{color_text(color, ii)}{_truncate(l, maxlen)}{color_text(color, ii[::-1]) if right else ''}\n"
    return lines

def _truncate(txt, maxlen):
    return txt[:maxlen] + ('...' if len(txt) > maxlen else '') if maxlen else txt


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

COLORS = {'new': C.CYAN, 'modified': C.YELLOW, 'moved': C.YELLOW, 'deleted': C.RED, 'trash': C.RED, 'additional': C.RED, 'unchanged': C.GREEN, 'token': C.CYAN, 'none': C.BLUE}
ICONS = {'new': '🌱', 'modified': '🍂', 'moved': '🚛', 'deleted': '🪵 ', 'trash': '🪵 ', 'additional': '🪵 ', 'unchanged': '🌲', 'none': '🫥'}
SYMBOLS = {'new': '+', 'modified': '│', 'moved': '>', 'deleted': '×', 'trash': '×', 'additional': '×', 'unchanged': '.', 'none': '.'}

def color_text(color, x, i=True):
    x = "" if x is None else x
    c = COLORS.get(color, getattr(C, color.upper(), None)) if color else None
    return f'{c}{x}{C.END}' if c else x


def status_text(status, fmt=None, i=True, icon=None):
    color = COLORS.get(status)
    icon = ICONS.get(icon or status,"") if icon is not False else ""
    fmt = fmt or status or ""
    fmt = f'{icon} {i: >2} {fmt}' if i is not True else f'{icon} {fmt}'
    return f'{color}{fmt}{C.END}' if color else fmt



def str_diff(old, new):
    if old == new:
        return ""
    result = ""
    codes = difflib.SequenceMatcher(a=old, b=new).get_opcodes()
    for code in codes:
        if code[0] == "equal": 
            result += old[code[1]:code[2]]
        elif code[0] == "delete":
            result += color_text('red', old[code[1]:code[2]])
        elif code[0] == "insert":
            result += color_text('green', new[code[3]:code[4]])
        elif code[0] == "replace":
            result += (color_text('red', old[code[1]:code[2]]) + color_text('green', new[code[3]:code[4]]))
    return result