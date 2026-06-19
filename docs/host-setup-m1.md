# Host setup — M1 Pro, always-on, fresh machine

Goal: take a brand-new (or wiped) M1 Pro / 16 GB / macOS box and end with
ClickHouse + the FastAPI backend running 24/7, ingestion automated, the API
reachable from anywhere via a Cloudflare Tunnel, and nightly backups to R2.

Companion doc: [DEPLOY.md](../DEPLOY.md) covers the actual app boot. This
file covers everything *around* it that DEPLOY.md assumes is already there.

## 1. One-time prereqs (~15 min)

Homebrew + the tools the app needs:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
brew install --cask orbstack         # Docker runtime (lighter than Docker Desktop on M1)
brew install uv git cloudflared      # uv = Python deps; cloudflared = public API tunnel
```

Start OrbStack once from Spotlight so the VM backend initialises, then:

```bash
docker ps   # should succeed
```

> OrbStack gotcha (see DEPLOY.md §Notes): if `docker ps` later starts
> erroring randomly, run `~/.orbstack/bin/orb start` from the CLI.

Clone the repo and follow [DEPLOY.md §1](../DEPLOY.md) to bring up CH +
restore a dump (or start cold). Stop after the API is serving on
`127.0.0.1:8000`.

## 2. Make the machine actually always-on

`always-on mode` in System Settings isn't enough — by default macOS still
sleeps the disk and pauses Docker when the lid closes.

```bash
# Never sleep on AC power. Sleep on battery is fine.
sudo pmset -c sleep 0 disksleep 0 womp 1 autorestart 1

# Survive power blips: auto-boot after power loss
sudo pmset -c autorestart 1
```

Settings → Battery → Options → **"Prevent automatic sleeping when the
display is off"** — ON.

Verify:

```bash
pmset -g | grep -E 'sleep|autorestart|womp'
```

## 3. Run the backend as a launchd service

Docker Compose handles ClickHouse restart-on-reboot via OrbStack. The
FastAPI process needs its own keep-alive. Use launchd, not nohup.

Create `~/Library/LaunchAgents/com.researchpapers.api.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.researchpapers.api</string>
  <key>ProgramArguments</key>
  <array>
    <string>/opt/homebrew/bin/uv</string>
    <string>run</string>
    <string>papers</string>
    <string>api-serve</string>
    <string>--host</string><string>127.0.0.1</string>
    <string>--port</string><string>8000</string>
    <string>--lean</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/sarthak/Desktop/fleet/researchPapers</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/sarthak/Library/Logs/researchpapers-api.log</string>
  <key>StandardErrorPath</key><string>/Users/sarthak/Library/Logs/researchpapers-api.err</string>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.researchpapers.api.plist
launchctl list | grep researchpapers     # should show a PID
curl http://127.0.0.1:8000/healthz       # should 200
```

To restart after code changes: `launchctl kickstart -k gui/$(id -u)/com.researchpapers.api`.

## 4. Expose the API via Cloudflare Tunnel (free, no port-forwarding)

You already pay for the CF $5 Workers plan; Tunnel is included free.

```bash
cloudflared tunnel login                                      # opens browser, picks a zone
cloudflared tunnel create researchpapers
cloudflared tunnel route dns researchpapers api.<your-domain>
```

Create `~/.cloudflared/config.yml`:

```yaml
tunnel: researchpapers
credentials-file: /Users/sarthak/.cloudflared/<TUNNEL-UUID>.json
ingress:
  - hostname: api.<your-domain>
    service: http://127.0.0.1:8000
  - service: http_status:404
```

Install as a launchd service so it survives reboots:

```bash
sudo cloudflared service install
```

Verify: `curl https://api.<your-domain>/healthz` from your phone on
cellular. If it 200s, you're done with networking.

> Putting CF Access in front of `api.<your-domain>` is the single best
> security upgrade — adds auth at CF's edge so the API isn't open to
> the internet. Five minutes in the Zero Trust dashboard.

## 5. Frontend on Cloudflare Pages (not on this host)

The API has to live on this machine because ClickHouse does. The website
does not — it's a static Astro build, ~1.4 MB gzipped. Putting it on Pages
gets you a global CDN, automatic deploys on `git push`, and graceful
degradation when the API blips (cached pages still load).

[DEPLOY.md §3](../DEPLOY.md) has the actual build steps. Specific to this
two-domain setup:

- Connect the GitHub repo in the CF Pages dashboard, point at `web/`
- Build command: `npm run build`
- Output: `dist`
- Env var: `PUBLIC_API_URL=https://api.<your-domain>` ← the tunnel from §4
- Custom domain: `papers.<your-domain>` (same zone as `api.`)

The JSON files in `web/public/data/` are baked at build time, so data
freshness needs a rebuild trigger. After the daily `papers refresh-web &&
papers export-ch` job in §6, hit the Pages Deploy Hook:

```bash
curl -X POST "https://api.cloudflare.com/client/v4/pages/webhooks/deploy_hooks/<HOOK-ID>"
```

Add that line to the end of `scripts/refresh_web.sh` (or whatever wraps
the daily export). Pages rebuilds in ~30s and ships the new bundle to the
edge.

Why this split is worth the small extra setup:
- Latency: page loads hit CF's edge, not your apartment uplink
- Availability: laptop reboot → site still loads, only live queries fail
- Bandwidth: your home upload pipe serves zero visitors

## 6. Automate ingestion with launchd

The arXiv / OpenReview / citation overlays should run on a schedule. macOS
ignores cron when the user isn't logged in; use launchd `StartCalendarInterval`.

Pattern — one plist per scheduled job at `~/Library/LaunchAgents/com.researchpapers.<job>.plist`:

```xml
<!-- ... ProgramArguments invokes `uv run papers <subcommand>` ... -->
<key>StartCalendarInterval</key>
<dict>
  <key>Hour</key><integer>3</integer>
  <key>Minute</key><integer>0</integer>
</dict>
```

Suggested cadence (tune to your source rate limits):

| Job                          | When          | Command                                   |
|------------------------------|---------------|-------------------------------------------|
| arXiv daily delta            | 03:00 daily   | `papers ingest arxiv --since=1d`          |
| OpenReview overlay refresh   | 04:00 daily   | `papers overlay openreview`               |
| Citation graph rebuild       | 05:00 weekly  | `papers overlay references`               |
| Web JSON export + refresh    | 06:00 daily   | `papers refresh-web && papers export-ch`  |

Load each: `launchctl load ~/Library/LaunchAgents/com.researchpapers.<job>.plist`.
Tail logs at `~/Library/Logs/researchpapers-<job>.log`.

## 7. Backups to R2 (your CF plan covers this free)

ClickHouse + `web/public/data/` are the only things worth backing up — the
code is in git.

One-time R2 setup: create a bucket `researchpapers-backup` in the CF
dashboard, generate an R2 access key. Store in `~/.config/rclone/rclone.conf`:

```ini
[r2]
type = s3
provider = Cloudflare
access_key_id = ...
secret_access_key = ...
endpoint = https://<account-id>.r2.cloudflarestorage.com
```

Nightly backup script (`scripts/backup_to_r2.sh`):

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
./scripts/dump_data.sh                                          # writes researchpapers_data_<ts>.tar.gz
DUMP=$(ls -t researchpapers_data_*.tar.gz | head -1)
rclone copy "$DUMP" r2:researchpapers-backup/
# keep 7 most recent on R2
rclone lsf r2:researchpapers-backup/ | sort -r | tail -n +8 | xargs -I{} rclone delete "r2:researchpapers-backup/{}"
rm "$DUMP"
```

Add a launchd plist for 02:00 daily. Test the restore path once on a
throwaway directory before you trust it.

## 8. Health monitoring (5 minutes, do not skip)

A free `cron-job.org` or UptimeRobot hitting `https://api.<your-domain>/healthz`
every 5 min → email if it goes down. The tunnel handles "is the box up"; this
catches "is the app actually serving."

## What you DON'T need

- No reverse proxy on the host (CF Tunnel terminates TLS at the edge)
- No firewall rules for the API port (it stays bound to 127.0.0.1)
- No Postgres in production — only CH; the compose file has PG for legacy
  ingestion shims, can be left stopped

## Recovery runbook

| Symptom                          | Check                                                | Fix                                                       |
|----------------------------------|------------------------------------------------------|-----------------------------------------------------------|
| API 502s via tunnel              | `launchctl list \| grep researchpapers`              | `launchctl kickstart -k gui/$(id -u)/com.researchpapers.api` |
| Tunnel offline                   | `sudo launchctl print system/com.cloudflare.cloudflared` | `sudo launchctl kickstart -k system/com.cloudflare.cloudflared` |
| CH unreachable                   | `docker ps`                                          | `~/.orbstack/bin/orb start && docker compose up -d clickhouse` |
| Disk full                        | `df -h`                                              | `docker system prune -a`, rotate `~/Library/Logs/researchpapers-*` |
| Cold-restore from R2             | (see §7)                                             | `rclone copy r2:... /tmp/ && ./scripts/deploy.sh /tmp/researchpapers_data_*.tar.gz` |

## Open decisions for you

- Domain name for `api.<your-domain>` — pick before §4
- CF Access policy — gate the API behind your email, or leave it open?
- Backup retention on R2 — 7 days is the default above; increase if you
  want longer recovery window (R2 storage is cheap: 10 GB free, then
  $0.015/GB/mo).
