# SharedSignals/cron

This directory contains thin cron wrappers for SharedSignals production jobs.

- Scripts must `cd` to the SharedSignals root before running Python.
- Scripts may source root `.env` for local configuration, but must not contain secrets.
- Use `flock` locks under `logs/locks/` to avoid overlapping runs.
- Write stdout/stderr to `logs/cron/`.
- Keep business logic in the main SharedSignals modules; cron scripts should only orchestrate.
