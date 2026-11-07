# GoHyderabad: fixes and remaining work

Backend and frontend, in one place. Written in plain language. Checked on 7 November 2026 against the real code, with the tests run and the app built.

For how the system works, see [GOHYDERABAD.md](GOHYDERABAD.md).

## Table of contents

1. [How to read this file](#1-how-to-read-this-file)
2. [What was checked](#2-what-was-checked)
3. [Summary: fix these first](#3-summary-fix-these-first)
4. [Backend fixes](#4-backend-fixes)
   - [P0: before real customers or money](#backend-p0)
   - [P1: right after](#backend-p1)
   - [P2: should do](#backend-p2)
   - [P3: later](#backend-p3)
5. [Frontend fixes](#5-frontend-fixes)
   - [P0: before real customers or money](#frontend-p0)
   - [P1: right after](#frontend-p1)
   - [P2: should do](#frontend-p2)
   - [P3: later](#frontend-p3)
6. [Infrastructure and process](#6-infrastructure-and-process)
7. [Business decisions needed](#7-business-decisions-needed)
8. [Recently fixed (for reference)](#8-recently-fixed-for-reference)
9. [How to run the checks yourself](#9-how-to-run-the-checks-yourself)

---

## 1. How to read this file

| Priority | Meaning |
|---|---|
| **P0** | Must be done before real customers or real money. |
| **P1** | Important. Do right after P0. |
| **P2** | Should do. The product works without it. |
| **P3** | Nice to have, later. |

Each item has an ID (`B-` backend, `F-` frontend, `I-` infrastructure) so you can refer to it in conversation. "Where" points to the file or screen.

---

## 2. What was checked

| Check | Result |
|---|---|
| Backend automated tests | **56 of 56 pass** (46 existing, fixed; 10 new for WhatsApp delivery) |
| Django system check | No errors |
| Django deployment check | Run with development settings: security warnings that clear once production settings are used (B-02), and 100+ API-documentation warnings (B-16) |
| Every admin table (171) | List, search and sort work; create, edit, delete and file upload tested on representative tables |
| Customer journey against the real API | Sign in, profile, checkout, participants, waiver, payment attempt, bookings: all work (payment needs live keys) |
| Website and admin at 360, 390, 768, 1280 px | 13 pages × 4 widths: no horizontal overflow |
| Frontend type check and production build | Pass |
| Frontend automated tests | **None exist** |
| Python dependency check | No conflicts |
| Node dependency audit | 2 issues, both inside the framework's bundled CSS tool (see F-11) |

---

## 3. Summary: fix these first

| ID | Fix | Why |
|---|---|---|
| B-01 | Use a limited database user | Tenant isolation is switched off for a superuser |
| B-02 | Production security settings | `DEBUG`, HTTPS, secure cookies |
| B-03 | Real business values (name, GST, advance, balance) | Invoices and payments would be wrong |
| B-04 | Razorpay live keys and webhook secret | No real payments without them |
| B-05 | Approve message templates with Meta and set their names | Confirmations and reminders (sign-in codes already work in code) |
| B-06 | Move local photos to S3 | Photo links already point at S3 |
| B-07 | Remove demo data | About 150 "Demo" rows and a demo booking |
| B-22 | Stop `--publish` skipping the translation rule | It can publish content that was never approved |
| F-01 | Publish real trips with dates, prices and photos | `/trips` is empty today |
| F-02 | Real waiver text | Checkout has a generic sentence |
| F-06 | Secure cookies instead of local-storage tokens | Safer sessions |

---

## 4. Backend fixes

<a id="backend-p0"></a>
### P0: before real customers or money

**B-01. Database user is a superuser** (P0)
- **Problem:** PostgreSQL ignores row-level security for superusers, so the tenant isolation rules do not protect anything on this machine. The system check is skipped in development, which hides it.
- **Fix:** create a limited user and use it in `POSTGRES_URL`:
  `CREATE ROLE gohyd_app LOGIN PASSWORD '…' NOSUPERUSER NOBYPASSRLS;` then grant it the schema (run migrations as the owner). Use a separate admin role only for migrations.
- **Where:** PostgreSQL role, `.env`, `tenancy/checks.py`.

**B-02. Production security settings** (P0)
- **Already in code:** secure session and CSRF cookies and HSTS switch on automatically when `DEBUG` is off; `SECURE_SSL_REDIRECT` is an environment switch.
- **To do:** in production set `DEBUG=False`, a strong `SECRET_KEY`, `SECURE_SSL_REDIRECT=True`, correct `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` and `CSRF_TRUSTED_ORIGINS`. Then run `python manage.py check --deploy` against the production environment until it is clean. (Run in development it still warns, because `DEBUG` is on.)
- **Where:** `config/settings.py`, environment variables.

**B-03. Placeholder business values** (P0)
- **Problem:** company name reads "GoHyderabad (set legal name)", GST is off at 0%, advance is 30% and balance is 7 days before. These are first-run values, not decisions.
- **Fix:** enter real values. The admin dashboard lists what is missing under "Finish setting up".
- **Where:** Admin → Finance → Business entities and GST configurations; System → Settings.

**B-04. Razorpay live credentials** (P0)
- **Problem:** without keys, "Pay" shows that online payment is unavailable.
- **Fix:** set `RAZORPAY_KEY_ID`, `RAZORPAY_KEY_SECRET`, `RAZORPAY_WEBHOOK_SECRET`; register the webhook URL `/webhooks/razorpay/`; run a real test payment and a test refund end to end.
- **Where:** `.env`, Razorpay dashboard.

**B-05. WhatsApp: finish the Meta side** (P0)
- **Done in code (7 Nov):** sign-in codes are sent in development straight away (no worker needed; if Meta refuses, the code is printed in the server console). All other messages (booking confirmation, cancellation, balance reminder, trip reminder, payment receipt) are now delivered through approved templates, with retries, a delivery log and a clear reason when a message is skipped. 10 new tests cover it.
- **Checked:** your token is valid (permanent system-user token with messaging and management rights) and the number `+91 91547 03403` is reachable on the Cloud API (quality GREEN).
- **Still to do on the Meta side:**
  1. Confirm the sign-in template is named exactly as in `WHATSAPP_TEMPLATE_NAME`, is **Approved**, and note its language. If it is not plain `en` (for example `en_US`), set `WHATSAPP_TEMPLATE_LANGUAGE` to match.
  2. Create and get approved one template per message below, then type each approved name into Admin → Notifications → Templates (field "Provider template name"). Until a name is set, that message is skipped and the reason is recorded.
  3. The registered display name of the number is "GA updates" with status declined; request a GoHyderabad display name so customers see the right sender.
  4. Add a delivery-status webhook (Meta reports delivered / read) if you want delivery receipts.
- **Template variables must be in this order** (Meta rejects a different count):

  | Message | `{{1}}` | `{{2}}` | `{{3}}` | `{{4}}` |
  |---|---|---|---|---|
  | booking_confirmation | name | booking reference | trip name | trip date |
  | cancellation | name | booking reference | trip name | |
  | balance_reminder | name | booking reference | amount due | due date |
  | trip_reminder | name | trip name | trip date | |
  | payment_receipt | name | amount | | |

- **Where:** `accounts/services.py`, `notifications/tasks.py`, `notifications/services.py` (`TEMPLATE_PARAMS`).
- **Run the worker in production:** with a WhatsApp URL set and `DEBUG` off, codes and messages are queued and only a running Celery worker sends them.

**B-06. Local photos not in S3** (P0)
- **Problem:** with the S3 bucket set, photo links point at S3, but the 18 imported photos exist only on the development machine.
- **Fix:** on a machine with AWS access run `python manage.py upload_local_media`. For production use an instance role, not keys in `.env`.
- **Where:** `core/management/commands/upload_local_media.py`.

**B-07. Demo data must not go live** (P0)
- **Problem:** the demo trip, demo customer, a demo booking and about 150 "Demo" rows were added for development.
- **Fix:** write a cleanup command that removes only rows created by `seed_demo_data` (they all start with "Demo" and use the `+91 90000 001xx` numbers), and run it before launch. Never run `seed_demo_data` in production.
- **Where:** `core/management/commands/seed_demo_data.py`.

**B-22. Importing with `--publish` skips the translation rule** (P0)
- **Problem:** the rule says a trip or destination cannot be published until English, Telugu and Hindi are all approved. `import_frontend_content --publish` sets the status directly and ignores the rule. The imported content only has English.
- **Fix:** make `--publish` go through the same publish check, or remove the option and publish only from the admin. Add the missing translations first.
- **Where:** `content/management/commands/import_frontend_content.py`, `content/models.py`.

<a id="backend-p1"></a>
### P1: right after

**B-08. Data deletion and export workflow** (P1): privacy requests are stored but nothing deletes or anonymises the person. Build the workflow, keep financial records, and add a test (mandatory scenario 18). *Where:* `core` (`DataRequest`).

**B-09. Missing safety tests** (P1): add tests for finance access by an unauthorised admin (scenario 14) and for a failed background job retrying (scenario 19). *Where:* `payments/tests.py`, `core/tests.py`.

**B-10. Roles tested only with the superuser** (P1): create a test user for each of the 12 roles and confirm they see only what they should (for example a Content Writer cannot see payments). *Where:* seeded roles, `admin_api`.

**B-11. Payment and refund paths on real cases** (P1): verify, reject, approve refund, cancel and departure exception work in code, but only the happy path was run on a real booking. Run through failed and partial cases with test keys. Manual payments must be refunded manually; add a clear admin step for this. *Where:* `payments/services.py`.

**B-12. Restore drill** (P1): practise restoring the database from a backup and record the result (scenario 20). *Where:* backups.

**B-13. Staff account clean-up** (P1): the second superuser has no `+91` in its number, so it cannot sign in. Fix it in Django admin. Give each staff member a role and an operator membership. *Where:* Django admin → Users.

**B-23. Worker and scheduler not verified running** (P1): confirm Celery worker and beat run together with Redis, that the outbox relay and reminders fire, and add alerts for failed jobs. *Where:* `config/settings.py` (`CELERY_BEAT_SCHEDULE`), `core/tasks.py`.

<a id="backend-p2"></a>
### P2: should do

**B-14. SMS fallback for codes** (P2): if WhatsApp is down nobody can sign in. Add an SMS provider fallback. *Where:* `accounts/otp.py`.

**B-15. Analytics pipeline** (P2): no jobs fill the daily summary, trip performance, customer metrics and attribution tables, and nothing forwards to PostHog. *Where:* `tracking`.

**B-16. API documentation warnings** (P2): the generated API docs report 100+ warnings (custom authentication not described, many views without declared serializers). Add schema hints so `/api/docs/` is accurate. *Where:* `tenancy/authentication.py`, `accounts/views.py`, `admin_api/views.py`.

**B-17. Exports and reports** (P2): add CSV, Excel and PDF exports and the finance and BI endpoints the dashboards need. *Where:* new.

**B-18. Customer-side finance data** (P2): expose payment history, invoices and refund status to the customer API. *Where:* `bookings`, `payments`.

**B-19. Refund approvals and limits** (P2): decide who may approve which amounts; add a maximum without a second approver. *Where:* `payments/services.py`.

**B-24. Notification preferences respected** (P2): confirm customers' channel preferences are honoured when jobs are queued. *Where:* `notifications/services.py`.

**B-25. Upload limit** (P2): the 5 MB limit is a safe default but small for photos. Raise `MAX_FILE_UPLOAD_SIZE` if needed. *Where:* `.env`.

<a id="backend-p3"></a>
### P3: later

- **B-20.** QR check-in endpoint for trips. *Where:* `operations`, `bookings`.
- **B-21.** Membership and loyalty purchase flows; coupons applied at checkout; review submission API. *Where:* `crm`, `bookings`.
- **B-26.** Local PostgreSQL 13 workaround (`POSTGRES_ALLOW_OLD`, `config/pgcompat`): use PostgreSQL 15 or newer in every environment and remove it.

---

## 5. Frontend fixes

<a id="frontend-p0"></a>
### P0: before real customers or money

**F-01. Publish real trips** (P0)
- **Problem:** no trip is published, so `/trips` is empty and the home page still shows its built-in cards.
- **Fix:** for each trip add a cover photo, dates and prices, all three languages, then publish from the admin. When any trip is published the home page swaps its hand-made cards for live ones; check how that looks first.
- **Where:** Admin → Trips; `components/publicContent.ts`.

**F-02. Real waiver text** (P0): checkout shows a generic sentence. Replace it with your approved waiver and link to the full text; store which version was accepted. *Where:* `components/booking/CheckoutView.tsx`.

**F-03. One full test booking** (P0): the booking pages were tested against the API and by rendering, not with a real payment. Do one complete booking with Razorpay test keys on a phone. *Where:* `/trips` → `/account`.

<a id="frontend-p1"></a>
### P1: right after

**F-04. Cart for several trips** (P1): the backend supports many trips in one checkout; the website books one at a time. Add a cart page and "Add to cart". *Where:* `components/booking`.

**F-05. Missing public pages** (P1): destinations (list and detail), blogs, membership, about, corporate outings, contact, FAQs. *Where:* `app/(public)`.

**F-06. Safer sessions** (P1): customer and staff tokens are kept in local storage. Move to secure, HTTP-only cookies (or a small server layer) before launch. *Where:* `lib/api/client.ts`.

**F-07. Customer account gaps** (P1): add payment history, invoice and receipt download, refund status, saved trips, reviews, notification preferences and privacy requests. *Where:* `components/account`.

**F-08. Website content from the CMS** (P1): home page text, sections and photos live in code (`components/site`). Make them editable from the admin and read from the API. *Where:* `components/site`, `content`.

**F-09. Frontend tests** (P1): there are none. Add unit tests for the booking and account logic and end-to-end tests for sign-in, booking and payment. *Where:* new.

**F-10. Tracking and consent** (P1): add the cookie and tracking notice and send events (`page_view`, `trip_viewed`, `booking_started`, …) to the tracking endpoints, respecting opt-out. *Where:* new in `app/(public)`.

<a id="frontend-p2"></a>
### P2: should do

**F-11. Framework security update** (P2): `npm audit` reports two issues in a CSS tool bundled inside Next.js (build-time only). Update Next.js to the latest 15.5 patch now and plan the move to the next major version. *Where:* `package.json`.

**F-12. Admin improvements** (P2):
- Filters by status and date, and bulk actions in tables.
- A searchable picker for linked records (lists over 200 items fall back to a plain text box).
- Real date pickers in forms (the component is installed, unused).
- Upload a trip cover inside the trip form (today: upload in Media assets, then pick it).
- A friendlier editor for JSON fields.
- *Where:* `components/admin/ResourceView.tsx`, `admin_api/serializers.py`.

**F-13. Dashboards and reports** (P2): the dashboard has five figures and two charts. Add the finance, trips, customers and marketing dashboards from the requirements, with exports. *Where:* `app/admin`.

**F-14. Error and loading pages** (P2): add `error.tsx` and `loading.tsx` for the booking pages and admin, so failures and slow loads look intentional. *Where:* `app/(public)/(site)`, `app/admin`.

**F-15. Search engine basics** (P2): add `sitemap.xml`, `robots.txt`, structured data for trips and destinations, and complete page metadata. *Where:* `app`.

**F-16. Telugu and Hindi** (P2): the website interface is English only, while content must exist in three languages. Add language switching and localized addresses. *Where:* `app/(public)`.

**F-17. Accessibility check** (P2): run a keyboard and screen-reader pass and check colour contrast (gold on dark, white on amber buttons). *Where:* whole frontend.

**F-18. Real-device mobile testing** (P2): the phone checks used browser emulation. Try real iPhone and Android devices; review the tablet layout; a few long labels are still cut off (for example the sidebar account line). *Where:* whole frontend.

<a id="frontend-p3"></a>
### P3: later

- **F-19.** Clean out unused demo content: the default menus inside the sidebar components, the large global stylesheet for unused demo screens, and one leftover demo logo image. *Where:* `components/application/dashboard`, `styles/globals.css`.
- **F-20.** Check that the home page scripts (scroll effects, map) behave well with Next.js navigation and hydration. *Where:* `components/PageBehavior.tsx`, `components/Motion.tsx`, `components/initPage.ts`.
- **F-21.** Blog and FAQ pages fed by the CMS. *Where:* `app/(public)`.
- **F-22.** Search box inside the customer account bookings list. *Where:* `components/account`.

---

## 6. Infrastructure and process

| ID | Priority | Fix |
|---|---|---|
| **I-01** | P0 | Provision staging and production environments (separate from development): managed PostgreSQL, Redis, application hosting, HTTPS, domain. |
| **I-02** | P0 | Secrets in a secrets manager, not `.env` files. |
| **I-03** | P1 | Continuous integration: run backend tests (with a limited database user), type check and build on every change. There is no pipeline today and no container files. |
| **I-04** | P1 | Deployment recipe: container images for the Django API, worker, scheduler and Next.js app; migrations as a release step. |
| **I-05** | P1 | Monitoring and alerts: errors, failed background jobs, payment webhook failures, uptime. |
| **I-06** | P1 | Automated database backups and the restore drill (B-12). |
| **I-07** | P2 | CDN for photos and static files; web firewall; rate limits at the edge. |
| **I-08** | P2 | Decide whether the admin stays inside the same Next.js app or is deployed separately. |

---

## 7. Business decisions needed

1. Legal company name and GSTIN (B-03).
2. GST rate, and whether prices include tax; confirm with the tax adviser (B-03).
3. Advance percentage and balance due days (B-03).
4. Approved participation waiver text (F-02).
5. Which trips to publish first, with dates, prices and photos (F-01).
6. WhatsApp message templates to submit to Meta (B-05).
7. Refund approval rules (B-19).

---

## 8. Recently fixed (for reference)

| Area | Fix |
|---|---|
| Backend tests | 27 errors and 1 failure became **46 passing**. The tests predated multi-tenancy; a shared base class and user helper now set the tenant context. Also fixed the concurrency test and the admin-page test. |
| Admin API | Ten tables crashed when listing (serializer settings conflict); search crashed on five tables (fields that do not exist); rows had no `id` for some tables; audit logging failed on UUID values; `tenant` was editable. |
| Uploads | File upload now works in the admin with validation; storage failures give a clear message; the S3 libraries were missing and are now installed and listed in `requirements.txt`. |
| Login | Password sign-in for staff with lockout; first-time customer sign-in no longer crashes. |
| Content | Website content imported into the database as drafts, idempotently. |
| Website | Home page rebuilt from one 135 KB file into small components (output verified identical); duplicate React keys fixed; header tidied. |
| Phones | Account and home page no longer overflow; mobile "See latest plans" bar fixed; compact checkout; admin tables as cards; larger tap targets. |
| Cleanup | Removed the old static site and duplicate image folder (17 MB), unused demo components and images, build artifacts and an unused library. |

---

## 9. How to run the checks yourself

**Backend tests (needs a limited database user)**

1. Create a role once: `CREATE ROLE gohyd_test LOGIN PASSWORD 'testpw' NOSUPERUSER NOBYPASSRLS CREATEDB;`
2. Run: `POSTGRES_URL='postgres://gohyd_test:testpw@localhost:5432/gohyderabad' python manage.py test --noinput`
3. Expect: `Ran 46 tests … OK`.

**Backend health**

- `python manage.py check`
- `python manage.py check --deploy` (use production settings)
- `pip check`

**Frontend**

- `npx tsc --noEmit` (type check)
- `npm run build` (production build)
- `npm audit --omit=dev`

**Screens at phone size:** open the site in Chrome, press F12, choose the device toolbar, and test 360 and 390 px widths; look for sideways scrolling and tiny buttons.
