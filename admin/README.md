# Admin console

Interviewer/operator surface, running concurrently with the candidate session on the
platform host. Auth via dedicated admin accounts — never shared logins.

## Session configuration (pre-session)

- **Candidate & code:** enter the candidate's display name (used for the welcome on
  the home page; PII stays in the admin system, never in workspace or logs); issue the
  access code. Codes are reusable within the session (reconnects) and auto-disable
  1 hour after session end — expiry adjustable per session.
- **Problem set:** compose the session from registry problems; flip registry `status`
  (draft/hidden/active/retired) to control what is selectable at all.
- **Terms:** default standard terms (confidentiality, monitoring notice, code of
  conduct, IT integrity — see `ui/README.md`); optionally customize or add NDA-style
  disclaimers per session.
- **LLM policy:** model selection (defaults: gemini flash tiers; pro tier only if
  explicitly enabled) and budget (default $5).
- **Internet policy:** default full access; restrict per session if needed.
- **Timing:** session duration; can be extended live.

## Live moderation (during)

- Progress view: latest workspace snapshot diff, shell tail, notebook activity,
  LLM transcript.
- **Deliver hints** / inject messages into the session (this primitive later grows
  into multi-stage injection).
- Extend time, revoke access code, kill switch for the LLM key or the whole session.
- Every admin action lands in the same audit record as candidate activity.

## Close-out (post-session)

- Trigger/verify the **audit export bundle** (see `logging/`), download it.
- Initiate workspace **reset** for the next candidate.
- Review mode: audit timeline side-by-side with the problem's rubric.
