# Spec — Authentication, Identity & Multi-Tenancy

> Status: **v2 — device-bound model locked + P1/device layer IMPLEMENTED & tested.**
> Scope: identity, authentication, authorization, tenancy, onboarding, trusted
> learning devices, and the foundation for parental controls ("child lock /
> monitor"). Companion to [ADR-pagedex-and-pilot.md](./ADR-pagedex-and-pilot.md)
> (ADR-009 covers the tenant data-plane already shipped).
>
> This spec exists because the platform started with **no real auth** (a single
> static `dev-local-key` + a mock frontend login) and tenant was a **client-supplied
> header** — so isolation was "polite," not enforced. We're going to a real-school
> pilot with multiple tenants; this is the foundation everything else rests on.
>
> **v2 change (post-review).** Identity is reframed around a **Parent Account +
> Student Profile + trusted Learning Device** model (Netflix-style), replacing
> "family-switch reuses the parent session" as the canonical stay-signed-in path.
> The student is the **root identity**; the parent is one of three *authenticators*
> (parent / self / school). A paired learning device holds a **device-bound,
> student-scoped** session that can never escalate to a parent token. See §2.5
> (two axes), §3.7 (device pairing), §5 (scopes/claims). **Implementation status**
> is tracked inline with ✅ (built+tested) / ⏳ (pending) markers and summarised in §16.

---

## 1. Goals & non-goals

**Goals**
1. Real per-user authentication for **5 stakeholders**: student, parent, teacher,
   school admin, superadmin.
2. **Student login that is genuinely easy** even when the student has **no email and
   no phone** (the common K-12 case, esp. classes 3–8).
3. **Tenant (school) isolation enforced from the verified token**, not a header.
4. **Role-based authorization** on every endpoint.
5. **Bulk onboarding** of schools, teachers, students, classes/rosters.
6. A data model that makes **parental linkage + child-lock/monitoring** a first-class,
   later-buildable feature — not a re-architecture.
7. **Scalable** to many tenants and stateless at the request path.
8. **DPDP Act 2023 (India) aware**: verifiable parental consent for minors, data
   minimization, parent-initiated (not platform) monitoring.

**Non-goals (for v1)**
- Payments/billing, SSO for every provider, SCIM auto-provisioning, full audit-grade
  compliance certification. (Designed-for, not built day one.)

---

## 1.5 Go-to-market modes (decided)

The same identity core serves two business modes; **B2B is the near-term pilot**:

| Mode | Who onboards | Tenant | Student content trigger |
|---|---|---|---|
| **B2B (pilot)** | School onboards → roster → tells parents to use the app → parent claims child | the **school** | teacher records class → grounded summary/mindmap/quiz (the pipeline we built) |
| **B2C (later)** | Parent finds the app, signs up directly, picks class/board | a **"direct" tenant** (no school) | **NCERT/curriculum self-study** (same Pagedex, no teacher transcript) |
| **Older students (post-10th, later)** | Class 11–12 students self-sign-up | school or direct | self-study; **individual login** (they usually have phone/email) |

**Consequence to design for (not build now):** B2C / self-study content comes from
**NCERT directly** (pick a chapter), since there is no teacher transcript. Auth is the
same; the *content trigger* differs.

---

## 1.6 Two orthogonal identity axes (auth source × content source)

Every student carries **two independent attributes**. Conflating them is the classic
mistake; keeping them separate is what keeps the model simple.

| Axis | Question | Values | Drives |
|---|---|---|---|
| **Auth source** | *Who authenticates the student?* | parent-managed · self-managed (post-10th) · school-managed | the login flow only |
| **Enrollment / content source** | *Where does the student's content come from?* | **school** (teacher transcript) · **self** (NCERT curriculum) | the content pipeline |

They're independent: a **parent-authenticated** child is still a **school** student —
the parent logging them in doesn't change that their daily content is the teacher's
taught topic. So the content-mode flag lives on the **student's enrollment**, never on
the auth method or the device.

> *"The student doesn't change. Only who authenticates the student changes."*

**Content engine (one substrate, two triggers).** NCERT Pagedex grounding is shared by
both. **School** = topic is *pushed* (teacher's daily class decides it) + transcript
grounding (falling back to NCERT for that exact section if there's no recording).
**Self** = topic is *pulled* (student/parent picks a chapter) + NCERT grounding only.
Self-study is therefore a **capability available to everyone**; enrollment type only
decides the *default daily experience*. ✅ The flag is carried as a `mode` token claim
(`school|self`) sourced from `tenants.type` + `users.enrollment.type`; the content-resolver
branch that consumes it is ⏳ (syllabus pacing deferred).

Encoded as: `tenants.type ∈ {school, direct}` and `users.enrollment = { type, class_no, section?, board }` (§4).

---

## 2. Stakeholders, roles & relationships

| Role | Belongs to | Created by | Primary device | Auth method (v1) |
|---|---|---|---|---|
| **Superadmin** | platform (cross-tenant) | bootstrap/internal | desktop | email + password + **MFA** |
| **School admin** | one tenant | superadmin (at school onboarding) | desktop | email + password (+ optional MFA) |
| **Teacher** | one tenant | school admin | mobile/desktop | email **or** phone + password / OTP |
| **Parent** | one tenant\* | self-claims via school invite (OTP); roster seeds the phone | mobile (family device) | **phone + OTP** |
| **Student** | one tenant + class + section | school admin seeds the roster; **parent claims & manages** the child | **family / own device** (home) | **family mode (primary, §3.3)** · school-device PIN (§3.1) · SSO (later) |

\* A parent is anchored to one tenant but linked to **one or more students** (their
children). Cross-tenant parents (children in different schools) are a v2 concern.

> **Teachers have zero identity/auth responsibilities** — they never provision, reset,
> unlock, or recover student logins. Student auth is rooted in the **parent** (home) or
> the **school admin** (school-issued devices). This matches the after-school usage
> context (§3).

**Hierarchy / who-creates-whom**

```
Superadmin
  └── creates School (tenant) + first School Admin
        └── School Admin
              ├── creates Teachers
              ├── creates Classes / Sections, assigns teachers (subject)
              ├── imports Students (roster CSV) → auto-generates credentials
              └── invites/links Parents to students
```

**Capability matrix (server-enforced via `require_role`)**

| Capability | Student | Parent | Teacher | Admin | Superadmin |
|---|:--:|:--:|:--:|:--:|:--:|
| Consume own summary/mindmap/story/quiz | ✅ (self) | – | – | – | – |
| View own progress / streak | ✅ (self) | ✅ (their child) | ✅ (their class) | ✅ (school) | – |
| Record class / generate lesson plan / quiz | – | – | ✅ | ✅ | – |
| View class insights / interventions | – | – | ✅ (own class) | ✅ (school) | – |
| Manage teachers / students / classes / roster | – | – | – | ✅ | – |
| Parental controls (child lock / limits) | – | ✅ (their child) | – | – | – |
| Create schools / school admins | – | – | – | – | ✅ |
| Cross-tenant access | – | – | – | – | ✅ |

---

## 3. The core challenge — student login without email/phone

Students (especially younger) typically **cannot** self-register or do email/SMS OTP.
Identity for students is therefore **always provisioned for them**, never self-signup.

**Usage context drives the design:** this is a **home / after-school revision** app. The
daily device is the **family/parent device or the student's own device** — there is no
classroom, no proctor, no daily card-scanning, and **teachers have no role in student
authentication** (they teach; they never provision, reset, or unlock student logins).

Therefore the **primary student path is a parent-anchored family account** (§3.3): the
**parent is the root of trust, recovery, and DPDP consent**. A school-issued device path
(Student Code + PIN, §3.1) is a **secondary** option for schools that run it in-school.
**QR is for one-time onboarding/linking, not daily login** (§3.2). All paths resolve to
the same JWT + session model, and a long rotating refresh keeps everyone "stay signed in".

### 3.0 Tenant resolution — the student never *types* a school code
The tenant (school) must be known at the **API layer** so the `student_code`/PIN lookup
is scoped to one school (two schools can both have "roll 7"). But the **student should
not type a school code every login**. We resolve the tenant from context, in priority:

1. **School-bound app / device** — a school-issued tablet or the school's branded build
   carries its `tenant` in config; login is already "inside" the school.
2. **Subdomain / deep link / QR** — `dav-hyd.mymedha.app` or a school link/QR resolves
   the tenant from the URL.
3. **First-run, then remembered** — the student (or teacher setting up the device) picks
   the school **once**; the app stores it locally and skips it thereafter.
4. **Family mode** — the parent's token already carries the tenant; the child switch
   needs nothing typed.

So: **tenant is always required server-side, but typed by a student `0` times/day.** The
daily flow is just "**tap your name + PIN**" (or scan a card).

> **What "subdomain" means here:** a per-school web address, e.g. `dav-hyd.mymedha.com`
> (the prefix `dav-hyd` = the tenant). The school gets its unique link at onboarding; when
> a user opens it, the frontend reads the prefix and resolves the tenant — no code typed.
> On **mobile (Capacitor)** the equivalent is a **deep link** (`mymedha.com/s/dav-hyd`),
> a one-time first-run school-code entry, or a school-branded build.
>
> **For the home/parent-primary product this is mostly moot:** in family mode the
> **parent's account already carries the tenant** (set at signup/claim), so daily login
> needs no resolution at all. Subdomain/school-code matters only at **parent signup** and
> on the **school-device student path**.

### 3.1 Secondary (school-issued device) — Student Code + PIN
*For schools that run the app on school tablets in a study period. Not the default for the
home product.*
- At login the client sends `{ tenant (from context, §3.0), student_code, pin }`. The
  student enters **only** their code (or picks their name on a shared device) + a **PIN**.
- **`student_code` is opaque and non-sequential** (e.g. `DAVH-9A-7Q3K`), *not* the roll
  number — roll number is for **display only**. This removes the "guess the next id"
  attack (see §3.5).
- Admin (never the teacher) generates credentials in bulk during roster import and
  distributes printable **login slips**. Optional **forced PIN change on first login**.
- **PIN is randomly generated** (never `1234`/DOB); **reset by the school admin** (or the
  parent if the child is also linked). **Brute-force lockout** + rate limiting (§3.5 / §9).
- A **rotating refresh token** keeps the student signed in on that device.

### 3.2 Onboarding / linking aid — QR & invite links (NOT daily login)
QR is a **one-time** convenience, never a daily ritual:
- **Parent claims a child**: the school roster carries the parent's phone; the parent gets
  an SMS **invite link / QR**, taps it, verifies via **OTP**, and the child is linked to
  their family account (consent captured here).
- **Device pairing**: scan once to bind a new device to an existing account.
- It does **not** replace daily login — at home the parent is already signed in (§3.3).

### 3.3 **Primary (home) — Parent-anchored family mode**
The default for the after-school product. Models a streaming-style family account:
- The **parent signs in once** with **phone + OTP** and **stays signed in** on the family
  device (long rotating refresh).
- The parent sees their **child profiles** and **taps a child** to enter **kid mode** — no
  email, no phone, no school code, nothing for the child to type.
- Optional **child profile PIN** as a *soft* lock to separate siblings; **set/reset by the
  parent** (not the teacher). Because access is already gated by the parent's
  authenticated device, the child PIN is low-stakes (see §3.5).
- The **parent is the root of trust**: provisioning a child, PIN reset, recovery, and
  **DPDP consent** all run through the parent — **zero teacher involvement**.
- Session is the child's identity (`sct` claim), scoped + policy-enforced (§7).

> **Two ways "kid mode" is reached — don't confuse them:**
> - **Family-switch on the parent's *own* phone** (§3.3) — the parent hands over their
>   phone momentarily. Reuses the **parent session**; mints a kid token (`sct`+`pid`),
>   no new refresh. Fine because the parent is present. ✅
> - **A dedicated/shared *learning device*** (the canonical "stay signed in") — the
>   device holds its **own device-bound, student-scoped session** that can *never* mint
>   a parent token. This is the §3.7 pairing flow and is the safe way to leave a tablet
>   logged in at home. ✅ Prefer this for any device the child keeps.

### 3.4 Optional per-school — SSO (Google Workspace for Education / Microsoft)
- If the school issues student Google/MS accounts, enable **OIDC SSO** for that tenant.
  Highest convenience where available; falls back to 3.1/3.2 otherwise.

> **Decision:** v1 ships **3.3 (parent-anchored family mode) as the primary path** +
> parent claim/onboarding; **3.1 (school-device Student Code + PIN)** for in-school
> tenants; **3.2 (QR/invite)** for one-time linking; **3.4 (SSO)** per-tenant opt-in
> later. All resolve to the same JWT + session model (§5). **Teachers are never in the
> student-auth loop.**

### 3.5 Preventing student-to-student impersonation
**Threat:** a child tries to log in as a classmate by guessing a sequential id + a weak
PIN. Low-sophistication, in-person; limited blast radius (sees/edits another child's
learning content + quiz score), but still violates trust and **DPDP** (one child must
not access another's data). Defenses, in order of effectiveness:

1. **Non-guessable login identifier** — auth uses the opaque `student_code`, *not* the
   roll number. (On a shared tablet, "pick your name" is acceptable because the name is
   not the secret — the PIN is.)
2. **Non-pattern secret** — PINs are **randomly generated**, never `1234`/DOB; optional
   forced change on first login. Length 4–6 (configurable per school).
3. **Lockout defeats guessing** — after **N failed attempts** (default 5) on a
   `student_code`, lock for a cooldown and require a **parent reset (home)** or
   **admin reset (school device)** — *never a teacher*; plus per-device/IP rate limits.
   This is the single most important control on the PIN path.
4. **Parent-rooted auth removes guessing entirely** — in **family mode (§3.3, the primary
   path)** the root of trust is the **parent's phone OTP**; the child PIN is only a soft
   sibling-separator, so cross-student guessing isn't even a meaningful attack at home.
5. **Audit + alert** — log every login to `audit_log`; surface repeated failures / logins
   from an unusual device to the **parent** (and school admin).

> Bar: make guessing *impractical* (opaque id + random PIN + lockout), not bank-grade.
> Family mode eliminates the risk for the home product. Account-takeover consequence is
> bounded anyway because a student can only ever touch their **own** `student_id`
> (ownership check, §6).

### 3.6 Older students (post-10th) — individual self-login *(designed-for, later)*
Classes 11–12 students usually **have their own phone/email**, so they get a **direct
individual account** (phone/email + OTP), no parent anchor required. Same JWT/session
model; just another login method that resolves to a `role=student` token. Build when the
product expands past Class 10.

### 3.7 **Trusted Learning Devices — device-bound, student-scoped sessions** ✅
The canonical "stay signed in on a tablet" mechanism, and the fix for the one real gap in
plain family-switch (a parent-session refresh token sitting on a child's device could be
used to mint a *parent* token). Modeled on the **OAuth Device Authorization Grant
(RFC 8628)** — the smart-TV "enter this code" flow — *inverted*: the already-authenticated
parent phone **issues** a one-time grant; the tablet **consumes** it.

**Pairing (one-time).** Parent (with **fresh** auth, §6 step-up) taps *Add Learning Device*
→ server mints a **single-use grant** rendered as **a QR token + a 6-digit code**
(`PAIRING_TTL_MIN`, default 5 min). The tablet scans the QR (primary) or types the code
(fallback) → server issues the device its session. *Not an either/or — one grant, two
representations.*

**The device session (the security boundary).** A paired device gets a session with
`scope="device"`, owned by the parent but **restricted to `allowed_students`**. Its
refresh token can **only ever mint `role=student` tokens for those children — never a
parent token**, even on silent refresh. (Proven in tests: a device refresh cannot
escalate to parent.)

**Dedicated vs shared is one flow, not two.** Every device pairs to the **family**.
A `pinned_student_id` makes it "dedicated" — it opens straight into that child. Without a
pin it's "shared" — it shows a **"Who's learning?"** profile selector (`/auth/device/switch`,
soft-PIN gated per child). No second pairing path.

**Management.** Parent sees a **Learning Devices** list and can **Remove** a device
(revokes all its sessions — lost/stolen tablet) — both step-up-gated. ✅

**Pairing grant properties (security):** short TTL · single-use (atomic consume) ·
bound to the issuing parent + specific child(ren) · QR carries a high-entropy token, the
6-digit code is the convenience fallback. ✅

> **Decision:** the **device-bound session is the primary stay-signed-in path** for any
> child-kept device; family-switch (§3.3) remains for the parent's-own-phone hand-over.
> Both resolve to the same `role=student` token model. ✅

---

## 4. Identity data model

New/changed collections (Mongo). All per-tenant collections carry `tenant`.

### `tenants` (schools)
```jsonc
{ "_id", "tenant": "dav-hyd", "school_code": "DAV-HYD", "name": "DAV Public School",
  "board": "CBSE", "status": "active",
  "type": "school" | "direct",          // content axis (§1.6): school=transcript, direct=B2C self-study
  "sso": { "provider": null, "domain": null },
  "settings": { "student_login": ["pin","family"], "consent_required": true },
  "group_id": null,                      // dormant — future school groups (§12.2)
  "created_by": "<superadmin_id>", "created_at" }
```

### `users` (one collection, all roles)
```jsonc
{ "_id", "tenant": "dav-hyd",
  "role": "student | parent | teacher | admin | superadmin",
  "status": "active | invited | suspended",
  // identifiers (sparse — students may have none of email/phone):
  "email": null, "phone": "+9198…",
  "student_code": "DAVH-9A-7Q3K",   // opaque, non-sequential — login id (NOT roll no)
  "roll_no": "7",                    // display only, never used to authenticate
  "username": null, "sso_subject": null,
  // credentials (never plaintext):
  "password_hash": null, "pin_hash": null,
  // lockout (anti-guessing, §3.5):
  "failed_attempts": 0, "locked_until": null, "must_change_pin": false,
  // profile:
  "name": "Aarav S", "avatar": "...", "class_no": 9, "section": "A",
  // enrollment / content axis (§1.6) — students only:
  "enrollment": { "type": "school", "class_no": 9, "section": "A", "board": "CBSE" },
  "first_login_at": null, "created_by", "created_at" }
```
Indexes (unique, partial where nullable):
`(tenant, email)`, `(tenant, phone)`, `(tenant, student_code)`, `(tenant, student_id)`, `(tenant, role)`. ✅

### `parent_links` (parent ↔ student, first-class)
```jsonc
{ "_id", "tenant", "parent_id", "student_id", "relationship": "mother|father|guardian",
  "consent": { "granted": true, "granted_at", "method": "otp", "scope": ["learning","progress"] },
  "status": "active", "created_at" }
```

### `sessions` (refresh tokens — rotation + revocation) ✅
```jsonc
{ "_id", "tenant", "user_id", "device_id", "refresh_token_hash",
  "scope": "full" | "device",            // "device" = student-scoped, cannot mint a parent token (§3.7)
  "allowed_students": ["STU-…"],         // device sessions: which children this device may open
  "pinned_student_id": null,             // dedicated device → default profile
  "auth_time": 1719500000,               // epoch of last STRONG auth — drives step-up (§6); not advanced by silent refresh
  "label": "Aarav's tablet",
  "issued_at", "expires_at", "rotated_from", "rotation_count", "revoked": false, "user_agent" }
```

### `devices` (trusted learning devices) ✅
```jsonc
{ "_id", "tenant", "device_id", "parent_id", "label",
  "allowed_students": ["STU-…"], "pinned_student_id": null,
  "session_id": "<sessions._id>", "trusted": true, "last_seen", "created_at", "revoked_at": null }
```

### `pairing_grants` (one-time device-pairing grant — QR + code) ✅
```jsonc
{ "_id", "tenant", "parent_id", "student_ids": ["STU-…"], "pinned_student_id": null,
  "code": "048213", "qr_token_hash": "<sha256>", "label",
  "consumed": false, "consumed_at": null, "created_at", "expires_at" }   // TTL index on expires_at; single-use
```

### `student_policies` (foundation for child-lock / monitoring — §7)
```jsonc
{ "_id", "tenant", "student_id", "set_by": "<parent_id>",
  "locked": false, "daily_minutes_limit": 60, "allowed_hours": { "start": "15:00", "end": "21:00" },
  "content_filters": [], "updated_at" }
```

### `audit_log` (security + parental-visible activity)
```jsonc
{ "_id", "tenant", "actor_id", "action", "target", "ip", "at" }
```

> Existing `students` data migrates into `users` (role=student) with `tenant` +
> `student_code` + `pin_hash`; existing teacher/parent docs likewise.

---

## 5. Tokens & sessions

- **Access token** — JWT, short-lived (**15–30 min**, default 30). Claims: ✅
  `{ sub, role, tenant, sid, sct, kids, pid, auth_time, mode, did }`
  - `sct` = active student in kid/family/device mode · `kids` = a parent's linked students
  - `pid` = parent behind a kid-mode (family-switch) token, for provenance
  - `auth_time` = epoch of last **strong** auth → step-up (§6); copied from the session,
    **not** advanced by silent refresh
  - `mode` = content source `school|self` (§1.6) · `did` = paired device id (device sessions)
- **Refresh token** — opaque, long-lived (**default 60 days**), **rotating**, stored hashed
  in `sessions`, **device-bound** (Capacitor + "stay signed in" so kids don't re-enter a PIN).
- **Session scope is a hard boundary** — a `scope="device"` session refresh returns **only**
  a `role=student` token for its `allowed_students`; it can never produce a parent token (§3.7). ✅
- **Verification is stateless** — role + tenant come from the signed JWT, so the hot
  path does **no DB lookup** for authz (scales). DB is touched only on login/refresh.
- **Revocation** — short access TTL + refresh rotation + `sessions.revoked` (logout /
  compromise / admin force-logout). Optional small denylist for instant access-token kill.
- **Signing** — HS256 with a strong `JWT_SECRET` (Key Vault) for v1; migrate to RS256
  (rotatable public keys) when an edge/gateway verifies tokens.

---

## 6. Authorization & tenancy enforcement

1. **`get_current_user`** dependency — verifies the JWT, returns `{user_id, role, tenant, sid, sct, pid, kids, claims}`. ✅
2. **`get_tenant` derives from the token**, *not* the `X-Tenant-ID` header — with a
   **header fallback during migration** (legacy clients + internal worker calls). Once a
   valid token is present, tenant is taken from it. ✅ (Superadmin may still pass an explicit
   tenant to act within a school.)
3. **`require_role("teacher","admin")`** dependency on protected routers. ✅
4. **`require_fresh_auth(...)` — step-up (AAL).** Sensitive actions (pair a device, change
   settings, recovery) require the token's `auth_time` to be within `FRESH_AUTH_WINDOW_MIN`
   (default 10 min). A silently-refreshed token does **not** advance `auth_time`, so a stale
   session is forced to **re-verify OTP** before the action → `401 reauth_required`. ✅
5. **Resource ownership** — students/parents may only touch their own (or their child's)
   `student_id`; enforced in the handler, not just by tenant. ⏳ (enforcement sweep)
6. The **internal `api_key`** is retained only for **service-to-service** calls (the
   transcription/summary worker), never for end users. ✅

This replaces the current single `api_key_guard` gate. The ADR-009 tenant filters stay;
they now receive a **trustworthy** tenant.

---

## 7. Parental controls / "child lock & monitor" (design now, build later)

The business may later ask for child-lock + monitoring. We make it cheap to add by
baking the primitives in now:

- **Linkage**: `parent_links` makes parent→student first-class (already in §4).
- **Policy**: `student_policies` (lock flag, daily time limit, allowed hours, content
  filters) — **parent-editable for their own child only**.
- **Enforcement points**:
  - Token issuance refuses a kid session outside `allowed_hours` or when `locked`.
  - The app enforces `daily_minutes_limit` from a usage counter; server is source of truth.
- **Monitoring (parent view)**: reuse `student_daily_progress` + `audit_log`/usage to
  show the parent their child's activity, time spent, and completion.
- **Compliance — DPDP Act 2023 (India)**: minors' data needs verifiable consent. **Mode
  decides the authority:**
  - **B2B (pilot):** the **school is the consent authority / guardian-proxy** —
    institutional consent captured in the school agreement + a `tenants.consent` record.
  - **B2C (later):** **verifiable parental consent** captured at parent signup
    (`parent_links.consent`).
  - Monitoring is always **parent/guardian-initiated for their own child** (oversight, not
    platform surveillance); **data minimization** + **consent-withdrawal** supported.
    *(Legal to confirm the B2B school-proxy stance.)* Build the consent gate before the
    monitoring UI.

> Explicitly out of v1 scope to *build*, but the schema + token checks above mean it's
> additive later.

---

## 8. API surface (v1)

**Auth**
- `POST /auth/login/password` — admin/teacher/superadmin (email/phone + password).
- `POST /auth/login/student` — `{ tenant, student_code, pin }`. **`tenant` is resolved
  from context** (school-bound device / subdomain / first-run choice / QR — §3.0), *not*
  typed by the student each time. `student_code` is the opaque code (§3.1), not roll no.
- `GET /auth/resolve-tenant?school_code=DAV-HYD` — one-time helper to turn a
  human-entered school code (or subdomain) into the `tenant` the app then remembers.
- `POST /auth/login/qr` — `{ qr_token }` (carries tenant + student; possession-based, §3.2).
- `POST /auth/login/otp/request` + `/auth/login/otp/verify` — parent (phone OTP).
- `POST /auth/family/switch` — parent → kid-mode token for a linked `student_id`. ✅
- `POST /auth/refresh` — rotate (scope-aware: device sessions stay student-scoped); `POST /auth/logout` — revoke session. ✅
- `GET /auth/me` · `GET /auth/children` (parent) · `GET /auth/resolve-tenant?school_code=…`. ✅
- `POST /auth/sso/{tenant}/callback` — OIDC (later). ⏳

**Trusted devices (§3.7)** ✅
- `POST /parent/devices/pair/start` — parent (**step-up**) mints a one-time grant → `{ code, qr_token, expires_in, students }`.
- `POST /auth/device/claim` — device (no token) consumes `{ device_id, code|qr_token }` → student TokenPair + profile list.
- `POST /auth/device/switch` — shared device "Who's learning?" → `{ student_id, pin? }` (device token only).
- `GET /parent/devices` — list trusted devices · `DELETE /parent/devices/{device_id}` — revoke (**step-up**).

**Onboarding (role-guarded)**
- Superadmin: `POST /admin/tenants`, `POST /admin/tenants/{t}/admins`.
- School admin: `POST /school/teachers`, `POST /school/classes`,
  `POST /school/students:import` (CSV with **parent phone per student** → seeds `users`
  + `parent_links` (pending) + sends parent invites), `POST /school/students/{id}/reset-pin`
  (school-device path only).

**Parent (self-service — no teacher/admin in the loop for daily auth)**
- `POST /parent/claim` — accept invite → OTP → activate `parent_links` + **consent**.
- `GET /parent/children`, `POST /parent/children/{id}/pin` (set/reset child soft-PIN).
- *(later)* `GET/PUT /parent/children/{id}/policy`, `GET /parent/children/{id}/activity`.

---

## 9. Security considerations

- **Password hashing**: Argon2id (or bcrypt). **PIN**: hashed too (with the same KDF),
  randomly generated, never a pattern; **per-student brute-force lockout** (5 tries →
  cooldown → teacher reset) + per-device/IP rate limits. **Login id is the opaque
  `student_code`, not the roll number** (§3.5).
- **OTP**: 6-digit, 5-min TTL, rate-limited per phone + per IP; never logged.
- **Token**: rotation, device binding, short access TTL; secrets in **Key Vault**.
- **Transport**: HTTPS only; CORS locked to known origins (currently `*` — fix).
- **🔴 P0**: rotate the **secrets committed in `populate_mock_data.py`** and remove
  hardcoded creds before anything else.
- **Least privilege**: superadmin actions audited; admin scoped to own tenant.

---

## 10. Migration from the current state

1. Keep `api_key_guard` for **internal worker calls** only; introduce `get_current_user`
   for user-facing routes.
2. `get_tenant` reads the token (fallback to header only for internal/worker calls).
3. Migrate `students`/teacher/parent docs → `users` (+ `tenant`, `student_code`,
   `pin_hash`); seed a superadmin + the pilot school.
4. **Backfill `tenant`** on any legacy docs missing it (ADR-009 regression note).
5. **Worker tenant fix**: map `schoolId` (from the audio blob/filename) → `tenant` so
   worker-created `classes_daily` are attributed to the right school (today they default
   to `demo-school`).
6. Frontend: replace the mock login with the real `/auth/*` flows; store tokens
   securely (Capacitor secure storage); drop hardcoded `student_id`/class/section.

---

## 11. Phased delivery plan

Re-ordered for the **home-first** product: the parent-anchored family path is primary, so
it lands in P1, not late.

| Phase | Deliverable | Notes |
|---|---|---|
| **P0** | Rotate committed secrets → Key Vault; lock CORS | Blocker; ops + small code |
| **P1** ✅ | Core auth: `users` model, JWT access+refresh, `get_current_user`, `require_role`, **tenant-from-token**; **parent phone-OTP login + family mode**; admin/teacher password login. **+ device-bound trusted devices (§3.7) + step-up + two-axis `mode`.** | **Built & tested** (backend + FE login). Tenant isolation real; students have a working home login + device pairing |
| **P2** ⏳ | Onboarding: superadmin→school→admin; roster CSV import (**seeds parent phone**) → **parent invite/claim + DPDP consent**; teacher/class management; **worker schoolId→tenant** | Lets a real school self-stand-up; parents self-onboard |
| **P3** ✅* | School-device path: `student_code` + PIN + **lockout** (for in-school tenants) | *Backend built+tested; pulled forward into P1. Optional per school |
| **P4** | *(Backlog)* Parental controls: `student_policies` (lock, time limits, hours) + parent activity view | **Not a strict v1 item** (§15). Build only if cheap on top of family mode; primitives already designed-for |
| **P5** | QR/invite-link polish; SSO (OIDC) per tenant; RS256 keys; MFA for admin/superadmin | Convenience + enterprise |

Frontend work (login screens per role, token storage, role routing) tracks each phase;
the **parent + kid-profile** screens are P1.

---

## 12. Decisions (locked from review)

1. **Student primary login = parent-anchored family mode (§3.3).** Parent phone-OTP → tap
   child profile. School-device Student Code + PIN (§3.1) is secondary for in-school
   tenants. **No teacher in the auth loop.** ✅
1b. **Tenant binding.** Daily: tenant comes from the **parent's account** (nothing typed).
   At parent signup + school-device path: **web = subdomain**, **mobile = deep link /
   first-run school code / branded build**. ✅
2. **Tenant = single school** (no groups now). Keep a dormant `group_id` field for future
   grouping; no work today. ✅
3. **Two go-to-market modes** (see §1.5): **B2B (pilot)** — school onboards, roster seeds
   parent phones, parents claim child; **B2C (later)** — direct parent signup, NCERT
   self-study content; **older students (post-10th)** — individual self-login later. Parent
   + family mode is **P1**. ✅
4. **SSO — not now.** Stays P5 / later. ✅
5. **DPDP consent — B2B: school is the consent authority/guardian-proxy** for the pilot;
   B2C: parental consent. *(Legal to confirm school-proxy.)* ✅
6. **Sessions:** short access token **auto-refreshes silently** via the long rotating
   refresh token — access-token expiry is **not** a logout, so a child is never kicked out
   mid-revision. Real logout = refresh revoked or its long window (e.g. 60 days) / inactivity
   elapses. ✅

7. **Identity root = Student; Parent = authenticator (not the root aggregate).** Three
   auth sources (parent / self / school) resolve to the same student token. A student can
   exist with no parent (school-managed / no-smartphone cohort). ✅
8. **Trusted Learning Device = device-bound, student-scoped session (§3.7).** The primary
   stay-signed-in path for child-kept devices; refresh can never escalate to a parent
   token. Pairing = one-time grant as **QR + 6-digit code** (single-use, 5-min TTL). One
   pairing flow; `pinned_student_id` = dedicated, else shared selector. ✅
9. **Two-axis identity (§1.6).** Auth source × content source are independent. Content
   source (`school|self`) lives on `users.enrollment` / `tenants.type` and rides as a
   `mode` claim. Syllabus pacing for self-study is deferred. ✅
10. **Step-up (AAL) for sensitive parent actions** via `auth_time` + `require_fresh_auth`
    (default 10-min freshness) → else `reauth_required`. ✅

**Parameters — resolved:** refresh-token window **60 days** ✅ · OTP **6-digit / 5-min** ✅ ·
student & child PIN length **4** (configurable per school) ✅ · pairing code **6-digit / 5-min,
single-use** ✅ · step-up window **10 min** ✅. Still pilot-dependent: whether the school
supplies **parent phone numbers** in the roster (enables auto-invite vs. school-distributed
link) — a data question, not a design one.

---

## 13. Scalability notes

- **Stateless JWT** → authz adds no DB round-trip; horizontal scale is trivial.
- **Per-tenant data is small** (K-12); no sharding needed. Compound `(tenant, …)` indexes
  cover query isolation + performance.
- **Auth lives in the existing FastAPI** initially (no separate service); it can be
  carved out later behind a gateway using the same JWT contract.
- **Multi-tenant onboarding** is data-driven (create a `tenants` row + admin); no
  per-tenant deploys.

---

## 14. Mobile app (Capacitor) considerations

The frontend ships as a **Capacitor** hybrid app (iOS/Android) as well as web. The auth
architecture maps cleanly to native — several pieces are *better* on mobile.

**Works well / better on mobile**
- **Token storage** → **Capacitor Secure Storage** (iOS Keychain / Android Keystore) for
  the **refresh token**; keep the **access token in memory**. More secure than browser
  localStorage.
- **Parent phone-OTP** → the native SMS flow (Android can auto-read the code via the SMS
  Retriever API). The ideal mobile login.
- **Stay signed in / silent refresh** → persistent app + secure refresh token means a kid
  never re-logs-in; refresh silently on app launch/resume.
- **Family mode / profile switch** → pure in-app UX.
- **Biometric unlock** (enhancement) → parent unlocks with Face ID / fingerprint instead
  of re-OTP.
- **QR onboarding** → native camera / barcode plugin (onboarding only, §3.2).

**App-specific setup (not blockers — configuration)**
- **Deep links = the mobile replacement for subdomains.** Configure **Universal Links
  (iOS)** + **App Links (Android)** so the SMS invite link (`mymedha.com/s/dav-hyd…`)
  opens the app and passes the tenant / claim token. Requires associated-domains entitlement
  + `/.well-known/assetlinks.json` & `apple-app-site-association`.
- **CORS / WebView origin** — native requests originate from `capacitor://localhost`
  (custom scheme), not a browser origin; the API must allow the app scheme (separate from
  the web CORS rule).
- **`VITE_API_URL`** must point at the **prod API** in the app build (never localhost).
- **Offline / reconnect** — JWT auth needs connectivity; keep access-token validity
  comfortable and refresh on reconnect. Content can be cached; auth cannot.
- **Push notifications** (later) — Capacitor Push for parental alerts (failed-login,
  child-lock events).

**Honest caveat — "child lock" on a device.** An app can fully enforce **in-app** limits
(daily minutes, allowed hours, lock a profile) and parent monitoring. But **device-level
lockdown** (stopping the child from leaving the app) is an **OS feature**, not an app
capability — **Android Screen Pinning** / **iOS Guided Access**, both parent-initiated on
the device. We deliver child-lock as **in-app usage control + monitoring**, and document
device lockdown as an OS instruction, not a build item.

---

## 15. Status of parental controls / child-lock — **backlog**

Per product call: **not a strict v1 requirement.** We've designed the **primitives** so
it's additive later (`parent_links`, `student_policies`, consent, `audit_log` — §4, §7),
but the feature itself (P4) is **backlog**: build it **only if it turns out cheap** to add
on top of the parent + family-mode foundation; otherwise defer with no architectural debt.
Nothing else in the plan depends on it.

---

---

## 16. Implementation status (what's built vs pending)

**Built & tested ✅** (backend, verified end-to-end on a separate `mymedha_auth_test` DB —
22/22 checks incl. the device security boundary + step-up):
- `users` / `tenants` / `parent_links` / `sessions` / `otp_codes` / `audit_log` collections + indexes.
- JWT access (`auth_time`/`mode`/`did`/`sct`/`kids`/`pid`) + opaque rotating refresh (60-day).
- `get_current_user`, `require_role`, **token-aware `get_tenant`** (header fallback), `require_fresh_auth`.
- Login: password (teacher/admin/superadmin), student `code+PIN` (+ lockout), **parent phone-OTP**,
  **family-switch**, refresh (scope-aware), logout.
- **Trusted devices (§3.7):** `devices` + `pairing_grants`; pair-start (step-up) → claim →
  **device-bound student-scoped** refresh (cannot escalate to parent) → switch / list / revoke.
- Two-axis identity: `tenants.type`, `users.enrollment`, `mode` claim. Seed script (`app.scripts.seed_auth`).
- **Frontend P1:** token store + authenticated `apiClient` (silent refresh) + `AuthService` +
  multi-role `LoginPage` (incl. parent OTP → kid-mode) + student data-calls migrated.

**Pending ⏳:**
- **Frontend device-pairing screens** — parent "Add Learning Device" (show QR/code), tablet
  claim screen, device "Who's learning?" selector.
- **Enforcement sweep** — migrate all routers to `require_role` + ownership checks; point every
  service at the authenticated client (≈18 call-sites still header-only, single-tenant-safe).
- **Capacitor secure token storage** (Keychain/Keystore) — currently localStorage.
- **Real SMS provider** for OTP (dev-echoed today) — `otp_service._send_sms`.
- **P2 onboarding** — roster CSV import → parent invite/claim + DPDP consent; worker `schoolId→tenant`.
- **Content-resolver branch** consuming the `mode` claim (school transcript vs NCERT self-study).
- **P0 ops** — rotate committed secrets; lock CORS.
- Parental controls / child-lock (§7, §15) — **backlog**.

*Decisions locked (§12). v2 device-bound model implemented; next concrete step is the
frontend device-pairing UI, then the enforcement sweep.*
