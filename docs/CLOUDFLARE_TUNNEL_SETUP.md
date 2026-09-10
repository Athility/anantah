# Cloudflare Tunnel Setup Guide for Anantah

This guide provides step-by-step instructions for running the **Anantah** backend locally on Windows PC (leveraging CPU-accelerated AI image refinement with `rembg/u2netp` + `OpenCV/CLAHE`) while securely serving API requests to the static frontend deployed on **Vercel**.

---

## 1. Architecture Overview

```
┌────────────────────────────────────────────────────────┐
│                   Vercel (Frontend)                    │
│   Vanilla HTML/CSS/JS Single-Page Application (SPA)    │
│   Deployed at https://anantah.vercel.app               │
└──────────────────────────┬─────────────────────────────┘
                           │ Direct HTTPS API calls
                           │ Authorization: Bearer <JWT>
                           ▼
┌────────────────────────────────────────────────────────┐
│                 Cloudflare Edge Network                │
│    Terminates SSL, provides DDoS and Bot Protection    │
│    URL: https://api.yourdomain.com (or trycloudflare)  │
└──────────────────────────┬─────────────────────────────┘
                           │ Encrypted Outbound QUIC Tunnel
                           │ (No router port-forwarding / CGNAT friendly)
                           ▼
┌────────────────────────────────────────────────────────┐
│                   Local Windows PC                     │
│  ┌──────────────────────────────────────────────────┐  │
│  │ cloudflared.exe tunnel                           │  │
│  │ Proxies https requests to http://127.0.0.1:8000  │  │
│  └───────────────────────┬──────────────────────────┘  │
│                          │ Local HTTP loopback         │
│                          ▼                             │
│  ┌──────────────────────────────────────────────────┐  │
│  │ Django REST Framework (Port 8000)                │  │
│  │ - Python 3.11/3.13                               │  │
│  │ - Rembg / u2netp (CPU ONNX Runtime)              │  │
│  │ - OpenCV CLAHE contrast & saturation correction  │  │
│  │ - Local Media serving (/media/)                  │  │
│  │ - MySQL / Aiven / SQLite                         │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

---

## 2. Prerequisites & Installation on Windows

### A. Install `cloudflared` CLI on Windows

Open **PowerShell** (as Administrator or regular user) and run:

```powershell
# Option 1: Via Windows Package Manager (Winget) - Recommended
winget install --id Cloudflare.cloudflared

# Option 2: Via Chocolatey (if installed)
choco install cloudflared

# Option 3: Via Scoop (if installed)
scoop install cloudflared
```

*Alternatively, download `cloudflared-windows-amd64.exe` directly from the [Cloudflare GitHub Releases](https://github.com/cloudflare/cloudflared/releases), rename it to `cloudflared.exe`, and place it in your `PATH` or project folder.*

Verify installation:
```powershell
cloudflared --version
```

---

## 3. Starting the Local Stack

You need two terminal windows running side-by-side on your Windows PC.

### Terminal 1: Start Django Backend

```powershell
# Navigate to project directory
cd c:\artisan-demo

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Run Django development / production server bound to localhost port 8000
python manage.py runserver 127.0.0.1:8000
```

### Terminal 2: Start Cloudflare Tunnel

#### Option A: Quick Ephemeral Tunnel (Fastest, No Domain Required)

If you want an instant HTTPS URL without owning a domain or logging into Cloudflare:

```powershell
cloudflared tunnel --url http://127.0.0.1:8000
```

Cloudflare will output a public URL similar to:
```
+--------------------------------------------------------------------------------------------+
|  Your quick Tunnel has been created! Visit it at (it may take some time to be reachable):  |
|  https://random-words-subdomain.trycloudflare.com                                          |
+--------------------------------------------------------------------------------------------+
```

*Copy this `https://...trycloudflare.com` URL. You can immediately test it with your frontend!*

---

#### Option B: Stable Custom Hostname (e.g. `https://api.yourdomain.com`)

For a permanent, production deployment with your own domain name (registered on or proxied by Cloudflare):

1. **Log in to Cloudflare**:
   ```powershell
   cloudflared tunnel login
   ```
   A browser window will open. Select your domain to authenticate.

2. **Create a Named Tunnel**:
   ```powershell
   cloudflared tunnel create anantah-api
   ```
   *This outputs a Tunnel ID (e.g. `12345678-abcd-1234-abcd-1234567890ab`) and creates a credentials JSON file in `C:\Users\<User>\.cloudflared\`.*

3. **Route DNS to your tunnel**:
   ```powershell
   cloudflared tunnel route dns anantah-api api.yourdomain.com
   ```

4. **Create a config file** `C:\Users\<User>\.cloudflared\config.yml`:
   ```yaml
   tunnel: anantah-api
   credentials-file: C:\Users\<User>\.cloudflared\12345678-abcd-1234-abcd-1234567890ab.json

   ingress:
     - hostname: api.yourdomain.com
       service: http://127.0.0.1:8000
     - service: http_status:404
   ```

5. **Run the Named Tunnel**:
   ```powershell
   cloudflared tunnel run anantah-api
   ```

6. *(Optional) Run Cloudflare Tunnel as a persistent Windows Service*:
   ```powershell
   cloudflared service install
   Start-Service cloudflared
   ```

---

## 4. Frontend Configuration for Vercel

The frontend Single-Page Application (SPA) is hosted on Vercel. All browser API requests go directly to your Cloudflare Tunnel public URL.

### Setting the Public Backend URL

There are three convenient methods to point the frontend to your backend:

#### Method 1: In `index.html` (Recommended for stable production deployments)
Open `index.html` and edit line 6:
```html
<meta name="backend-url" content="https://api.yourdomain.com">
```
Push to GitHub to trigger Vercel auto-deployment.

#### Method 2: In `config.js`
Open `config.js` and set:
```javascript
const DEFAULT_PRODUCTION_API_URL = 'https://api.yourdomain.com';
```

#### Method 3: Instant Browser Console Override (Zero-redeploy testing)
If you are testing an ephemeral quick tunnel (`https://*.trycloudflare.com`) on your live Vercel site without wanting to redeploy:
1. Open your Vercel site in Chrome / Edge (`https://anantah.vercel.app`).
2. Press `F12` to open DevTools, switch to **Console**, and run:
   ```javascript
   localStorage.setItem('custom_backend_url', 'https://your-temporary-subdomain.trycloudflare.com');
   location.reload();
   ```
   *The SPA will instantly switch all API requests and media URLs to your tunnel!*
3. To revert back to default:
   ```javascript
   localStorage.removeItem('custom_backend_url');
   location.reload();
   ```

---

## 5. Backend `.env` Configuration

Ensure your `.env` on Windows contains the following:

```ini
SECRET_KEY=your-secure-random-secret-key-at-least-50-characters
DEBUG=False

# Add your tunnel domains to ALLOWED_HOSTS (quick tunnel .trycloudflare.com is allowed by default)
ALLOWED_HOSTS=127.0.0.1,localhost,.trycloudflare.com,api.yourdomain.com

# Public API URL (ensures serializers generate correct media URLs)
PUBLIC_API_URL=https://api.yourdomain.com

# CORS: Allow your Vercel domain
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,https://anantah.vercel.app

# CSRF: Trusted Origins
CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000,https://anantah.vercel.app,https://api.yourdomain.com

# Enforce HTTPS redirect
SECURE_SSL_REDIRECT=True
```

---

## 6. Understanding ISP, CGNAT, & Hardware Considerations

### Why Cloudflare Tunnel Works Behind CGNAT / Firewalls
- **Outbound Only**: Traditional port forwarding requires your router to accept inbound connections and requires a public IPv4 address from your ISP. Most residential ISPs in India (Jio, Airtel, ACT, etc.) use **Carrier-Grade NAT (CGNAT)** where thousands of customers share a single public IP.
- Cloudflare Tunnel creates an **outbound encrypted connection** (using HTTP/2 or QUIC over UDP port 7844) from your PC to Cloudflare. Because the connection is outbound, **CGNAT, ISP firewalls, and home router NAT do not block it**.

### Remaining Limitations & Operational Best Practices

1. **PC Sleep / Hibernation**:
   - If your Windows PC goes into sleep or hibernation mode, the CPU shuts off and `cloudflared` + Django will disconnect. Visitors on Vercel will receive HTTP 502 Bad Gateway from Cloudflare.
   - **Fix**: In Windows **Power & battery** settings, set **"When plugged in, put my device to sleep after"** to **"Never"**.

2. **PC Reboots / Windows Updates**:
   - If Windows restarts for updates, the server won't restart automatically unless configured.
   - **Fix**: Install `cloudflared` as a Windows service (`cloudflared service install`) and run Django with a process manager like NSSM (`nssm install DjangoBackend`) or Task Scheduler.

3. **PC Offline / Internet Dropout**:
   - If your home Wi-Fi drops, the frontend on Vercel stays online, but API requests will fail.
   - The Anantah frontend has built-in connection monitoring (`customFetch` alerts the user with: *"Network connection lost. Please check your internet."*).

4. **Ephemeral Tunnel URLs Expire**:
   - If you use `cloudflared tunnel --url http://127.0.0.1:8000` (Option A), stopping the process and restarting it will generate a *new* random URL.
   - For long-term availability, use **Option B (Named Tunnel)** with a custom domain.
