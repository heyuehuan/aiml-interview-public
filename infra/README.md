# Infra

> **Historical design note — superseded by the implementation.**
> The deployment is realized in `environments/` (`compose.yaml`, `Dockerfile*`),
> `scripts/`, and `DEPLOY.md`. This file records the original intent and may have
> drifted — the compose/scripts and `DEPLOY.md` are authoritative. (`images/` still
> holds the base-image spec referenced below.)

Deployment of the single persistent platform host. Owns everything server-side below
the application layer.

## Deployment model

- **One long-lived small VM instance** hosts portal, admin console, proxy, and
  the candidate workspace. No per-session provisioning; capacity model is one
  candidate at a time with the admin concurrent.
- **Host OS: RHEL8-family** (Rocky Linux 8 / AlmaLinux 8 — suits broad enterprise
  compatibility; favor stability over recency). Host stays thin: container runtime,
  platform services, nothing candidate-facing installed on the host itself.
- **Audit stays on-host** for now (no S3/CloudWatch dependency); sessions end with an
  export bundle the admin downloads. Off-host archival is a later hardening step.

## Scope

- **Image build** (`images/`): workspace container image spec —
  [`images/base-image-spec.md`](images/base-image-spec.md).
- **Host provisioning** (planned): repeatable bring-up of the platform host (packages,
  container runtime, TLS, service units, firewall). One script/playbook from clean
  RHEL8-family image to running platform — the host is rebuildable even though it is
  long-lived.
- **Reset mechanics** (planned, with `environments/`): the between-candidates reset —
  destroy workspace containers + volumes, revoke session key, verify export completed.
  Reset must be a single idempotent operation, never manual cleanup.

## Principles

- Long-lived host, but **no pet state**: anything not reproducible from this repo
  (plus secrets in `.env`) is a bug.
- The session's audit export is the only output that must survive a reset.
- Secrets (Vertex AI key, admin credentials) live in host-local config (`.env` or
  similar), never in the repo or the workspace.
