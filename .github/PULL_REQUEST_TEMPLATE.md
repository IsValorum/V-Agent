## What and why

<!-- One fix or feature. What changes for people using V-Agent? -->

## How it was checked

- [ ] `python -m unittest discover -s tests` and the `tests/*.cjs` interface tests pass
- [ ] Interface changes: edited files in `agent/ui/` and ran `python scripts/build-ui.py`
- [ ] New visible text has translations for es, en, pt, fr and de in `agent/ui/locales.json`
- [ ] Tool or agent-loop changes were tried with a real local model
- [ ] No personal data, keys or model files in the diff
