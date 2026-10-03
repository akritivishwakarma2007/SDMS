# SDMS: Comprehensive Project Overview & UI Walkthrough Manual

> **Smart Donation Management System (SDMS)**  
> *A vision-verified, cryptographically sealed, tamper-evident cash donation counting and audit platform for Indian Currency.*

---

## 1. Executive Project Summary

### 1.1 The Core Problem
Cash donation boxes (Hundis in temples, shrines, charitable trusts, and non-profits) process millions of rupees in physical paper currency. Traditionally, counting and managing these donations suffers from three critical vulnerabilities:
1. **Internal Pilferage & Skimming:** Cash is collected and counted behind closed doors by volunteers or staff. Without immediate, automated receipting at the physical moment of drop, banknotes can disappear before being booked into financial accounts.
2. **Manual Miscounting & Human Error:** Counting thousands of mixed, crumpled, worn, and folded banknotes of multiple denominations (₹10, ₹20, ₹50, ₹100, ₹200, ₹500, ₹2000) causes human counting fatigue and arithmetic discrepancies.
3. **Database Manipulation & Lack of Donor Trust:** Conventional centralized databases can be silently manipulated by database administrators, internal insiders, or compromised software to alter transaction totals. Donors have no cryptographic guarantee that their donations were accurately recorded.

### 1.2 The SDMS Solution
SDMS transforms dumb donation boxes into intelligent, cryptographically secured IoT endpoints:
- **Instant Optical Recognition:** A ceiling-mounted camera inside the box detects banknote drops, crops candidate notes, and classifies denominations using a trained deep learning neural network.
- **Two-Stage Vision Architecture:**
  - **Stage-1 Proposal Detector:** Uses Canny edge detection, morphological closing, and contour analysis to locate banknote candidate bounding boxes.
  - **Stage-2 Keras Deep Classifier:** Evaluates candidates using `currency_model_final.keras` (MobileNetV2 backbone, 224x224x3 RGB, 8-class softmax) to predict denomination and confidence.
- **Conservative Decision Policy:** The system enforces the rule: *Never count what you are unsure of.*
  - **ACCEPT:** High-confidence notes ($\ge 85\%$) are automatically added to the session tally.
  - **REVIEW:** Uncertain notes (folded corners, low confidence $< 85\%$, optical blur) are routed to a human auditor review queue.
  - **REJECT:** Non-currency items (slips, envelopes, receipts, fingers) are discarded.
- **Cryptographic Append-Only Ledger:**
  - Every drop event is signed locally by the box hardware using **Ed25519 digital signatures**.
  - Every block links to its predecessor via a **SHA-256 hash chain** (`record_hash = sha256(prev_hash + canonical_payload)`).
  - SQLite database triggers forbid `UPDATE` or `DELETE` operations. Any direct database tampering breaks the hash chain and is flagged immediately by `verify()`.
- **Human-in-the-Loop Review Queue:** Auditors resolve uncertain notes. Confirming or correcting an item appends a cryptographically signed amendment event; the original record is permanently preserved in the hash chain.
- **Anti-Pilferage Cash Reconciliation:** When closing a session, the system's recorded total is compared against physical bank deposit slips in a color-coded **Variance Analysis Table** to detect shortages down to a single banknote.

---

## 2. End-to-End System Architecture

```
+----------------------------------------------------------------------------------------------------+
|                                    SMART DONATION BOX (EDGE HARDWARE)                              |
|                                                                                                    |
|  [Optical Camera Sensor] ------------> [Trigger (Proximity/Motion)] ------> [Clock / RTC]         |
|             |                                                                                      |
|             v                                                                                      |
|   [BoxPipeline Controller]                                                                         |
|             |                                                                                      |
|             +---------> [Stage-1 Proposal Finder: Canny Edge + Contours]                           |
|             |                        |                                                             |
|             |                        v (Cropped Bounding Box ROI)                                  |
|             +---------> [Stage-2 Keras MobileNetV2 Deep Learning Classifier]                       |
|             |                        |                                                             |
|             |                        v (Denomination + Confidence Score)                           |
|             +---------> [Decision Policy: ACCEPT / REVIEW / REJECT]                                |
|                                      |                                                             |
|                                      v                                                             |
|                        [Ed25519 Private Key Digital Signing]                                       |
+--------------------------------------|-------------------------------------------------------------+
                                       | Signed JSON Payload + Image SHA-256 Digest
                                       v
+----------------------------------------------------------------------------------------------------+
|                                       SDMS BACKEND (FASTAPI)                                       |
|                                                                                                    |
|  [Ingestion Service (/ingest/event)]                                                               |
|    - Authenticates Box Identity using Registered Ed25519 Public Key                                |
|    - Validates Image SHA-256 Digest against payload                                                |
|                                                                                                    |
|  [Cryptographic Ledger Engine (sdms/core/ledger)]                                                  |
|    - Computes Parent Block Link: prev_hash = last_record_hash                                      |
|    - Computes Canonical SHA-256 Digest: record_hash = sha256(prev_hash + canonical_json)           |
|    - Writes to SQLite with Append-Only Triggers (events_no_update, events_no_delete)                |
|    - Periodic External Hash Anchoring (Daily Merkle/Ledger Snapshot)                               |
|                                                                                                    |
|  [FastAPI HTTP & WebSocket APIs]                                                                   |
|    - /ws/live-detect   : Real-time camera frames & NoteTracker                                     |
|    - /donations        : Live session totals & recent drop events                                  |
|    - /review/queue     : Human-in-the-loop pending audit items                                     |
|    - /ledger/verify    : Full mathematical SHA-256 & Ed25519 integrity validator                   |
|    - /demo/tamper      : Adversarial tamper attack injection & repair tools                        |
|    - /sessions         : Session closing & anti-pilferage cash variance reconciliation             |
+----------------------------------------------------------------------------------------------------+
                                       |
             +-------------------------+-------------------------+
             v                                                   v
+----------------------------------------+  +----------------------------------------+
|       MODERN SLATE WEB DASHBOARD       |  |          STREAMLIT WORKSTATION         |
|         (Port 8000: /index.html)       |  |          (Port 8501: app.py)           |
|                                        |  |                                        |
|  - Role-Based Responsive SPA           |  |  - Public Transparency Portal          |
|  - Operator Live Camera & Dropper      |  |  - Operator Live Feed & Sim            |
|  - Auditor Review Queue                |  |  - Auditor Review Expander             |
|  - Live Cryptographic Tamper Demo      |  |  - Session Reconciliation & CSV Export |
|  - Physical Variance Table             |  |  - 5-Minute Stakeholder Demo Script    |
|  - Device & Session Admin              |  |                                        |
|  - Public Transparency Portal          |  |                                        |
+----------------------------------------+  +----------------------------------------+
```

---

## 3. Deep Learning Vision Pipeline

The system uses `currency_model_final.keras`, integrated through `sdms/core/vision/classifier_keras.py`:

```
Input Image Frame (640x480 RGB)
              |
              v
[Stage 1: Proposal Finder (OpenCV)]
  - Convert to Grayscale -> Gaussian Blur (5x5) -> Canny Edge Detection
  - Morphological Closing (7x7 kernel) to bridge note borders
  - Contour finding (cv2.findContours) sorted by descending bounding area
  - Geometry Filter: Rejects area < 3% or > 95% of total frame
              |
              v (Cropped Bounding Box ROI)
[Stage 2: Keras Deep Classifier (`currency_model_final.keras`)]
  - Architecture: MobileNetV2 Backbone (`mobilenetv2_1.00_224`)
  - Input Layer: Shape `(None, 224, 224, 3)`, float32, RGB order
  - Built-in Rescaling Layer: `Rescaling(scale=1/127.5, offset=-1.0)`
  - Dense Softmax Output (8 classes):
      Index 0: "10" (₹10 Note)
      Index 1: "100" (₹100 Note)
      Index 2: "20" (₹20 Note)
      Index 3: "200" (₹200 Note)
      Index 4: "2000" (₹2000 Note)
      Index 5: "50" (₹50 Note)
      Index 6: "500" (₹500 Note)
      Index 7: "Background" (Non-currency items, mapped to "non_currency")
  - Accuracy: 97.5% direct test note accuracy; 100% rejection on non-currency test frames
              |
              v
[Decision Policy Engine (`sdms/core/policy.py`)]
  - Aspect Ratio Sanity Bounds: 1.3 <= length / width <= 3.2
  - Denomination Membership: Valid Indian currency denominations
  - Confidence Thresholds:
      - conf < 0.30              -> REJECT ("below_floor")
      - 0.30 <= conf < 0.85       -> REVIEW ("grey_zone")
      - Overlapping IoU > 0.30   -> REVIEW ("overlap_conflict")
      - conf >= 0.85             -> ACCEPT ("confident")
```

---

## 4. UI Design System & Aesthetics

- **Dark Slate Palette:**
  - Canvas Background: `#090d16` (Deep Obsidian Slate)
  - Card Surfaces: `#111827` (Charcoal Surface) with `#1e293b` borders
  - Primary Accents: `#3b82f6` (Vibrant Royal Blue)
  - Status Indicators:
    - 🟢 **Emerald Green (`#10b981`):** Verified ledger, accepted notes, zero cash variance.
    - 🟡 **Amber Orange (`#f59e0b`):** Pending review, low confidence, cash overage.
    - 🔴 **Rose Red (`#ef4444`):** Tampered ledger, rejected items, cash shortage.
- **Typography:**
  - UI Sans: `Inter`, system fallback
  - Cryptographic / Numeric: `JetBrains Mono` for SHA-256 digests, Ed25519 keys, and currency values.
- **Micro-Interactions:**
  - Pulsing live indicators on camera feeds and cryptographic health pills.
  - Hover glow and depth elevation on interactive cards.
  - Real-time animated progress bars for neural network confidence.

---

## 5. Page-by-Page UI Formats, Layouts & User Flows

---

### Page 1: Global Shell, Navigation & Role Switcher

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| [₹] SDMS Smart Donation  |  [Live Monitor]  [Review Queue]  [Ledger Integrity]  [Reconciliation]  | [🟢 Chain OK (42)]  [ADMIN: admin ▼] |
+-------------------------------------------------------------------------------------------------------------------------+
```

#### Modal Role Switcher / Login Form
```
+-------------------------------------------------------------------------------+
|                                  Sign In to SDMS                              |
+-------------------------------------------------------------------------------+
|  QUICK DEMO PERSONAS (1-CLICK SWITCH):                                        |
|                                                                               |
|  +---------------------+  +---------------------+  +-----------------------+  |
|  |    👷‍♂️ Operator       |  |     🔍 Auditor       |  |      ⚙️ Admin          |  |
|  |    Live Drop Feed   |  |   Review & Integrity|  |    Full Governance    |  |
|  +---------------------+  +---------------------+  +-----------------------+  |
|                                                                               |
|  ------------------------- OR ENTER CREDENTIALS ----------------------------  |
|                                                                               |
|  Username: [ admin                                                         ]  |
|  Password: [ •••••••••                                                     ]  |
|                                                                               |
|  [                              SIGN IN                                    ]  |
+-------------------------------------------------------------------------------+
```

#### Elements & Features
1. **Global Brand Header:** ₹ currency badge with gradient illumination.
2. **Dynamic Role Navigation:** Shows only the tabs authorized for the current persona:
   - **Operator:** Live Monitor, Reconciliation.
   - **Auditor:** Review Queue, Ledger Integrity, Reconciliation, Analytics.
   - **Admin:** All pages (Live Monitor, Review Queue, Ledger Integrity, Reconciliation, Devices, Analytics).
   - **Public:** Public Transparency Portal.
3. **Cryptographic Integrity Pill:**
   - Always visible in the top header on every page.
   - Displays `🟢 Chain OK (42)` when all cryptographic links and Ed25519 signatures are verified.
   - Displays `🔴 TAMPER DETECTED #41` with a pulsing red alert if any record in the database was altered.
   - Clicking the pill immediately jumps to the **Ledger Integrity** page.
4. **Persona Switcher:** Allows instant switching between Operator, Auditor, Admin, and Public Donor modes during presentations.

#### User Flow
1. User clicks the user profile chip in the top right.
2. Dropdown opens displaying active role and available personas.
3. User selects a persona (e.g., **Auditor**):
   - Auth token is updated via `/auth/login`.
   - Navigation links re-render according to role permissions.
   - View automatically navigates to the Auditor home screen (**Review Queue**).

---

### Page 2: Live Monitor (Operator Home Screen)

**Target Role:** On-Site Operator / Cashier  
**Primary Job:** Monitor physical banknote drops, verify optical recognition, and immediately correct misreads.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| 🟢 Box #01 — Main Sanctum Donation Desk    Location: Central Shrine    Session: 00:34:12    [⚡ Simulate Drop] [End Session →] |
+-------------------------------------------------------------------------------------------------------------------------+

+--------------------------------------------------------------------+  +-------------------------------------------------+
| CURRENT SESSION VERIFIED TOTAL                                     |  | RECENT ACTIVITY STRIP (LAST 15 DROPS)           |
|                                                                    |  | +---------------------------------------------+ |
|                            ₹28,450                                 |  | | #42  [ACCEPTED]   ₹500             17:42:10 | |
|                                                                    |  | | #41  [ACCEPTED]   ₹100             17:41:55 | |
|                    58 Notes Verified · Ledger Anchored             |  | | #40  [REVIEW]     ₹50              17:41:30 | |
+--------------------------------------------------------------------+  | | #39  [ACCEPTED]   ₹200             17:41:12 | |
                                                                        | | #38  [ACCEPTED]   ₹20              17:40:48 | |
+--------------------------------------------------------------------+  | +---------------------------------------------+ |
| LATEST BANKNOTE DETECTION                         [ACCEPTED (98%)] |  +-------------------------------------------------+
| +---------------------------------+ +----------------------------+ |  
| |                                 | | VERIFIED DENOMINATION      | |  +-------------------------------------------------+
| |        Live Video Stream        | |            ₹500            | |  | SESSION DENOMINATION TALLY                      |
| |                                 | |                            | |  | +------+ +------+ +------+ +------+ +------+    |
| |   [Bounding Box Bounding ROI]   | | Model Conf: 98.4%          | |  | | ₹10  | | ₹20  | | ₹50  | | ₹100 | | ₹200 |    |
| |                                 | | [||||||||||||||||||||----] | |  | |  12  | |  8   | |  14  | |  10  | |  6   |    |
| |                                 | |                            | |  | +------+ +------+ +------+ +------+ +------+    |
| +---------------------------------+ | [✅ Confirm]  [✏️ Correct]  | |  | | ₹500 | | ₹2000|                          |
|                                     +----------------------------+ |  | |  7   | |  1   |                          |
+--------------------------------------------------------------------+  +-------------------------------------------------+
```

#### Component Breakdown & Interactions
1. **Device Status Bar:** Displays connection health (`🟢 Online`), active Box ID, physical location, running session duration, and action buttons.
2. **Big Running Total Card:** Giant `3.5rem` typography showing total verified rupee value in the active session. Updates live via WebSocket or polling without page reload.
3. **Latest Banknote Detection Card:**
   - **Video Viewport:** Shows real-time camera feed with bounding boxes rendered over detected notes.
   - **Denomination Callout:** Large badge showing recognized denomination (`₹500`) and Stage-2 Keras confidence score (`98.4%`).
   - **Confidence Meter:** Dynamic color-coded bar:
     - Green: $\ge 85\%$ (High confidence, auto-accepted).
     - Amber: $30\% - 84\%$ (Grey-zone, flagged for review).
     - Red: $< 30\%$ (Non-currency or severe occlusion, rejected).
   - **`[✅ Confirm Note]` Button:** Directly confirms note into the append-only ledger via `POST /donations/confirm`.
   - **`[✏️ Correct Value]` Button:** Expands an inline denomination picker (`₹10`, `₹20`, `₹50`, `₹100`, `₹200`, `₹500`, `₹2000`, `❌ Non-Currency`). Clicking any denomination records an immediate correction event.
4. **Recent Activity Strip:** Chronological reverse-sorted stream of the last 15 notes processed, showing block sequence number, badge, denomination, and exact timestamp.
5. **Denomination Tally Grid:** 7 individual count cards displaying current volume for each legal denomination.
6. **`[⚡ Simulate Drop]` Button:** Automatically injects a simulated banknote drop to showcase live detection during demonstrations.
7. **`[End Session →]` Button:** Navigates directly to **Session Reconciliation** to close the session and count physical cash.

#### Operator User Flow
```
[Physical Banknote Dropped into Box]
               |
               v
[Camera Detects Motion -> Stage-1 Bounding Box -> Stage-2 Keras Classification]
               |
    +----------+----------+
    |                     |
[conf >= 85%]         [conf < 85%]
    |                     |
    v                     v
[Auto-ACCEPTED]       [Routed to REVIEW QUEUE]
    |                     |
[Running Total +₹500] [Recent Strip flags #40 [REVIEW]]
[Audible / Visual Ping]
```

---

### Page 3: Review Queue (Auditor Home Screen)

**Target Role:** Internal / External Auditor  
**Primary Job:** Audit and resolve ambiguous, folded, stained, or low-confidence banknote drops.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| Human-in-the-Loop Review Queue                                                      [ 3 of 8 Items Pending Resolution ] |
| Resolve notes with low confidence, folded corners, or model disagreements.            [||||||||||||-------------------] |
+-------------------------------------------------------------------------------------------------------------------------+

+-------------------------------------------------------------------------------------------------------------------------+
| 🛡️ Audit Ledger Guarantee: Resolving an item creates an append-only correction amendment in the ledger. The original    |
|    captured event and signature are permanently preserved in the hash chain.                                            |
+-------------------------------------------------------------------------------------------------------------------------+

+---------------------------------------------------+  +---------------------------------------------------+
| Event #24 · ev-8a9d0f3b         [REVIEW NEEDED]   |  | Event #28 · ev-4c119e2a         [REVIEW NEEDED]   |
+---------------------------------------------------+  +---------------------------------------------------+
|  [Captured Banknote Image Crop: Folded Corner]    |  |  [Captured Banknote Image Crop: Low Lighting]     |
|                                                   |  |                                                   |
+---------------------------------------------------+  +---------------------------------------------------+
|  Stage-1 Proposal: ₹50    Stage-2 Keras Conf: 68% |  |  Stage-1 Proposal: ₹100   Stage-2 Keras Conf: 62% |
|                                                   |  |                                                   |
|  [ Approve as ₹50 ]    [ Relabel ▾ ]    [ Reject ]|  |  [ Approve as ₹100 ]   [ Relabel ▾ ]    [ Reject ]|
+---------------------------------------------------+  +---------------------------------------------------+
```

#### Component Breakdown & Audit Controls
1. **Audit Progress Bar:** Displays count and percentage of pending review items. Progresses toward 100% as the auditor processes items.
2. **Audit Guarantee Banner:** Clear explanation reminding auditors that SDMS never overwrites database rows; human resolutions create append-only amendment records (`amends: ev-8a9d0f3b`).
3. **Review Cards:**
   - **High-Resolution Crop:** The exact image crop captured by the camera at the instant of drop.
   - **Model Analysis:** Displays the Stage-1 contour proposal and the Stage-2 Keras softmax probability.
   - **`[Approve as ₹X]` Button:** Accepts the model's suggested denomination with one click (`POST /review/{id}/resolve`).
   - **`[Relabel ▾]` Dropdown:** Allows the auditor to override the denomination if the note was misclassified (e.g., folded ₹500 misread as ₹50).
   - **`[Reject]` Button:** Marks the item as non-currency (coupons, devotional slips, receipts, foreign currency).

#### Auditor User Flow
1. Auditor opens Review Queue.
2. Inspects Event `#24`: The image shows a ₹50 note with a folded corner that scored $68\%$ confidence.
3. Auditor clicks **`[Approve as ₹50]`**.
4. The frontend sends resolution request to `POST /review/ev-8a9d0f3b/resolve`.
5. Backend creates new amendment block `#25` linked to parent `#24`, signed by the auditor's key.
6. The card smoothly transitions off the screen and the progress meter increments.

---

### Page 4: Ledger Integrity & Tamper Detection (Auditor / Admin)

**Target Role:** Auditor & Security Administrator  
**Primary Job:** Verify cryptographic integrity of the append-only ledger and demonstrate tamper-evidence in real time.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| Cryptographic Ledger Integrity                                [⚡ Verify Chain Now]  [📥 Export Anchor]  [⚠️ Tamper Attack] |
| Real-time Ed25519 signature & SHA-256 hash chain verification.                                                          |
+-------------------------------------------------------------------------------------------------------------------------+

+-------------------------------------------------------------------------------------------------------------------------+
| [ 🛡️ ]  Cryptographic Chain 100% Verified                                                                               |
|          All 42 blocks cryptographically validated against Ed25519 public keys and parent hashes.                       |
|          Checked: 42 Blocks    Latency: 4ms    Compliance: PASS (Requirement R4)                                        |
+-------------------------------------------------------------------------------------------------------------------------+

BLOCKCHAIN TIMELINE (APPEND-ONLY LEDGER)
+-------------------------------------------------------------------------------------------------------------------------+
| #42  Record Hash: e3b0c44298fc1c149afbf4c8...     Prev Hash: 7a88b1...    [ACCEPTED]   ₹500          17:42:10           |
+-------------------------------------------------------------------------------------------------------------------------+
                                       | (Chained via SHA-256)
+-------------------------------------------------------------------------------------------------------------------------+
| #41  Record Hash: 7a88b13926f8271a098bc19d...     Prev Hash: 4f12d8...    [ACCEPTED]   ₹100          17:41:55           |
+-------------------------------------------------------------------------------------------------------------------------+
                                       |
+-------------------------------------------------------------------------------------------------------------------------+
| #40  Record Hash: 4f12d88192a837e2b109cc3a...     Prev Hash: 000000...    [GENESIS]    System Start  17:30:00           |
+-------------------------------------------------------------------------------------------------------------------------+
```

#### Tamper Attack Demonstration Screen (State after Malicious Modification)
```
+-------------------------------------------------------------------------------------------------------------------------+
| [ 🚨 ]  TAMPER DETECTED AT BLOCK #41                                                                                    |
|          Hash mismatch: record_hash does not match recomputed SHA-256 digest!                                           |
|          Database tampering or silent row edit detected. The cryptographic chain is broken.                             |
|          [ 🔧 Restore & Repair Ledger ]                                                                                 |
+-------------------------------------------------------------------------------------------------------------------------+
```

#### Interactive Verification & Demo Controls
1. **`[⚡ Verify Chain Now]`:** Executes full backend audit (`GET /ledger/verify`). Traverses every single block in the ledger, recalculates `sha256(prev_hash + canonical_payload)`, and verifies the Ed25519 digital signature against the registered public key of the device that signed it.
2. **`[⚠️ Tamper Attack (Demo)]`:**
   - Calls `POST /demo/tamper`.
   - Temporarily bypasses database triggers to simulate a malicious root database administrator altering row `#41` (e.g., changing a ₹10 note to ₹500 to steal cash).
   - Re-verifies chain: The banner instantly turns **Crimson Red**, proving **Requirement R4 (Tamper Detection)** works in real time.
3. **`[🔧 Restore & Repair Ledger]`:** Calls `POST /demo/repair` to recalculate valid cryptographic hashes and return the system to pristine verified status.
4. **`[📥 Export Anchor]`:** Downloads external Merkle/ledger root digest snapshot for third-party publishing or long-term cold storage.

---

### Page 5: Session & Cash Reconciliation (Anti-Pilferage)

**Target Role:** Cashier Operator & Audit Supervisor  
**Primary Job:** Close a collection session and mathematically cross-check the vision system total against the physical cash deposited into the bank.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| Session Closing & Cash Reconciliation                                                             [📥 Download Audit CSV] |
| Anti-pilferage verification: compare recorded vision count against physical bank count.                                 |
+-------------------------------------------------------------------------------------------------------------------------+

+---------------------------------------------------+  +------------------------------------------------------------------+
| 1. ENTER PHYSICAL CASH COUNT                      |  | 2. VARIANCE ANALYSIS (ANTI-PILFERAGE AUDIT)        [Zero Variance] |
|                                                   |  +------------------------------------------------------------------+
| +---------------------+   +---------------------+ |  | Denom | System | Sys Val | Phys | Phys Val | Units | Cash Diff   |
| | ₹10 Notes:   [ 12 ] |   | ₹20 Notes:   [  8 ] | |  |-------+--------+---------+------+----------+-------+-------------|
| | ₹50 Notes:   [ 14 ] |   | ₹100 Notes:  [ 10 ] | |  | ₹10   |   12   |  ₹120   |  12  |   ₹120   |   0   |   ₹0 (OK)   |
| | ₹200 Notes:  [  6 ] |   | ₹500 Notes:  [  7 ] | |  | ₹20   |    8   |  ₹160   |   8  |   ₹160   |   0   |   ₹0 (OK)   |
| | ₹2000 Notes: [  1 ] |                         | |  | ₹50   |   14   |  ₹700   |  14  |   ₹700   |   0   |   ₹0 (OK)   |
| +---------------------+   +---------------------+ |  | ₹100  |   10   | ₹1,000  |  10  |  ₹1,000  |   0   |   ₹0 (OK)   |
|                                                   |  | ₹200  |    6   | ₹1,200  |   6  |  ₹1,200  |   0   |   ₹0 (OK)   |
| Total Physical Cash: ₹8,180                       |  | ₹500  |    7   | ₹3,500  |   7  |  ₹3,500  |   0   |   ₹0 (OK)   |
| [⚡ Match System Count] [🔒 Close & Reconcile]     |  | ₹2000 |    1   | ₹2,000  |   1  |  ₹2,000  |   0   |   ₹0 (OK)   |
+---------------------------------------------------+  +------------------------------------------------------------------+
```

#### Pilferage Detection Scenario (Physical Bank Count Shortage)
```
+-------------------------------------------------------------------------------------------------------------------------+
| [ ⚠️ ]  CASH SHORTAGE DETECTED: -₹500 (PILFERAGE WARNING)                                                               |
|          System vision recorded 7 notes of ₹500, but only 6 notes were physically deposited.                            |
|          Row: ₹500  | System: 7 | Physical: 6 | Unit Difference: -1 | Net Variance: -₹500 (SHORTAGE)                    |
+-------------------------------------------------------------------------------------------------------------------------+
```

#### Reconciliation Workflow
1. The operator empties the donation box at the end of the day and counts physical cash.
2. The operator inputs the physical banknote count into the numeric input fields.
3. The system computes a live, side-by-side **Variance Analysis Table**:
   - **Green Badge (`₹0 OK`):** Physical count matches system vision count exactly.
   - **Red Alert (`-₹500 SHORT`):** Physical count is lower than vision records (skimming/theft).
   - **Amber Alert (`+₹100 OVER`):** Physical count exceeds vision records (unrecognized note).
4. Operator clicks **`[🔒 Close & Reconcile]`**:
   - Commits the reconciliation record to `reconciliations` table.
   - Finalizes session in `sessions` table.
   - Generates an immutable, cryptographically signed audit summary and triggers CSV download.

---

### Page 6: Device & Session Management (Admin Home Screen)

**Target Role:** System Administrator  
**Primary Job:** Register smart donation box hardware, manage authorized operators and auditors, and inspect audit logs.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| Device & Session Management                                                     [+ Register Box]  [+ Add Staff Account] |
+-------------------------------------------------------------------------------------------------------------------------+

REGISTERED SMART DONATION BOXES
+-------------------------------------------------------------------------------------------------------------------------+
| Box ID   | Installation Location      | Ed25519 Public Key       | Network Status | Last Heartbeat | Actions            |
|----------+----------------------------+--------------------------+----------------+----------------+--------------------|
| box-01   | Main Sanctum Altar         | ed25519-pk-9f82c4e1...   | 🟢 Online      | Just now       | [Configure] [Logs] |
| box-02   | East Gate Counter          | ed25519-pk-4a11b8d9...   | 🟢 Online      | 2m ago         | [Configure] [Logs] |
+-------------------------------------------------------------------------------------------------------------------------+

AUTHORIZED STAFF USERS (RBAC)
+-------------------------------------------------------------------------------------------------------------------------+
| Username    | Role       | Permissions Assigned                         | Account Status | Security Auth        |
|-------------+------------+----------------------------------------------+----------------+----------------------|
| admin       | ADMIN      | Full Root Access, Hardware Config, Ledger    | 🟢 Active      | PBKDF2-SHA256 (200k) |
| auditor     | AUDITOR    | Review Queue, Hash Verification, Audit CSV   | 🟢 Active      | PBKDF2-SHA256 (200k) |
| operator    | OPERATOR   | Live Camera Drops, Session Reconciliation    | 🟢 Active      | PBKDF2-SHA256 (200k) |
+-------------------------------------------------------------------------------------------------------------------------+
```

#### Administrative Controls
- **`[+ Register Box]` Modal:** Enrolls a new smart donation box by assigning a unique `box_id`, physical location string, and registering its Ed25519 public key.
- **`[+ Add Staff Account]` Modal:** Creates operator or auditor credentials with PBKDF2-HMAC-SHA256 password hashing and role enforcement.
- **Hardware Heartbeat:** Monitors network ping and optical sensor health across all distributed boxes.

---

### Page 7: Analytics & Model Health Dashboard (Admin / Auditor)

**Target Role:** Administrator & Auditor  
**Primary Job:** Monitor optical classification health, acceptance rates, and donation distribution trends.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
| System Analytics & Model Health                                                                     [📥 Export CSV Report] |
+-------------------------------------------------------------------------------------------------------------------------+

+--------------------+  +--------------------+  +--------------------+  +--------------------+
| Total Verified     |  | Total Banknotes    |  | Auto-Accept Rate   |  | Pending Review     |
|   ₹142,850         |  |   324 Notes        |  |   98.4%            |  |   0 Items          |
| Cryptographically  |  | Across 4 Sessions  |  | Target >= 95% PASS |  | Human-in-the-Loop  |
+--------------------+  +--------------------+  +--------------------+  +--------------------+

+-------------------------------------------------+  +-------------------------------------------------+
| DENOMINATION DISTRIBUTION (RUPEE VOLUME)        |  | MODEL CLASSIFICATION STABILITY                  |
|                                                 |  |                                                 |
|   [ Bar Chart: Rupee breakdown across           |  |   [ Doughnut Chart:                             |
|     ₹10, ₹20, ₹50, ₹100, ₹200, ₹500, ₹2000 ]    |  |     - Auto-Accepted: 98.4% (Green)            |
|                                                 |  |     - Human Review:   1.2% (Amber)            |
|                                                 |  |     - Rejected:       0.4% (Red) ]            |
+-------------------------------------------------+  +-------------------------------------------------+
```

#### Metrics Displayed
1. **Total Verified Funds:** Cumulative value of all cryptographically validated drop events.
2. **Banknote Volume:** Total physical currency count processed.
3. **Auto-Accept Rate:** Percentage of notes accepted without human intervention (benchmark $\ge 95\%$).
4. **Pending Review Items:** Backlog of items currently awaiting auditor confirmation.
5. **Interactive Charts:** Visual distribution of cash across denominations and pipeline stability breakdown.

---

### Page 8: Public Transparency Portal (Public Donor / No Auth)

**Target Role:** Donors, Public Citizens, Devotees  
**Primary Job:** Provide transparent, verifiable donation totals without compromising private internal security feeds.

#### Visual UI Layout Format
```
+-------------------------------------------------------------------------------------------------------------------------+
|                                           PUBLIC DONATION TRANSPARENCY PORTAL                                           |
|                                                Trust Through Cryptography                                               |
|                                                                                                                         |
|                                                         ₹142,850                                                        |
|                                            TOTAL DONATIONS VERIFIED & AUDITED                                           |
|                                                                                                                         |
|  +----------------------------+  +----------------------------+  +---------------------------------------------------+  |
|  | 🔒 Cryptographically Sealed|  | 🛡️ Zero Silent Errors      |  | ⚖️ Physical Cash Reconciliation                   |  |
|  | Each drop is signed with   |  | Low confidence notes are   |  | System totals are mathematically matched with     |  |
|  | Ed25519 & chained via SHA. |  | audited; 0% false accepts. |  | physical bank deposits to prevent pilferage.      |  |
|  +----------------------------+  +----------------------------+  +---------------------------------------------------+  |
+-------------------------------------------------------------------------------------------------------------------------+

+-------------------------------------------------------------------------------------------------------------------------+
| VERIFIED DONATIONS BY DENOMINATION                                                                [Live Aggregate Data] |
|                                                                                                                         |
|   [ Bar Chart: Total rupees counted across ₹10, ₹20, ₹50, ₹100, ₹200, ₹500, ₹2000 ]                                     |
+-------------------------------------------------------------------------------------------------------------------------+
```

#### Key Highlights for Public Viewers
- No authentication or passwords required.
- Omits internal camera feeds, operator names, and device private keys.
- Shows total verified collection and public proof of cryptographic sealing.

---

## 6. Verification & How to Run the Entire System

### 6.1 Server Architecture & Ports
The system includes two running UI workstations powered by the FastAPI backend:
1. **FastAPI Backend + Modern Slate Web Dashboard:**
   - URL: `http://localhost:8000/`
   - Serves both REST/WebSocket API endpoints and the modern responsive HTML/CSS/JS single page application.
2. **Streamlit Workstation:**
   - URL: `http://localhost:8501/`
   - Serves the Python data scientist and desktop auditor interface.

### 6.2 Launch Commands
```bash
# Activate Python Virtual Environment
.\.venv\Scripts\Activate.ps1

# Run Complete Pytest Suite (All 40 tests passing)
python -m pytest tests/ -v

# Run FastAPI Backend Server (Port 8000)
python -m uvicorn sdms.api.main:create_app --factory --host 0.0.0.0 --port 8000

# Run Streamlit Application (Port 8501)
python -m streamlit run sdms/ui/app.py --server.port 8501
```

### 6.3 Default User Credentials
| Username | Password | Role Assigned | Default Landing Screen |
|---|---|---|---|
| `operator` | `operator` | `OPERATOR` | Live Monitor (`/live-monitor`) |
| `auditor` | `auditor` | `AUDITOR` | Review Queue (`/review-queue`) |
| `admin` | `admin` | `ADMIN` | Analytics & Devices (`/analytics`) |

---

## 7. 5-Minute Client & Stakeholder Demonstration Script

Follow these steps to demonstrate the full capabilities of SDMS:

1. **Open the Web Dashboard:** Navigate to `http://localhost:8000/`.
2. **Show the Global Header:** Point out the dark slate aesthetic, the ₹ brand identity, and the top-right `🟢 Chain OK (42)` cryptographic health pill.
3. **Log in as Operator:**
   - Select **👷‍♂️ Operator** from the persona switcher.
   - Land on the **Live Monitor**.
   - Click **`[⚡ Simulate Drop]`**: Watch the running total increase, the confidence progress bar animate to $98.4\%$, and the new note appear in the Recent Activity Strip.
   - Click **`[✏️ Correct Value]`**: Show how an operator can override a denomination on the fly if needed.
4. **Log in as Auditor:**
   - Switch persona to **🔍 Auditor**.
   - Land on the **Review Queue**.
   - Show the raw banknote image crop with a folded corner and explain how low-confidence notes are flagged rather than guessed.
   - Click **`[Approve as ₹50]`** to resolve the item and advance the progress meter.
5. **The Climax: Proving Tamper Detection (Requirement R4):**
   - Navigate to **Ledger Integrity**.
   - Click **`[⚡ Verify Chain Now]`**: Observe 100% chain validation in $\approx 4\text{ ms}$.
   - Click **`[⚠️ Inject Tamper Attack (Demo)]`**: Simulates a hacker editing an SQLite database record behind the scenes.
   - Click **`[⚡ Verify Chain Now]`**: The banner immediately flashes **Crimson Red (`🚨 Tamper Detected at Block #41`)**, proving mathematically that financial data cannot be secretly altered.
   - Click **`[🔧 Repair / Reset]`**: Restores the cryptographic chain to pristine green status.
6. **Anti-Pilferage Cash Reconciliation (Requirement R7):**
   - Navigate to **Session & Reconciliation**.
   - Click **`[⚡ Match System Count]`** to simulate bank cash deposit matching.
   - Decrease a ₹500 note from 7 to 6: Highlight how the row immediately flashes **Red (`-₹500 SHORT`)**, showing how pilferage is caught automatically.
7. **Public Transparency Portal:**
   - Switch persona to **🌐 Public Donor**.
   - Conclude by demonstrating how the general public can view verified totals and audit proofs without exposing internal security camera feeds.

---

## 8. Cryptographic Threat Model & Attack Matrix

SDMS mathematically isolates and defends against 8 distinct attack vectors:

| Threat / Attack Vector | Defense Mechanism | Automated Test Suite |
|---|---|---|
| **Edit a record's contents** (e.g. changing denomination in SQLite) | Parent SHA-256 hash chaining | `test_attack_byte_edit` |
| **Delete a record** (e.g. deleting a cash drop record) | Monotonic sequence number + predecessor link | `test_attack_deleted_row` |
| **Reorder records** (swapping timestamps or sequence) | Strict sequence continuity checks | `test_attack_reordered_rows` |
| **Replay a payload** (re-submitting identical network packet) | Event UUID idempotency + duplicate detection in `verify()` | `test_idempotent_retry`, `test_attack_replayed_payload_rows` |
| **Edit + recompute whole chain** (attacker with root database access) | Per-box Ed25519 digital signatures (private key kept in secure hardware) | `test_rehashed_forgery_fails_signature` |
| **Truncate the tail / rewrite with server key** | External periodic Merkle/Ledger hash anchoring | `test_anchor_detects_truncation` |
| **Unauthorized reads / data scraping** | Role-Based Access Control (RBAC with JWT); Public sees aggregates only | `test_role_separation_R6` |
| **Cash removed after counting (Theft)** | Physical Cash vs. System Count Reconciliation table (flags shortages) | `test_200_drop_run` |

### Threat Caveats & Scope Boundaries:
- **Counterfeiting:** SDMS is a denomination classifier and automated ledger, not a forensic counterfeit currency lab.
- **Physical Sensor Sabotage:** Smearing camera lenses or physically breaking the box hardware requires physical enclosure security and tamper switches.

---

## 9. Real Dataset Collection & Client Handover Guide

To extend and fine-tune the deep learning model across novel micro-variations of physical currency, follow these field capture standards:

### 9.1 Target Quantities
Capture **80 to 100 high-resolution photographs per denomination**:
- **₹10:** Mahatma Gandhi (New) Series — Chocolate Brown
- **₹20:** Mahatma Gandhi (New) Series — Greenish Yellow
- **₹50:** Mahatma Gandhi (New) Series — Fluorescent Blue
- **₹100:** Mahatma Gandhi (New) Series — Lavender
- **₹200:** Mahatma Gandhi (New) Series — Bright Orange/Yellow
- **₹500:** Mahatma Gandhi (New) Series — Stone Grey
- **₹2000:** *(Optional)* Mahatma Gandhi (New) Series — Magenta
- **Non-Currency (Negatives):** 50 photos of plain paper, thermal cash register receipts, envelopes, and donation prayer slips.

### 9.2 Photographic Conditions
1. **Both Orientations:** Front face (Mahatma Gandhi portrait) and reverse face (historical monuments).
2. **Physical Wear:** Crisp notes, single-fold notes, multi-creased notes, worn/soiled notes.
3. **Lighting Setup:** Top-down bright LED, diffused warm room light, dim ambient light, and cast hand shadows.
4. **Partitioning Rule:** Keep capture sessions separated in folders (`data/raw/YYYY-MM-DD_location_session/`). Images from the same capture session must **never** cross between train and test splits.

---

## 10. Model Card & Benchmark Profile

- **Backbone Architecture:** MobileNetV2 (`mobilenetv2_1.00_224`)
- **Input Tensor:** Shape `(None, 224, 224, 3)`, float32, normalized to `[-1.0, 1.0]` via built-in Keras Rescaling layer.
- **Output:** 8 classes (`10`, `100`, `20`, `200`, `2000`, `50`, `500`, `Background` / `non_currency`).
- **Inference Latency Profile (CPU):**
  - Mean Latency: ~2.8 ms (~350 FPS on modern CPU)
  - 95th Percentile Latency: ~3.8 ms
  - Embedded Target: Under 45 ms on Raspberry Pi 4/5 hardware.
- **Accuracy:** 97.5% direct test note accuracy, 100% negative frame rejection on test splits.

---

## 11. Project Milestones & Verification Checklist

- [x] **Deep Learning Integration:** `currency_model_final.keras` loaded and integrated via `sdms/core/vision/classifier_keras.py`.
- [x] **Cryptographic Hash Chain:** SHA-256 predecessor links + Ed25519 digital signature signing engine.
- [x] **Append-Only Triggers:** SQLite triggers prevent `UPDATE` or `DELETE` commands.
- [x] **Automated Test Suite:** 40 passing unit, property, and integration tests (`pytest tests/`).
- [x] **FastAPI Ingestion & WebSockets:** Real-time event streaming and frame prediction.
- [x] **Modern Slate Web Dashboard:** 8 role-aware screens (Live Monitor, Review Queue, Integrity, Reconciliation, Devices, Analytics, Public Portal).
- [x] **Streamlit Workstation:** Desktop operator & data science audit suite.
- [x] **Live Tamper Demonstration:** Adversarial trigger bypass simulation (`/demo/tamper`) and instant detection.
