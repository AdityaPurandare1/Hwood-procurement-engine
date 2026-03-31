"""
HWOOD Procurement Engine
========================
Dual-loop (s,S) / (r,S) inventory system for multi-venue hospitality operations.

Usage:
    from procurement_engine import Item, Venue, Warehouse, ProcurementEngine

    engine = ProcurementEngine()

    # Add an item
    engine.add_item(
        name="Serving Tong Medium",
        sku="GRM 880071",
        category="OS&E",
        subcategory="Bar Tools",
        case_size=12,
        unit_cost=None,          # fill when pricing comes back
        shipping_cost=None,
        supplier="Charingworth/Studio William",
        supplier_contact="Sabrina Sandha <sabrina.sandha@studiowilliam.com>",
        supplier_lead_time_days=21,
    )

    # Add venues with PAR and behavior
    engine.add_venue("Delilah LA", "Serving Tong Medium", par=30, monthly_demand=9)
    engine.add_venue("Delilah MIA", "Serving Tong Medium", par=50, monthly_demand=9)
    engine.add_venue("Delilah Dallas", "Serving Tong Medium", par=50, monthly_demand=9)

    # Configure warehouse
    engine.configure_warehouse("Serving Tong Medium", max_simultaneous_venues=2)

    # Run all calculations
    report = engine.calculate("Serving Tong Medium")
    engine.print_report("Serving Tong Medium")
"""

import math
import json
from dataclasses import dataclass, field
from typing import Optional
from datetime import datetime, timedelta


# ─────────────────────────────────────────────
# Data Classes
# ─────────────────────────────────────────────

@dataclass
class Item:
    name: str
    sku: str
    category: str                          # OS&E, Collateral, Other Items
    subcategory: str                       # Glassware, Bar Tools, Flatware, etc.
    case_size: int                         # units per case/pack
    unit_cost: Optional[float] = None
    shipping_cost: Optional[float] = None  # per shipment (flat or estimated)
    shipping_type: str = "flat"            # "flat" | "per_case" | "per_unit"
    supplier: str = ""
    supplier_contact: str = ""
    supplier_lead_time_days: int = 14      # default 14, collateral/equipment 21
    image_path: Optional[str] = None
    notes: str = ""


@dataclass
class Venue:
    name: str
    item_name: str
    par: int                               # on-hand target
    monthly_demand: float                  # actual observed monthly usage
    current_on_hand: int = 0               # what they have right now
    reorder_trigger_months: float = 2.5    # months of stock left before trigger
    # Calculated fields
    min_r: int = 0
    max_s: int = 0
    order_qty: int = 0
    daily_demand: float = 0.0


@dataclass
class WarehouseConfig:
    item_name: str
    review_period_days: int = 7
    max_simultaneous_venues: int = 2       # realistic max venues ordering at once
    current_on_hand: int = 0
    current_on_po: int = 0
    # Calculated fields
    safety_stock: int = 0
    s_reorder_point: int = 0
    S_order_up_to: int = 0
    reorder_qty: int = 0
    reorder_qty_cases: int = 0


# ─────────────────────────────────────────────
# Attrition Rates
# ─────────────────────────────────────────────

ATTRITION_RATES = {
    "Glassware - Delicate":  0.10,   # wine stems, coupes, martini, nick & nora, flutes
    "Glassware - Sturdy":    0.07,   # rocks, collins, highball, tumbler, mug, beer
    "Flatware":              0.04,   # forks, knives, spoons
    "Dinnerware":            0.03,   # plates, bowls, platters, ramekins
    "Bar Tools":             0.025,  # shakers, strainers, jiggers, tongs
    "Smallwares":            0.02,   # cambro pans, squeeze bottles, scoops
}

# Velocity thresholds
VELOCITY_FAST = 15
VELOCITY_MED = 5

# Buffer days by velocity (warehouse / venue)
BUFFER_DAYS_WAREHOUSE = {"FAST": 7, "MED": 14, "SLOW": 7}
BUFFER_DAYS_VENUE = {"FAST": 3, "MED": 5, "SLOW": 3}

# Service level
Z_SCORE = 1.65  # 95% service level


# ─────────────────────────────────────────────
# Procurement Engine
# ─────────────────────────────────────────────

class ProcurementEngine:

    def __init__(self):
        self.items: dict[str, Item] = {}
        self.venues: dict[str, list[Venue]] = {}       # item_name -> [Venue]
        self.warehouse: dict[str, WarehouseConfig] = {} # item_name -> WarehouseConfig

    # ── Item Management ──

    def add_item(self, name: str, **kwargs) -> Item:
        item = Item(name=name, **kwargs)
        self.items[name] = item
        if name not in self.venues:
            self.venues[name] = []
        return item

    def update_item(self, name: str, **kwargs):
        if name not in self.items:
            raise ValueError(f"Item '{name}' not found. Add it first.")
        for k, v in kwargs.items():
            if hasattr(self.items[name], k):
                setattr(self.items[name], k, v)

    def list_items(self):
        for name, item in self.items.items():
            venues = self.venues.get(name, [])
            venue_names = [v.name for v in venues]
            print(f"  {name} ({item.sku}) — {item.category}/{item.subcategory}")
            print(f"    Case size: {item.case_size} | LT: {item.supplier_lead_time_days}d | Supplier: {item.supplier}")
            if venue_names:
                print(f"    Venues: {', '.join(venue_names)}")
            print()

    # ── Venue Management ──

    def add_venue(self, venue_name: str, item_name: str, par: int,
                  monthly_demand: float, current_on_hand: int = 0,
                  reorder_trigger_months: float = 2.5) -> Venue:
        if item_name not in self.items:
            raise ValueError(f"Item '{item_name}' not found. Add item first.")

        venue = Venue(
            name=venue_name,
            item_name=item_name,
            par=par,
            monthly_demand=monthly_demand,
            current_on_hand=current_on_hand,
            reorder_trigger_months=reorder_trigger_months,
        )
        self.venues[item_name].append(venue)
        return venue

    def update_venue_on_hand(self, venue_name: str, item_name: str, on_hand: int):
        for v in self.venues.get(item_name, []):
            if v.name == venue_name:
                v.current_on_hand = on_hand
                return
        raise ValueError(f"Venue '{venue_name}' not found for item '{item_name}'")

    # ── Warehouse Configuration ──

    def configure_warehouse(self, item_name: str,
                            max_simultaneous_venues: int = 2,
                            review_period_days: int = 7,
                            current_on_hand: int = 0,
                            current_on_po: int = 0,
                            override_s: Optional[int] = None,
                            override_S: Optional[int] = None) -> WarehouseConfig:
        """
        Configure warehouse for an item.

        override_s / override_S: Manually set reorder point and order-up-to
        when the formula output doesn't match your real-world judgment.
        The engine will still run stress tests against these values.
        """
        if item_name not in self.items:
            raise ValueError(f"Item '{item_name}' not found.")

        wh = WarehouseConfig(
            item_name=item_name,
            review_period_days=review_period_days,
            max_simultaneous_venues=max_simultaneous_venues,
            current_on_hand=current_on_hand,
            current_on_po=current_on_po,
        )
        # Store overrides as attributes
        wh._override_s = override_s
        wh._override_S = override_S
        self.warehouse[item_name] = wh
        return wh

    # ── Core Calculations ──

    def _get_velocity(self, avg_monthly: float) -> str:
        if avg_monthly > VELOCITY_FAST:
            return "FAST"
        elif avg_monthly > VELOCITY_MED:
            return "MED"
        else:
            return "SLOW"

    def _round_to_case(self, units: int, case_size: int) -> int:
        """Round UP to nearest case size."""
        return math.ceil(units / case_size) * case_size

    def calculate(self, item_name: str) -> dict:
        """Run all calculations for an item. Returns full report dict."""

        item = self.items.get(item_name)
        if not item:
            raise ValueError(f"Item '{item_name}' not found.")

        venues = self.venues.get(item_name, [])
        if not venues:
            raise ValueError(f"No venues configured for '{item_name}'.")

        wh_config = self.warehouse.get(item_name)
        if not wh_config:
            raise ValueError(f"Warehouse not configured for '{item_name}'. Run configure_warehouse() first.")

        # ── Venue-level calculations ──
        venue_results = []
        total_monthly_demand = 0

        for v in venues:
            v.daily_demand = v.monthly_demand / 30
            velocity = self._get_velocity(v.monthly_demand)
            buffer = BUFFER_DAYS_VENUE[velocity]

            # Venue safety stock
            venue_ss = max(1, math.ceil(v.daily_demand * buffer))

            # Venue Min: trigger based on months of stock remaining
            # But NEVER exceed PAR (otherwise min > max which is nonsensical)
            raw_min = math.ceil(v.monthly_demand * v.reorder_trigger_months)
            v.min_r = max(1, min(raw_min, v.par - 1))

            # Venue Max: full PAR
            v.max_s = v.par

            # Order qty: top up to PAR from min (typical reorder)
            v.order_qty = max(0, v.par - v.min_r)

            # Typical ongoing order: ~1 month of demand (what warehouse should plan for)
            typical_venue_draw = math.ceil(v.monthly_demand)

            # What they need RIGHT NOW (starting from current on hand)
            need_now = max(0, v.par - v.current_on_hand)
            need_now_cases = self._round_to_case(need_now, item.case_size) if need_now > 0 else 0

            total_monthly_demand += v.monthly_demand

            venue_results.append({
                "venue": v.name,
                "par": v.par,
                "monthly_demand": v.monthly_demand,
                "daily_demand": round(v.daily_demand, 2),
                "velocity": velocity,
                "venue_ss": venue_ss,
                "min_r": v.min_r,
                "max_s": v.max_s,
                "order_qty": v.order_qty,
                "typical_draw": typical_venue_draw,
                "current_on_hand": v.current_on_hand,
                "need_now": need_now,
                "need_now_cases": need_now_cases,
                "need_now_packs": need_now_cases // item.case_size if need_now_cases > 0 else 0,
                "reorder_trigger_months": v.reorder_trigger_months,
            })

        # ── Warehouse-level calculations ──
        #
        # KEY INSIGHT: Warehouse is sized for ONGOING replenishment, not
        # initial PAR fills. Venues draw monthly demand, not full PAR.
        # The simultaneous draw = monthly demand × N simultaneous venues.
        #
        combined_daily = total_monthly_demand / 30
        velocity = self._get_velocity(total_monthly_demand)
        buffer = BUFFER_DAYS_WAREHOUSE[velocity]

        # Warehouse safety stock
        wh_ss = max(1, math.ceil(combined_daily * buffer))
        wh_config.safety_stock = wh_ss

        # Simultaneous venue draw: use typical monthly draw (not full PAR top-up)
        typical_draws = sorted([vr["typical_draw"] for vr in venue_results], reverse=True)
        simultaneous_draw = sum(typical_draws[:wh_config.max_simultaneous_venues])

        # s: cover lead time + review period demand + safety stock
        lt_review_demand = math.ceil(combined_daily * (item.supplier_lead_time_days + wh_config.review_period_days))
        wh_config.s_reorder_point = lt_review_demand + wh_ss

        # S: s + one review period of demand (enough to not immediately re-trigger)
        raw_S = wh_config.s_reorder_point + max(simultaneous_draw, math.ceil(combined_daily * wh_config.review_period_days))
        wh_config.S_order_up_to = self._round_to_case(raw_S, item.case_size)

        # Apply manual overrides if set
        formula_s = wh_config.s_reorder_point
        formula_S = wh_config.S_order_up_to
        overridden = False
        if hasattr(wh_config, '_override_s') and wh_config._override_s is not None:
            wh_config.s_reorder_point = wh_config._override_s
            overridden = True
        if hasattr(wh_config, '_override_S') and wh_config._override_S is not None:
            wh_config.S_order_up_to = wh_config._override_S
            overridden = True

        # Reorder qty
        raw_reorder = wh_config.S_order_up_to - wh_config.s_reorder_point
        wh_config.reorder_qty = self._round_to_case(max(item.case_size, raw_reorder), item.case_size)
        wh_config.reorder_qty_cases = wh_config.reorder_qty // item.case_size

        # Current position
        current_position = wh_config.current_on_hand + wh_config.current_on_po
        warehouse_need = max(0, wh_config.S_order_up_to - current_position)
        warehouse_need_cases = self._round_to_case(warehouse_need, item.case_size)

        # ── TCO ──
        tco = None
        if item.unit_cost is not None and item.shipping_cost is not None:
            tco = self._calculate_tco(item, venue_results, wh_config)

        # ── First Order (from zero) ──
        total_venue_need = sum(vr["need_now_cases"] for vr in venue_results)
        total_first_order = total_venue_need + warehouse_need_cases
        total_first_order_cases = total_first_order // item.case_size

        # ── Stress Test ──
        stress_test = self._stress_test(item, wh_config, simultaneous_draw, combined_daily)

        report = {
            "item": {
                "name": item.name,
                "sku": item.sku,
                "category": f"{item.category} / {item.subcategory}",
                "case_size": item.case_size,
                "unit_cost": item.unit_cost,
                "shipping_cost": item.shipping_cost,
                "supplier": item.supplier,
                "supplier_lt": item.supplier_lead_time_days,
            },
            "venues": venue_results,
            "warehouse": {
                "combined_monthly_demand": round(total_monthly_demand, 1),
                "combined_daily_demand": round(combined_daily, 2),
                "velocity": velocity,
                "safety_stock": wh_ss,
                "s_reorder_point": wh_config.s_reorder_point,
                "S_order_up_to": wh_config.S_order_up_to,
                "S_cases": wh_config.S_order_up_to // item.case_size,
                "reorder_qty": wh_config.reorder_qty,
                "reorder_qty_cases": wh_config.reorder_qty_cases,
                "max_simultaneous_venues": wh_config.max_simultaneous_venues,
                "simultaneous_draw": simultaneous_draw,
                "review_period": wh_config.review_period_days,
                "current_on_hand": wh_config.current_on_hand,
                "current_on_po": wh_config.current_on_po,
                "warehouse_need": warehouse_need_cases,
                "warehouse_need_cases": warehouse_need_cases // item.case_size,
                "overridden": overridden,
                "formula_s": formula_s,
                "formula_S": formula_S,
            },
            "first_order": {
                "venue_units": total_venue_need,
                "venue_cases": total_venue_need // item.case_size,
                "warehouse_units": warehouse_need_cases,
                "warehouse_cases": warehouse_need_cases // item.case_size,
                "total_units": total_first_order,
                "total_cases": total_first_order_cases,
                "total_cost": round(total_first_order * item.unit_cost, 2) if item.unit_cost else None,
            },
            "tco": tco,
            "stress_test": stress_test,
        }

        return report

    def _calculate_tco(self, item: Item, venue_results: list, wh_config: WarehouseConfig) -> dict:
        """Calculate TCO at different order sizes."""
        results = []
        case_size = item.case_size

        # Test various case quantities
        for num_cases in [1, 2, 3, 5, 8, 10, 11, 12, 15, 20]:
            units = num_cases * case_size
            product_cost = units * item.unit_cost

            if item.shipping_type == "flat":
                shipping = item.shipping_cost
            elif item.shipping_type == "per_case":
                shipping = item.shipping_cost * num_cases
            elif item.shipping_type == "per_unit":
                shipping = item.shipping_cost * units
            else:
                shipping = item.shipping_cost

            total = product_cost + shipping
            tco_per_unit = round(total / units, 2)

            results.append({
                "cases": num_cases,
                "units": units,
                "product_cost": round(product_cost, 2),
                "shipping": round(shipping, 2),
                "total": round(total, 2),
                "tco_per_unit": tco_per_unit,
            })

        return results

    def _stress_test(self, item: Item, wh_config: WarehouseConfig,
                     simultaneous_draw: int, combined_daily: float) -> list:
        """Simulate worst-case warehouse drawdown during supplier lead time."""
        stock = wh_config.s_reorder_point  # start at reorder point (worst trigger)
        lt = item.supplier_lead_time_days
        review = wh_config.review_period_days
        events = []

        events.append({
            "day": 0,
            "event": f"Warehouse at s ({stock}), PO placed to supplier",
            "stock": stock,
        })

        day = 0
        wave = 0
        while day < lt:
            day += review
            wave += 1
            if day <= lt:
                stock -= simultaneous_draw
                events.append({
                    "day": day,
                    "event": f"Wave {wave}: {wh_config.max_simultaneous_venues} venues order ({simultaneous_draw} units out)",
                    "stock": max(0, stock),
                    "stockout": stock < 0,
                })

        # Delivery arrives
        stock += wh_config.reorder_qty
        events.append({
            "day": lt,
            "event": f"Supplier delivery arrives (+{wh_config.reorder_qty} units)",
            "stock": stock,
        })

        return events

    # ── TCO Target Calculator ──

    def tco_target(self, item_name: str, target_tco: float) -> dict:
        """Calculate minimum order size to hit a target TCO per unit."""
        item = self.items.get(item_name)
        if not item or not item.unit_cost or not item.shipping_cost:
            raise ValueError("Item needs unit_cost and shipping_cost set.")

        if item.shipping_type == "flat":
            # (qty * unit_cost + shipping) / qty < target
            # shipping < qty * (target - unit_cost)
            # qty > shipping / (target - unit_cost)
            if target_tco <= item.unit_cost:
                return {"error": f"Target TCO ${target_tco} is below unit cost ${item.unit_cost}. Impossible."}
            min_qty = math.ceil(item.shipping_cost / (target_tco - item.unit_cost))
            min_cases = math.ceil(min_qty / item.case_size)
            actual_qty = min_cases * item.case_size
            actual_tco = round((actual_qty * item.unit_cost + item.shipping_cost) / actual_qty, 2)
            return {
                "target_tco": target_tco,
                "min_units": min_qty,
                "min_cases": min_cases,
                "rounded_units": actual_qty,
                "actual_tco": actual_tco,
            }
        else:
            return {"note": "TCO target calc only works with flat shipping. For per-unit/per-case, use tco table."}

    # ── Reporting ──

    def print_report(self, item_name: str):
        """Print a clean report for an item."""
        r = self.calculate(item_name)
        item = r["item"]

        print("=" * 70)
        print(f"  PROCUREMENT REPORT: {item['name']}")
        print(f"  SKU: {item['sku']} | {item['category']}")
        print(f"  Supplier: {item['supplier']} | Lead Time: {item['supplier_lt']} days")
        print(f"  Case Size: {item['case_size']} units")
        if item['unit_cost']:
            print(f"  Unit Cost: ${item['unit_cost']}")
        print("=" * 70)

        # Venues
        print("\n── VENUE BREAKDOWN ──\n")
        for v in r["venues"]:
            print(f"  {v['venue']}")
            print(f"    PAR: {v['par']} | Monthly Demand: {v['monthly_demand']} | Velocity: {v['velocity']}")
            print(f"    Min (r): {v['min_r']} ({v['reorder_trigger_months']}mo trigger) | Max (S): {v['max_s']} (PAR)")
            print(f"    Order Qty (top-up): {v['order_qty']}")
            print(f"    Current On-Hand: {v['current_on_hand']} → Need Now: {v['need_now_cases']} units ({v['need_now_packs']} packs)")
            print()

        # Warehouse
        wh = r["warehouse"]
        print("── WAREHOUSE (s, S) SYSTEM ──\n")
        print(f"  Combined Monthly Demand: {wh['combined_monthly_demand']} | Daily: {wh['combined_daily_demand']}")
        print(f"  Velocity: {wh['velocity']} | Safety Stock: {wh['safety_stock']}")
        print(f"  Max Simultaneous Venues: {wh['max_simultaneous_venues']} → Draw: {wh['simultaneous_draw']} units")
        print(f"  Review Period: every {wh['review_period']} days")
        print()
        if wh['overridden']:
            print(f"  s (Reorder Point):  {wh['s_reorder_point']} units  ← MANUAL OVERRIDE (formula suggested {wh['formula_s']})")
            print(f"  S (Order-Up-To):    {wh['S_order_up_to']} units ({wh['S_cases']} cases)  ← MANUAL OVERRIDE (formula suggested {wh['formula_S']})")
        else:
            print(f"  s (Reorder Point):  {wh['s_reorder_point']} units")
            print(f"  S (Order-Up-To):    {wh['S_order_up_to']} units ({wh['S_cases']} cases)")
        print(f"  Reorder Qty:        {wh['reorder_qty']} units ({wh['reorder_qty_cases']} cases)")
        print()

        # First Order
        fo = r["first_order"]
        print("── FIRST ORDER (from current stock) ──\n")
        for v in r["venues"]:
            print(f"  {v['venue']}: {v['need_now_cases']} units ({v['need_now_packs']} packs)")
        print(f"  Warehouse: {fo['warehouse_units']} units ({fo['warehouse_cases']} packs)")
        print(f"  ─────────────────────────")
        print(f"  TOTAL: {fo['total_units']} units ({fo['total_cases']} cases)")
        if fo['total_cost']:
            print(f"  Est. Cost: ${fo['total_cost']}")
        print()

        # Stress Test
        print("── STRESS TEST (worst case from s) ──\n")
        for e in r["stress_test"]:
            marker = " ⚠️ STOCKOUT" if e.get("stockout") else ""
            print(f"  Day {e['day']:>3}: {e['event']} → Stock: {e['stock']}{marker}")
        print()

        # TCO
        if r["tco"]:
            print("── TCO BY ORDER SIZE ──\n")
            print(f"  {'Cases':>6} {'Units':>6} {'Product':>10} {'Shipping':>10} {'Total':>10} {'TCO/Unit':>10}")
            print(f"  {'─'*6} {'─'*6} {'─'*10} {'─'*10} {'─'*10} {'─'*10}")
            for t in r["tco"]:
                print(f"  {t['cases']:>6} {t['units']:>6} ${t['product_cost']:>9.2f} ${t['shipping']:>9.2f} ${t['total']:>9.2f} ${t['tco_per_unit']:>9.2f}")
            print()

    def generate_orders(self, item_name: str) -> list[dict]:
        """Generate individual PO-ready orders for each venue + warehouse."""
        r = self.calculate(item_name)
        item = self.items[item_name]
        orders = []

        for v in r["venues"]:
            if v["need_now_cases"] > 0:
                orders.append({
                    "type": "venue_stockup",
                    "destination": v["venue"],
                    "item": item.name,
                    "sku": item.sku,
                    "units": v["need_now_cases"],
                    "cases": v["need_now_packs"],
                    "purpose": f"PAR stock-up (PAR={v['par']})",
                })

        wh = r["warehouse"]
        if wh["warehouse_need"] > 0:
            orders.append({
                "type": "warehouse_stockup",
                "destination": "Warehouse",
                "item": item.name,
                "sku": item.sku,
                "units": wh["warehouse_need"],
                "cases": wh["warehouse_need_cases"],
                "purpose": f"Warehouse buffer (S={wh['S_order_up_to']})",
            })

        return orders

    def print_orders(self, item_name: str):
        """Print PO-ready order summary."""
        orders = self.generate_orders(item_name)
        item = self.items[item_name]

        print(f"\n{'=' * 50}")
        print(f"  PURCHASE ORDERS — {item.name}")
        print(f"  Supplier: {item.supplier}")
        print(f"{'=' * 50}\n")

        total_units = 0
        total_cases = 0
        for i, o in enumerate(orders, 1):
            print(f"  PO #{i}: {o['destination']}")
            print(f"    {o['item']} ({o['sku']})")
            print(f"    Qty: {o['units']} units ({o['cases']} packs of {item.case_size})")
            print(f"    Purpose: {o['purpose']}")
            print()
            total_units += o['units']
            total_cases += o['cases']

        print(f"  ─────────────────────────")
        print(f"  TOTAL: {total_units} units ({total_cases} cases)")
        if item.unit_cost:
            print(f"  Est. Cost: ${round(total_units * item.unit_cost, 2)}")
        print()

    # ── Export ──

    def export_json(self, item_name: str, filepath: str = None):
        """Export full report as JSON."""
        report = self.calculate(item_name)
        if filepath is None:
            filepath = f"{item_name.replace(' ', '_').lower()}_report.json"
        with open(filepath, "w") as f:
            json.dump(report, f, indent=2)
        print(f"  Report exported to: {filepath}")
        return filepath
