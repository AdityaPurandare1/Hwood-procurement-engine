# HWOOD Procurement Engine

Dual-loop inventory system for multi-venue hospitality operations.

## What It Does

Takes your item data (PAR, case size, lead time, demand, cost, shipping) and calculates:

- **Venue Min/Max** — when each venue should reorder, and how much
- **Warehouse s/S** — reorder point and order-up-to levels, case-rounded
- **First orders** — exact quantities per venue + warehouse (starting from any stock level)
- **Stress tests** — worst-case drawdown simulation during supplier lead time
- **TCO analysis** — total cost of ownership at different order sizes
- **TCO targeting** — minimum order size to hit a $/unit target (for expensive shipping)
- **PO generation** — order-ready quantities per destination

## System Design

```
Supplier → Warehouse (s,S periodic review) → Venues (r,S continuous) → Guests
```

- **Warehouse:** Weekly review. When stock ≤ s, order up to S from supplier.
- **Venues:** When on-hand drops to Min, request top-up from warehouse to PAR.
- **Venue behavior modeling:** Accounts for venues that order late (configurable trigger).

## Quick Start

```python
from procurement_engine import ProcurementEngine

engine = ProcurementEngine()

# 1. Add item
engine.add_item(
    name="Serving Tong Medium",
    sku="GRM 880071",
    category="OS&E",
    subcategory="Bar Tools",
    case_size=12,
    supplier_lead_time_days=21,
)

# 2. Add venues
engine.add_venue("Delilah LA", "Serving Tong Medium", par=30, monthly_demand=9)
engine.add_venue("Delilah MIA", "Serving Tong Medium", par=50, monthly_demand=9)

# 3. Configure warehouse
engine.configure_warehouse("Serving Tong Medium", max_simultaneous_venues=2)

# 4. Run
engine.print_report("Serving Tong Medium")
engine.print_orders("Serving Tong Medium")
```

## Key Parameters

| Parameter | What It Means |
|-----------|--------------|
| `par` | Units the venue needs on hand to operate |
| `monthly_demand` | Actual observed usage per month |
| `current_on_hand` | What's physically there right now |
| `reorder_trigger_months` | Months of stock remaining before venue should reorder (default 2.5) |
| `max_simultaneous_venues` | Realistic max venues ordering from warehouse at same time |
| `case_size` | All orders rounded up to this |
| `shipping_type` | "flat" (same cost any qty), "per_case", or "per_unit" |

## Files

- `procurement_engine.py` — Core engine (import this)
- `example_usage.py` — Tongs + glassware scenarios with full output
- `HWOOD_Procurement_System_Logic.md` — Complete methodology reference

## Attrition Rates (built-in)

| Category | Monthly Rate |
|----------|-------------|
| Glassware — Delicate | 10% |
| Glassware — Sturdy | 7% |
| Flatware | 4% |
| Dinnerware | 3% |
| Bar Tools | 2.5% |
| Smallwares | 2% |

## Requirements

Python 3.10+ (standard library only, no dependencies)
