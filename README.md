# Research Paper Assistant

A Django web application for building a searchable, AI-powered library of scientific research posters and papers. Upload a poster via the web, Telegram, or WhatsApp: the system extracts metadata, finds the published paper, searches for the code repository, and saves everything in a structured dashboard.

---

## Features

### Multi-Channel Upload
- **Web** -- drag-and-drop upload with progress bar, real-time AI analysis status, and multi-image batch upload
- **Telegram bot** -- send a photo or document to receive structured results
- **WhatsApp bot** -- same workflow, with interactive button prompts

### AI-Powered Extraction (GPT-4o Vision)
From a single poster image the system extracts:
- Title, authors, abstract, keywords, category, conference, year, institution
- Automatic classification into: ML, CV, NLP, Robotics, HCI, Data Science, Theory, Systems
- Non-research image detection -- rejects photos that do not contain scientific content

### Paper and Code Search Pipeline

| Step | Source | Purpose |
|------|--------|---------|
| 1 | Semantic Scholar API | Paper link, open-access PDF, arXiv ID, DOI, authors |
| 2 | Google Scholar (fallback) | Scraping-based search when Semantic Scholar is unavailable |
| 3 | Paper page / DOI scraping | Visits the paper page and follows DOI redirects to find the real PDF |
| 4 | arXiv API | Title-based search as last-resort PDF source |
| 5 | PDF annotation extraction | Reads clickable hyperlink annotations embedded in the PDF |
| 6 | PDF text extraction | Finds `github.com` links in extracted text |
| 7 | GitHub API | Multi-strategy repository search with word-overlap validation |

### Dashboard
- Full table view: title, authors, category, tags, paper link, GitHub link, summary, notes
- Poster thumbnail in a unified "Links & Poster" column
- Advanced search: filter by author, description, date range
- Column sorting: clickable headers for ID/date, title, category, status
- Filter by status (Pending / Approved / Rejected), category, subfields, favorites, GitHub availability
- Inline notes: add/edit personal notes directly in the table row
- Bulk actions: select multiple papers to approve, reject, star, unstar, or delete
- Pagination: configurable page size (10 / 25 / 50 / 100)
- Stat tiles with live counters (total, pending, approved, rejected, favorites)
- Activity log with clear-all option
- `NEW` badge on papers uploaded in the last 24 hours
- Export approved papers as CSV or JSON

### Upload Page
- Drag-and-drop single or multiple images at once
- Multi-image batch upload: each image becomes a separate analysis task
- Collapsible tips panel for best upload results
- Optional notes and tags (shared across batch uploads)
- Collapsible recent uploads section showing the last 3 uploads with status
- Upload progress bar with real-time feedback

### Analysis Status & Retry
- **Processing** -- AI analysis running in background via Celery
- **OK** -- analysis completed successfully
- **Failed** -- AI error; poster is kept in DB with the original image
  - Retry button re-queues the analysis task
  - Stop button cancels a running analysis
- **Duplicate** -- poster discarded (detected by image hash), existing record kept
- **No text** -- non-scientific image, poster discarded

### Responsive Design
- Table rows become stacked cards on mobile
- All columns remain accessible on small screens
- Bulk bar, pagination, and advanced filters adapt to mobile layout
- Dark mode support

### Bot Commands

| Platform | Commands |
|----------|----------|
| Telegram | `/start`, `/help`, `/dashboard`, `/search <keyword>`, send photo/document |
| WhatsApp | `start`, `help`, `dashboard`, `search <keyword>`, send photo/document |

Both bots support:
- Inline notes and tags via captions (e.g. `note: interesting  tag: deep learning, mri`)
- Year-filtered search (e.g. `/search transformer year:2024` or `/search segmentation year:2020-2024`)
- Upload tips and usage guidance via `/help`

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Django 6.x, Python 3.12, Gunicorn |
| Task Queue | Celery 5.4, Redis 7 |
| Database | MySQL 8.4 |
| AI | OpenAI GPT-4o (Vision) |
| Paper search | Semantic Scholar, Google Scholar, arXiv |
| Code search | GitHub API, pypdf, BeautifulSoup |
| Messaging | Telegram Bot API, WhatsApp Cloud API |
| Frontend | Django templates, Tailwind CSS (CDN), vanilla JS |
| Reverse Proxy | Apache HTTPD 2.4 |
| Containerization | Docker, Docker Compose |

---

## Architecture

```
                 +------------+
  Browser ------>|  Apache    |---- /media/ --> static files
  Telegram ----->|  (port 80) |---- /* ------> Gunicorn :8000
  WhatsApp ----->|            |                  |
                 +------------+                  |
                                                 v
                                          +------------+
                                          |  Django    |
                                          |  views.py  |
                                          +-----+------+
                                                | .delay()
                                     +----------+----------+
                                     v                     v
                              +------------+        +------------+
                              |   Celery   |        |   Celery   |
                              |   Worker   |        |   Beat     |
                              +------+-----+        +------------+
                                     |
                           +---------+---------+
                           v         v         v
                       +-------+ +-------+ +--------+
                       | MySQL | | Redis | | OpenAI |
                       +-------+ +-------+ +--------+
```

All media downloads from Telegram and WhatsApp are handled asynchronously via Celery to prevent webhook timeouts.

---

## Deployment

### Prerequisites
- Docker and Docker Compose
- OpenAI API key
- Telegram Bot token (from @BotFather)
- WhatsApp Cloud API credentials (Meta Business)
  - Use a **System User token** (permanent) -- temporary tokens expire every 24 hours

### 1. Clone the repository
```bash
git clone <your-repo-url>
cd PaperProject
```

### 2. Configure environment variables
Create a `.env` file in the project root:
```env
# Django
SECRET_KEY=your_django_secret_key
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com

# OpenAI
OPENAI_API_KEY=your_openai_api_key

# Telegram
BOT_TOKEN=your_telegram_bot_token
TELEGRAM_WEBHOOK_SECRET=your_random_secret

# WhatsApp (use System User token for permanent access)
WHATSAPP_TOKEN=your_whatsapp_permanent_token
WHATSAPP_PHONE_ID=your_whatsapp_phone_id
WHATSAPP_VERIFY_TOKEN=your_webhook_verify_token

# Semantic Scholar (optional, improves paper search)
SEMANTIC_SCHOLAR_API_KEY=your_key

# GitHub API (optional, higher rate limits)
GITHUB_TOKEN=your_github_token
```

### 3. Start all services
```bash
docker compose up --build -d
```

This starts six containers:

| Container | Role |
|-----------|------|
| `paperproject-db` | MySQL 8.4 database |
| `paperproject-redis` | Redis 7 (Celery broker + cache) |
| `paperproject-django` | Gunicorn (3 workers, 120s timeout) |
| `paperproject-apache` | Apache reverse proxy (port 80) |
| `paperproject-worker` | Celery worker (async tasks) |
| `paperproject-beat` | Celery beat (scheduled tasks, persistent schedule) |

### 4. Configure bot webhooks
Set webhook URLs in each platform's dashboard:

- **Telegram** -- `https://yourdomain.com/telegram-webhook/`
- **WhatsApp** -- `https://yourdomain.com/whatsapp-webhook/`

### 5. Create a superuser (optional)
```bash
docker compose exec django python manage.py createsuperuser
```

---

## Project Structure

```
PaperProject/
├── apache/
│   ├── Dockerfile
│   └── httpd.conf
├── bot_engine/
│   ├── models.py          # ResearchPoster, ActivityLog, Favorite
│   ├── views.py           # Web views + bot webhook handlers
│   ├── tasks.py           # Celery tasks (media download, AI analysis)
│   ├── utils_ai.py        # OpenAI integration, paper/code search
│   ├── prompts.py         # GPT-4o system prompts
│   ├── forms.py           # Upload and edit forms
│   ├── migrations/
│   ├── static/
│   │   ├── css/style.css
│   │   └── js/
│   └── templates/
│       ├── base.html
│       ├── dashboard.html
│       ├── upload.html
│       ├── poster_detail.html
│       ├── edit_poster.html
│       └── login.html
├── tesi_project/
│   ├── settings.py
│   ├── urls.py
│   ├── celery.py
│   └── wsgi.py
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── manage.py
└── .env
```

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET/POST | Upload page (supports multi-image upload) |
| `/dashboard/` | GET | Dashboard with filters and search |
| `/dashboard/live-status/` | GET | Live processing status (AJAX) |
| `/poster/<id>/` | GET | Paper detail page |
| `/edit/<id>/` | GET/POST | Edit paper metadata |
| `/login/` | GET/POST | Login page |
| `/task-status/<task_id>/` | GET | Celery task status (AJAX) |
| `/retry-analysis/<id>/` | POST | Retry failed AI analysis |
| `/stop-analysis/<id>/` | POST | Stop running AI analysis |
| `/update-status/<id>/` | POST | Update paper validation status |
| `/toggle-favorite/<id>/` | POST | Toggle favorite/star |
| `/update-notes/<id>/` | POST | Save inline notes |
| `/bulk-action/` | POST | Bulk actions on selected papers |
| `/api/tags-autocomplete/` | GET | Tag autocomplete suggestions |
| `/export/approved/csv/` | GET | Export approved papers (CSV) |
| `/export/approved/json/` | GET | Export approved papers (JSON) |
| `/telegram-webhook/` | POST | Telegram bot webhook |
| `/whatsapp-webhook/` | GET/POST | WhatsApp bot webhook |

---

## Monitoring

### View logs
```bash
docker compose logs -f django        # Web server
docker compose logs -f worker        # Celery tasks
docker compose logs -f beat          # Scheduled tasks
docker compose logs -f               # All services
```

### Check container health
```bash
docker compose ps
```

### Restart after code changes
```bash
docker compose up --build -d
```

---

## Notes

- Media files (poster images) are served directly by Apache via the `/app/media/` volume mount
- The AI pipeline handles non-research images, API errors, and network failures gracefully
- Failed analyses are kept in DB for retry -- only duplicates and non-scientific images are auto-deleted
- Bot media downloads run asynchronously in Celery to prevent webhook timeouts
- Redis is used both as the Celery broker and as a Django cache backend for bot state management
- Redis locks prevent duplicate processing of the same poster across workers
- Celery Beat schedule is persisted in a Docker volume to survive container restarts
- Error details are logged server-side only -- bot and web users receive generic error messages
