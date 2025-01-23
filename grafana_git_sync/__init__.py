import os
import logging
log = logging.getLogger(__name__)
log.setLevel(getattr(logging, os.getenv("LOG_LEVEL") or "INFO"))

# local env file
load_env = lambda: {k.strip():v.strip() for k,v in (x.split('=',1) for x in open('.env').readlines() if x.strip() and not x.strip().startswith('#'))} if os.path.isfile('.env') else {}
os.environ.update(load_env())

# env vars
ENV_PREFIX = os.environ.get("GRAFANA_ENV") or "GRAFANA"
URL = os.environ.get(ENV_PREFIX + "_URL") or "http://localhost:3000"
USERNAME = os.environ.get(ENV_PREFIX + "_USER") or "admin"
PASSWORD = os.environ.get(ENV_PREFIX + "_PASS") or "admin"
API_KEY = os.environ.get(ENV_PREFIX + "_KEY")
EXPORT_DIR = os.environ.get(ENV_PREFIX + "_PATH") or "grafana"

# print(URL, USERNAME, API_KEY, EXPORT_DIR)
# input()

from . import util
from .api import API
from .resources import Resources
