# E2E Test Runbook

This runbook captures the exact command sequence used for the Docker-based end-to-end smoke test under `/tmp/music-monitor-e2e`.

## Preconditions

- Local image exists: `music-monitor:local`
- Environment file exists: `/tmp/music-monitor-e2e/lidarr.env`
- Test folders exist:
  - `/tmp/music-monitor-e2e/watch`
  - `/tmp/music-monitor-e2e/output`
  - `/tmp/music-monitor-e2e/logs`
- Source album/test files are available at `/mnt/c/test`

## Command sequence

```bash
docker run --rm -d --name music-monitor-e2e --env-file /tmp/music-monitor-e2e/lidarr.env -v /tmp/music-monitor-e2e/watch:/data/watch -v /tmp/music-monitor-e2e/output:/data/output -v /tmp/music-monitor-e2e/logs:/logs -e MUSIC_MONITOR_WATCH_PATH=/data/watch -e MUSIC_MONITOR_OUTPUT_PATH=/data/output -e LOG_FILE=/logs/music-monitor.log -e LOG_LEVEL=INFO -e BACKOFF_INITIAL=0.2 -e BACKOFF_MAX=2 -e BACKOFF_ATTEMPTS=3 music-monitor:local

cp -r /mnt/c/test/. /tmp/music-monitor-e2e/watch/

sleep 8 && find /tmp/music-monitor-e2e/output -type f | sort

sleep 8 && find /tmp/music-monitor-e2e/watch -type f | sort

sleep 8 && tail -n 120 /tmp/music-monitor-e2e/logs/music-monitor.log

find /tmp/music-monitor-e2e/output -type f | sort

find /tmp/music-monitor-e2e/watch -type f | sort

docker stop music-monitor-e2e
```

## Expected observations

- Output files appear under `/tmp/music-monitor-e2e/output`.
- Watch files decrease/move out of `/tmp/music-monitor-e2e/watch` as processing completes.
- Logs include startup + processing events such as:
  - `music_monitor_starting`
  - `processing_album_directory`
  - `file_processed` / `file_moved`
  - `album_progress`
- Container stops cleanly with `docker stop music-monitor-e2e`.
