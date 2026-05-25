# Bill Detail Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make history rows clickable to open a slide-in detail panel showing payment-out info, per-housemate collection status with manual override toggles, a timeline, and notes; simultaneously make History the default tab and retire Active Bills as a separate tab.

**Architecture:** New `/api/bills/cycle/<cycle_tag>` endpoint returns rich per-cycle data (payment date, housemate shares + paid dates + override sources, notes). The panel reuses the existing slide-in CSS pattern from `insights.html`. The `ACTIVE.BILLS` tab is removed; its card content is still accessible via the panel when the current month's history row is clicked. The `manual_overrides.csv` storage and `upsert_override` logic are extended to support cycle-tag-based lookups (bypassing the bill ID requirement for historical cycles).

**Tech Stack:** Vanilla JS, Flask/Python, CSV data layer (`manual_overrides.csv`), existing slide-in panel CSS pattern.

---

### Task 1: New API endpoint — `/api/bills/cycle/<cycle_tag>`

**Files:**
- Modify: `server.py` — insert new endpoint after `api_bills_history` (~line 921)

This endpoint returns everything needed to render the detail panel for one cycle: payment-out details, per-housemate share/paid/date/source, notes, and timeline events.

- [ ] **Step 1: Add `GET /api/bills/cycle/<cycle_tag>` to `server.py`**

Insert this after the `api_bills_history` function (around line 921):

```python
@app.get("/api/bills/cycle/<cycle_tag>")
def api_bill_cycle_detail(cycle_tag: str):
    history = compute_bill_history()
    cycle = next((h for h in history if h["cycle_tag"] == cycle_tag), None)
    if not cycle:
        return jsonify({"error": "Cycle not found"}), 404

    parsed = parse_cycle_tag(cycle_tag)
    if not parsed:
        return jsonify({"error": "Invalid cycle tag"}), 400
    slug, month, year = parsed

    bill_model = cycle_bill_model(slug, month, str(year))
    housemates = read_housemates()
    overrides = build_override_lookup()

    # Load tagged beem transactions to find per-housemate payment dates
    spending_rows = read_csv(DATA_DIR / "transactions_spending.csv")
    beem_rows = [r for r in spending_rows if is_incoming_beem(r)]

    total_due = cycle.get("total_due")

    housemate_detail = []
    for hm in housemates:
        name = (hm.get("name") or "").lower()
        share = share_for_housemate(bill_model, hm, total_due)
        paid = False
        source = None
        paid_date = None

        # Check tagged transactions for this housemate + cycle
        for txn in beem_rows:
            tags = tag_set(txn.get("tags", ""))
            expanded = expand_bill_cycle_tags(tags)
            if name in tags and cycle_tag in expanded:
                paid = True
                source = "tag"
                paid_date = txn.get("settled_at") or txn.get("created_at")
                break

        # Check manual overrides (keyed by housemate, slug, month, year)
        if not paid:
            override = overrides.get((name, slug.lower(), month, str(year)))
            if override is not None:
                paid = parse_bool(override.get("paid"))
                source = "manual" if paid else None
                paid_date = override.get("paid_date") or None

        housemate_detail.append({
            "name": name,
            "share": share,
            "paid": paid,
            "source": source,
            "paid_date": paid_date,
        })

    # Build timeline: merge payment-out date + housemate paid dates
    timeline = []
    if cycle.get("paid_date"):
        timeline.append({
            "date": cycle["paid_date"],
            "event": f"Bill paid to {cycle.get('provider') or slug}",
            "type": "payment_out",
        })
    for hm in housemate_detail:
        if hm["paid"] and hm["paid_date"]:
            timeline.append({
                "date": hm["paid_date"],
                "event": f"{hm['name'].title()} paid {('$'+f\"{hm['share']:.2f}\") if hm['share'] else 'share'}",
                "type": "housemate_paid",
            })
    timeline.sort(key=lambda e: e["date"] or "")

    # Load notes from config
    config = load_config()
    notes_key = f"bill_notes_{cycle_tag}"
    notes = config.get(notes_key, "")

    return jsonify({
        "cycle_tag": cycle_tag,
        "slug": slug,
        "month": month,
        "year": int(year),
        "label": cycle["label"],
        "provider": cycle.get("provider", ""),
        "status": cycle["status"],
        "paid_date": cycle.get("paid_date"),
        "total_due": total_due,
        "incoming_total": cycle.get("incoming_total", 0),
        "housemates": housemate_detail,
        "timeline": timeline,
        "notes": notes,
    })
```

- [ ] **Step 2: Verify endpoint returns valid data**

```bash
curl -s http://localhost:5001/api/bills/cycle/rent-may-2026 | python3 -m json.tool | head -40
```

Expected: JSON with `cycle_tag`, `label`, `status`, `housemates` array with `paid`, `share`, `paid_date` fields, `timeline` array, `notes` string. No 500 errors.

- [ ] **Step 3: Add `POST /api/bills/cycle/<cycle_tag>/override` endpoint**

The existing `/api/bills/<bill_id>/override` requires a bill ID from `bills.csv`, which historical cycles don't always have. This new endpoint accepts a `cycle_tag` directly.

Insert after the new GET endpoint:

```python
@app.post("/api/bills/cycle/<cycle_tag>/override")
def api_bill_cycle_override(cycle_tag: str):
    parsed = parse_cycle_tag(cycle_tag)
    if not parsed:
        return jsonify({"ok": False, "error": "Invalid cycle tag"}), 400
    slug, month, year = parsed

    payload = request.get_json(force=True) or {}
    housemate = (payload.get("housemate") or "").lower().strip()
    if housemate not in HOUSEMATE_NAMES:
        return jsonify({"ok": False, "error": "Unknown housemate"}), 400

    paid = bool(payload.get("paid"))
    note = payload.get("note", "")
    paid_date = payload.get("paid_date", "")

    overrides = read_manual_overrides()
    fieldnames = ["housemate", "slug", "month", "year", "paid", "note", "paid_date"]

    updated = False
    for row in overrides:
        if (
            row.get("housemate", "").lower() == housemate
            and row.get("slug", "").lower() == slug.lower()
            and row.get("month", "").lower() == month
            and str(row.get("year", "")) == str(year)
        ):
            row["paid"] = "true" if paid else "false"
            row["note"] = note
            row["paid_date"] = paid_date
            updated = True
            break

    if not updated:
        overrides.append({
            "housemate": housemate,
            "slug": slug,
            "month": month,
            "year": str(year),
            "paid": "true" if paid else "false",
            "note": note,
            "paid_date": paid_date,
        })

    write_csv(DATA_DIR / "manual_overrides.csv", fieldnames, overrides)
    return jsonify({"ok": True, "housemate": housemate, "paid": paid})
```

- [ ] **Step 4: Add `POST /api/bills/cycle/<cycle_tag>/notes` endpoint**

Insert after the override endpoint:

```python
@app.post("/api/bills/cycle/<cycle_tag>/notes")
def api_bill_cycle_notes(cycle_tag: str):
    parsed = parse_cycle_tag(cycle_tag)
    if not parsed:
        return jsonify({"ok": False, "error": "Invalid cycle tag"}), 400

    payload = request.get_json(force=True) or {}
    notes = (payload.get("notes") or "").strip()

    config = load_config()
    notes_key = f"bill_notes_{cycle_tag}"
    config[notes_key] = notes
    import json as _json
    CONFIG_PATH.write_text(_json.dumps(config, indent=2))
    return jsonify({"ok": True, "notes": notes})
```

- [ ] **Step 5: Restart server and verify all three new endpoints respond**

```bash
pkill -f "python3.*server.py"; sleep 1
/Users/anguss/dev/finance_dash/venv/bin/python3 /Users/anguss/dev/finance_dash/server.py &>/tmp/server.log &
sleep 2
curl -s -o /dev/null -w "%{http_code}" http://localhost:5001/api/bills/cycle/rent-may-2026
# Expected: 200 or 404 (not 500)
curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:5001/api/bills/cycle/rent-may-2026/override \
  -H 'Content-Type: application/json' -d '{"housemate":"angus","paid":true}'
# Expected: 200
```

- [ ] **Step 6: Commit**

```bash
git add server.py
git commit -m "feat: add /api/bills/cycle/<tag> detail, override, and notes endpoints"
```

---

### Task 2: Slide-in panel CSS + HTML in `bills.html`

**Files:**
- Modify: `bills.html` — add CSS styles and panel HTML

The panel reuses the same slide-in pattern as `insights.html` (`.drill-overlay` / `.drill-panel`). We use the same class names since the CSS is per-page.

- [ ] **Step 1: Add panel CSS to `bills.html`**

Find the `.tab-pane.active{display:block}` rule (around line 43) and add after it:

```css
.drill-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.55);z-index:200;opacity:0;pointer-events:none;transition:opacity 0.2s}
.drill-overlay.open{opacity:1;pointer-events:all}
.drill-panel{position:fixed;top:0;right:0;bottom:0;width:520px;max-width:100vw;background:var(--panel);border-left:1px solid var(--rule);z-index:201;transform:translateX(100%);transition:transform 0.22s cubic-bezier(.4,0,.2,1);overflow-y:auto;display:flex;flex-direction:column}
.drill-panel.open{transform:translateX(0)}
.drill-hdr{display:flex;align-items:center;justify-content:space-between;padding:16px;border-bottom:1px solid var(--rule);flex-shrink:0}
.drill-title{font-size:13px;font-weight:600;color:var(--fg)}
.drill-title-sub{font-size:11px;color:var(--dim);margin-top:2px}
.drill-close{background:none;border:1px solid var(--rule);color:var(--dim);font-family:var(--font);font-size:11px;padding:4px 10px;cursor:pointer}
.drill-close:hover{color:var(--fg);border-color:var(--fg)}
.drill-body{padding:16px;flex:1}
.drill-section{margin-bottom:20px}
.drill-section-label{font-size:10px;font-weight:600;color:var(--dim);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:8px}
.drill-hm-row{display:flex;align-items:center;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--rule)}
.drill-hm-row:last-child{border-bottom:none}
.drill-hm-name{font-size:12px;color:var(--fg);display:flex;align-items:center;gap:6px}
.drill-hm-indicator{width:10px;height:10px;border-radius:50%;background:var(--rule)}
.drill-hm-indicator.paid{background:var(--green)}
.drill-hm-meta{font-size:11px;color:var(--dim);display:flex;align-items:center;gap:8px}
.drill-hm-toggle{background:none;border:1px solid var(--rule);color:var(--dim);font-family:var(--font);font-size:10px;padding:3px 8px;cursor:pointer;border-radius:2px}
.drill-hm-toggle:hover{border-color:var(--green);color:var(--green)}
.drill-hm-toggle.paid-toggle{border-color:var(--red);color:var(--red)}
.drill-hm-toggle.paid-toggle:hover{border-color:var(--red)}
.drill-timeline-row{display:flex;gap:10px;padding:5px 0;font-size:11px}
.drill-timeline-dot{width:8px;height:8px;border-radius:50%;margin-top:3px;flex-shrink:0}
.drill-timeline-dot.payment_out{background:var(--amber)}
.drill-timeline-dot.housemate_paid{background:var(--green)}
.drill-timeline-date{color:var(--dim);min-width:80px}
.drill-timeline-event{color:var(--fg)}
.drill-notes-input{width:100%;background:var(--bg);border:1px solid var(--rule);color:var(--fg);font-family:var(--font);font-size:12px;padding:8px;resize:vertical;min-height:60px;box-sizing:border-box}
.drill-notes-input:focus{outline:none;border-color:var(--green)}
.drill-save-btn{margin-top:6px;background:none;border:1px solid var(--rule);color:var(--dim);font-family:var(--font);font-size:11px;padding:4px 12px;cursor:pointer}
.drill-save-btn:hover{border-color:var(--green);color:var(--green)}
.tbl-row-click{cursor:pointer}
.tbl-row-click:hover td{background:rgba(126,231,135,0.05)!important}
```

- [ ] **Step 2: Add panel HTML to `bills.html`**

Find `<footer class="cmd">` (around line 224) and insert before it:

```html
<div class="drill-overlay" id="drillOverlay" onclick="closeBillPanel()"></div>
<div class="drill-panel" id="drillPanel">
  <div class="drill-hdr">
    <div>
      <div class="drill-title" id="drillTitle"></div>
      <div class="drill-title-sub" id="drillSub"></div>
    </div>
    <button class="drill-close" onclick="closeBillPanel()">[X] CLOSE</button>
  </div>
  <div class="drill-body" id="drillBody">
    <div class="drill-empty">Loading...</div>
  </div>
</div>
```

- [ ] **Step 3: Verify the HTML is valid — open the page in browser, confirm no console errors from the new elements**

```
Open http://localhost:5001/bills in browser, check Console tab — should be no errors.
```

- [ ] **Step 4: Commit**

```bash
git add bills.html
git commit -m "feat: add slide-in bill detail panel CSS and HTML shell"
```

---

### Task 3: Panel JS — open, close, fetch, render

**Files:**
- Modify: `bills.html` — add JS for panel open/close/render before the closing `</script>` tag

- [ ] **Step 1: Add `closeBillPanel()` and `openBillPanel(cycleTag)` JS**

Add before the `(async()=>{` IIFE at the bottom of the `<script>` block:

```js
let _currentCycleTag = null;

function closeBillPanel(){
  document.getElementById('drillPanel').classList.remove('open');
  document.getElementById('drillOverlay').classList.remove('open');
  document.body.style.overflow = '';
  _currentCycleTag = null;
}

async function openBillPanel(cycleTag){
  _currentCycleTag = cycleTag;
  document.getElementById('drillTitle').textContent = 'Loading…';
  document.getElementById('drillSub').textContent = '';
  document.getElementById('drillBody').innerHTML = '<div class="loading">loading...</div>';
  document.getElementById('drillPanel').classList.add('open');
  document.getElementById('drillOverlay').classList.add('open');
  document.body.style.overflow = 'hidden';

  try {
    const data = await fetchJson(`/api/bills/cycle/${encodeURIComponent(cycleTag)}`);
    renderBillPanel(data);
  } catch(e) {
    document.getElementById('drillBody').innerHTML = `<div class="empty">${escapeHtml(e.message)}</div>`;
  }
}

function renderBillPanel(data){
  const fmtDate = s => s ? new Date(s).toLocaleDateString('en-AU',{day:'numeric',month:'short',year:'numeric'}) : '—';
  const sClass = data.status === 'paid' ? 's-paid' : data.status === 'partial' ? 's-partial' : 's-pending';

  document.getElementById('drillTitle').textContent = data.label;
  document.getElementById('drillSub').textContent =
    `${data.month.charAt(0).toUpperCase()+data.month.slice(1)} ${data.year}` +
    (data.provider ? ` · ${data.provider}` : '') +
    ` · `;
  // append status badge
  const subEl = document.getElementById('drillSub');
  const badge = document.createElement('span');
  badge.className = `status-badge ${sClass}`;
  badge.textContent = data.status.toUpperCase();
  subEl.appendChild(badge);

  // Payment out section
  const paymentOutHtml = data.paid_date
    ? `<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0">
         <span style="font-size:12px;color:var(--fg)">${fmtDate(data.paid_date)}</span>
         <span style="font-size:13px;font-weight:600;color:var(--amber)">${data.total_due != null ? formatCurrency(data.total_due) : '—'}</span>
       </div>`
    : `<div style="font-size:11px;color:var(--dim);padding:8px 0">Not detected from 2Up transactions.</div>`;

  // Housemates section
  const housematesHtml = data.housemates.map(hm => {
    const srcTag = hm.source ? `<span class="source-tag ${hm.source}">${hm.source === 'tag' ? 'tagged' : 'manual'}</span>` : '';
    const dateStr = hm.paid_date ? `<span style="color:var(--dim);font-size:10px">${fmtDate(hm.paid_date)}</span>` : '';
    const toggleLabel = hm.paid ? 'UNMARK' : 'MARK PAID';
    const toggleClass = hm.paid ? 'paid-toggle' : '';
    return `<div class="drill-hm-row">
      <div class="drill-hm-name">
        <span class="drill-hm-indicator${hm.paid ? ' paid' : ''}"></span>
        ${escapeHtml(hm.name.charAt(0).toUpperCase()+hm.name.slice(1))}
        ${srcTag}
      </div>
      <div class="drill-hm-meta">
        ${dateStr}
        <span style="font-size:12px;color:var(--fg)">${hm.share != null ? formatCurrency(hm.share) : '—'}</span>
        <button class="drill-hm-toggle ${toggleClass}" onclick="toggleHousematePaid('${escapeHtml(data.cycle_tag)}','${escapeHtml(hm.name)}',${!hm.paid})">${toggleLabel}</button>
      </div>
    </div>`;
  }).join('');

  // Timeline section
  const timelineHtml = data.timeline.length
    ? data.timeline.map(e => `
        <div class="drill-timeline-row">
          <span class="drill-timeline-dot ${e.type}"></span>
          <span class="drill-timeline-date">${fmtDate(e.date)}</span>
          <span class="drill-timeline-event">${escapeHtml(e.event)}</span>
        </div>`).join('')
    : '<div style="font-size:11px;color:var(--dim)">No events yet.</div>';

  // Notes section
  const notesHtml = `
    <textarea class="drill-notes-input" id="drillNotes" placeholder="Add notes…">${escapeHtml(data.notes || '')}</textarea>
    <button class="drill-save-btn" onclick="saveBillNotes('${escapeHtml(data.cycle_tag)}')">[ SAVE NOTES ]</button>`;

  document.getElementById('drillBody').innerHTML = `
    <div class="drill-section">
      <div class="drill-section-label">Payment Out</div>
      ${paymentOutHtml}
    </div>
    <div class="drill-section">
      <div class="drill-section-label">Collection · ${data.housemates.filter(h=>h.paid).length}/${data.housemates.length} paid</div>
      ${housematesHtml}
    </div>
    <div class="drill-section">
      <div class="drill-section-label">Timeline</div>
      ${timelineHtml}
    </div>
    <div class="drill-section">
      <div class="drill-section-label">Notes</div>
      ${notesHtml}
    </div>`;
}

async function toggleHousematePaid(cycleTag, housemate, paid){
  try {
    await fetchJson(`/api/bills/cycle/${encodeURIComponent(cycleTag)}/override`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({housemate, paid, note: paid ? 'manual override' : 'removed'})
    });
    // Refresh panel content
    const data = await fetchJson(`/api/bills/cycle/${encodeURIComponent(cycleTag)}`);
    renderBillPanel(data);
    // Also refresh history table in background
    loadHistory();
  } catch(e) {
    window.alert(e.message);
  }
}

async function saveBillNotes(cycleTag){
  const notes = document.getElementById('drillNotes').value;
  try {
    await fetchJson(`/api/bills/cycle/${encodeURIComponent(cycleTag)}/notes`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({notes})
    });
  } catch(e) {
    window.alert(e.message);
  }
}

// Close panel on Escape key
document.addEventListener('keydown', e => {
  if(e.key === 'Escape' && _currentCycleTag) closeBillPanel();
});
```

- [ ] **Step 2: Commit**

```bash
git add bills.html
git commit -m "feat: add bill detail panel JS (open/close/render/override/notes)"
```

---

### Task 4: Make history rows clickable

**Files:**
- Modify: `bills.html` — update `historyTableHtml()` and `renderHistoryByPerson()`

- [ ] **Step 1: Update `historyTableHtml()` to add click handler on each row**

Find the `historyTableHtml` function and replace the `return` template literal row so each `<tr>` has `class="tbl-row-click"` and `onclick`:

```js
function historyTableHtml(rows){
  if(!rows.length)return'<div class="empty">No data.</div>';
  const fmtDate=s=>s?new Date(s).toLocaleDateString('en-AU',{day:'numeric',month:'short',year:'numeric'}):'—';
  return`<div style="overflow-x:auto"><table class="tbl" style="table-layout:fixed;width:100%"><colgroup><col style="width:16%"><col style="width:16%"><col style="width:14%"><col style="width:14%"><col style="width:22%"><col style="width:18%"></colgroup><thead><tr><th>BILL</th><th>PROVIDER</th><th style="text-align:right">PAID OUT</th><th style="text-align:right">COLLECTED</th><th>PAID TAGS</th><th>PAID DATE</th></tr></thead><tbody>${rows.map(r=>{
    const paidDate=fmtDate(r.paid_date);
    const pills=r.housemates_paid.length?`<div class="pill-list">${r.housemates_paid.map(n=>`<span class="mini-pill">${escapeHtml(n)}</span>`).join('')}</div>`:'<span class="dim2">none</span>';
    const paidOut=r.total_due!=null?formatCurrency(r.total_due):'<span class="dim2">—</span>';
    const collected=r.incoming_total>0?formatCurrency(r.incoming_total):'<span class="dim2">—</span>';
    return`<tr class="tbl-row-click" onclick="openBillPanel('${escapeHtml(r.cycle_tag)}')"><td>${escapeHtml(r.label)}</td><td>${escapeHtml(r.provider||'—')}</td><td style="text-align:right">${paidOut}</td><td style="text-align:right">${collected}</td><td>${pills}<div class="dim2" style="font-size:10px">${r.housemates_paid_count}/5</div></td><td>${paidDate}</td></tr>`;
  }).join('')}</tbody></table></div>`;
}
```

- [ ] **Step 2: Update `renderHistoryByPerson()` rows to also be clickable**

Find the `renderHistoryByPerson` function and update the row template (around line 319) — the per-person table currently has `<th>BILL</th><th>PROVIDER</th><th>PAID</th><th>LATEST</th>`. Update:

```js
function renderHistoryByPerson(history){
  const c=document.getElementById('historyContent');
  const fmtDate=s=>s?new Date(s).toLocaleDateString('en-AU',{day:'numeric',month:'short',year:'numeric'}):'—';
  c.innerHTML=["angus","sean","alex","jarrod","ryan"].map(name=>{
    const rows=history.map(r=>({cycle_tag:r.cycle_tag,label:r.label,provider:r.provider||'—',paid:r.housemates_paid.includes(name),paid_date:r.paid_date}));
    const paidCount=rows.filter(r=>r.paid).length;
    return`<div class="history-group"><div class="history-group-heading">${name.charAt(0).toUpperCase()+name.slice(1)}<span class="history-group-sub">${paidCount}/${rows.length} paid</span></div><div style="overflow-x:auto"><table class="tbl"><thead><tr><th>BILL</th><th>PROVIDER</th><th>PAID</th><th>PAID DATE</th></tr></thead><tbody>${rows.map(r=>{
      const check=r.paid?'<span style="color:var(--green)">✓</span>':'<span class="dim2">–</span>';
      return`<tr class="tbl-row-click" onclick="openBillPanel('${escapeHtml(r.cycle_tag)}')"><td>${escapeHtml(r.label)}</td><td>${escapeHtml(r.provider)}</td><td>${check}</td><td>${fmtDate(r.paid_date)}</td></tr>`;
    }).join('')}</tbody></table></div></div>`;
  }).join('');
}
```

- [ ] **Step 3: Test in browser**

Open `http://localhost:5001/bills`, click the HISTORY tab, click any row → panel should slide in from the right with data.

- [ ] **Step 4: Commit**

```bash
git add bills.html
git commit -m "feat: make history rows clickable to open bill detail panel"
```

---

### Task 5: Restructure tabs — History first, retire Active Bills

**Files:**
- Modify: `bills.html` — reorder tabs, remove Active Bills tab

- [ ] **Step 1: Reorder tab buttons — History becomes first**

Find the tab buttons HTML (around line 163–168):

```html
<div class="tabs">
  <button class="tab-btn active" data-tab="active">ACTIVE.BILLS</button>
  <button class="tab-btn" data-tab="upcoming">UPCOMING</button>
  <button class="tab-btn" data-tab="history">HISTORY</button>
  <button class="tab-btn" data-tab="add">+ ADD</button>
  <button class="tab-btn" data-tab="docs">DOCS</button>
</div>
```

Replace with (History first, Active Bills removed):

```html
<div class="tabs">
  <button class="tab-btn active" data-tab="history">HISTORY</button>
  <button class="tab-btn" data-tab="upcoming">UPCOMING</button>
  <button class="tab-btn" data-tab="add">+ ADD</button>
  <button class="tab-btn" data-tab="docs">DOCS</button>
</div>
```

- [ ] **Step 2: Remove the Active Bills tab pane and make History pane active by default**

Find:

```html
<div class="tab-pane active" id="tab-active">
  <div class="bills-grid" id="billList"><div class="loading">loading...</div></div>
</div>
```

Remove that entire block.

Find:

```html
<div class="tab-pane" id="tab-history">
```

Change to:

```html
<div class="tab-pane active" id="tab-history">
```

- [ ] **Step 3: Fix the init IIFE at the bottom — it currently calls `loadBills()` to populate Active Bills**

Find:

```js
(async()=>{
  const s=await loadStatus();
  if(!s.last_sync_spending&&s.token_present){await runSync(false);return;}
  await Promise.all([loadBills(),loadHistory()]);
})().catch(e=>{document.getElementById('billList').innerHTML=`<div class="empty">${escapeHtml(e.message)}</div>`;});
```

Replace with:

```js
(async()=>{
  const s=await loadStatus();
  if(!s.last_sync_spending&&s.token_present){await runSync(false);return;}
  await Promise.all([loadBills(),loadHistory()]);
})().catch(e=>{document.getElementById('historyContent').innerHTML=`<div class="empty">${escapeHtml(e.message)}</div>`;});
```

Note: keep `loadBills()` in the init — the Upcoming tab still uses `state.bills`, and it keeps `renderUpcoming()` working.

- [ ] **Step 4: Fix the "after add bill" redirect**

Find (around line 398):

```js
document.querySelectorAll('.tab-btn')[0].click();
```

Replace with:

```js
document.querySelector('.tab-btn[data-tab="history"]').click();
```

- [ ] **Step 5: Test in browser**

- Page opens on History tab by default
- Clicking Upcoming still shows upcoming bills
- Adding a bill redirects to History
- No console errors

- [ ] **Step 6: Commit**

```bash
git add bills.html
git commit -m "feat: make History the default tab, retire Active Bills tab"
```

---

### Self-Review

**Spec coverage check:**
- ✅ Clickable history rows → Task 4
- ✅ Slide-in panel → Tasks 2 + 3
- ✅ Payment-out info (date + amount) → Task 3 `renderBillPanel`
- ✅ Per-housemate paid dates → Task 1 endpoint + Task 3 render
- ✅ Manual override toggle → Task 3 `toggleHousematePaid` + Task 1 POST endpoint
- ✅ Timeline → Task 1 endpoint + Task 3 render
- ✅ Notes field → Task 1 GET/POST endpoints + Task 3 render
- ✅ History as first/default tab → Task 5
- ✅ Active Bills tab retired → Task 5

**Placeholder scan:** None found.

**Type consistency:**
- `cycle_tag` used consistently across all endpoints and JS calls
- `housemates` array shape consistent: `{name, share, paid, source, paid_date}` in API and render
- `openBillPanel(cycleTag)` called from both `historyTableHtml` and `renderHistoryByPerson`

**Ambiguity resolved:**
- `UPCOMING` tab still works because `loadBills()` is kept in init; it populates `state.bills` which `renderUpcoming()` reads from
- The existing `POST /api/bills/<id>/override` is left intact (used by `bindHousemateToggles` if that code is referenced elsewhere); the new cycle-based override endpoint is additive
