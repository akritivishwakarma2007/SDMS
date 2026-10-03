# SDMS: Smart Donation Management System

> **Vision-verified, cryptographically sealed, tamper-evident cash donation counting and audit platform for Indian Currency.**

Recognizes Indian banknotes from images using deep learning (`currency_model_final.keras`), records every donation into an append-only MongoDB hash-chained ledger, routes uncertain notes to a human review queue, and reconciles system totals against physical cash counts at session closing to eliminate pilferage.

---

## ⚠️ Scope & Disclosures

### In Scope
- **Banknote Denominations:** ₹10, ₹20, ₹50, ₹100, ₹200, ₹500, and ₹2000 Indian currency notes.
- **Multi-Note Frame Proposals:** Candidate contour extraction + MobileNetV2 classification.
- **Append-Only MongoDB Ledger:** Hash-chained (`SHA-256`) and digitally signed (`Ed25519`) blocks.
- **Strict Multi-Role Security:** Operator, Auditor, Administrator, and an unauthenticated Public Transparency Portal.
- **Scan & Verify Testing Studio:** Camera/Upload modes with continuous evaluation, Ed25519 sealed receipt generation, and batch cryptographic verification.
- **Session Reconciliation:** Mathematical discrepancy reporting between optical counts and physical cash counts.

### Out of Scope (Stated Openly)
- **Coins, UPI, and Cheques:** Designed specifically for paper currency banknotes.
- **Counterfeit Detection:** SDMS classifies denomination; it does **not** authenticate physical security threads, watermarks, or paper fibers.
- **Physical Hardware Integration:** Current implementation accepts optical input via simulated frames, file uploads, and webcam streams.

---

## 🏛️ System Architecture

```
                    ┌─────────────────────────┐
                    │ Camera / Frame Upload  │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Stage-1 Proposal Finder │  (Canny + Contours)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Stage-2 Keras Model     │  (MobileNetV2: 8 Classes)
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │ Strict Decision Policy  │
                    └────────────┬────────────┘
         ┌───────────────────────┼───────────────────────┐
         ▼                       ▼                       ▼
    [ ACCEPT ]              [ REVIEW ]              [ REJECT ]
  Conf >= 0.85            Conf 0.30 - 0.85        Conf < 0.30 or
  Ratio 1.3 - 3.2         or IoU > 0.30           Non-Currency
  IoU <= 0.30             or Ratio Anomaly
         │                       │                       │
         ▼                       ▼                       ▼
┌──────────────────┐   ┌──────────────────┐   ┌──────────────────┐
│ MongoDB Ledger   │   │ Review Queue     │   │ Flagged & Logged │
│ (Append Block)   │   │ (Human Auditor)  │   │ As Rejected      │
└────────┬─────────┘   └────────┬─────────┘   └──────────────────┘
         │                      │ (Amends with new block)
         └──────────────────────┘
```

---

## 🗄️ MongoDB Append-Only Ledger

The ledger is implemented in `sdms/core/ledger/mongo_ledger.py` across 8 structured collections:

| Collection | Description | Invariant Enforcement |
|---|---|---|
| `events` | Core append-only ledger blocks | Strictly `insert_one` only. No `update` or `delete`. |
| `event_items` | Individual detected notes inside each event | Bound to parent `event_id` and sequence number. |
| `boxes` | Registered intake boxes and public keys | Authenticated Ed25519 public keys. |
| `sessions` | Active and closed counting sessions | Session lifecycle tracking. |
| `receipts` | Tamper-evident donation receipts | Cryptographically linked to ledger block hashes. |
| `feedback` | Auditor resolution audit trail | Documents original guess vs. human override. |
| `users` | Role-based credentials (RBAC) | Salted PBKDF2-HMAC-SHA256 password hashes. |
| `reconciliations` | End-of-session cash audit reports | Variance calculations and cash discrepancy proofs. |

### Cryptographic Invariants
1. **Hash Chaining:** Each block calculates $H_i = \text{SHA-256}(H_{i-1} \parallel \text{CanonicalBytes}(\text{Payload}))$.
2. **Digital Signatures:** Every event is signed using Ed25519 digital signatures.
3. **Immutability:** Original records are never edited. Corrections are appended as **Amendment Blocks** referencing `amends: <original_id>`.
4. **Offline Resilience:** If an active MongoDB instance is unavailable, `MongoLedger` automatically falls back to `mongomock`, ensuring complete test and demo portability.

To configure production MongoDB collections with JSON Schema validation and append-only database roles:
```bash
mongosh mongodb://localhost:27017/sdms scripts/init_mongo_roles.js
```

---

## 🎨 User Interface (Light Ledger-Book Design System)

The web dashboard uses a prestigious **Light Ledger-Book Design System**:
- **Canvas:** `#F7F7F4` (Warm off-white paper)
- **Surfaces:** `#FFFFFF` (Ruled index cards)
- **Borders:** `#E2E3DC` (Notebook lines)
- **Text:** `#1B2430` (Dark charcoal ink)
- **Accent:** `#0E6E58` (Deep forest teal seal stamp)
- **State Indicators:** `#2E7D52` (Verified), `#A9762A` (Review), `#B0392C` (Alert/Reject)
- **Navigation:** 240px Left-Rail layout with role-aware tab filtering.

### 9 Distinct Screens
1. **Login & Persona Switch:** Fast 1-click persona switching (Operator, Auditor, Admin, Public).
2. **Live Monitor (Operator):** Active session stats, live video intake with overlay, and recent events feed.
3. **Scan & Verify Studio:** Camera/Upload intake modes, continuous auto-scan, dataset presets, 8-class probability charts, and Ed25519 sealed receipt creation & verification.
4. **Review Queue (Auditor):** Human-in-the-loop review with progress completion bar and append-only amendment guarantees.
5. **Ledger Integrity:** Real-time hash-chain walker, visual block timeline, external JSON anchor export, and an interactive **Tamper & Self-Repair Lab**.
6. **Session Close & Cash Reconciliation:** Per-denomination ruled audit sheet comparing machine counts with physical cash counts. Exports CSV and TXT audit reports.
7. **Devices & Staff (Admin):** Box registration and user management modals.
8. **Analytics:** Volume distribution, cash totals, first-pass acceptance rates, and model health trends.
9. **Public Transparency Portal:** Unauthenticated trust portal featuring verified totals, live chain head hash, and the 3 core pillars of mathematical trust.

---

## 🚀 Getting Started

### 1. Environment Setup
```bash
# Clone the repository
cd SDMS

# Activate the virtual environment
.\.venv\Scripts\Activate.ps1

# Verify test suite (16 tests passing)
python -m pytest tests/test_api.py tests/test_mongo_ledger.py -v
```

### 2. Run the Application
```bash
# Start FastAPI Server (serves Web UI on port 8000)
python -m uvicorn sdms.api.main:create_app --factory --host 0.0.0.0 --port 8000
```
Open **[http://localhost:8000/](http://localhost:8000/)** in your web browser.

### 3. Demo Persona Credentials
| Persona | Username | Password | Permitted Views |
|---|---|---|---|
| **Operator** | `operator` | `operator` | Live Monitor, Scan & Verify, Session Close, Public Portal |
| **Auditor** | `auditor` | `auditor` | Review Queue, Scan & Verify, Ledger Integrity, Reconciliation, Analytics, Public Portal |
| **Admin** | `admin` | `admin` | Full System Access (All 9 Views) |
| **Public** | *(No Login)* | *(None)* | Public Transparency Portal & Scan & Verify Demo |

---

## 🧪 Testing Suite

- `tests/test_api.py`: Validates role separation (R6), idempotent ingestion, frame retrieval, review queue resolution, cash reconciliation, and analytics.
- `tests/test_mongo_ledger.py`: Validates SHA-256 hash chaining, Ed25519 signatures, replay deduplication, tamper detection on modified payload, tamper detection on deleted blocks, receipt validation, and decision policy ratio/IoU bounds.
