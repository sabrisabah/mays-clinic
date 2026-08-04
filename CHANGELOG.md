# Changelog

All notable changes made to the Dr. Mais Al-Rubaie Nutrition Clinic system, grouped by area. This is a running log of the system's evolution, not a step-by-step build history.

## Branding

- Clinic name updated to "Dr. Mais Al-Rubaie Nutrition Clinic" (Arabic: عيادة دكتورة ميس الربيعي للتغذية) across every page title, the top navigation bar, the logo alt text, and the Django admin site header/title.
- New clinic logo (gold apple/heart/stethoscope mark) applied across all patient, doctor, and secretary pages.

## Roles & Access Control

The system now supports three account roles instead of two:

- **Doctor** — full access to every clinical and administrative feature.
- **Secretary** (new) — front-desk role with access to: patient registration, the patient list, the assessment form, the follow-up file, and appointment scheduling. Nutrition plans, lab test tracking, Mounjaro dose tracking, weight-progress tracking, and doctor notes remain doctor-only and are hidden from the secretary's view.
- **Patient** — self-service portal, scoped to their own record only.

Secretary accounts are provisioned by a doctor/administrator through the Django admin panel (Users section, role = "secretary"); there is no public self-signup for this role.

## Patient Portal

- The assessment form locks automatically after the patient's first save. Once submitted, the patient can view but no longer edit their own answers — only a doctor (or secretary, for the fields in scope) can make further changes. A banner explains this to the patient.
- The "current weight" field was removed from the patient-facing treatment-goal section (it remains available in the doctor/secretary view). "Target weight" is unaffected.
- The Mounjaro dose-tracking page and the weight-progress-tracking page were removed from the patient interface entirely. Both remain available in the doctor interface.
- The follow-up record's diet plan (type, details, calorie target) is visible to doctor/secretary only and is hidden from the patient's follow-up view; the patient still sees their treatment/prescription, next-appointment interval, and insulin-resistance value.

## Doctor & Secretary Portal

- **Lab test tracking**: five additional lab markers were added (Prolactin, Testosterone, Anti Glia Ab, H. Pylori, and a free-text "Other" field), and a dedicated "Lab Test Follow-up" tab was added to the patient file. Because labs are typically repeated monthly, this is a running dated log (like the Mounjaro and progress logs) rather than a single overwritten value. This tab is doctor-only.
- **Prescription structure**: the treatment/prescription field was split into three parts — an injections section (Mounjaro / Ozempic / dissolving injections, multi-select), a free-text medications & supplements section, and a standalone fat-burning-sessions toggle.
- **Next scheduled visit**: the follow-up tab now computes and displays the next expected visit date automatically, based on the follow-up interval the doctor sets (e.g. "in 2 weeks") relative to the most recent recorded update — this had previously failed to display.
- **Appointment scheduling**: each patient's visit record now carries a specific date and time (not just a date), settable and editable by the doctor or secretary at registration or at any later point.
- **Arrival tracking & alert**: a patient's appointment carries a "checked in" flag. Starting one hour before a scheduled appointment, if the patient hasn't been marked as arrived, their row is highlighted in red on both the secretary dashboard and the doctor's view, with a "Patient Arrived" action that clears the alert. The alert persists (it does not clear itself with time) until a staff member acts on it.

## Secretary Dashboard (New)

- A dedicated dashboard lists every patient with their file number, name, phone, and upcoming appointment (date + time, editable inline), plus a status badge (arrived / not arrived) and the red-alert highlighting described above.
- A "Register New Patient" page lets the secretary create a new patient account (name, age, gender, phone, address, occupation, visit date & time, and an initial password) without ending her own session — a deliberate safeguard, since the underlying registration endpoint issues a login token for the new patient and that token is not applied to the secretary's browser session.
- The secretary can open any patient's full file (profile, assessment form, follow-up record) through the same file view used by the doctor, with the medical-only tabs hidden.

## Bulk Data Management (Django Admin)

Two areas of the Django admin now support bulk Excel import and export, without any custom front-end page:

- **User accounts**: export produces an Excel file with account fields (email, name, phone, role, active/staff status); it deliberately excludes the password field so that re-importing an exported file can never leak or corrupt a password hash. Import can create new accounts or update existing ones (matched by email); a password column is optional on import — leave it blank to keep an existing password unchanged, or fill it in to set/reset one (it is hashed automatically, never stored as plain text). Importing a "patient" role row only creates the login account, not the full clinical patient file — new patients should still go through the registration page so their file number and profile are created correctly.
- **Assessment forms**: export/import is matched by the patient's file number (the patient must already exist). Derived fields — BMI, BMI classification, waist-hip ratio, WHR classification, and activity level — are recomputed automatically from the imported weight, height, waist, hip, and exercise-frequency values using the same formulas the live application uses; any value typed directly into those derived columns in the spreadsheet is ignored, so bulk edits can't leave the data internally inconsistent. List-type fields (medical history, digestive issues, weight-loss medications) are exchanged as JSON arrays.

## Clinical Calculations

- **BMI classification** follows the WHO six-tier grading table: underweight, normal weight, overweight, and obesity grades I/II/III, replacing the previous simpler breakdown.
- **Activity level** is derived automatically from weekly exercise frequency rather than entered manually: sedentary, light activity, regular activity, and high activity, each mapped to its corresponding calorie-multiplier used in the calorie recommendation.

## Infrastructure

- The application is version-controlled on GitHub and deployed on Railway, serving the API and the static front-end from a single service with a persistent storage volume for the database.
- Deployment builds from the full repository root so that the backend and front-end directories are packaged together consistently.
