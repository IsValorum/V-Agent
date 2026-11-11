## What and why

<!-- One fix or feature. What changes for people using V-Agent? -->

## How it was checked

- [ ] `python -m unittest discover -s tests` and the `tests/*.cjs` interface tests pass
- [ ] Interface changes: edited the `agent/ui-*` module and ran `python scripts/sync-ui.py`
- [ ] New visible text has translations for es, en, pt, fr and de in `agent/locales.json`
- [ ] Tool or agent-loop changes were tried with a real local model
- [ ] No personal data, keys or model files in the diff
