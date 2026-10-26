# Deploying the Streamlit app (Streamlit Community Cloud)

Status as of 2026-10-10: the code is ready and pushed (commit `1c7f0fa`), but it is **not
deployed yet**. The steps below need the owner's Streamlit login.

## Steps

1. Go to https://share.streamlit.io and sign in with GitHub (`nishantkandoi`).
2. **Create app** → **Deploy a public app from GitHub**:
   - Repository: `nishantkandoi/ai-agent`
   - Branch: `main`
   - Main file path: `app.py`
   - App URL: pick a name, e.g. `ipl-agent`
3. **Advanced settings → Secrets**: paste in the full contents of the secrets file (see below).
4. Click **Deploy**. The first build takes a few minutes, and the link will look like `https://ipl-agent.streamlit.app`.

## Secrets file

The Secrets text contains the service-account key, so it is never stored in this repo.
Generate it into a private temp file from the local key:

```bash
.venv/bin/python -I - /tmp/streamlit-secrets.toml <<'EOF'
import json, os, secrets, sys
key = json.load(open("/Users/nishant/credentials/workshop_oct2/.local/workshop-user-key.json"))
lines = [f"app_password = {json.dumps(secrets.token_urlsafe(12))}", "", "[gcp_service_account]"]
lines += [f"{k} = {json.dumps(v)}" for k, v in key.items()]
fd = os.open(sys.argv[1], os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
os.write(fd, ("\n".join(lines) + "\n").encode()); os.close(fd)
EOF
open -e /tmp/streamlit-secrets.toml
```

- `app_password` is a random password that viewers must enter. Change it to something
  easier to remember if you like.
- Delete the temp file after pasting it: `rm /tmp/streamlit-secrets.toml`.

## How the app behaves

- **When deployed:** it reads the key from Secrets, shows a password screen, and refuses to
  run if `app_password` is missing.
- **Locally:** it uses `GOOGLE_APPLICATION_CREDENTIALS` and shows no password screen.
- Every question runs on the `ipl-nao` Google Cloud bill, so share the link and password
  separately, and only with people you trust.

## After deploying

- Check that the password screen appears, then ask a test question.
- If the build or a question fails, the logs are under **Manage app** in the bottom-right
  of the deployed app.
- Add the live URL to this file and to the README.
