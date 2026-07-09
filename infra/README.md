# Infra

Deployment and provisioning. Owns everything AWS-side.

## Scope

- **Image build** (`images/`): workspace container image + host AMI. Spec in
  [`images/base-image-spec.md`](images/base-image-spec.md).
- **Provisioning** (`terraform/`, planned): per-session EC2 instance (small VM),
  IAM roles for log shipping, S3 buckets for audit archives.
- **Session lifecycle** (planned): provision → seed problems → run → archive → destroy.
  Triggered by the admin service; nothing here is manually operated in steady state.

## Principles

- Instances are disposable; the audit record (logging/) is the only durable output
  of a session.
- Candidate workspaces never hold long-lived credentials — the LLM proxy key is
  session-scoped, log shipping uses the instance role.
- Everything reproducible from this directory: no hand-configured pets.
