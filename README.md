# NVR Shield — Django Web-Based NVR Camera Surveillance System

A fully modular Django web application for managing and viewing live camera streams
from multiple Network Video Recorders (NVRs) via embedded iframe previews.

---

## Quick Start

### 1. Install dependencies

```bash
# Minimum (uses SQLite – no MySQL needed for dev)
pip install django requests beautifulsoup4 lxml

# For MySQL in production
pip install mysqlclient
```

### 2. Configure the database

**SQLite (default — works immediately, no setup):**
No changes needed. A `db.sqlite3` file is created automatically.

**MySQL (production):**
Edit `nvr_surveillance/settings.py` and uncomment the MySQL DATABASES block:

```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': 'nvr_surveillance',
        'USER': 'nvr_user',
        'PASSWORD': 'your_strong_password',
        'HOST': 'localhost',
        'PORT': '3306',
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
    }
}
```

Create the MySQL database first:
```sql
CREATE DATABASE nvr_surveillance CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'nvr_user'@'localhost' IDENTIFIED BY 'your_strong_password';
GRANT ALL PRIVILEGES ON nvr_surveillance.* TO 'nvr_user'@'localhost';
FLUSH PRIVILEGES;
```

### 3. Run database migrations

```bash
cd nvr_surveillance
python manage.py migrate
```

### 4. Start the development server

```bash
python manage.py runserver
```

Open: **http://127.0.0.1:8000**

---

## Login Credentials

| Field    | Value      |
|----------|-----------|
| Username | `admin`   |
| Password | `admin123` |

> Change these in `nvr_surveillance/settings.py`:
> `APP_ADMIN_USERNAME` and `APP_ADMIN_PASSWORD`

---

## Project Structure

```
nvr_surveillance/
│
├── manage.py
├── requirements.txt
├── README.md
│
├── nvr_surveillance/          ← Django project config
│   ├── __init__.py
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
│
├── core/                      ← Main app
│   ├── __init__.py
│   ├── apps.py
│   ├── models.py              ← NVR + Camera DB models
│   ├── views.py               ← All views + AJAX endpoints
│   ├── urls.py                ← URL routing
│   ├── admin.py               ← Django admin config
│   │
│   ├── adapters/              ← NVR brand adapters
│   │   ├── __init__.py
│   │   ├── base_adapter.py    ← Abstract base class
│   │   ├── hikvision_adapter.py
│   │   ├── cpplus_adapter.py
│   │   ├── dahua_adapter.py
│   │   └── generic_adapter.py
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   └── nvr_service.py     ← Business logic orchestration
│   │
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── url_parser.py      ← URL parsing, brand detection
│   │   └── helpers.py         ← HTTP session helpers
│   │
│   ├── migrations/
│   │   ├── __init__.py
│   │   └── 0001_initial.py    ← Auto migration
│   │
│   └── templatetags/
│       ├── __init__.py
│       └── nvr_tags.py        ← Custom Django template tags
│
├── templates/
│   ├── base.html              ← Base template
│   ├── login.html             ← Login page
│   ├── dashboard.html         ← Main surveillance UI
│   ├── 404.html
│   └── 500.html
│
└── static/
    ├── css/
    │   ├── base.css           ← Global CSS variables & utilities
    │   ├── login.css          ← Login page styles
    │   └── dashboard.css      ← Dashboard layout styles
    └── js/
        ├── utils.js           ← Shared JS utilities (CSRF, toast, AJAX)
        └── dashboard.js       ← Full dashboard interactivity
```

---

## Database Schema

### `nvr` table
| Column         | Type         | Notes                          |
|----------------|--------------|-------------------------------|
| id             | BigInt PK    |                                |
| location       | VARCHAR(255) | Human label, e.g. "Building A"|
| url            | VARCHAR(500) | Base URL, e.g. http://1.2.3.4 |
| port           | INT NULL     | Optional separate port         |
| username       | VARCHAR(150) |                                |
| password       | VARCHAR(255) |                                |
| brand          | VARCHAR(50)  | hikvision/cpplus/dahua/generic |
| status         | VARCHAR(20)  | connected/disconnected/error   |
| is_connected   | BOOL         |                                |
| last_connected | DATETIME     |                                |
| error_message  | TEXT         |                                |
| created_at     | DATETIME     |                                |
| updated_at     | DATETIME     |                                |
| notes          | TEXT         |                                |

### `camera` table
| Column       | Type         | Notes                       |
|--------------|--------------|-----------------------------|
| id           | BigInt PK    |                             |
| nvr_id       | FK → nvr     |                             |
| name         | VARCHAR(255) | Channel name                |
| camera_id    | VARCHAR(100) | Channel ID from NVR         |
| preview_path | VARCHAR(500) | Relative path or full URL   |
| channel      | INT NULL     | Channel number              |
| is_active    | BOOL         |                             |
| created_at   | DATETIME     |                             |
| updated_at   | DATETIME     |                             |

---

## API Endpoints

| Method | URL                        | Description                    |
|--------|----------------------------|-------------------------------|
| GET    | `/`  `/login/`             | Login page                    |
| POST   | `/login/`                  | Authenticate                  |
| GET    | `/logout/`                 | Clear session                 |
| GET    | `/dashboard/`              | Main surveillance dashboard   |
| POST   | `/nvr/connect/`            | Test connect + detect cameras |
| POST   | `/nvr/save/`               | Save NVR + cameras to DB      |
| DELETE | `/nvr/delete/<id>/`        | Delete NVR + all its cameras  |
| DELETE | `/camera/delete/<id>/`     | Delete single camera          |
| GET    | `/api/nvrs/`               | List all NVRs + cameras (JSON)|
| GET    | `/api/cameras/<nvr_id>/`   | List cameras for one NVR      |

---

## NVR Brand Detection

| Brand     | Detection Signals                                        |
|-----------|----------------------------------------------------------|
| Hikvision | `/doc/page/preview.asp`, `/doc/page/login.asp`, `/ISAPI/`|
| CP Plus   | `#/index/preview`, port `20443`, `cpplus` in URL        |
| Dahua     | `/RPC2`, `/cgi-bin/configManager.cgi`, `dahua` in URL   |
| Generic   | `/cgi-bin/main-cgi`, or fallback for unknown brands     |

---

## Feature Summary

### Dashboard
- **NVR Sidebar Tree** — Collapsible NVR → Camera hierarchy with brand badges
- **Status indicators** — Live connected/disconnected dot per NVR
- **Camera Grid** — 2×2 / 3×3 / 4×4 / 6×6 / 8×8 / Custom layout
- **Drag & Drop** — Drag camera row to any grid cell to start iframe stream
- **Double Click** — Auto-place in first empty cell
- **Multi-select** — Select multiple cameras → "Add Selected to Grid"
- **Remove streams** — ✕ button on each active cell
- **Delete NVR/Camera** — Removes from sidebar and database instantly
- **Live stats bar** — NVR count, camera count, active streams
- **Real-time clock**

### Add NVR Flow
1. Enter **Location**, **URL/IP**, optional **Port**, **Username**, **Password**
2. Click **Connect** → detects brand, logs in, scrapes cameras
3. Preview list of discovered cameras appears
4. Click **Save** → persists to database, adds to sidebar

### Streaming
- No RTSP. Each grid cell is an `<iframe>` pointing to the NVR's own web preview page
- Works with Hikvision `/doc/page/preview.asp`, CP Plus SPA, Dahua web UI, and generic CGI UIs

---

## Production Notes

- Set `DEBUG = False` in `settings.py`
- Set a strong `SECRET_KEY`
- Use HTTPS (NVR passwords transmitted in browser)
- Switch `DATABASES` to MySQL
- Run `python manage.py collectstatic` for static files
- Deploy with Gunicorn + Nginx
