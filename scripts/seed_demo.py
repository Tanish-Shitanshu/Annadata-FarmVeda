"""Fill the database with a small demo world: four farmers, a cooperative, two consumers, listings,
orders in every state, reviews, reminders and saved scheme answers.

    python scripts/seed_demo.py            # uses FARMVEDA_DB_PATH, or ./farmveda.db
    streamlit run app.py

Then sign in as ravi@example.com (farmer) or asha@example.com (consumer); every demo account uses the
password below. The script refuses to run on a database that already has accounts, so it can't
mix demo data into real data.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import auth, coop, db, market  # noqa: E402

PW = "demo-pass-123"


def main() -> None:
    db.init_db()
    with db.get_conn() as conn:
        if conn.execute("SELECT 1 FROM accounts LIMIT 1").fetchone():
            sys.exit("This database already has accounts; refusing to add demo data. "
                     "Point FARMVEDA_DB_PATH at an empty file to seed a fresh demo.")
    _seed()


def _seed() -> None:
    def farmer(email, name, village, state, land, soil):
        a = auth.register(email, PW, "farmer", name, {"village": village, "state": state, "land_size_acres": land, "soil_type": soil})
        return a, db.get_farmer_by_account(a.id)
    ra, rf = farmer("ravi@example.com", "Ravi Kumar", "Khanna", "Punjab", 4.0, "Alluvial")
    sa, sf = farmer("sita@example.com", "Sita Devi", "Karnal", "Haryana", 2.5, "Loamy")
    ga, gf = farmer("gurpreet@example.com", "Gurpreet Singh", "Ludhiana", "Punjab", 6.0, "Alluvial")
    ma, mf = farmer("meena@example.com", "Meena Patil", "Nashik", "Maharashtra", 3.0, "Black (Regur)")
    asha = auth.register("asha@example.com", PW, "consumer", "Asha Verma")
    ben = auth.register("ben@example.com", PW, "consumer", "Ben Thomas")
    cid = coop.create_coop(rf["id"], "Khanna Growers Cooperative", "Wheat, rice and vegetables pooled from small farms around Khanna", "Punjab", "Ludhiana")
    code = coop.get_coop(cid, rf["id"])["invite_code"]
    coop.join_coop(sf["id"], code); coop.join_coop(gf["id"], code)
    d = lambda n: (date.today() - timedelta(days=n)).isoformat()
    L = {}
    L["wheat_r"] = market.create_listing(rf["id"], "Sharbati Wheat", "Grains & Cereals", "kg", 28, 400, "both", "Stone-milled quality, cleaned and bagged in 25 kg sacks.", False, d(12), cid)
    L["wheat_g"] = market.create_listing(gf["id"], "Sharbati Wheat", "Grains & Cereals", "kg", 26, 900, "both", "Machine harvested, moisture under 12%.", False, d(10), cid)
    L["wheat_s"] = market.create_listing(sf["id"], "Sharbati Wheat", "Grains & Cereals", "kg", 30, 250, "pickup", "Small-farm lot, hand cleaned.", True, d(14), cid)
    L["tomato"] = market.create_listing(rf["id"], "Desi Tomato", "Vegetables", "kg", 32, 60, "both", "Vine-ripened, picked this morning.", True, d(1))
    L["rice"] = market.create_listing(gf["id"], "Basmati Rice", "Grains & Cereals", "kg", 92, 300, "both", "Aged 12 months, long grain.", False, d(40), cid)
    L["milk"] = market.create_listing(sf["id"], "Fresh Cow Milk", "Dairy", "litre", 58, 40, "delivery", "Morning milking, delivered chilled.", True, d(0))
    L["onion"] = market.create_listing(mf["id"], "Nashik Red Onion", "Vegetables", "kg", 22, 500, "both", "Dry, well cured, good for storage.", False, d(6))
    L["moong"] = market.create_listing(mf["id"], "Green Moong", "Pulses", "kg", 110, 120, "both", "Whole green gram, sun dried.", True, d(20))
    L["mango"] = market.create_listing(mf["id"], "Kesar Mango", "Fruits", "dozen", 360, 30, "pickup", "Tree-ripened, naturally ripened.", True, d(3))
    L["sarson"] = market.create_listing(rf["id"], "Mustard (Sarson) Seed", "Oilseeds", "kg", 64, 150, "both", "Clean seed suited for pressing.", False, d(30))
    # Orders in different states
    o = market.checkout(asha.id, {L["tomato"]: 3.0, L["wheat_r"]: 10.0}, "pickup", "", "9810012345", "Will come Saturday morning")[0]
    market.update_order_status(ra.id, o, "confirmed"); market.update_order_status(ra.id, o, "delivered"); market.mark_paid(ra.id, o)
    market.post_message(asha.id, o, "Thank you, the tomatoes were great!"); market.post_message(ra.id, o, "Glad you liked them. Come again!")
    market.submit_review(asha.id, o, 5, "Fresh tomatoes and very friendly farmer.")
    o2 = market.checkout(asha.id, {L["milk"]: 4.0}, "delivery", "B-12, Green Park Extension, New Delhi 110016", "9810012345", "Ring the bell twice")[0]
    market.update_order_status(sa.id, o2, "confirmed")
    market.post_message(sa.id, o2, "Will deliver tomorrow between 7 and 8 am.")
    o3 = market.checkout(ben.id, {L["tomato"]: 5.0, L["sarson"]: 10.0}, "pickup", "", "9899911122", "")[0]
    o4 = market.checkout(ben.id, {L["wheat_r"]: 25.0}, "delivery", "22 Model Town, Ludhiana 141002", "9899911122", "")[0]
    market.update_order_status(ra.id, o4, "confirmed")
    # a second review to make shops look real
    o5 = market.checkout(ben.id, {L["rice"]: 5.0}, "pickup", "", "9899911122", "")[0]
    market.update_order_status(ga.id, o5, "confirmed"); market.update_order_status(ga.id, o5, "delivered"); market.mark_paid(ga.id, o5)
    market.submit_review(ben.id, o5, 4, "Good aroma, cooks well.")
    # farm records, reminders, scheme answers for Ravi
    db.add_farm_record(rf["id"], "Wheat", "Rabi", d(5), "Sown after paddy, drilled")
    db.add_farm_record(rf["id"], "Rice (Paddy)", "Kharif", d(150), "Basmati, harvested")
    db.add_reminder(rf["id"], "Irrigate wheat field (first watering)", (date.today() + timedelta(days=2)).isoformat(), "Irrigation")
    db.add_reminder(rf["id"], "Spray for aphids if the forecast stays dry", (date.today() + timedelta(days=5)).isoformat(), "Spraying")
    db.save_scheme_profile(rf["id"], {"land_ownership": "owner", "owned_since_2019": True, "bank_aadhaar_linked": True,
                                       "pm_kisan_exclusions": [], "has_kcc": False, "allied_activity": False, "group_member": False,
                                       "plans": ["micro_irrigation"]})
    print(f"Demo data ready. Sign in as ravi@example.com (farmer) or asha@example.com (consumer), password {PW}.")


if __name__ == "__main__":
    main()
