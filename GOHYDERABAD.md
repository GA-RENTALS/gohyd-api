# GOHYDERABAD

**Software Requirements, Architecture and Implementation Report**

| | |
|---|---|
| **Version** | 2.0 |
| **Date** | 7 November 2026 |
| **Supersedes** | Version 1.0 (6 November 2026) |
| **Status** | Core platform built and tested; launch blockers listed in [FIXES.md](FIXES.md) |
| **Project** | GoHyderabad: travel, experiences, events and community platform |

Version 1.0 proposed three Next.js applications with Prisma and BullMQ. During implementation the team chose a different, simpler stack: a Django API with a Next.js website and admin. This version describes **what is actually built**, how it works, how it differs from version 1.0, and what remains.

---

## Table of contents

1. [Project overview](#1-project-overview)
2. [Architecture](#2-architecture)
3. [Business rules and where they are enforced](#3-business-rules-and-where-they-are-enforced)
4. [Authentication and accounts](#4-authentication-and-accounts)
5. [Payments and finance](#5-payments-and-finance)
6. [Public website](#6-public-website)
7. [Customer area](#7-customer-area)
8. [Admin panel](#8-admin-panel)
9. [Multilingual content and approval](#9-multilingual-content-and-approval)
10. [Visitor tracking and business intelligence](#10-visitor-tracking-and-business-intelligence)
11. [Background processing and notifications](#11-background-processing-and-notifications)
12. [Data model](#12-data-model)
13. [Security and privacy](#13-security-and-privacy)
14. [Quality and testing](#14-quality-and-testing)
15. [Coverage of the launch acceptance criteria](#15-coverage-of-the-launch-acceptance-criteria)
16. [Development phases: status](#16-development-phases-status)
17. [Decisions that changed from version 1.0](#17-decisions-that-changed-from-version-10)
18. [Running the system](#18-running-the-system)
19. [Decisions needed from the business](#19-decisions-needed-from-the-business)

---

## 1. Project overview

GoHyderabad is a community-driven platform for weekend trips, local experiences, events and memberships around Hyderabad.

It brings together:

- Weekend trips and adventure experiences.
- Local sightseeing and hidden destinations.
- Sports, events and social meetups.
- Food, cafés, art and cultural experiences.
- Community memberships and corporate outings.

It is a business platform, not a brochure site. It covers customer acquisition, content management, bookings, payments, trip operations, customer relationships, marketing, visitor intelligence and reporting.

---

## 2. Architecture

### 2.1 Technology

| Layer | Version 1.0 proposal | Built in version 2.0 | Why it changed |
|---|---|---|---|
| Public website | Next.js | **Next.js 15 (App Router, React 19, TypeScript)** | Same. |
| Admin panel | Separate Next.js app | **Same Next.js app, under `/admin`** | One deployable instead of two; shares the API client and login code. It can be split out later. |
| Backend / API | Separate Next.js app | **Django 6 + Django REST Framework** | Mature admin tooling, permissions, migrations and ORM; faster to a safe financial core. |
| Language | TypeScript | TypeScript (frontend), Python 3.12 (backend) | Follows the backend choice. |
| Database | PostgreSQL | **PostgreSQL** with row-level security | Same, plus database-enforced tenant isolation. |
| ORM | Prisma | **Django ORM** + migrations | Follows the backend choice. |
| Authentication | WhatsApp OTP | **WhatsApp OTP** for customers; **OTP or password** for staff | Staff password login added. |
| OTP provider | Meta WhatsApp Cloud API | Meta WhatsApp Cloud API (called directly) | Same. |
| Payments | Razorpay | Razorpay (orders, signature checks, webhooks, refunds) | Same. |
| Analytics | PostHog + first-party | First-party tables built; PostHog forwarding not yet | PostHog pending. |
| Background jobs | BullMQ | **Celery + Redis** (with a transactional outbox) | Follows the backend choice. |
| Queue / cache | Redis | Redis (queue, cache, login lockouts) | Same. |
| Hosting | AWS (ECS, RDS, S3, CloudFront…) | S3 file storage wired in; other AWS services not yet provisioned | Infrastructure work remains. |
| Admin interface | Not specified | React components built on accessible primitives, styled with Tailwind CSS 4 | Consistent, themeable, accessible. |

### 2.2 Applications

```
                         ┌────────────────────────────────────────────┐
   Browser / phone  ───► │  Next.js application (one deployable)      │
                         │                                            │
                         │  Public website  /  /trips  /login         │
                         │                  /checkout  /account       │
                         │  Admin panel     /admin/…                  │
                         └───────────────┬────────────────────────────┘
                                         │ HTTPS + JSON (JWT)
                                         ▼
                         ┌────────────────────────────────────────────┐
                         │  Django REST API  (/api/v1/…)              │
                         │  accounts · trips · bookings · payments    │
                         │  content · crm · operations · tracking     │
                         │  notifications · core · tenancy · admin_api│
                         └───────┬──────────────┬─────────────┬───────┘
                                 │              │             │
                                 ▼              ▼             ▼
                          PostgreSQL         Redis         S3 (files)
                          (system of      (cache, queue,
                           record, RLS)    lockouts)
                                 ▲              │
                                 │              ▼
                         ┌───────┴──────────────────────┐
                         │ Celery worker + beat          │
                         │ outbox relay · reminders ·    │
                         │ notifications · payments      │
                         └───────┬───────────────────────┘
                                 ▼
                    Razorpay · Meta WhatsApp Cloud API
```

**Deployables:** the Next.js application, the Django API, one Celery worker and one Celery beat scheduler. The browser never talks to PostgreSQL.

**Two page "roots" inside one Next.js app.** The public website and the admin each have their own root layout, so the admin's styles can never leak into the public site (and the reverse).

### 2.3 Repository layout

```
goHyd/
├── GOHYDERABAD.md              this document
├── FIXES.md                    backend and frontend fixes, prioritised
├── backend/                    Django project
│   ├── config/                 settings, URLs, Celery
│   ├── core/                   money rules, audit/security logs, outbox, tests base classes
│   ├── tenancy/                tenant, domains, memberships, row-level security
│   ├── accounts/               users, WhatsApp OTP, password login, roles
│   ├── content/                destinations, CMS, blogs, FAQs, media, approval workflow
│   ├── trips/                  trips, schedules, pricing, pickups, policies
│   ├── bookings/               cart, checkout, bookings, participants, cancellation
│   ├── payments/               Razorpay, allocations, refunds, GST, invoices, finance
│   ├── operations/             vendors, vehicles, drivers, safety, incidents
│   ├── crm/                    enquiries, support, marketing, memberships, loyalty
│   ├── tracking/               consent-gated visitor tracking, summaries, KPIs
│   ├── notifications/          templates, jobs, delivery logs, integrations
│   └── admin_api/              staff API behind the admin panel
└── GoHyderabad/                Next.js application
    ├── app/(public)/           home page and booking pages (trips, login, checkout, account)
    ├── app/admin/              admin panel
    ├── components/site/        home page sections and data
    ├── components/booking/     booking pages
    ├── components/account/     customer account
    ├── components/admin/       admin screens
    ├── components/base/        shared UI components (forms, tables, dialogs…)
    ├── lib/                    API client, config, customer and admin API layers
    └── styles/                 design tokens for the admin
```

### 2.4 Multi-tenancy and data isolation

- Each operator is a **tenant**. The tenant is found from the request's host name (verified domains).
- Every business table carries a tenant, and PostgreSQL **row-level security** hides other tenants' rows.
- The application also checks tenant ownership on every save.
- The database user must **not** be a superuser and must not bypass row-level security, otherwise PostgreSQL ignores the isolation rules. A Django system check enforces this whenever `DEBUG` is off (production, tests); it is skipped in local development, where a superuser works but tenant isolation is not actually enforced. See [FIXES.md](FIXES.md).

### 2.5 Request paths

**Customer books a trip**

1. Visitor opens `/trips/<name>`; the page is rendered on the server from the public API.
2. Visitor chooses a date, people and a pickup point, then signs in with a WhatsApp code.
3. The API creates a **checkout** with one **booking** per trip, checks capacity inside a database transaction, and stores a price and tax snapshot.
4. The customer adds participants and accepts the waiver.
5. The API creates a Razorpay order; the browser pays; the API verifies the signature. The Razorpay webhook independently confirms the payment.
6. Payment allocations mark the advance as paid; the booking becomes *Confirmed (balance due)*. A reminder is queued for the balance.

**Staff manage records:** the admin panel calls `/api/v1/admin/…`. The API checks Django permissions on every request, validates the data, writes an audit log entry, and routes sensitive actions (payment verification, refund approval, departure exceptions) through the same service functions the customer flow uses.

### 2.6 Configuration

| Setting | Purpose |
|---|---|
| `POSTGRES_URL` | Database connection (use a limited role). |
| `SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS` | Django basics. |
| `REDIS_URL`, `CELERY_BROKER_URL` | Cache, queue, lockouts. |
| `CORS_ALLOWED_ORIGINS`, `FRONTEND_ORIGIN` | Which websites may call the API. |
| `WHATSAPP_API_URL`, `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_TEMPLATE_NAME`, `WHATSAPP_APP_SECRET` | Meta WhatsApp Cloud API. |
| `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET` | Payments. |
| `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`, `AWS_S3_CUSTOM_DOMAIN`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` | File storage. Leave the bucket empty to store files on the server (development only). |
| `MAX_FILE_UPLOAD_SIZE` | Upload size limit (default 5 MB). |
| `DEFAULT_ADVANCE_BASIS_POINTS`, `DEFAULT_BALANCE_DUE_DAYS_BEFORE` | First-run defaults for advance and balance rules. |
| `NEXT_PUBLIC_BACKEND_URL` (frontend) | Where the Django API lives. Use `127.0.0.1`, not `localhost`, in development. |

### 2.7 Infrastructure target

| Item | State |
|---|---|
| File storage on S3 | Wired in and tested with local disk; needs credentials or an instance role. |
| Application hosting (containers), load balancer, CDN, web firewall | Not provisioned. |
| Managed PostgreSQL and Redis | Not provisioned (local services in development). |
| Secrets manager, monitoring, alerts | Not set up. |
| Separate development, staging and production environments | Not set up; only local development exists. |
| Continuous integration and deployment | None yet. |

---

## 3. Business rules and where they are enforced

| Rule | How it works | Where |
|---|---|---|
| **Percentage-based advance** | A global default can be overridden per trip and per departure date. The advance and balance are calculated on the server and stored separately. | `bookings/services.py`, `core` money helpers |
| **Balance before the trip** | The due date is "N days before departure", set globally and overridable per trip. Reminders are scheduled hourly. | `bookings/services.py`, `notifications/tasks.py` |
| **Departure clearance** | A participant cannot be cleared with an unpaid balance unless an authorised exception is recorded and audited. | `bookings/services.py` |
| **Multiple trips in one checkout** | One checkout holds one booking per trip. Capacity is checked for every trip first; if any fails, nothing is created. | `bookings/services.py` |
| **No double-booking** | Seats are counted inside a locked transaction. A concurrency test confirms two customers cannot take the last seats. | `bookings/tests.py` |
| **Primary booker only has an account** | Participants are stored separately and never become accounts. | `bookings` models |
| **Independent cancellation and refunds** | Each booking cancels on its own; refunds are separate transactions. | `bookings`, `payments` |
| **Configurable GST** | Enabled or disabled, inclusive or exclusive, with rate components. A snapshot is saved against each booking and invoice. | `payments` models and services |
| **Money is never trusted from the browser** | Orders are created by the server; signatures and webhooks are verified; replays are ignored. | `payments/services.py` |
| **Publishing needs all three languages approved** | English, Telugu and Hindi must be approved before content can be published. | `content/models.py` |
| **Operational availability is separate from publishing** | A trip's "open / sold out / cancelled" status does not depend on the editorial workflow. | `trips/models.py` |

---

## 4. Authentication and accounts

| Topic | Behaviour |
|---|---|
| Customer sign-in | Mobile number → 6-digit code sent on WhatsApp → session. New customers give a name. |
| Code safety | Codes are hashed, expire, have attempt limits, resend delay, and per-number and per-address rate limits. Codes are never logged in production. |
| Staff sign-in | Same code flow, or phone number and password. Password sign-in locks a number for 15 minutes after 5 wrong tries and answers every failure with the same message. Only staff accounts can use it. |
| Sessions | Signed access and refresh tokens that carry the tenant. The websites keep them in the browser's local storage (see [FIXES.md](FIXES.md) for the planned move to secure cookies). |
| Phone format | Numbers are stored as `+91XXXXXXXXXX`. |
| SMS fallback | Not built. |

---

## 5. Payments and finance

**Built**

- Online payments with Razorpay: order creation on the server, signature verification, webhook handling with duplicate protection.
- Manual payments recorded by one staff member and verified by a **different** staff member.
- Advance, balance and full payments; one payment can cover several bookings.
- Partial and full refunds as separate records; refunds need staff approval.
- Invoices with gapless numbering, credit notes, GST snapshots, vendor invoices, expenses, settlements and reconciliation tables.

**Not built yet**

- Finance and profit dashboards, and CSV / Excel / PDF exports.
- Customer-facing receipts and invoice downloads.
- Live gateway credentials.

---

## 6. Public website

| Page | State |
|---|---|
| Home (hero, experiences, events, Explore Hyderabad map, community, how it works, testimonials) | Built. Content is currently kept in code and data files. |
| Trips list `/trips` | Built (shows published trips). |
| Trip detail `/trips/<name>` | Built: dates, price, people, pickup point, inclusions, refund policy, booking panel, mobile "Book now" bar. |
| Sign in `/login` | Built (WhatsApp code). |
| Checkout `/checkout/<id>` | Built: participants, waiver, Razorpay payment, confirmation. |
| My account `/account` | Built (see section 7). |
| Destinations list and detail, Blogs, Membership, About, Corporate outings, Contact, FAQs | Not built. |
| Cart for several trips | Backend ready; the page books one trip at a time. |

The website is responsive and was checked at 360, 390, 768 and 1280 px wide with no horizontal overflow.

---

## 7. Customer area

At `/account` a signed-in customer sees:

- A sidebar with their profile, **My bookings**, **My details**, **Browse trips**, **Support** and **Log out**.
- Summary counts: upcoming trips, payments due, past trips.
- **Upcoming / Past / Cancelled** tabs.
- A card for each booking: photo, status, date and time, pickup point, booking reference, total and people, progress steps (booked → advance paid → balance paid → trip day), pay-balance button, details (price breakdown, people, balance due date) and cancellation with confirmation.
- A **My details** page to edit name and email.

Not yet in the customer area: payment history, invoice downloads, refund status, saved trips, reviews, notification preferences, privacy requests, memberships.

---

## 8. Admin panel

The admin panel is a full web application at `/admin`, not the stock Django admin (which remains available at `/admin/?classic=1` as a fallback).

| Capability | Detail |
|---|---|
| Sign in | Staff phone with a code or a password. |
| Navigation | Seven groups (Home, Trips, Bookings, Finance, Customers, Operations, Marketing) plus Settings; opens as a drawer on phones. |
| Dashboard | Key figures with 30-day change, revenue and bookings charts (this year against last), recent bookings, and a **"Finish setting up"** card that warns about placeholder business values and missing integrations. |
| Records | **171 managed tables in 20 modules**, each with search, sorting, paging, create, edit and delete according to the user's permissions. Phones show each row as a card. |
| Forms | Built from the API's description of each table: choices, linked records, switches, text, JSON, and **file upload** (type and size checked). |
| Service actions | Verify or reject a manual payment, approve a refund, grant a departure exception, check a participant in, publish content. All go through the same service code as the customer flow. |
| Safety | Server-side permission checks on every call; every create, update and delete is audit-logged; sensitive tables are read-only; personal-data views are logged. |
| Roles | Twelve roles are seeded (Super Admin, Admin, Content Manager, Content Writer, Trip Manager, Trip Organizer, Booking Manager, Finance Manager, Customer Support, Marketing Manager, Operations Manager, Analytics Viewer). |

| Module | Tables |
|---|---|
| Trips | 19 |
| Destinations | 5 |
| Bookings | 8 |
| Checkout | 4 |
| Participants | 6 |
| Payments | 6 |
| Finance | 14 |
| Customers | 2 |
| Vendors | 7 |
| Logistics and safety | 12 |
| CRM and support | 12 |
| Marketing | 11 |
| Memberships and loyalty | 8 |
| Content (CMS) | 14 |
| Analytics and reporting | 16 |
| Notifications | 6 |
| Permissions | 5 |
| Audit and logs | 8 |
| System | 8 |

---

## 9. Multilingual content and approval

- Content exists in English, Telugu and Hindi, each with its own status, SEO text and localized address.
- Workflow: Draft → Submitted → Under Review → Changes Requested / Rejected → Approved → Published or Scheduled.
- Publishing is **blocked until all three languages are approved**.
- Version history is kept for key content types.
- The admin edits translations as ordinary records; there is no dedicated side-by-side translation screen yet.

---

## 10. Visitor tracking and business intelligence

- **Built:** consent-gated first-party tracking endpoints, tables for visitors, sessions, events, devices, interests, identities, consents, conversions and campaign attribution; table definitions for daily summaries, KPIs and reports.
- **Not built:** the browser code that sends events and shows a consent notice, the jobs that fill the summary tables, PostHog forwarding, the dashboards in section 10 of version 1.0, scheduled reports and exports.

---

## 11. Background processing and notifications

- **Celery + Redis** run the worker and the scheduler. A **transactional outbox** records important events (booking created, payment succeeded, refund approved) in the same database transaction, and a relay job publishes them, so events cannot silently disappear.
- Scheduled jobs: outbox relay every 5 seconds; balance reminders and trip reminders hourly.
- Notifications: 13 event types × 4 channels (WhatsApp, email, SMS, in-app) have template rows ready (52). **Sign-in codes and these messages are delivered by WhatsApp using approved Meta templates:** booking confirmation, cancellation, balance reminder, trip reminder, payment receipt. Each template's approved name is entered in the admin; a message with no name set is skipped and the reason recorded. Failed sends are retried, then marked failed. Email and SMS providers are not connected, and delivery-status receipts from Meta are not handled yet.

---

## 12. Data model

205 tables exist in PostgreSQL (189 business tables across 11 apps, plus framework tables).

| App | Tables | Covers |
|---|---|---|
| `accounts` | 7 | Users, profiles, teams, assignments, OTP records, login history |
| `tenancy` | 3 | Tenants, domains, memberships |
| `core` | 6 | Settings, audit, data-access and security logs, privacy requests, outbox |
| `content` | 25 | Destinations, CMS pages, blogs, FAQs, media, testimonials, approvals, schedules |
| `trips` | 25 | Trips, schedules, itineraries, pricing, pickups, policies, categories, events |
| `bookings` | 13 | Cart, checkout, bookings, participants, seats, cancellations, confirmations |
| `payments` | 22 | Payments, allocations, refunds, GST, invoices, expenses, settlements |
| `operations` | 21 | Vendors, vehicles, drivers, pickups, waivers, incidents |
| `crm` | 31 | Enquiries, support, campaigns, coupons, memberships, loyalty, reviews |
| `tracking` | 22 | Visitor tracking, attribution, summaries, KPIs, reports |
| `notifications` | 14 | Templates, jobs, delivery logs, integrations, health |

Engineering standards followed: UUID primary keys, decimal money with explicit currency, UTC timestamps, foreign keys and constraints, a migration for every change, transactions around money and capacity, preserved price and tax snapshots, soft deletion only where needed.

---

## 13. Security and privacy

| Control | State |
|---|---|
| Server-side authorization on every admin call | Done |
| Tenant isolation enforced by the database | Done (needs a limited database user) |
| Audit log for admin changes; access log for personal data | Done |
| Rate limits on sign-in, resend, password attempts | Done |
| Payment signature, webhook and idempotency checks | Done |
| Upload checks (type, size, real image decode) | Done |
| Secret values kept in environment, never in code | Done |
| Secure cookies, HSTS | Built in; switch on automatically when `DEBUG` is off |
| HTTPS redirect, `DEBUG` off, production host and CORS lists | **Set in the production environment** |
| Browser tokens in local storage | Acceptable for development; move to secure cookies |
| Data deletion and export workflow | Records exist; the workflow that acts on them is not built |
| Analytics consent notice and masking | Not built |

---

## 14. Quality and testing

- **46 automated backend tests pass.** They cover money rules, one-time codes, checkout and multi-trip bookings, capacity races, payments, webhooks, refunds, invoices, publishing rules, enquiries, tracking and trip APIs.
- Tests must run with a database user that is not a superuser (see [FIXES.md](FIXES.md)).
- Every admin table endpoint was exercised for listing, searching and sorting; create / edit / delete, uploads and permission checks were tested on representative tables.
- The website and admin were audited in a real browser at four screen widths (13 pages × 4 widths): no horizontal overflow.
- The production build and TypeScript checks pass.
- **Not yet covered:** automated frontend tests, end-to-end tests of the booking and payment journey with a real payment, and real-device testing.

### Mandatory scenarios from version 1.0

| # | Scenario | Automated |
|---|---|---|
| 1 | Two customers race for the last seats | Yes |
| 2 | Several trips in one checkout | Yes |
| 3 | One trip becomes unavailable during checkout | Yes |
| 4 | Different advance percentages per trip | Yes |
| 5 | One payment covers several bookings | Yes |
| 6 | Balance paid separately before departure | Yes |
| 7 | One trip cancelled inside a multi-trip checkout | Yes |
| 8 | Partial refund for one booking | Yes |
| 9 | Payment succeeds but the browser closes | Yes |
| 10 | Duplicate gateway webhook | Yes |
| 11 | Manual payment entered incorrectly | Yes |
| 12 | GST changes after an invoice is issued | Yes |
| 13 | Several participants without accounts | Yes |
| 14 | Unauthorised admin tries to reach finance | **No** (permissions exist; test to write) |
| 15 | Publishing without all translations | Yes |
| 16 | Visitor declines analytics | Yes |
| 17 | Duplicate analytics event | Yes |
| 18 | Customer requests data deletion | **No** (workflow not built) |
| 19 | Background job fails and retries | **No** |
| 20 | Database restored after a simulated failure | **No** |

---

## 15. Coverage of the launch acceptance criteria

| Criterion | Status |
|---|---|
| Public website is responsive | **Done** for built pages |
| Admin panel manages all approved modules | **Done** for record management; dashboards and reports pending |
| Customer accounts work with WhatsApp OTP | **Done** (credentials verified; confirm the approved template name and language) |
| Multi-trip checkout works correctly | **Done** in the backend; website books one trip at a time |
| Multiple participants under one primary booker | **Done** |
| Percentage-based advance payments | **Done** |
| Balances collected before departure | **Done** (reminders send once the WhatsApp templates are approved and named) |
| Razorpay payments and refunds verified | **Pending** live keys and a real test |
| Manual payment verification | **Done** |
| GST configurable | **Done** (values to be set by the business) |
| Invoices generated correctly | **Done** in the backend; no customer download yet |
| Trip operations and logistics manageable | **Done** as records; QR check-in not built |
| CRM and support workflows | **Partial** (records and admin; customer intake endpoints for enquiries) |
| Membership and marketing modules | **Partial** (records only; no purchase or checkout flows) |
| Visitor tracking respects privacy | **Partial** (endpoints and consent records; no browser notice) |
| Business intelligence reports validated | **Not started** |
| Multilingual publication rules enforced | **Done** |
| Role permissions tested | **Partial** (rules in place; roles not exercised with real people) |
| Backup and recovery verified | **Not started** |
| Production monitoring active | **Not started** |
| Technical and user documentation delivered | **In progress** (this document, `FIXES.md`, READMEs) |

---

## 16. Development phases: status

| Phase | Scope | Status |
|---|---|---|
| 0 | Requirements and architecture | Done (this document is the current version) |
| 1 | Foundation: apps, authentication, authorization, audit, queue | **Done** |
| 2 | Public website and CMS | **Partial**: home, trips, trip detail built; CMS-driven pages, destinations, blogs, SEO pages pending |
| 3 | Customer, checkout, bookings, payments | **Mostly done**: full backend and booking pages; cart page, receipts, live payments pending |
| 4 | Operations and logistics | **Partial**: records and admin; manifests, QR check-in, completion reports pending |
| 5 | CRM, membership, marketing | **Partial**: records and admin; purchase, coupon and review flows pending |
| 6 | Visitor tracking | **Partial**: backend only |
| 7 | Business intelligence | **Not started** |
| 8 | Testing and production | **Started**: backend tests pass; frontend tests, security review, deployment pending |

---

## 17. Decisions that changed from version 1.0

| Version 1.0 | Now | Consequence |
|---|---|---|
| Three separate deployable Next.js applications | **Two** deployables: Next.js (website and admin together) and the Django API | Fewer moving parts. The admin can be split into its own application later if it needs a separate release schedule or access boundary. |
| Backend in Next.js with Prisma | Django REST Framework with the Django ORM | Different language for the backend team. |
| BullMQ jobs | Celery jobs | Same capabilities (retries, scheduling); monitoring still to add. |
| Secure cookie sessions | Signed tokens in the browser | Planned change to cookies before launch. |
| Shared package monorepo | Two folders (`backend`, `GoHyderabad`) | Shared types are kept in the frontend `lib` folder. |

---

## 18. Running the system

**Backend**

```
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp -n .env.example .env            # fill in the values (see section 2.6)
python manage.py migrate
python manage.py seed_platform     # roles, settings, KPI and event definitions, templates
python manage.py createsuperuser   # phone like +919876543210
python manage.py runserver         # http://127.0.0.1:8000
celery -A config worker -l info -P solo     # needs Redis
celery -A config beat -l info
```

**Frontend**

```
cd GoHyderabad
cp .env.local.example .env.local   # NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:8000
npm install
npm run dev                        # http://localhost:3000   (admin: /admin)
```

**Useful commands**

| Command | Purpose |
|---|---|
| `python manage.py import_frontend_content` | Load the website's trips, categories, destination details and testimonials into the database (as drafts). |
| `python manage.py seed_demo_data` | Fill every admin table with clearly marked demo rows and one demo booking. Never run in production. |
| `python manage.py upload_local_media` | Copy locally stored files up to S3. |
| `python manage.py test` | Run the backend tests (needs a limited database user). |

---

## 19. Decisions needed from the business

1. Legal company name and GSTIN for invoices.
2. GST treatment: rate and whether displayed prices include tax (confirm with the tax adviser).
3. Advance percentage and how many days before departure the balance is due.
4. The final participation waiver and safety text.
5. Which trips to publish first, with dates, prices and cover photos.
6. Which WhatsApp message templates to submit to Meta for approval.
7. Whether the admin should stay inside the same application or be deployed separately.
