# Working on orel

This is a local, single-operator prototype. Keep it understandable and easy to change.

- Read README.md and docs/architecture.md before changing behavior.
- Keep detection, domain rules, persistence, API, and UI separate. Domain rules must not import FastAPI, OpenCV, or YOLO.
- Use typed Python and TypeScript. Prefer small functions and explicit data over generic frameworks.
- The backend is authoritative for permit status, zone evaluation, and saved events. The browser supplies playback position only in the explicitly labelled replay demo.
- All datetimes crossing the API must include a timezone. Store timestamps in UTC; display Europe/Moscow.
- Never treat missing detections or an offline source as proof of safety. Missing PPE is a review signal, not a confirmed violation.
- Do not imply person identity, guaranteed tracking continuity, correct PPE fastening, or production qualification. Short-lived IoU track IDs are geometric hints; ambiguity and source gaps must reset warning timers.
- No fabricated detections or metrics in normal operation. Test fixtures stay in tests; sample media must be labelled and have source provenance.
- Do not overwrite trained weights or training runs. Keep model/dataset provenance and evaluation reports.
- Before training a new model, verify data splits, class IDs, and annotations. Do not split adjacent frames of one recording between training and final testing.
- Keep raw video, datasets, models, runtime DB, and credentials out of Git.
- Run backend tests, Ruff, frontend type checking/build, and the relevant browser flow before delivery. Add tests for business rules and failure paths, not implementation trivia.
- The primary UI is live surveillance with one forbidden quadrilateral selected with four ordered clicks and whole-frame PPE checks. Warnings require multi-frame evidence; escalation uses 10 observed seconds and fresh reconfirmation. Permit/replay APIs remain outside the main workflow.
- Telegram is optional and disabled until explicitly configured. Never expose tokens in API responses/logs/Git. Deliver in the background from confirmed live events, deduplicate by event/level, and never automatically repeat an uncertain send. Tests must not send real external messages.
- Browser webcam capture is the working preview. Rubetek is the target source; its native SDK/model runtime and API integration cannot be claimed implemented until a camera/SDK is provided. Keep source adapters separate from portable rules. Cloud publishing is out of scope.
- Change only files related to the current request; inspect the diff after a failed edit.
