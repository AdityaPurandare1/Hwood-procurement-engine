"""
HWOOD Procurement Engine — Example Usage
=========================================
This file recreates the exact scenarios we worked through in conversation.
Run this to verify the engine matches our manual calculations.
"""

from procurement_engine import ProcurementEngine


engine = ProcurementEngine()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCENARIO 1: Food Tongs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

engine.add_item(
    name="Serving Tong Medium",
    sku="GRM 880071",
    category="OS&E",
    subcategory="Bar Tools",
    case_size=12,
    unit_cost=None,                  # waiting on Sabrina's pricing
    shipping_cost=None,
    supplier="Charingworth/Studio William",
    supplier_contact="Sabrina Sandha <sabrina.sandha@studiowilliam.com>",
    supplier_lead_time_days=21,
)

# Venues — all starting from 0, demand is 12-24 per venue per 2 months (midpoint 9/month)
engine.add_venue("Delilah LA",     "Serving Tong Medium", par=30, monthly_demand=9, current_on_hand=0)
engine.add_venue("Delilah MIA",    "Serving Tong Medium", par=50, monthly_demand=9, current_on_hand=0)
engine.add_venue("Delilah Dallas", "Serving Tong Medium", par=50, monthly_demand=9, current_on_hand=0)

# Warehouse — max 2 venues order at once (never had all 3 at same time)
# Override s=24, S=36 — lean levels we agreed on in conversation
engine.configure_warehouse("Serving Tong Medium", max_simultaneous_venues=2, current_on_hand=0,
                           override_s=24, override_S=36)

print("\n" + "━" * 70)
print("  SCENARIO 1: FOOD TONGS (Serving Tong Medium)")
print("━" * 70)
engine.print_report("Serving Tong Medium")
engine.print_orders("Serving Tong Medium")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCENARIO 2: Bottle Service Tongs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

engine.add_item(
    name="Bottle Service Tong",
    sku="GRM 880071-BS",             # placeholder SKU
    category="OS&E",
    subcategory="Bar Tools",
    case_size=12,
    unit_cost=None,
    shipping_cost=None,
    supplier="Charingworth/Studio William",
    supplier_contact="Sabrina Sandha <sabrina.sandha@studiowilliam.com>",
    supplier_lead_time_days=21,
)

engine.add_venue("Delilah LA",     "Bottle Service Tong", par=30, monthly_demand=9, current_on_hand=0)
engine.add_venue("Delilah MIA",    "Bottle Service Tong", par=30, monthly_demand=9, current_on_hand=0)
engine.add_venue("Delilah Dallas", "Bottle Service Tong", par=20, monthly_demand=9, current_on_hand=0)

engine.configure_warehouse("Bottle Service Tong", max_simultaneous_venues=2, current_on_hand=0,
                           override_s=24, override_S=36)

print("\n" + "━" * 70)
print("  SCENARIO 2: BOTTLE SERVICE TONGS")
print("━" * 70)
engine.print_report("Bottle Service Tong")
engine.print_orders("Bottle Service Tong")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SCENARIO 3: Glassware (single venue, high shipping)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

engine.add_item(
    name="Coupe Glass",
    sku="EXAMPLE-COUPE",
    category="OS&E",
    subcategory="Glassware - Delicate",
    case_size=24,
    unit_cost=4.48,
    shipping_cost=660.00,
    shipping_type="flat",            # $660 flat per shipment
    supplier="Overseas Supplier",
    supplier_lead_time_days=21,
)

# Single venue, 120 usage in 6 months = 20/month
engine.add_venue("Delilah LA", "Coupe Glass", par=120, monthly_demand=20,
                 current_on_hand=15, reorder_trigger_months=2.5)

engine.configure_warehouse("Coupe Glass", max_simultaneous_venues=1, current_on_hand=0)

print("\n" + "━" * 70)
print("  SCENARIO 3: COUPE GLASS (single venue, overseas shipping)")
print("━" * 70)
engine.print_report("Coupe Glass")
engine.print_orders("Coupe Glass")

# TCO target calculation
print("── TCO TARGET: Under $7.00 ──\n")
result = engine.tco_target("Coupe Glass", target_tco=7.00)
print(f"  To hit ${result['target_tco']}/unit TCO:")
print(f"  Min order: {result['min_units']} units → {result['min_cases']} cases ({result['rounded_units']} units)")
print(f"  Actual TCO at that qty: ${result['actual_tco']}/unit")
print()


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# QUICK REFERENCE: How to use for new items
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

print("""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  QUICK REFERENCE — Adding a New Item
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  1. Add the item:
     engine.add_item(
         name="Item Name",
         sku="SKU-123",
         category="OS&E",              # OS&E | Collateral | Other Items
         subcategory="Glassware - Delicate",  # determines attrition rate
         case_size=24,
         unit_cost=4.48,
         shipping_cost=660,
         shipping_type="flat",          # flat | per_case | per_unit
         supplier="Supplier Name",
         supplier_lead_time_days=21,
     )

  2. Add venues:
     engine.add_venue("Venue Name", "Item Name",
         par=120,                       # on-hand target
         monthly_demand=20,             # actual observed usage/month
         current_on_hand=15,            # what they have now
         reorder_trigger_months=2.5,    # months left before they should reorder
     )

  3. Configure warehouse:
     engine.configure_warehouse("Item Name",
         max_simultaneous_venues=2,     # realistic max venues ordering at once
         current_on_hand=0,
     )

  4. Run:
     engine.print_report("Item Name")   # full analysis
     engine.print_orders("Item Name")   # PO-ready quantities
     engine.tco_target("Item Name", 7)  # min order for target TCO
""")
