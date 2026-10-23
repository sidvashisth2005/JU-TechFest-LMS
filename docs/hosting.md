# Hosting the dashboard from the laptop

The API (port 8000) serves the built dashboard and everything it needs, so one public link is enough.

## Quick public link (no account)

```powershell
.\infra\tunnel.ps1          # or: .\infra\run_all.ps1 -Tunnel
```

Prints a `https://<random>.trycloudflare.com` address. It works from any network (mobile data included) without router changes, and changes every time the tunnel restarts. `cloudflared.exe` is downloaded to `D:\DevCache\bin`.

## Fixed address

With a domain on Cloudflare: `cloudflared tunnel login`, `cloudflared tunnel create lms`, route a hostname such as `lms.example.com` to the tunnel, and run it with `--url http://localhost:8000`. Run it as a Windows service so it starts with the laptop.

## Before sharing a link

- The dashboard needs a login, but the link reaches the login page and, after login, the rover controls. Use a long random `API_ADMIN_PASSWORD`.
- The laptop must stay on and awake while the link is in use (Power settings: never sleep when plugged in).
