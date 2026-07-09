# UI — candidate portal

The candidate-facing web surface.

## Scope

- **Access-code entry:** single field; valid code → session workspace. No accounts,
- **Session home:** problem statement, remaining time, links to VS Code (code-server)
  and JupyterLab, submit button.
- **Submit:** triggers a final workspace snapshot and marks the session complete.

Deliberately thin: the real environment is code-server/Jupyter; the portal only
handles entry, orientation, and submission. Reverse-proxies the workspace services
over HTTPS with the session cookie as auth.
