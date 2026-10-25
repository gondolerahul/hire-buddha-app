"""One journey per role in a real browser (Phase 15 T10-2; 08 §5, §9 item 1; 07 §10).

* Sign-up: a United States workspace is billed in USD (FX-1).
* Business admin: signs in with the form, sees its ₹ wallet and the GST on a
  top-up, spends past its balance into debt (the banner, Recharge), is
  credited by a recharge (the banner goes), and reads its usage report in ₹
  with no cost.
* Business user: no Billing, no wallet controls; billing routes go home.
* Gold partner: earnings in its currency, works inside the customer it
  resells (the acting banner, the business menu) — and is refused in one it
  does not.
* Silver partner: referred customers' billed summaries only; no tenant pages,
  no workspace switcher.
* Staff: the console's queues, an FX rate's preview, a daily-credit policy's
  preview, and a partner moved from Gold to Silver on Partner 360.
* Old routes redirect for each workspace.

Assertions on what a page shows use Playwright's ``expect``, which waits for
the page's data to arrive (``conftest`` gives it 20 s), and match the page's
text as written — not as CSS renders it (some labels are shown upper-case).
"""
from __future__ import annotations

import re

import pytest
from playwright.sync_api import expect

from tests.journeys import world as w
from tests.journeys.conftest import db_call, go, path_of

pytestmark = pytest.mark.slow


def test_a_us_sign_up_is_billed_in_usd(anonymous, world):
    page = go(anonymous, "/register")
    address = w.email("signup", world.tag)
    country = page.locator("#country-select")
    country.select_option(label="United States")
    expect(page.get_by_text("Billed in USD")).to_be_visible()
    country.select_option(label="India")
    expect(page.get_by_text("Billed in INR")).to_be_visible()
    country.select_option(label="United States")
    page.locator("input[type=text]").first.fill("Journey Sign-up")
    page.locator("input[type=email]").fill(address)
    page.locator("input[type=password]").fill(w.PASSWORD)
    page.locator("button[type=submit]").click()
    page.wait_for_function("() => !location.pathname.startsWith('/register') || "
                           "document.body.innerText.toLowerCase().includes('verif')", timeout=15000)
    company = db_call(w.company_of, address)
    assert company is not None, "the sign-up made no workspace"
    world.extra_companies.append(company["id"])
    assert (company["type"], company["country"], company["currency"]) == ("TENANT", "US", "USD")


def test_a_business_admin_goes_into_debt_and_recharges(anonymous, world):
    page = go(anonymous, "/login")
    page.locator("input[type=email]").fill(world.emails["tenant_admin"])
    page.locator("input[type=password]").fill(w.PASSWORD)
    page.locator("button[type=submit]").click()
    page.wait_for_url(re.compile(r".*/home$"), timeout=20000)
    main = page.locator("main")
    expect(main).to_contain_text("Your business at a glance")
    expect(main).to_contain_text("₹2,000.00")

    go(page, "/billing")
    expect(main).to_contain_text("Add funds in INR")
    expect(main).to_contain_text("valid for 90 days")
    expect(main).to_contain_text("₹1,000.00 credit + 18% GST (₹180.00) = ₹1,180.00 charged")

    db_call(w.spend, world.business, "25")                     # ₹2,500 of usage against ₹2,000
    go(page, "/home")
    expect(page.get_by_text("Your balance is over its limit")).to_be_visible()
    expect(page.locator("body")).to_contain_text("Owed: ₹500.00")
    page.locator("a.shell-banner-action", has_text="Recharge").first.click()     # the shell's balance banner
    page.wait_for_url(re.compile(r".*/billing$"))
    expect(main).to_contain_text("Owed: ₹500.00")

    db_call(w.pay, world.business, "1000")                     # the gateway's confirmation of ₹1,000
    go(page, "/home")
    expect(main).to_contain_text("Your business at a glance")
    expect(page.get_by_text("Your balance is over its limit")).to_have_count(0)
    expect(main).to_contain_text("₹500.00")                     # the debt repaid first

    go(page, "/reports/R-T02")
    expect(main).to_contain_text("₹2,500.00")
    expect(main).to_contain_text("INR")
    text = main.inner_text()
    assert "Cost" not in text and "$" not in text               # billed only, in the business's currency
    expect(main.locator("select").nth(1)).to_contain_text("AI models")   # filter labels, not keys


def test_a_business_user_has_no_billing(signed_in, world):
    page = go(signed_in(world.emails["tenant_user"]), "/home")
    expect(page.locator("main")).to_contain_text("Your work at a glance")
    menu = page.locator("body").inner_text().split("BUSINESS WORKSPACE")[0]          # the rendered menu
    assert "Wallet" not in menu and "Invoices" not in menu and "Spend controls" not in menu
    for path in ("/billing", "/billing/plan", "/billing/invoices", "/console"):
        go(page, path)
        expect(page).to_have_url(re.compile(r".*/home$"))


def test_a_gold_partner_earns_and_works_in_its_own_customer_only(signed_in, world):
    page = go(signed_in(world.emails["gold_admin"]), "/partner")
    main = page.locator("main")
    expect(main).to_contain_text("Gold partner · active")
    expect(main).to_contain_text("₹20,000.00")

    go(page, "/partner/earnings")
    expect(main).to_contain_text(world.names["gold_customer"])
    expect(main).to_contain_text("₹1,00,000.00")
    expect(main).to_contain_text("20 %")
    assert "cost" not in main.inner_text().lower()

    go(page, "/partner/tenants")
    expect(main).to_contain_text(world.names["gold_customer"])
    expect(main).to_contain_text("Combined Balance")
    text = main.inner_text()
    assert world.names["not_resold"] not in text and "$" not in text   # the partner's own currency (₹)

    switcher = page.get_by_label("Working in")
    expect(switcher.locator("option")).to_have_text(["My own company", world.names["gold_customer"]])
    switcher.select_option(label=world.names["gold_customer"])
    expect(page.locator("body")).to_contain_text(re.compile(r"Business workspace \(acting\)", re.I))
    expect(page.locator("body")).to_contain_text(f"You are working in {world.names['gold_customer']}")
    go(page, "/agents")
    expect(main).to_contain_text("Entity Library")

    page.evaluate("id => localStorage.setItem('acting_company', JSON.stringify({id, name: 'not mine'}))",
                  str(world.not_resold))
    with page.expect_response(lambda r: "/api/v1/ai/entities" in r.url) as answer:
        go(page, "/agents")
    assert answer.value.status == 403                            # no grant, no data


def test_a_silver_partner_sees_no_tenant_data(signed_in, world):
    page = go(signed_in(world.emails["silver_admin"]), "/partner")
    main = page.locator("main")
    expect(main).to_contain_text("Silver partner · active")
    go(page, "/partner/customers")
    expect(main).to_contain_text(world.names["silver_customer"])
    expect(main).to_contain_text("Referred")
    expect(page.get_by_label("Working in")).to_have_count(0)     # never acts in a business
    for path in ("/partner/tenants", "/partner/charges", "/agents"):
        go(page, path)
        expect(page).to_have_url(re.compile(r".*/partner$"))


def test_staff_run_the_console(signed_in, world):
    page = go(signed_in(world.emails["staff"]), "/console")
    main = page.locator("main")
    expect(main).to_contain_text("Companies in debt")
    expect(main).to_contain_text("The platform this month")

    go(page, "/console/currency")
    expect(main).to_contain_text("Rate history")
    page.get_by_label("Units per USD").fill("120")
    expect(main).to_contain_text(re.compile(r"\d+(\.\d+)?\s*%"))   # the change's impact, before it is saved

    go(page, "/console/daily-credits")
    page.get_by_role("button", name="New policy").click()
    expect(main).to_contain_text("₹100.00 ($1.00)")               # a band's preview in INR and USD
    page.get_by_role("button", name="Cancel").click()

    go(page, f"/console/partners/{world.gold}")
    expect(main).to_contain_text(world.names["gold_customer"])
    page.once("dialog", lambda dialog: dialog.accept("journey: no longer delivers"))
    page.get_by_role("button", name="Make Silver").click()
    expect(main).to_contain_text("Now Silver")
    state = db_call(w.partner_state, world.gold)
    assert state["type"] == "SILVER" and state["customers"] == {world.gold_customer: "referred"}
    expect(page.get_by_role("button", name="Make Gold")).to_be_visible()


@pytest.mark.parametrize("who, old, new", [
    ("tenant_admin", "/dashboard", "/home"),
    ("tenant_admin", "/ai/executions", "/work"),
    ("staff", "/dashboard", "/console"),
    ("staff", "/platform-management", "/console/companies"),
    ("staff", "/admin/partners", "/console/partners"),
    ("gold_admin", "/dashboard", "/partner"),
])
def test_old_routes_redirect(signed_in, world, who, old, new):
    page = go(signed_in(world.emails[who]), old)
    expect(page).to_have_url(re.compile(f".*{re.escape(new)}$"))
    assert path_of(page) == new
