import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { PosPanel } from "./pos-panel";

const product = { id: "product-1", sku: "TEA", name: "Tea", selling_price: "10.0000", is_active: true };

describe("PosPanel", () => {
  afterEach(cleanup);
  beforeEach(() => {
    vi.stubGlobal("crypto", { randomUUID: () => "checkout-key" });
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL | Request) => {
      const path = String(input);
      const body = path.endsWith("products/") ? { items: [product] } : path.endsWith("pos/terminals/") ? [{ id: "terminal-1", code: "T1", name: "Front till" }] : path.includes("pos/terminals/") && path.endsWith("/session") ? null : path.endsWith("pos/sessions/open") ? { id: "session-1", session_number: "SHIFT-1", status: "OPEN" } : path.endsWith("pos/checkout") ? { id: "sale-1", sale_number: "SALE-1", total_amount: "10.0000" } : [];
      return { ok: true, json: async () => body };
    }));
  });

  it("opens a shift and submits string money with an idempotency key", async () => {
    const fetchMock = vi.mocked(fetch); render(<PosPanel />);
    await screen.findByText("Front till"); fireEvent.click(screen.getByRole("button", { name: "Open shift" }));
    await screen.findByText("Shift SHIFT-1 is open"); fireEvent.click(screen.getByRole("button", { name: /Tea/ }));
    fireEvent.change(screen.getByLabelText("Cash tender"), { target: { value: "10.0000" } }); fireEvent.click(screen.getByRole("button", { name: "Pay" }));
    await screen.findByText(/Receipt SALE-1/);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith("/api/bff/pos/checkout", expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "Idempotency-Key": "checkout-key" }), body: JSON.stringify({ session_id: "session-1", lines: [{ product_id: "product-1", quantity: "1", discount_rate: "0" }], payments: [{ tender: "CASH", amount: "10.0000", change_given: "0" }] }) })));
  });

  it("supports keyboard-first add and clear", async () => {
    render(<PosPanel />); await screen.findByText("Front till"); fireEvent.click(screen.getByRole("button", { name: "Open shift" })); await screen.findByText("Shift SHIFT-1 is open");
    fireEvent.keyDown(window, { key: "F2" }); expect(screen.getByText("× 1")).toBeVisible(); fireEvent.keyDown(window, { key: "Escape" }); expect(screen.queryByText("× 1")).toBeNull();
  });
});
