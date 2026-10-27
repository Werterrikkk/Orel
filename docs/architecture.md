# Architecture

orel is a single-operator surveillance prototype. Its primary workflow is live video, one forbidden convex quadrilateral, whole-frame PPE checks, and yellow/red warnings. Permit/replay APIs remain compatible with existing stored data but are outside the primary interface.

## Modules and deployment boundary

- `orel/domain.py`: pure geometry and PPE association; retained replay permit rules.
- `orel/temporal.py`: bounded per-condition frame voting and clearing hysteresis; no external dependencies.
- `orel/notifications.py`, `orel/telegram_client.py`: private bot configuration, durable delivery queue and Bot API transport, independent of inference.
- `orel/surveillance.py`: portable IoU association and per-track/per-reason warning episodes. Only standard-library imports; no HTTP, storage, camera SDK, OpenCV, or YOLO.
- `orel/sources.py`: source metadata and the `FrameObservation` adapter contract. Laptop is available; Rubetek explicitly awaits hardware/SDK.
- `orel/detector.py`, `orel/vision.py`: the working local CPU detector; trained weight hash validation and normalized observations. The single spawned worker caches the model for sequential JPEG inference.
- `orel/live.py`: session lease, freshness, shared rule invocation, and event persistence.
- `orel/evidence.py`, `orel/storage.py`: exact evidence frame, configuration/model provenance, and short SQLite transactions.
- `orel/app.py`, `orel/schemas.py`: validated endpoints and worker ownership.
- `frontend/src/hooks/useCamera.ts`: capture, sequential transport, freshness, session cleanup.
- `frontend/src/hooks/useCameraPreview.ts`: MediaStream playback independent of inference state; cancelled play promises do not report device failure.
- `CameraWorkspace.tsx`: video fills the available viewport, labelled boxes, zone editor, and lower-right warning feed. `App.tsx` owns navigation and the full journal/source views.

The target camera-side agent would combine the vendor detector/runtime with the portable domain and surveillance rules. The operator browser and journal need not run on the camera. The current Python/PyTorch local runtime is a preview implementation; it is not an installable Rubetek package.

## Adapter contract and Rubetek boundary

`FrameObservation` carries `objects` (`kind`, normalized `box`, `confidence`), `inference_height`, `inference_ms`, `model` provenance, and `settings`. A source adapter produces observations, never final safety decisions. The evaluator accepts monotonic timestamps supplied by the trusted capture/agent clock.

The laptop adapter captures JPEG in the browser, sends it to `/api/camera/sessions/{id}/frames?sequence=N`, and normalizes YOLO output in `analyze_frame`. `LiveMonitor.start(model, source)` already accepts source metadata independently of the rules.

`GET /api/sources` exposes honest availability. Rubetek native API requests, credentials, detection mapping and video transport are deliberately not invented. The [RVX-4 manual](https://support.rubetek.com/upload/iblock/50c/9u2c4eay1em5sx30bnn5us8ui86z21vn/RE-RVX_4.pdf) describes RTSP/WebRTC; this does not establish a custom-model runtime. A real integration needs the exact hardware, SDK, supported model/quantization format, resource limits, continuous detections or frames, health timestamps, and video display transport. Real device inference and rule placement must then be measured and verified.

## Local capture and playback

`getUserMedia` requests video only, ideally 1280×720. The live preview is independent of model sampling. JPEG requests use a maximum long edge of 640 px, with a 200 ms target period and one request in flight. Slow inference reduces frequency instead of growing a queue. Server-side admission also rejects concurrent/duplicate frames, including when a client aborts an unfinished request. Recording analysis and live capture share one worker and are mutually exclusive.

A server session expires after 15 seconds without renewal. Stop, page leave, backgrounding or errors stop tracks and request deletion; a late permission grant after cancellation is immediately stopped. Server results over two seconds old cannot create events. The client also rejects roundtrips over two seconds and hides old detections/alerts after two seconds without a fresh result.

Webcam permissions require localhost or HTTPS ([MDN](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia)). Playback sets muted/defaultMuted/playsInline before attaching the stream; load/canplay triggers playback. Stale or aborted `play()` promises cannot stop a newer session. Autoplay denial offers a manual button rather than reporting a broken camera ([WebKit](https://webkit.org/blog/6784/new-video-policies-for-ios/), [React effect cleanup](https://react.dev/learn/synchronizing-with-effects)). The stream is never reattached merely because an inference result changed.

## Zones, association and warnings

Camera configuration is `require_helmet`, `require_vest`, and optional `danger_zone` (named normalized bounds plus four optional ordered polygon points; legacy rectangles remain readable). PPE checks cover the whole image; the forbidden zone uses any overlap or boundary contact of each person's bounding box with the polygon. No permit is evaluated in this workflow.

Gear is geometrically assigned to plausible head/torso regions. Small people or clipped heads are uncertain, not missing PPE. Optional equipment does not trigger warnings.

Person boxes are matched one-to-one by IoU >= 0.35. Missing boxes remain eligible for ID recovery for up to 3 seconds since their last actual detection, provided frames continue arriving. Missing people are not rendered or included in current counts. Competing similarly plausible matches start new tracks; contested old IDs are retired instead of remaining available for later reassignment. Only geometric track hints are retained during an absence: warning evidence and episodes are discarded immediately, so reappearance starts fresh confirmation and cannot count unseen time toward escalation. Source gaps over 1.25 seconds, stale frames and configuration changes still reset all tracks. IDs are short-lived hints, never identity or guaranteed trajectory. No person recognition or cross-camera matching is introduced.

Each `(track, reason)` has a separate episode: `ppe_required` combines missing mandatory gear; `danger_zone` is independent. A temporal condition requires at least 6 positive violation observations, at least 2 seconds since supporting evidence began, and at least 80% support in a rolling 3-second window; the last two observations must also support it. Evidence is sampled at most 10 times per second, with 30 samples maximum. PPE conditions are independent per gear item, so a recent vest miss cannot inherit helmet confirmation. Only confirmed conditions create yellow alerts/events. After 10 seconds from supporting evidence onset, a critical level additionally requires three recent supporting observations and a currently supporting frame. A gap over 1.25 seconds, stale frame, changed configuration, disappearance, uncertainty about required gear, or ambiguous association resets the affected episode. Correction requires at least 3 opposing observations spanning 0.6 seconds, preventing one-frame status flicker. Unknown PPE clears its evidence immediately without declaring safety. Correcting one condition does not reset another continuing condition. Re-entry starts a new episode. Thus transient false negatives may restart the timer; real moving scenes still require validation.

The UI shows the server's severity and duration rather than advancing its own escalation clock. Alerts disappear when corrected. Older events may remain explicitly labelled as journal history. No current positive safety claim is inferred from unavailable data.

## Journal and compatibility

After temporal confirmation, an episode is persisted with the exact contributing JPEG, rules, model hash, track hint, reason and initial severity. Escalation updates the same record with `critical`, duration and `escalated_at`; it retains the original evidence frame and original `created_at`. The UI labels this as the first signal's image. Reviews are independent of severity. CSV includes severity and escalation time and escapes spreadsheet formulas.

Settings, uploads, replay configurations, events and snapshots remain in the existing SQLite/file layout. No destructive schema migration is required. Training runs and active weights are unchanged. Raw media, weights, databases and local QA screenshots remain ignored by Git.

Retained replay semantics: the browser supplies playback position only for explicitly simulated replay, source-frame indices select evidence, server time evaluates permit intervals, and seeking/config changes restart confirmation. Multiple API workers/cameras, authenticated network deployment and production qualification remain separate work.

## Telegram notifications

Telegram is disabled until the operator verifies a bot token, explicitly chooses a chat and saves enabled delivery. `POST /api/telegram/bot` uses `getMe`; `/api/telegram/chats` reads `getUpdates` only on request. No webhook is installed or removed, and no bot account is created automatically. `PUT /api/telegram` selects the target; `POST /api/telegram/test` sends an explicitly labelled test message. `GET /api/telegram` returns safe status, queue count and recent deliveries, never the token. Validation errors for these routes omit submitted values.

The token is written atomically to `data/runtime/telegram-secret.json` with mode 0600; runtime data is ignored by Git. It is not stored in SQLite or browser localStorage. Status and network errors never include Bot API URLs/tokens.

Confirmed live events enqueue a SQLite `notifications` job with a frozen target fingerprint, event/level key and the exact current JPEG. No network operation runs in the capture request. A lifespan task processes jobs in a thread using the standard library HTTPS transport. Captions contain source, zone, reason, UTC-to-Moscow time and event ID. `sendPhoto` carries the actual confirming/escalating frame; the journal separately retains the first event frame.

A level is enqueued once per event and destination. Identical source/zone/reason/level notifications have a 30-second cooldown to limit track-fragment spam. Red and yellow have separate cooldowns. An unsent pending yellow is superseded by red, avoiding stale delivery order. Disabled periods do not replay event history. Disabling/changing a bot or chat cancels pending jobs; jobs never silently migrate to another recipient. New chat selection clears the previous test status.

Pending jobs expire after 5 minutes. Explicit rate-limit/server failures may retry up to 3 attempts with the server delay. Timeout/ambiguous delivery is marked uncertain and never automatically repeated. A crash while sending also becomes uncertain at startup; no false exactly-once network guarantee is made. Terminal jobs remove temporary notification photos. A missing token disables effective delivery. Failure of queue insertion does not stop vision and is visible in notification status.

External photo transfer occurs only after enabling the chosen chat. Unit/API tests use an injected fake Bot API client; browser setup tests mock only Telegram endpoints. Camera scenarios still use the actual trained YOLO. A real Telegram account/token/chat are required for the final delivery check. See [setup](telegram.md) and the [official API](https://core.telegram.org/bots/api#sendphoto).

## v2 capture health and detection

The person network (base YOLO26n COCO) is independent of the PPE network. Only current detections contribute to counts; retained IDs never render as people. Both model weight hashes are recorded in inference metadata. Historical event links were removed from the live alert feed.

The JPEG adapter reports darkness/uniformity as `camera_health=obscured`. LiveMonitor clears current detections and warning evidence, retains only the normal 3-second geometric ID recovery, and saves a single critical camera event after 5 continuous seconds. Normal frames rearm the camera episode; stale frames and source gaps reset its evidence. Telegram uses a camera-specific explanation. A missing transport result displays a separate visible source-health warning in the client.

The zone editor collects four ordered clicks and requires explicit save. API validation rejects self-crossing, degenerate, non-convex and out-of-range quadrilaterals. Live entry uses convex polygon–box intersection (separating axis theorem); evidence snapshots use the polygon itself. Legacy replay foot anchors remain compatible. This is perspective-aware floor geometry, not 3D reconstruction.
