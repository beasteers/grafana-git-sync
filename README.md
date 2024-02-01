# directus-git-sync
A lightweight sidecar to apply directus schema and configuration.

Handles:
 - schema
 - flows (and operations)
 - dashboards (and panels)
 - webhooks
 - roles
 - permissions
 - settings


This is meant for doing GitOps-style bring-up of Directus, meaning that it only exports things that you might want to store in git.

API endpoints it (purposefully) does not handle:
 - collection items
 - files
 - activity
 - folders (for now? idk)
 - notifications
 - presets
 - relations
 - revisions
 - shares
 - translations

I think there could be a separate script that's specifically for "data" migration/import/export.