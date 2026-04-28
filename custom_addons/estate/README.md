# Estate Module (Interview-Ready)

## 1) Business Goal
`estate` is a Real Estate management module for Odoo:
- Manage properties from listing to closing.
- Track customer offers with acceptance/refusal workflow.
- Support manager-only critical actions.
- Provide AI-assisted offer recommendation with safe fallback.

---

## 2) Core Business Flow

### Property lifecycle
- `new` → default state when property is created.
- `offer` → automatically set when the first offer is created.
- `sold` → only allowed after at least one accepted offer.
- `cancel` → blocked for sold properties; cancel resets sale-related fields.

### Offer lifecycle
- `pending` (default) → `accepted` or `refused`.
- Accepting one offer automatically refuses other active offers.
- A property can have only one accepted offer.
- New/updated active offers must be higher than existing active offers.

### Access control
- Only users in `estate.group_estate_manager` can:
  - Accept offers.
  - Mark property as sold.

---

## 3) Key Functional Areas
- **Models**
  - `estate.property`
  - `estate.property.offer`
  - `estate.property.type`
  - `estate.property.tag`
  - `estate.ai.service`
  - `estate.notification.mixin`
- **Views**
  - Property tree/kanban/form with inline offers.
  - Offer tree/form/search.
  - AI insights panel on property form.
- **Security**
  - Group-based permissions and model access rules.

---

## 4) AI Recommendation Design
- Provider is configurable in Settings (`OpenRouter` or `Gemini`).
- Recommendation input includes property context + active offers.
- Expected response schema:
  - `offer_id`
  - `reasoning`
  - `confidence` (normalized to `0..100`)
- If provider fails (quota/key/model/network), module falls back to rule-based selection (best active price) so business flow is never blocked.

---

## 5) Technical Decisions (Why)
- Keep business rules in model layer (`@api.constrains`, actions, overrides) for data integrity regardless of UI entry point.
- Use status transitions as explicit workflow states to simplify validation.
- Enforce multi-company consistency in offers with company-aware fields and constraints.
- Keep AI integration isolated in a dedicated service model for maintainability and easier testability.

---

## 6) Test Coverage (Current)
Tests are in `custom_addons/estate/tests/test_estate_property.py` and cover:
- Offer creation transitions property to `offer`.
- Accept flow updates buyer/selling price and refuses other offers.
- Manager permission checks for accept/sold actions.
- Sold preconditions (must have accepted offer).
- Cancel behavior resets sale fields.
- Offer price rules (active vs refused behavior).
- AI fallback behavior when provider call fails.

Run focused tests:

```powershell
python odoo-bin -c D:\odoo-pet-project\odoo.conf -d estate_test_db -u estate --test-enable --test-tags /estate:TestEstateProperty --stop-after-init
```

Run full module tests:

```powershell
python odoo-bin -c D:\odoo-pet-project\odoo.conf -d estate_test_db -u estate --test-enable --test-tags /estate --stop-after-init
```

---

## 7) Suggested Demo Script (5–7 minutes)
1. Create a property (`new`).
2. Add multiple offers (property auto moves to `offer`).
3. Accept one offer as manager (others auto refused).
4. Show AI insights and recommendation flow.
5. Mark property as sold.
6. Open offer/property reporting/search views.

---

## 8) Known Limits / Next Steps
- Add concurrency-focused tests (simultaneous accept attempts).
- Add richer record rules for advanced ownership/team scenarios.
- Add recommendation history log for full AI audit trail.
