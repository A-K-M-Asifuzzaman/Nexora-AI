import { cleanup, render, screen, waitFor, fireEvent } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { InsightsPanel } from "./insights-panel";

const product = { id: "product-1", sku: "TEA", name: "Tea", is_active: true };

const forecastResult = {
  product_id: product.id,
  periods_ahead: 2,
  historical_actuals: [
    { date: "2026-01-05", value: "10.0000" },
    { date: "2026-01-12", value: "12.0000" },
  ],
  point_forecast: [
    { date: "2026-01-19", value: "11.0000" },
    { date: "2026-01-26", value: "11.5000" },
  ],
  prediction_interval_low: [
    { date: "2026-01-19", value: "9.0000" },
    { date: "2026-01-26", value: "9.2000" },
  ],
  prediction_interval_high: [
    { date: "2026-01-19", value: "13.0000" },
    { date: "2026-01-26", value: "13.8000" },
  ],
  model_used: "Naive",
  backtest_scores: [{ model: "Naive", mae: "1.0000", rmse: "1.2000", mase: null }],
  limitation_note: "Based on 2 weeks of history.",
};

const alert = {
  id: "alert-1",
  detector: "REFUND_RATE",
  severity: "HIGH",
  observed_value: "0.4000",
  expected_low: "0.0000",
  expected_high: "0.2000",
  deviation: "0.2000",
  reason: "38.0% of today's sales were refunded, well above the usual range.",
  occurred_at: "2026-08-30T00:00:00Z",
  resource_type: "BRANCH",
  resource_id: "branch-1",
  label: "Main Branch",
  status: "OPEN",
};

function stubFetch(overrides: Record<string, unknown> = {}) {
  const fetchMock = vi.fn(async (input: string | URL | Request) => {
    const path = String(input);
    if (path.endsWith("products/")) return { ok: true, json: async () => ({ items: [product] }) };
    if (path.includes("forecasting/products/")) {
      return { ok: true, json: async () => overrides.forecast ?? forecastResult };
    }
    if (path.includes("/anomalies/run")) return { ok: true, json: async () => ({ alerts_created: 1 }) };
    if (path.includes("/alert-1/acknowledge")) {
      return { ok: true, json: async () => ({ ...alert, status: "ACKNOWLEDGED" }) };
    }
    if (path.includes("/alert-1/dismiss")) {
      return { ok: true, json: async () => ({ ...alert, status: "DISMISSED" }) };
    }
    if (path.includes("anomalies")) return { ok: true, json: async () => overrides.alerts ?? [alert] };
    return { ok: true, json: async () => ({}) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("InsightsPanel", () => {
  afterEach(cleanup);
  beforeEach(() => stubFetch());

  it("renders a forecast chart, uncertainty table and alert inbox", async () => {
    render(<InsightsPanel />);

    await screen.findByText("Model: Naive");
    expect(screen.getByText("11.0000")).toBeVisible();
    expect(screen.getByText("9.0000")).toBeVisible();
    expect(screen.getByText("13.0000")).toBeVisible();
    expect(screen.getByText("Based on 2 weeks of history.")).toBeVisible();

    expect(await screen.findByText(/Refund rate/)).toBeVisible();
    expect(screen.getByText("HIGH")).toBeVisible();
  });

  it("shows the insufficient-history message instead of a chart", async () => {
    stubFetch({
      forecast: {
        status: "INSUFFICIENT_HISTORY",
        periods_available: 3,
        periods_required: 8,
        message: "Only 3 week(s) of sales history exist for this product.",
      },
    });
    const { container } = render(<InsightsPanel />);

    await screen.findByText("Only 3 week(s) of sales history exist for this product.");
    expect(container.querySelectorAll(".insights-chart i")).toHaveLength(0);
  });

  it("acknowledging an open alert removes it from the default (open) view", async () => {
    const fetchMock = stubFetch();
    render(<InsightsPanel />);

    await screen.findByText(/Refund rate/);
    fireEvent.click(screen.getByRole("button", { name: /Acknowledge/ }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/bff/anomalies/alert-1/acknowledge",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() => expect(screen.queryByText(/Refund rate/)).toBeNull());
  });

  it("picks up a product created later, via the products-changed event", async () => {
    let products: unknown[] = [];
    const fetchMock = vi.fn(async (input: string | URL | Request) => {
      const path = String(input);
      if (path.endsWith("products/")) return { ok: true, json: async () => ({ items: products }) };
      if (path.includes("forecasting/products/")) return { ok: true, json: async () => forecastResult };
      if (path.includes("anomalies")) return { ok: true, json: async () => [] };
      return { ok: true, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<InsightsPanel />);
    await screen.findByText("No products are available to forecast yet.");

    products = [product];
    fireEvent(window, new Event("nexora:products-changed"));

    await screen.findByText("Model: Naive");
    expect(screen.queryByText("No products are available to forecast yet.")).toBeNull();
  });

  it("runs detectors on demand and reloads the alert list", async () => {
    const fetchMock = stubFetch();
    render(<InsightsPanel />);

    await screen.findByText(/Refund rate/);
    fireEvent.click(screen.getByRole("button", { name: "Run detectors now" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/bff/anomalies/run",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/bff/anomalies?status=OPEN", expect.anything()),
    );
  });
});
