"""Streamlit views (Operator/Auditor/Public/Demo) over the API.
Run:  streamlit run sdms/ui/app.py   (API at SDMS_API, default http://localhost:8000)
"""
import os
import json
import requests
import streamlit as st

API = os.environ.get("SDMS_API", "http://localhost:8000")
st.set_page_config(page_title="SDMS - Smart Donation Management System", layout="wide")


def call(method, path, **kw):
    h = {"Authorization": f"Bearer {st.session_state['token']}"} if st.session_state.get("token") else {}
    return requests.request(method, API + path, headers=h, timeout=10, **kw)


with st.sidebar:
    st.title("SDMS")
    st.caption("Smart Donation Management System")
    if st.session_state.get("token"):
        st.write(f"Signed in as **{st.session_state['user']}** (`{st.session_state['role']}`)")
        if st.button("Sign out"):
            st.session_state.clear()
            st.rerun()
    else:
        u = st.text_input("Username", value="admin")
        p = st.text_input("Password", type="password", value="admin")
        if st.button("Sign in"):
            try:
                r = requests.post(API + "/auth/login", json={"username": u, "password": p}, timeout=10)
                if r.ok:
                    st.session_state.update(token=r.json()["access_token"], role=r.json()["role"], user=u)
                    st.rerun()
                else:
                    st.error("Bad credentials")
            except Exception as ex:
                st.error(f"Cannot connect to API at {API}: {ex}")

role = st.session_state.get("role", "public")
tabs = ["Public", "Test Currency Upload"] + (["Operator", "Auditor", "Demo Flow & Simulator"] if role in ("admin", "auditor") else [])

for tab, name in zip(st.tabs(tabs), tabs):
    with tab:
        if name == "Public":
            st.subheader("Public Donation Transparency Portal")
            try:
                d = call("GET", "/analytics/realtime").json()
                c1, c2 = st.columns(2)
                c1.metric("Total Donations Verified", f"Rs {d['total_value']:,}")
                c2.metric("Items Pending Auditor Review", d["pending_review"])
                st.markdown("#### Banknotes Verified by Denomination")
                st.bar_chart(d["notes_by_denomination"])
                st.info("Tamper-evident ledger: All amounts are cryptographically anchored and audited.")
            except Exception as ex:
                st.warning(f"Connecting to API at {API}... ({ex})")

        elif name == "Test Currency Upload":
            st.subheader("Test Currency Recognition (Upload Banknote)")
            st.caption("Upload any banknote image (JPEG, PNG, WEBP) to test Stage-2 deep learning classification and tamper-evident ledger sealing.")
            uploaded_file = st.file_uploader("Select Currency Photo to Inspect", type=["jpg", "jpeg", "png", "webp"], label_visibility="visible")
            if uploaded_file is not None:
                import base64
                raw_bytes = uploaded_file.read()
                b64_str = f"data:image/jpeg;base64,{base64.b64encode(raw_bytes).decode('utf-8')}"
                col_img, col_res = st.columns([1, 1])
                with col_img:
                    st.image(raw_bytes, caption="Uploaded Banknote Photo", use_container_width=True)
                with col_res:
                    with st.spinner("Classifying banknote with Stage-2 Neural Network..."):
                        r = call("POST", "/vision/classify", json={"image_b64": b64_str, "session_id": "session-live"})
                        if r.ok:
                            res = r.json()
                            status_badge = ":green[ACCEPT]" if res["status"] == "ACCEPT" else (":orange[REVIEW]" if res["status"] == "REVIEW" else ":red[REJECT]")
                            st.markdown(f"### Predicted: **Rs {res['label']}** ({status_badge})")
                            st.progress(res.get("conf", 0.95))
                            st.write(f"Confidence: **{round(res.get('conf', 0.95) * 100, 1)}%**")
                            st.info(f"Cryptographic Block #{res['seq']} sealed into audit ledger.")
                            if "probabilities" in res:
                                st.bar_chart(res["probabilities"])
                        else:
                            st.error(f"Classification failed: {r.text}")

        elif name == "Operator":
            st.subheader("Operator Live Feed")
            if st.button("Refresh Feed", key="op_refresh"):
                st.rerun()
            try:
                events = call("GET", "/events", params={"limit": 25}).json()
                if not events:
                    st.info("No donation events recorded yet. Use the Simulator tab to generate drops.")
                for e in reversed(events):
                    labels = [i["label"] for i in e.get("items", [])]
                    badge = ":green[ACCEPT]" if e['status'] == "ACCEPT" else (":orange[REVIEW]" if e['status'] == "REVIEW" else ":red[REJECT]")
                    st.markdown(f"**#{e['seq']}** · {badge} · Denominations: `{labels}` · Timestamp: `{e['ts'][:19]}`")
            except Exception as ex:
                st.error(f"Error fetching feed: {ex}")

        elif name == "Auditor":
            st.subheader("Auditor Integrity & Reconciliation Control")
            try:
                v = call("GET", "/ledger/verify").json()
                if v["ok"]:
                    st.success(f"Ledger Integrity: OK ({v['checked']} records verified without corruption)")
                else:
                    st.error(f"Ledger Integrity: CORRUPTED at seq #{v['first_bad_seq']} - Reason: {v['reason']}")

                st.markdown("---")
                st.subheader("Review Queue (Human-in-the-Loop)")
                queue = call("GET", "/review/queue").json()
                if not queue:
                    st.info("Review queue is clean. All uncertain events resolved.")
                for e in queue:
                    with st.expander(f"Event #{e['seq']} · ID: {e['event_id'][:8]} · Session: {e['session_id']}"):
                        r = call("GET", f"/frames/{e['frame_sha']}")
                        if r.ok:
                            st.image(r.content, caption="Captured Frame")
                        st.json(e["items"])
                        labels = st.multiselect("Auditor Correct Denominations", ["10", "20", "50", "100", "200", "500", "2000"], key="rev_" + e["event_id"])
                        note = st.text_input("Audit Note", value="auditor manual confirmation", key="note_" + e["event_id"])
                        if st.button("Confirm Resolution", key="b_" + e["event_id"]):
                            call("POST", f"/review/{e['event_id']}/resolve", json={"labels": labels, "note": note})
                            st.success("Resolved & amendment appended to ledger.")
                            st.rerun()

                st.markdown("---")
                st.subheader("Session Reconciliation")
                sid = st.text_input("Session ID", value="sim-session")
                cols = st.columns(6)
                denoms = ["10", "20", "50", "100", "200", "500"]
                phys = {d: cols[i].number_input(f"Rs {d}", 0, step=1, key="p_" + d) for i, d in enumerate(denoms)}

                col_btn1, col_btn2 = st.columns([1, 1])
                with col_btn1:
                    if st.button("Close Session & Reconcile") and sid:
                        call("POST", f"/sessions/{sid}/close")
                        rep = call("POST", f"/sessions/{sid}/reconcile", json={"physical": {k: int(v) for k, v in phys.items()}}).json()
                        st.metric("Total Cash Variance", f"Rs {rep['variance_total']}")
                        st.json(rep["per_denomination"])

                with col_btn2:
                    if sid:
                        export_res = call("GET", f"/sessions/{sid}/export", params={"format": "csv"})
                        if export_res.ok:
                            st.download_button("Download Reconciliation CSV", data=export_res.content, file_name=f"reconciliation_{sid}.csv", mime="text/csv")
            except Exception as ex:
                st.error(f"Auditor view error: {ex}")

        elif name == "Demo Flow & Simulator":
            st.subheader("5-Minute Demo Flow (Section 16)")
            st.markdown("""
            1. **Simulate Drops:** Ingest sample drops into the ledger with network retries and blur faults.
            2. **Resolve Review:** Resolve uncertain items in the review queue.
            3. **Tamper Test:** Inject row corruption into the database and watch `verify()` flag it.
            4. **Session Reconciliation:** Match physical cash count against recorded ledger.
            """)

            d_col1, d_col2 = st.columns(2)
            with d_col1:
                st.markdown("#### Step 1: Simulator Injection")
                n_drops = st.slider("Number of synthetic drops", 5, 100, 20)
                if st.button("Inject Drops"):
                    with st.spinner("Simulating virtual box drops..."):
                        from sdms.simulator.virtual_box import run_simulation
                        res, _ = run_simulation(n_drops, seed=42)
                        st.success(f"Simulated {res.drops} drops: {res.counts['ACCEPT']} ACCEPT, {res.counts['REVIEW']} REVIEW, {res.counts['REJECT']} REJECT.")
                        st.rerun()

            with d_col2:
                st.markdown("#### Step 3: Tamper Attack Demonstration")
                st.warning("Tests R4: Injects direct row modification into SQLite to demonstrate tamper-evident detection.")
                if st.button("Inject Row Tampering"):
                    try:
                        import sqlite3, json as js
                        conn = sqlite3.connect("data/sdms.db")
                        conn.execute("DROP TRIGGER IF EXISTS events_no_update")
                        row = conn.execute("SELECT seq, items FROM events ORDER BY seq DESC LIMIT 1").fetchone()
                        if row:
                            seq, items_str = row[0], row[1]
                            items = js.loads(items_str)
                            if items:
                                items[0]["label"] = "500" if items[0].get("label") != "500" else "2000"
                            conn.execute("UPDATE events SET items=? WHERE seq=?", (js.dumps(items, sort_keys=True, separators=(",", ":")), seq))
                            conn.commit()
                            st.error(f"Tampered with record seq #{seq} (modified denomination to falsify count).")
                            st.rerun()
                        else:
                            st.info("No events in data/sdms.db yet. Generate drops first.")
                    except Exception as e:
                        st.error(f"Tamper failed: {e}")
