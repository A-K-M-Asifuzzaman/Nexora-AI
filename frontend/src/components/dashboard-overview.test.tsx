import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DashboardOverview, formatMoney, weeklyTrend } from "./dashboard-overview";

describe("DashboardOverview", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const path = String(input);
      const body = path.includes("reports/dashboard")
        ? { pos_revenue: "15000.0000", gross_profit: "6400.0000", transactions: 240, accounts_receivable: "3200.0000", accounts_payable: "1800.0000", inventory_value: "92000.0000" }
        : path.includes("sales-trend")
          ? { items: [{ date: "2026-08-31", revenue: "100.0000", transactions: 2 }, { date: "2026-09-01", revenue: "250.0000", transactions: 3 }] }
          : path.includes("top-products")
            ? { items: [{ product_id: "p1", sku: "SKU-1", name: "Wireless Keyboard", quantity: "4", revenue: "400.0000", margin: "120.0000" }] }
            : path.includes("pipeline")
              ? { items: [{ stage: "PROPOSAL", count: 12, amount: "50000.0000", weighted_amount: "25000.0000" }] }
              : { items: [{ product_id: "p2", sku: "SKU-2", name: "USB-C Dock", warehouse: "WH1", on_hand: "4", reserved: "1", reorder_point: "10" }] };
      return { ok: true, json: async () => body };
    }));
  });

  it("renders live reporting data with direct chart labels and a table fallback", async () => {
    render(<DashboardOverview />);

    expect(await screen.findByRole("heading", { name: "Clarity at a glance" })).toBeVisible();
    expect((await screen.findAllByText("$15,000"))[0]).toBeVisible();
    expect(screen.getByText("Wireless Keyboard")).toBeVisible();
    expect(screen.getByText("proposal")).toBeVisible();
    expect(screen.getByText("USB-C Dock")).toBeVisible();
    expect(screen.getByRole("img", { name: /Weekly point-of-sale revenue/ })).toBeVisible();
    expect(screen.getByText("View weekly values")).toBeVisible();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(5));
  });
});

describe("dashboard transforms", () => {
  it("aggregates daily values into Monday-based weekly buckets", () => {
    expect(weeklyTrend([
      { date: "2026-08-31", revenue: "10.0000", transactions: 1 },
      { date: "2026-09-01", revenue: "15.5000", transactions: 2 },
      { date: "2026-09-07", revenue: "7.0000", transactions: 1 },
    ])).toEqual([
      { date: "2026-08-31", revenue: "25.5000", transactions: 3 },
      { date: "2026-09-07", revenue: "7.0000", transactions: 1 },
    ]);
  });

  it("does not display invalid money as a plausible zero", () => {
    expect(formatMoney("not-money")).toBe("—");
  });
});
