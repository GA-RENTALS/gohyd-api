# GoHyderabad backend

The Django API behind the GoHyderabad website, customer area and staff admin panel.

**Stack:** Python 3.12 · Django 6 · Django REST Framework · PostgreSQL (row-level security) · Redis · Celery · JWT · S3 (django-storages) · Razorpay · Meta WhatsApp Cloud API.

> Read next: [GOHYDERABAD.md](../GOHYDERABAD.md) (architecture and requirements coverage) and [FIXES.md](../FIXES.md) (what is left to do, by priority). Latest audit: [BUGS.md](../BUGS.md), [GAPS.md](../GAPS.md), [ADMIN_ENHANCEMENTS.md](../ADMIN_ENHANCEMENTS.md). The web app lives in the sibling project `gohyd-ui/`.

## Contents

1. [Open the Django site](#1-open-the-django-site)
2. [Quick start](#2-quick-start)
3. [Configuration](#3-configuration)
4. [How it is organised](#4-how-it-is-organised)
5. [Multi-tenancy (important)](#5-multi-tenancy-important)
6. [Sign-in and sessions](#6-sign-in-and-sessions)
7. [API reference](#7-api-reference)
8. [Staff admin API and permissions](#8-staff-admin-api-and-permissions)
9. [Bookings, payments and money rules](#9-bookings-payments-and-money-rules)
10. [Background jobs and notifications](#10-background-jobs-and-notifications)
11. [WhatsApp setup](#11-whatsapp-setup)
12. [Razorpay setup](#12-razorpay-setup)
13. [File storage (S3)](#13-file-storage-s3)
14. [Management commands](#14-management-commands)
15. [Tests](#15-tests)
16. [Troubleshooting](#16-troubleshooting)
17. [Going to production](#17-going-to-production)

---

## 1. Open the Django site

With the server running (`python manage.py runserver`), open:

| What | Address | Notes |
|---|---|---|
| **Backend home (links to everything)** | <http://127.0.0.1:8000/> | A small page that links to the items below. |
| **Staff admin panel** (new) | <http://localhost:3000/admin> | The Next.js admin. `/admin/` on the backend forwards here. Set `ADMIN_PANEL_URL` to change it. |
| **Django admin** (classic) | <http://127.0.0.1:8000/admin/?classic=1> | Curated, grouped staff navigation with an all-models index. Sign in with phone number (always `+91…`) and password. |
| **API documentation** | <http://127.0.0.1:8000/api/docs/> | Interactive Swagger UI. |
| **API schema** | <http://127.0.0.1:8000/api/schema/> | Machine-readable OpenAPI. |
| **Public API example** | <http://127.0.0.1:8000/api/v1/trips/> | Published trips as JSON. |

Use `127.0.0.1` (not `localhost`) for the backend in development. The dev server listens on IPv4 only and browsers may try IPv6 first.

To sign in to the Django admin you need a superuser: `python manage.py createsuperuser` (phone number like `+919876543210`, then a password).

---

## 2. Quick start

```
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env             # then fill it in (section 3)
python manage.py migrate
python manage.py seed_platform      # roles, settings, KPI and event definitions, notification templates
python manage.py createsuperuser    # phone like +919876543210
python manage.py runserver          # http://127.0.0.1:8000
```

You also need **PostgreSQL** and **Redis** running. In a second and third terminal (needed for real WhatsApp delivery in production, optional in development, see section 10):

```
celery -A config worker -l info -P solo     # sends codes and messages, runs payment and refund jobs
celery -A config beat -l info               # outbox relay every 5 s; balance and trip reminders hourly
```

Optional demo content:

```
python manage.py import_frontend_content    # website trips, categories, destination details (as drafts)
python manage.py seed_demo_data             # development only: one demo booking and a "Demo" row in every table
```

Local PostgreSQL older than 15 needs `POSTGRES_ALLOW_OLD=True` in `.env` (development only; Django 6.1 needs PostgreSQL 15+).

---

## 3. Configuration

All settings come from environment variables, read from `.env` (never commit it; it is ignored by git). `.env.example` lists the names.

| Group | Variable | Meaning |
|---|---|---|
| Django | `DEBUG` | `True` in development only. Turns on friendly errors and the development sign-in behaviour. |
| | `SECRET_KEY` | Required when `DEBUG` is off. |
| | `ALLOWED_HOSTS` | Comma-separated host names. |
| Database | `POSTGRES_URL` | `postgres://user:password@host:5432/dbname`. Use a role that is **not** a superuser (section 5). |
| | `POSTGRES_ALLOW_OLD` | Development only, for PostgreSQL older than 15. |
| Redis | `REDIS_URL` | Cache and login lockouts. |
| | `CELERY_BROKER_URL` | Job queue. |
| Web | `CORS_ALLOWED_ORIGINS` | Websites allowed to call the API, e.g. `http://localhost:3000,http://localhost:3001`. |
| | `CSRF_TRUSTED_ORIGINS` | Needed for the Django admin behind HTTPS. |
| | `FRONTEND_ORIGIN` | The public website address (used in the API docs). |
| | `ADMIN_PANEL_URL` | Where `/admin/` forwards (default `http://localhost:3000/admin`). |
| WhatsApp | `WHATSAPP_API_URL` | `https://graph.facebook.com/v21.0/<PHONE_NUMBER_ID>/messages` |
| | `WHATSAPP_ACCESS_TOKEN` | Permanent system-user token. |
| | `WHATSAPP_TEMPLATE_NAME` | Approved sign-in template name. |
| | `WHATSAPP_TEMPLATE_LANGUAGE` | How the template was registered with Meta (`en`, `en_US`…). |
| | `WHATSAPP_APP_SECRET` | Adds Meta's `appsecret_proof` to each call. |
| Payments | `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Razorpay credentials. |
| Files | `AWS_STORAGE_BUCKET_NAME` | Empty = store files on this machine (development only). |
| | `AWS_S3_REGION_NAME`, `AWS_S3_CUSTOM_DOMAIN` | Region (default `ap-south-1`); optional CDN domain. |
| | `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | Leave empty on AWS when an instance role is attached. |
| | `MAX_FILE_UPLOAD_SIZE` | Bytes (default 5 MB). |
| Sign-in | `OTP_TTL_SECONDS` (300), `OTP_RESEND_SECONDS` (45), `OTP_MAX_ATTEMPTS` (5) | One-time code rules. |
| Business | `DEFAULT_ADVANCE_BASIS_POINTS` (3000), `DEFAULT_BALANCE_DUE_DAYS_BEFORE` (7) | First-run values only. Real values are set in the admin. |
| Security | `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`, `COOKIES_SECURE` | Cookies and HSTS turn on automatically when `DEBUG` is off; set the redirect explicitly. |
| Limits | `API_ANON_RATE` (60/minute), `API_USER_RATE` (300/minute) | General rate limits. |

---

## 4. How it is organised

```
backend/
├── manage.py
├── requirements.txt
├── .env / .env.example
├── config/            settings.py, urls.py, celery.py
├── core/              money rules, settings table, audit / data-access / security logs, outbox, test helpers, landing page
├── tenancy/           tenants, domains, memberships, row-level security, JWT + host resolution
├── accounts/          users, WhatsApp one-time codes, staff password login, roles
├── content/           destinations, CMS pages, blogs, FAQs, media, testimonials, 3-language approval
├── trips/             trips, schedules, pricing, pickup points, policies, categories, events
├── bookings/          cart, checkout, bookings, participants, seats, cancellation
├── payments/          Razorpay, payments and allocations, webhooks, refunds, GST, invoices, finance
├── operations/        vendors, vehicles, drivers, safety waivers, incidents
├── crm/               enquiries, support, corporate quotes, campaigns, coupons, memberships, loyalty, reviews
├── tracking/          consent-gated visitor tracking, attribution, summaries, KPIs
├── notifications/     templates, jobs, delivery logs, integrations, health
└── admin_api/         the staff API behind the admin panel
```

| App | Tables | Main responsibilities |
|---|---|---|
| `core` | 6 | Settings, audit trail, outbox events, privacy requests |
| `tenancy` | 3 | Which operator a request belongs to; keeps operators' data apart |
| `accounts` | 7 | People, sign-in, roles and teams |
| `content` | 25 | Everything editors manage; publish rules |
| `trips` | 25 | What can be booked and when |
| `bookings` | 13 | Customers' bookings, with capacity checks |
| `payments` | 22 | Money in and out, tax, invoices |
| `operations` | 21 | Running the trips |
| `crm` | 31 | Customers, marketing, memberships |
| `tracking` | 22 | Understanding visitors |
| `notifications` | 14 | Messages to customers |

The rule of thumb: **business rules live in `services.py` files** (for example `bookings/services.py`, `payments/services.py`). Views stay thin, and the staff admin API calls the same services as the customer API, so there is one implementation of each rule.

---

## 5. Multi-tenancy (important)

- Every request belongs to a **tenant** (an operator). It is found from the request's **host name**, using the `tenant_domains` table. The first migration creates the tenant `gohyderabad` with the hosts `localhost`, `127.0.0.1`, `::1` and `testserver`.
- A request to a host that is not a verified domain gets **404** on `/api/v1/…`. For a new environment, add the host in the Django admin (Tenancy → Tenant domains, verified).
- Every business table has a tenant column. **PostgreSQL row-level security** hides other tenants' rows, and the code also refuses to save a row that points at another tenant.
- Code that runs outside a request (commands, tasks, shell) must wrap work in `tenant_scope(tenant_id)` from `tenancy.context`.
- **Use a database user that is not a superuser.** A superuser bypasses row-level security, so isolation is silently off. A Django system check enforces this whenever `DEBUG` is off; in development it is skipped.

```
-- as an administrator, once
CREATE ROLE gohyd_app LOGIN PASSWORD '…' NOSUPERUSER NOBYPASSRLS;
-- give it the schema's privileges (migrations are run by the owner role), then point POSTGRES_URL at gohyd_app
```

---

## 6. Sign-in and sessions

| Who | How |
|---|---|
| Customers | Phone number → 6-digit code on WhatsApp → tokens. New customers then give their name. |
| Staff | Same code flow, **or** phone number + password (`/auth/password-login/`). |

- Codes are hashed, expire after 5 minutes, allow 5 attempts, and can be resent after 45 seconds. Per-number and per-address limits apply (10 code requests/hour, 30 verifications/hour).
- Password sign-in is for staff only, gives one generic error for every failure, locks a number for 15 minutes after 5 wrong tries, and is limited to 20 attempts/hour per address.
- Access tokens last **15 minutes**; refresh tokens last **7 days** and are rotated and blacklisted after use. Tokens carry the tenant.
- Send `Authorization: Bearer <access token>` on protected calls.
- Phone numbers are always stored as `+91XXXXXXXXXX` (the API accepts `98765 43210`, `09876543210`, `+91…`).

---

## 7. API reference

Base: `/api/v1/`. Full interactive documentation: `/api/docs/`.

### Authentication

| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `auth/request-otp/` | anyone | Send a code to WhatsApp. Body: `{"phone_number": "98765 43210"}` |
| POST | `auth/verify-otp/` | anyone | Check the code, return `access` and `refresh`. Body: `{"phone_number", "otp"}` |
| POST | `auth/password-login/` | staff | Phone + password. |
| POST | `auth/refresh/` | anyone with a refresh token | New access token. |
| POST | `auth/logout/` | anyone with a refresh token | Revoke the refresh token. |
| GET, PATCH | `me/` | signed in | Profile (`full_name`, `email`, `preferred_language`). |

### Public content

| Path | Returns |
|---|---|
| `trips/`, `trips/<slug>/` | Published trips; detail has schedules with seats left, pickup points, inclusions, refund tiers. Add `?lang=en|te|hi`. |
| `events/`, `events/<slug>/` | Published events; detail has venue, schedules, itinerary, things to bring, inclusions and exclusions. Add `?lang=en|te|hi`. |
| `categories/` | Trip categories. |
| `destinations/`, `blogs/`, `pages/`, `faqs/`, `testimonials/` | Published content. |

`POST enquiries/` accepts event booking requests from the public website and saves them in CRM. It stores the Event and selected date or preferred date, group size, contact details, and consent. This is a follow-up request, not a seat reservation or payment.

### Booking (signed-in customer)

| Method | Path | Purpose |
|---|---|---|
| GET, POST, DELETE | `cart/` | The cart (several trips). |
| POST | `checkouts/` | Create a checkout: `{"items": [{"schedule", "participant_count", "pickup_point"}]}`. Send an `Idempotency-Key` header. All-or-nothing; a repeated key returns the same checkout. |
| GET | `checkouts/`, `checkouts/<id>/` | The customer's checkouts with their bookings. |
| POST | `checkouts/<id>/pay/` | Create a Razorpay order for `ADVANCE`, `BALANCE` or `FULL`. |
| POST | `checkouts/<id>/confirm/` | Verify the Razorpay signature after payment. |
| GET | `bookings/`, `bookings/<id>/` | The customer's bookings. |
| PUT | `bookings/<id>/participants/` | Replace the people on the booking. |
| POST | `bookings/<id>/accept-waiver/` | Record waiver acceptance. |
| POST | `bookings/<id>/cancel/` | Cancel one booking. |

### Public intake and webhooks

| Path | Purpose |
|---|---|
| `enquiries/`, `corporate-enquiries/` | Contact forms. |
| `track/`, `track/consent/` | Visitor events and consent (privacy-gated). |
| `/webhooks/razorpay/` (not under `/api/v1/`) | Razorpay events, signature verified, duplicates ignored. |

### Errors

Errors return JSON: `{"detail": "…"}` or `{"message": "…"}` or `{"field": ["…"]}`. Typical codes: `400` invalid, `401` not signed in, `403` not allowed, `404` not found, `409` a checkout cannot be fulfilled, `413` file too large, `429` rate limited, `502` payment or storage service failed.

---

## 8. Staff admin API and permissions

Used by the admin panel. All paths are under `admin/` and require a staff user with an active operator membership.

| Method | Path | Purpose |
|---|---|---|
| GET | `admin/session/` | Who is signed in and their permissions. |
| GET | `admin/modules/` | The menu: modules and tables this user may see, with allowed actions. |
| GET | `admin/dashboard/` | Figures, charts, recent bookings, upcoming open trip dates, and the "finish setting up" list. |
| GET | `admin/resources/<table>/schema/` | Describes the fields of a table (types, choices, linked records, upload limits). |
| GET, POST | `admin/resources/<table>/` | List (`?search=`, `?ordering=`, `?page=`) and create. Accepts JSON or multipart (files). Trips can be created by staff with the `trips.add_trip` permission. |
| GET, PATCH, PUT, DELETE | `admin/resources/<table>/<id>/` | Read, edit, delete. |
| POST | `admin/actions/<action>/` | Sensitive actions: `verify-payment`, `approve-refund`, `record-manual-payment`, `departure-exception`, `content-transition`, `participant-check-in`. |

**171 tables in 20 modules** are exposed. The list is the allow-list in `admin_api/registry.py`: each entry sets the table's mode (full, read, create, update), searchable and sortable fields, hidden fields, and whether it holds personal data. To expose a new table, add it there.

Rules enforced on every call: Django model permission for the action; writes only where the mode allows; sensitive fields hidden; every create, update and delete written to the audit log; personal-data reads written to the access log; uploads limited by type and size and, for images, actually decoded.

**Roles** (seeded by `seed_platform`): Super Admin, Admin, Content Manager, Content Writer, Trip Manager, Trip Organizer, Booking Manager, Finance Manager, Customer Support, Marketing Manager, Operations Manager, Analytics Viewer. Add a user to a Django group to give a role.

**Adding a staff member:** create the user in the Django admin with *Staff* on, add them to a group, and add an operator membership with role *Staff* for the `gohyderabad` tenant. Use the `+91…` number format.

---

## 9. Bookings, payments and money rules

- **Advance %** and **balance due days** are set globally (Admin → System → Settings) and can be overridden per trip and per departure. All amounts are calculated on the server with consistent rounding.
- **Capacity** is checked inside a locked transaction for every trip in a checkout; if any trip cannot be fulfilled, nothing is created.
- Each booking keeps its own **price, tax and refund-policy snapshot**, so later setting changes never alter past bookings or invoices.
- **GST** is configurable (enabled or not, inclusive or exclusive, rate components). Final treatment must be approved by the business and its tax adviser.
- **Payments:** the server creates the Razorpay order; the browser pays; the server verifies the signature; the webhook confirms independently and duplicates are ignored. Successful payments are never overwritten, and refunds are separate records.
- **Manual payments** are recorded by one staff member and must be verified by a **different** one.
- **Departure clearance:** a participant cannot be cleared with an unpaid balance unless an authorised exception is recorded (audited).
- **Booking statuses:** Awaiting advance → Confirmed (balance due) → Fully paid → Completed; or Cancelled / No show.

---

## 10. Background jobs and notifications

- **Celery** (worker + beat) with Redis. Important events (booking created, payment succeeded, refund approved) go through a **transactional outbox**: they are saved in the same database transaction as the change, then relayed, so they cannot be lost.
- Beat schedule: outbox relay every 5 s; balance reminders and trip reminders hourly.
- **In development** (`DEBUG=True`) sign-in codes are sent immediately during the request, so no worker is needed. With no WhatsApp settings the code is printed in the server console; if Meta refuses the send, the code is printed too.
- **In production** codes and messages are queued, so **a worker must be running**.
- Messages: 13 events × 4 channels have template rows. WhatsApp is delivered through approved templates (section 11). A message is skipped, with the reason recorded (Admin → Notifications → Failures), when no template name is set or WhatsApp is not configured. Failed sends retry with backoff, then are marked failed. Email and SMS providers are not connected.

---

## 11. WhatsApp setup

1. In Meta Business, create the Cloud API app and a permanent system-user token with `whatsapp_business_messaging` and `whatsapp_business_management`.
2. Set `WHATSAPP_API_URL` (the number's `…/messages` address), `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_APP_SECRET`.
3. **Sign-in template:** an *authentication* template with a copy-code button. Set `WHATSAPP_TEMPLATE_NAME` and `WHATSAPP_TEMPLATE_LANGUAGE` exactly as registered.
4. **Other messages:** create and approve a template for each event below, then enter its approved name in Admin → Notifications → Templates ("Provider template name"). Variables **must** follow this order; Meta rejects a different count.

| Message | `{{1}}` | `{{2}}` | `{{3}}` | `{{4}}` |
|---|---|---|---|---|
| booking_confirmation | name | booking reference | trip name | trip date |
| cancellation | name | booking reference | trip name | |
| balance_reminder | name | booking reference | amount due | due date |
| trip_reminder | name | trip name | trip date | |
| payment_receipt | name | amount | | |

The order is defined in `notifications/services.py` (`TEMPLATE_PARAMS`). Missing values are sent as `-` (WhatsApp rejects empty variables).

---

## 12. Razorpay setup

1. Set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET` (test keys first).
2. In the Razorpay dashboard add the webhook `https://<api host>/webhooks/razorpay/` and set its secret as `RAZORPAY_WEBHOOK_SECRET`. Subscribe to payment and refund events.
3. Run one full test booking and one test refund before switching to live keys.

Without keys, the customer's "Pay" button reports that online payment is unavailable, and staff can still record and verify manual payments.

---

## 13. File storage (S3)

- `AWS_STORAGE_BUCKET_NAME` empty: files are stored in `media/` on the server (development only).
- Set: files go to S3 through `django-storages`. On AWS, attach an instance role and leave the access keys empty. Locally you need keys, otherwise an upload returns a clear "file storage is not reachable" message.
- After switching on S3, copy existing local files up: `python manage.py upload_local_media`.
- Allowed uploads: images, PDF, CSV, TXT, Word, Excel, MP4; up to `MAX_FILE_UPLOAD_SIZE` (5 MB default). Images are decoded to prove they are real images.

---

## 14. Management commands

| Command | Purpose |
|---|---|
| `seed_platform` | First-run roles, settings, KPI and event definitions, notification templates. Safe to repeat. |
| `import_frontend_content` | Load the website's trips, categories, destination details, testimonials and site figures. Idempotent; imported content always remains draft until the admin approval workflow publishes it. `--dry-run`. |
| `seed_demo_data` | **Development only.** One demo booking and a "Demo" row in every empty admin table. `--dry-run`. |
| `upload_local_media` | Copy local files to S3. `--dry-run`. |

---

## 15. Tests

**56 tests, all passing.** They must run with a database user that is **not** a superuser (a check fails otherwise, because `DEBUG` is off in tests).

```
# once, as an administrator
CREATE ROLE gohyd_test LOGIN PASSWORD 'testpw' NOSUPERUSER NOBYPASSRLS CREATEDB;

POSTGRES_URL='postgres://gohyd_test:testpw@localhost:5432/gohyderabad' python manage.py test --noinput
```

- Tests use a temporary `test_…` database and do not touch your data.
- Base classes and factories are in `core/testing.py`: `TenantTestCase` (runs each test as the default operator), `make_user`, `make_trip`, `make_gst`, `make_entity`. Tests that write tenant-owned rows must use them.
- Covered: money and tax, one-time codes (including the development send), WhatsApp message delivery and variable order, multi-trip checkout, capacity races, advance and balance payments, webhooks and duplicates, refunds, invoices and credit notes, publishing rules, enquiries, tracking, trip APIs.
- Not yet covered: finance access by an unauthorised admin, data deletion, failed-job retry end to end, database restore.

Other checks: `python manage.py check`, `python manage.py check --deploy`, `pip check`.

---

## 16. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `relation "tenant_domains" does not exist` | Migrations not applied: `python manage.py migrate`. |
| API returns 404 on `/api/v1/…` | The host is not a verified tenant domain (section 5). |
| Website says "Failed to fetch" | Backend not running, or the site's address is missing from `CORS_ALLOWED_ORIGINS`, or `localhost` was used instead of `127.0.0.1`. |
| Sign-in code never arrives | In production a Celery worker must run. Check the template name and language match Meta's. In development read the server console. |
| `Tenant context is required to write tenant-owned data` | Code ran outside a request: wrap it in `tenant_scope(tenant_id)`. |
| `tenancy.E004` when starting or testing | The database user is a superuser or bypasses row-level security (section 5). |
| Upload returns 502 "file storage is not reachable" | S3 bucket is set but there are no credentials here. Add keys, or clear `AWS_STORAGE_BUCKET_NAME` for local work. |
| Cannot sign in to the new panel with a staff account | The number must be `+91XXXXXXXXXX`, the user must have *Staff* on, and an active operator membership with role Staff or Tenant admin. |
| Port 8000 already in use | Another server is running: stop it or `runserver 8001`. |

---

## 17. Going to production

A short checklist (full list with priorities in [FIXES.md](../FIXES.md)):

- `DEBUG=False`, strong `SECRET_KEY`, real `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`.
- `SECURE_SSL_REDIRECT=True` (cookies and HSTS turn on automatically). Run `python manage.py check --deploy` until clean.
- A non-superuser database role; managed PostgreSQL and Redis; automated backups and a tested restore.
- Run Gunicorn for the API, plus one Celery worker and one Celery beat.
- Live Razorpay keys and webhook; WhatsApp token and approved templates; S3 with an instance role.
- Add the production host as a verified tenant domain.
- Do **not** run `seed_demo_data`; remove any demo rows first.
- Set the real business values: legal name, GSTIN, GST, advance %, balance days.
