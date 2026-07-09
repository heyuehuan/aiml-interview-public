# UI — candidate portal

The candidate-facing web surface. Deliberately thin: entry, orientation, and
submission — the real environment is the workspace tools it links to.

## Candidate flow

```
access code → terms acceptance → home page → tools
```

1. **Access code entry.** Single field, no account, no PII collected here. The code
   maps to a session configured in the admin console (which holds the candidate's
   display name so the experience is personalized). Codes remain valid for reconnects
   during the session and auto-disable 1 hour after session end (admin-adjustable).
2. **Terms acceptance (gate).** Shown before the workspace, must be accepted to
   proceed; acceptance is timestamped into the audit record. Default standard terms —
   admin can customize per session (see `admin/`):
   - confidentiality / do-not-share (problem content and session materials)
   - notice that the workspace is monitored and recorded for audit purposes
   - code of conduct; basic IT integrity, security, and privacy rules
   - workspace is for the interview only; no data exfiltration or other use
3. **Home page.** Welcome message addressed to the candidate by name, remaining time,
   and a clean tool dashboard (iCloud-dashboard style tiles):
   - **Problems** — dedicated problem page (opens in a new tab by default)
   - **IDE** — code-server (OSS Code)
   - **Jupyter** — JupyterLab
   - **Terminal** — via the IDE or Jupyter terminal
   - **Submit** — final snapshot + marks the session complete
4. All workspace tools are reverse-proxied over HTTPS with the session as auth;
   nothing is reachable without a live session.
