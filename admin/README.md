# Admin console

Interviewer/operator surface. Auth via SSO or per-user accounts — never shared logins.

## Scope

- **Access codes:** generate one-time, time-boxed codes; map code → candidate record
  (PII stays here, never in the workspace or logs); revoke.
- **Problem visibility:** flip registry `status` (draft/hidden/active/retired);
  compose a session's problem set.
- **Session management:** set duration, LLM budget/models, internet policy;
  provision/teardown via infra; extend or terminate live sessions.
- **Moderation:** live view of session activity (latest snapshot diff, shell tail,
  LLM transcript); inject messages/hints if the interview format allows; kill switch.
- **Review:** post-session audit browser — final artifacts plus the intermediate
  record timeline, side by side with the problem's rubric.
