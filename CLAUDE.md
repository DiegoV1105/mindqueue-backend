# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is MindQueue?

A mental health platform connecting independent psychologists with their patients. The core value is **continuity between sessions**: patients log daily emotional states, the backend auto-generates weekly summaries with detected patterns, and the psychologist arrives at each session already knowing what happened that week.

**Problem solved:**
- Patient is alone between sessions — no follow-up
- Therapist arrives at each session without knowing what happened that week
- First 15–20 min of each session lost reconstructing the week
- Independent therapists manage everything via WhatsApp + Zoom with no tooling

**Beta scope decision: NO external AI.** Analysis runs on pandas + numpy + scipy (linear regression, pattern detection). Motivational messages use contextual templates (35+ variants across 9 categories). Anthropic Claude API is used ONLY in `/analytics/therapist-insight`. Key is optional in dev, required in production.

Two repos:
- `mindqueue-backend` — Python + FastAPI (this repo)
- `mindqueue-frontend` — React + Vite at `C:\Users\dialv\Documents\GitHub\mindqueue-frontend`

Deploy targets: Render.com (backend) + Vercel (frontend), free tier, total cost $0.

## Backend Commands

```bash
# Activate virtual environment (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

API docs: `http://localhost:8000/docs` — no test runner or linter is configured.

## Frontend Commands

```bash
# From C:\Users\dialv\Documents\GitHub\mindqueue-frontend
npm install
npm run dev        # http://localhost:5173
npm run build
```

## Backend Architecture

**Stack:** FastAPI + Supabase (PostgreSQL + Auth) + Anthropic Claude API + pandas/scipy

### Request flow

All protected endpoints require `Authorization: Bearer <supabase_jwt>`. The auth pipeline in `app/dependencies.py`:
1. `get_current_user()` — validates JWT via Supabase
2. `get_current_profile()` — fetches `profiles` row (contains `role`)
3. `require_patient()` / `require_therapist()` — role guards as FastAPI dependencies

Two Supabase clients in `app/database.py`: a **service role client** (bypasses RLS) and `get_user_client(jwt)` (respects RLS, used for user-scoped reads).

### Routers

| Router | Prefix | Key responsibility |
|---|---|---|
| `auth.py` | `/auth` | Registration, login, profile CRUD, therapist profile |
| `journal.py` | `/journal` | Daily emotional entries (sleep 1–5, stress/energy/mood 1–10), streak |
| `sessions.py` | `/sessions` | Scheduling with double conflict barrier, availability, blocks |
| `analytics.py` | `/analytics` | Weekly summaries, trends, week-over-week comparison, AI insight |

### Analytics pipeline

Journal entries trigger `check_and_generate_summary()` in `analytics_service.py`. When 5+ entries exist for the week, it generates a `weekly_summaries` record with:
- pandas stats (mean/std/min/max per metric)
- scipy linear regression trend per metric (slope + p-value)
- 8 clinical pattern detections (see list below)
- Critical days flagged when `stress ≥ 8 OR mood ≤ 3 OR energy ≤ 2`, scored medium/high severity
- Alert level via weighted scoring: `normal` / `attention` / `urgent`
- Auto-generated narrative text from conditional templates
- Week-over-week comparison: deltas vs previous week (↑2.1 stress, ↓1.3 mood)
- Therapist notification on generation

**The 8 patterns detected:**
1. High frequency of elevated stress
2. Persistent low mood
3. Sleep–energy correlation
4. High emotional variability / instability (e.g. mood std dev > 2.5)
5. Work stress (weekday vs weekend differential)
6. Escalating stress
7. Positive recovery
8. Accumulated fatigue

`GET /analytics/therapist-insight` calls Anthropic API (claude-3-5-sonnet-20240620) for a free-text summary of all therapist's patients.

### Scheduling: double conflict barrier

- **Barrier 1 (code):** checks for conflicts before insert → returns HTTP 409 with next 3 available slots
- **Barrier 2 (DB):** `UNIQUE INDEX no_overlap_therapist ON sessions(therapist_id, scheduled_at) WHERE status NOT IN ('cancelled')`

### Motivation service

`app/services/motivation_service.py` is rule-based, no API calls. Selects from 35+ message variants across 9 categories based on emotional state. Uses `hashlib.md5(user_id + date)` for deterministic pseudo-randomness (same user/day always gets the same message).

### Database tables (Supabase — no migration files, managed via dashboard)

```
profiles              → user profiles (role: patient/therapist)
therapist_profiles    → license, specialties, fees, approach
patient_therapist     → many-to-many patient ↔ therapist
journal_entries       → daily entries, unique per user per date
weekly_summaries      → auto-generated, alert_level field
sessions              → appointments with conflict constraints
notifications         → real-time notifications
therapist_availability → weekly work schedule by day
availability_blocks   → manual blocks (vacations, meetings)
```

RLS enabled on all tables. DB trigger auto-creates `profiles` row on Supabase Auth signup.

**RLS visibility rules:**
- Patients see only their own data
- Therapists see only data of their assigned patients (via `patient_therapist`)
- Clinical notes on sessions are private — only the therapist who wrote them can read them

### Environment variables

See `.env.example`. Required: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SECRET_KEY`. Optional in dev: `ANTHROPIC_API_KEY` (required in production). `FRONTEND_URL` sets the single allowed CORS origin (default: `http://localhost:5173`).

---

## Frontend Architecture

**Stack:** React 18 + Vite + TailwindCSS + Zustand + TanStack Query v5 + Framer Motion + Recharts

### Design system

| Token | Value |
|---|---|
| Primary | `#2D6A4F` (forest green) |
| Secondary | `#52B788` (mint green) |
| Accent | `#F4A261` (soft orange — attention alerts) |
| Urgent | `#E76F51` (coral — critical alerts only, NEVER red) |
| Background | `#FAFAF8` (off-white, never pure white) |
| Surface | `#FFFFFF` (cards only) |
| Font body | DM Sans |
| Font headings | Playfair Display |
| Card radius | 16px |
| Input radius | 12px |

All pages use `bg-bg` (#FAFAF8). Cards use `bg-white shadow-card`. No pure white backgrounds on pages.

### State and data fetching

- **Zustand** (`src/store/authStore.js`): `user`, `accessToken`, `refreshToken`, `isTherapist()`, `isPatient()` — persisted to localStorage under `mq_auth`
- **TanStack Query**: staleTime 5 min, retry 1, refetchOnWindowFocus false
- **Axios** (`src/lib/axios.js`): auto-attaches Bearer token from `mq_access_token`, handles 401 → refresh flow → redirect to `/login`
- **Supabase client** (`src/lib/supabase.js`): real-time notifications via `subscribeToNotifications(userId, callback)`

### Routing (App.jsx)

```
/login, /register          → public
/patient/dashboard         → PatientDashboard
/patient/journal           → JournalPage (3-step form)
/patient/history           → HistoryPage
/patient/sessions          → SessionsPage
/therapist/dashboard       → TherapistDashboard (patient list by urgency)
/therapist/patients/:id    → PatientDetailPage (tabs: week / history / sessions)
/therapist/schedule        → SchedulePage (weekly calendar)
/therapist/profile         → ProfilePage
/                          → RoleRedirect (sends to correct dashboard)
```

### Patient journal form (JournalPage / JournalForm)

Three-step form — the core patient UX:
1. **Step 1:** 4 visual sliders (rows of clickable circles, not `<input type="range">`) — sleep (1–5), stress/energy/mood (1–10). Colors: green = good, orange = medium, coral = bad
2. **Step 2:** emotion chips (16 options, max 5) + optional situation text
3. **Step 3:** optional free text (up to 2000 chars, skippable)

Success screen shows animated checkmark + motivational message in Playfair Display italic + updated streak.

### Therapist dashboard logic

PatientCard shows: avatar, name, alert badge, stress/mood metrics, "Nuevo resumen" dot if unreviewed.

PatientDetailPage tabs:
- **"Esta semana"**: summary stats, critical days, detected patterns, emotion frequency, 7-day chart
- **"Historial"**: 6-week Recharts trend (stress/mood/energy, 3 lines)
- **"Sesiones"**: session history with upcoming and past sessions

SchedulePage: Mon–Fri 8am–5pm grid, slot states: available/booked/blocked/pending. Conflict → modal with 3 alternative slots.

### Hooks (src/hooks/)

| Hook | Key queries/mutations |
|---|---|
| `useAuth` | `useLogin`, `useRegister`, `useLogout` |
| `useJournal` | `useMyEntries`, `useCreateEntry`, `useStreak`, `useCurrentSummary` |
| `useSessions` | `useMySessions`, `useMyPatients`, `useCreateSession`, `useAvailableSlots` |
| `useAnalytics` | `usePatientSummaries`, `useTrends`, `useTherapistInsight` |
| `useNotifications` | `useNotifications` |

### UI component library (src/components/ui/)

Button (variants: primary/secondary/ghost/danger, loading state), Card, Avatar (initials fallback), Modal (Framer Motion), Badge (6 variants), Spinner, EmptyState, AlertBanner (info/success/warning/error). Always show EmptyState — never leave a blank screen.

