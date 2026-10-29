import pytest

from conftest import new_consumer, new_farmer
from core import coop, db, market
from core.coop import CoopError

PHONE = "9876543210"


@pytest.fixture
def group(tmp_db):
    a, fa = new_farmer("a@example.com", "Asha Devi", "Punjab", "Khanna")
    b, fb = new_farmer("b@example.com", "Balwant", "Punjab", "Ludhiana")
    c, fc = new_farmer("c@example.com", "Chand", "Haryana", "Karnal")
    buyer = new_consumer("buyer@example.com", "Buyer One")
    cid = coop.create_coop(fa["id"], "Khanna Growers", "Wheat and vegetables", "Punjab", "Ludhiana")
    return type("G", (), dict(a=a, fa=fa, b=b, fb=fb, c=c, fc=fc, buyer=buyer, cid=cid))


def code(g):
    return coop.get_coop(g.cid, g.fa["id"])["invite_code"]


def test_creator_becomes_admin_and_code_is_private(group):
    assert coop.my_coops(group.fa["id"])[0]["my_role"] == "admin"
    assert "invite_code" in coop.get_coop(group.cid, group.fa["id"])
    assert "invite_code" not in coop.get_coop(group.cid, group.fb["id"])
    assert "invite_code" not in coop.get_coop(group.cid)
    assert all("invite_code" not in dict(r) for r in coop.list_coops())


def test_join_by_code_only(group):
    with pytest.raises(CoopError, match="isn't valid"):
        coop.join_coop(group.fb["id"], "WRONGCODE")
    coop.join_coop(group.fb["id"], code(group).lower())               # case-insensitive
    assert coop.is_member(group.fb["id"], group.cid)
    with pytest.raises(CoopError, match="already"):
        coop.join_coop(group.fb["id"], code(group))
    assert coop.get_coop(group.cid)["member_count"] == 2


def test_duplicate_names_rejected_case_insensitively(group):
    with pytest.raises(CoopError, match="already exists"):
        coop.create_coop(group.fb["id"], "khanna growers")
    with pytest.raises(market.MarketError, match="required"):
        coop.create_coop(group.fb["id"], "   ")


def test_only_admin_manages_members_and_roles(group):
    coop.join_coop(group.fb["id"], code(group)); coop.join_coop(group.fc["id"], code(group))
    with pytest.raises(CoopError, match="admin"):
        coop.remove_member(group.fb["id"], group.cid, group.fc["id"])
    with pytest.raises(CoopError, match="admin"):
        coop.set_member_role(group.fb["id"], group.cid, group.fb["id"], "admin")      # no self-promotion
    with pytest.raises(CoopError, match="admin"):
        coop.regenerate_invite(group.fb["id"], group.cid)
    coop.set_member_role(group.fa["id"], group.cid, group.fb["id"], "admin")
    coop.remove_member(group.fb["id"], group.cid, group.fc["id"])                    # now allowed
    assert not coop.is_member(group.fc["id"], group.cid)


def test_cannot_remove_self_or_demote_last_admin(group):
    with pytest.raises(CoopError, match="Leave"):
        coop.remove_member(group.fa["id"], group.cid, group.fa["id"])
    with pytest.raises(CoopError, match="at least one admin"):
        coop.set_member_role(group.fa["id"], group.cid, group.fa["id"], "member")


def test_leave_rules(group):
    coop.join_coop(group.fb["id"], code(group))
    with pytest.raises(CoopError, match="another member an admin"):
        coop.leave_coop(group.fa["id"], group.cid)
    coop.leave_coop(group.fb["id"], group.cid)
    coop.leave_coop(group.fa["id"], group.cid)                         # last one out deletes the empty coop
    assert coop.get_coop(group.cid) is None


def test_regenerated_code_invalidates_old_one(group):
    old = code(group)
    new = coop.regenerate_invite(group.fa["id"], group.cid)
    assert new != old
    with pytest.raises(CoopError):
        coop.join_coop(group.fb["id"], old)
    coop.join_coop(group.fb["id"], new)


def test_membership_cap(group):
    for i in range(coop.MAX_COOPS_PER_FARMER - 1):
        coop.create_coop(group.fa["id"], f"Extra {i}")
    with pytest.raises(CoopError, match="at most"):
        coop.create_coop(group.fa["id"], "One too many")


def test_only_members_can_list_under_a_coop_and_leaving_detaches_listings(group):
    with pytest.raises(market.MarketError, match="belong to"):
        market.create_listing(group.fb["id"], "Wheat", "Grains & Cereals", "kg", 30, 50, coop_id=group.cid)
    coop.join_coop(group.fb["id"], code(group))
    lid = market.create_listing(group.fb["id"], "Wheat", "Grains & Cereals", "kg", 30, 50, coop_id=group.cid)
    with pytest.raises(market.MarketError, match="not found"):
        market.update_listing(group.fc["id"], lid, coop_id=group.cid)         # not their listing
    coop.leave_coop(group.fb["id"], group.cid)
    assert market.get_listing(lid)["coop_id"] is None and market.get_listing(lid)["status"] == "active"


def test_removed_member_listings_leave_the_pool(group):
    coop.join_coop(group.fb["id"], code(group))
    market.create_listing(group.fb["id"], "Wheat", "Grains & Cereals", "kg", 30, 50, coop_id=group.cid)
    assert coop.pooled_stock(group.cid)[0].total_quantity == 50
    coop.remove_member(group.fa["id"], group.cid, group.fb["id"])
    assert coop.pooled_stock(group.cid) == []


# ── Pooled stock & bulk orders ──────────────────────────────────────────────

@pytest.fixture
def pool(group):
    coop.join_coop(group.fb["id"], code(group))
    coop.join_coop(group.fc["id"], code(group))
    mk = lambda f, price, qty, title="Wheat": market.create_listing(
        f["id"], title, "Grains & Cereals", "kg", price, qty, "both", coop_id=group.cid)
    group.l_a, group.l_b, group.l_c = mk(group.fa, 30, 40), mk(group.fb, 28, 30), mk(group.fc, 32, 100)
    mk(group.fa, 90, 10, "Rice")
    return group


def test_pooled_stock_groups_same_product(pool):
    wheat = [p for p in coop.pooled_stock(pool.cid) if p.title == "Wheat"][0]
    assert (wheat.total_quantity, wheat.farmers, wheat.min_price, wheat.max_price) == (170, 3, 28, 32)
    assert coop.product_key(" WHEAT  ", "kg") == coop.product_key("wheat", "kg") != coop.product_key("wheat", "quintal")


def test_allocation_takes_cheapest_first(pool):
    key = coop.product_key("Wheat", "kg")
    assert coop.allocate(pool.cid, key, 50) == [(pool.l_b, 30), (pool.l_a, 20)]
    assert coop.allocate(pool.cid, key, 170) == [(pool.l_b, 30), (pool.l_a, 40), (pool.l_c, 100)]
    with pytest.raises(CoopError, match="only 170"):
        coop.allocate(pool.cid, key, 171)
    for bad in (0, -5, "x"):
        with pytest.raises(CoopError):
            coop.allocate(pool.cid, key, bad)


def test_allocate_greedy_handles_fractions_without_drift():
    rows = [{"id": 1, "quantity_available": 0.1, "price_per_unit": 1}, {"id": 2, "quantity_available": 0.2, "price_per_unit": 2}]
    assert coop.allocate_greedy(rows, 0.3) == [(1, 0.1), (2, 0.2)]


def test_bulk_order_splits_into_one_order_per_farmer(pool):
    ids = coop.bulk_order(pool.buyer.id, pool.cid, coop.product_key("Wheat", "kg"), 60, "pickup", "", PHONE)
    assert len(ids) == 2
    orders = market.list_orders_for_consumer(pool.buyer.id)
    assert sorted(o["total_amount"] for o in orders) == sorted([30 * 28, 30 * 30])
    assert market.get_listing(pool.l_b)["quantity_available"] == 0
    assert market.get_listing(pool.l_a)["quantity_available"] == 10
    # each farmer sees and controls only their part
    assert [o["farmer_id"] for o in market.list_orders_for_farmer(pool.fb["id"])] == [pool.fb["id"]]
    assert market.list_orders_for_farmer(pool.fc["id"]) == []


def test_bulk_order_is_all_or_nothing(pool):
    market.update_listing(pool.fb["id"], pool.l_b, status="paused")       # state changes between allocate and checkout
    with pytest.raises(market.MarketError):
        coop.bulk_order(pool.buyer.id, pool.cid, coop.product_key("Rice", "kg"), 50, "pickup", "", PHONE)
    assert market.get_listing(pool.l_a)["quantity_available"] == 40
    assert market.list_orders_for_consumer(pool.buyer.id) == []


def test_directory_lists_coops_by_state(pool):
    names = [c["name"] for c in coop.list_coops()]
    assert names == ["Khanna Growers"]
    assert coop.list_coops("punjab")[0]["member_count"] == 3 and coop.list_coops("Kerala") == []
    assert coop.list_coops()[0]["active_listings"] == 4
    assert [m["role"] for m in coop.members(pool.cid)][0] == "admin"
