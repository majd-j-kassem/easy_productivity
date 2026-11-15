# Productivity Studio

An API-first Django application for personal project planning, measured outcomes, cycle reviews, and income tracking. Each account has its own projects and preferences. The first release uses an English, responsive web interface.

## Run locally

Requirements: Python 3.12 and a network connection to your Python package index.

```sh
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Give the initial account an email address if you intend to test email reminders. Windows PowerShell uses `.venv\Scripts\Activate.ps1` and `Copy-Item .env.example .env`. Replace the example secret with a random value before use outside local development.

If updating an existing installation, run `python manage.py migrate` from the updated source folder using your existing database.

## First project

1. Set the default review interval, timezone, and reminder time in **Preferences**. You can customize your reason list there.
2. Create a project. Set the first review date explicitly if it needs to fall on a particular weekday. The review interval is set at creation. Use **Edit project** or **Edit cycle dates** to correct the current cycle dates. Recorded entries must stay within the corrected dates. Monthly rules use the day of the first review as the anchor and clamp to the last day of short months.
3. Click **Next** to add initial tasks and goals, or click **Create project** to add them later. A task can have just a name. Its description, reference, and reusable task type are optional. Open **Task types** when you want to define reusable task or output fields.
4. Use **Add goal** to set a Done, Count, Hours worked, or Net income target. Open **Daily entry** to record each output for a Count goal or one output for a Done goal. Confirm task completion when all current targets are met.
5. On the review date, decide what to complete, carry, close partially, or discard. Use **Plan next cycle** to prepare a draft, optionally copying tasks from the previous plan as new work. The draft activates when its predecessor closes. Recording progress also requires the cycle start date. Corrections to closed cycles require a reason and update cumulative progress.
6. End the project after resolving each open task. The final report shows initial project targets separately from the cycle targets. Download PDF or Excel. The workbook includes project, metrics, goals, cycle history, receivable, and payment sheets.

Delete a project, task, task type, goal, or pay terms using the corresponding **Delete** action and confirm. Deleting the entire project permanently removes its records. Individual deletions protect tasks and goals used in closed cycles, tasks linked to recorded work, task types in use, and pay terms used in the ledger.

## Finance and background processing

Choose Hourly income or Monthly income at project creation and set effective-dated pay terms before recording work. The project currency applies to every amount. The entered tax percentage is an input to the calculation. Amounts are rounded to two decimal places.

An **Hours worked** goal uses the hours recorded in the ledger for its task and cycle. Select the task when recording hourly work. To reuse linked work already in the ledger, choose **Switch to hours** on an open Count goal with no saved entries or closed-cycle history.

A **Net income** goal compares the target with the project's after-tax receivables whose work dates fall in that cycle, including work without a linked task. It uses the project currency and updates from the income ledger. Each cycle can have one Net income goal.

For monthly pay, schedule the initial terms on or before the project start. Later monthly rate or tax changes take effect on the first day of a month. Full-month receivables are generated on or after the last day of the month. Enter a partial first or final month manually as a gross amount. After work ends, unpaid projects remain in Awaiting payment. Once the last payment has been recorded, confirm closure from the project panel.

```sh
python manage.py process_planner
```

For an always-running installation, schedule this command every five minutes using your host scheduler, from the project directory with its virtual environment. The command generates monthly receivables and creates one review reminder per cycle. It sends email once marked delivered by the configured backend and retries failed sends on future runs. Use the SMTP options in `.env.example` for delivery. The development fallback prints emails to the console.

## Invite friends

Use Django Admin at `/admin/` to create an invite for an email address. Copy the displayed registration path and give it to the intended recipient privately. The link is single use and assigns that email to the new account. The admin interface provides account and invitation management.

Before hosting a friend trial, configure a production WSGI server, HTTPS, a secret key, allowed hosts, a persistent database and backups, static asset serving, SMTP, and scheduling. Set `DEBUG=0` and run `python manage.py check --deploy` against the resulting environment. The bundled SQLite settings are intended for local use and small controlled trials. For backups, stop writes and copy the SQLite database or use SQLite’s backup command. Protect backups as private data.

## API and tests

The web interface uses the versioned JSON API at `/api/v1/` with Django session authentication and CSRF protection. Application forms use server-side validation. The API has authenticated project list/detail, preferences, reasons, task types, planning, dated entries, review, finance, reports and notifications routes. See `config/urls.py` for the route list. A future mobile client will need a suitable authentication flow before distribution.

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest -q
```

Tests cover review rule immutability, user isolation, carry-forward and corrections, report downloads, financial closure, invite redemption, and reminder retries. Try creating a project with a review date of today for a quick manual review test.

## Content administration

Install updated requirements and run `python manage.py migrate`. Sign in as a superuser and open `/cms/` to manage onboarding templates and help articles under Snippets. Other staff need Wagtail admin access and the relevant model permissions. Set `WAGTAILADMIN_BASE_URL` to your deployed origin.
