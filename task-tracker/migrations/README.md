# Task Tracker Migrations

Migration files are applied in lexical order (`NNNN_name.sql`) by
`task-tracker/migrate.py`.

Current baseline:

- `0001_core_schema.sql`: core Task Tracker tables, constraints, and indexes.
