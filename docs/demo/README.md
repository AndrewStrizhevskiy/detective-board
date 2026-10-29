# Demo materials

- `STAGE_CHECKLIST.md`: what to do on the evening before, on site, and the exact words for every failure.
- `rehearsals.md`: the log of the three timed rehearsals and the failure drills.
- `bare-vs-agent.md`: recorded bare-model errors used on the slides (issue #13).
- `jury-faq.md`: prepared answers to the hard questions.
- Stored runs (replays) for the UI: `web/replay/*.json`, opened with `?replay=replay/<file>.json`; each shows the RECORDING badge.

## Backup screen recording (issue #15)

What: one clip per demo step plus one full run, recorded on the show laptop with the real stack (`just run`, model warmed), mp4, 1920x1080 (or the projector's 1366x768), no sound. The files are large and stay out of git: on the USB stick (exFAT) and in `~/detective-board-video/` on the laptop.

Names: `demo-<tag>-step<N>-<short>.mp4` (for example `demo-v1.0-step2-garcia-r1.mp4`) and `demo-<tag>-full.mp4`, where `<tag>` is the build the team agreed on (`git describe --tags`).

How (pick one; check first with `echo $XDG_SESSION_TYPE`):
- OBS Studio (X11 or Wayland): Settings -> Output -> Recording format mp4, encoder x264; Video -> output resolution 1920x1080, 30 fps; source "Screen Capture"; Start / Stop Recording.
- X11 without OBS: `ffmpeg -f x11grab -framerate 30 -video_size 1920x1080 -i :0.0 -c:v libx264 -preset veryfast -crf 23 -pix_fmt yuv420p demo-<tag>-step<N>-<short>.mp4` (stop with `q`).
- GNOME on Wayland: the built-in screen recorder (`Ctrl+Shift+Alt+R` to start and stop; it saves webm in `~/Videos/Screencasts`), then `ffmpeg -i in.webm -c:v libx264 -crf 23 -pix_fmt yuv420p out.mp4`.

After recording: play each file once from the stick on a second computer, then write the checksums below (`sha256sum demo-*.mp4`).

| File | sha256 | Length (m:s) | Recorded on, by |
|---|---|---|---|
| TBD | TBD | TBD | TBD |
