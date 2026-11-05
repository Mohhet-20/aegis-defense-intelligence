# Video Frame Analysis (Section 8)

`app/cv/video_sampling.py`. Bounded, point-in-time frame sampling --
**explicitly not continuous real-time surveillance.**

## How sampling works

`sample_frames(path, interval_seconds, max_frames)` opens the video
with `cv2.VideoCapture` and reads frames **sequentially**
(`cap.read()` in a loop), yielding only the frame at index 0, then
every `round(fps * interval_seconds)`-th frame after that, until either
the video ends or `max_frames` sampled frames have been yielded --
whichever comes first. Every frame that is *not* selected is decoded
and immediately discarded; at most one decoded frame exists in memory
at any instant, and **the full video is never held in memory as a
list.**

```python
frame_stride = max(1, round(fps * interval_seconds))
# frame_index % frame_stride == 0  ->  this frame is sampled
```

## Why sequential reads, not seeking

`cv2.VideoCapture.set(CAP_PROP_POS_FRAMES, n)` is unreliable across
codecs/containers (seeking accuracy varies by backend). Sequential
`.read()` calls are the conservative, broadly-correct choice, at the
cost of still decoding (and discarding) the skipped frames -- an
acceptable tradeoff given `CV_VIDEO_MAX_FRAMES_PER_JOB` and
`CV_MAX_VIDEO_DURATION_SECONDS` already bound the total work per job.

## What's preserved per sampled frame

Every `DetectionResult` from a video job carries the real
`frame_index` (the 0-based index in the original video) and
`frame_timestamp_seconds` (`frame_index / fps`) it came from --
**both always set together**, never approximated, never dropped --
verified by
`tests/test_video_inference.py::test_video_job_sampling_interval_controls_which_frames_are_used`,
which asserts the *exact* sampled frame indices for a known fps/
interval combination (`[0, 20, 40]` for a 10fps video with a 2-second
interval).

## Bounds, all settings-driven and always server-clamped

| Setting | Default | Enforced by |
|---|---|---|
| `CV_VIDEO_FRAME_SAMPLE_INTERVAL_SECONDS` | 2.0s | Default only -- a client can request any positive interval. |
| `CV_VIDEO_MAX_FRAMES_PER_JOB` | 30 | **Always** the real ceiling, via `min()` in `inference_service.submit_inference_job()` -- a client requesting `max_frames=10000` gets back whatever is actually `<= 30`, not a rejected request. |
| `CV_MAX_VIDEO_DURATION_SECONDS` | 600s (10 min) | Enforced at **upload** time (`media_service.ingest_media()`) -- a too-long video is rejected before it can ever be the subject of an inference job at all. |
| `CV_MAX_VIDEO_DIMENSION_PX` | 4000px/side | Enforced at upload time, same as above. |

## What this does NOT do (stated explicitly, per the specification's own requirement)

- **Not continuous/real-time surveillance.** There is no notion of an
  ongoing stream, no loop that keeps pulling new frames as time passes,
  and no code path reachable from any live camera feed. A video job
  processes one already-uploaded file, once, and stops.
- **Not cross-camera re-identification.** Each `InferenceJob` is
  scoped to exactly one `MediaAsset`; nothing here compares a detection
  in one video to a detection in a different video, and there is no
  `track_id`-like concept anywhere in this schema (the job, not
  this one -- see `docs/architecture/COMPUTER_VISION_CONTRACTS.md`'s
  still-untouched `TrackIdentifier`/`TrackObservation` contracts).
- **No frame thumbnail/image extraction endpoint.** The frontend's
  Video Analysis Workspace shows detections as a data table
  (frame index, timestamp, class, confidence) rather than a visual
  bounding-box overlay on an extracted frame image -- building that
  would require a new "serve me frame N's pixels" endpoint this layer
  deliberately did not add, since every actual requirement (bounded
  sampling, preserved frame identity, persisted/queryable results) is
  already met without it. Reasonable follow-up work for a future
  work, not a gap this one is silent about.
- No audio processing of any kind.
