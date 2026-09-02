import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CatalogInventoryPanel } from "./catalog-inventory-panel";

const product = {
  id: "product-1",
  sku: "TEA-1",
  name: "Black Tea",
  cost_price: "2.500000",
  selling_price: "4.0000",
  is_active: true,
};
const lookupProduct = { ...product, id: "product-2", sku: "TEA-2", name: "Green Tea" };
const unit = { id: "unit-1", code: "EACH", name: "Each", precision: 0 };
const warehouse = { id: "warehouse-1", code: "MAIN", name: "Main Store" };

function responseFor(path: string) {
  if (path.includes("products/")) {
    return path.includes("page=2")
      ? { items: [lookupProduct], total: 2, total_pages: 2 }
      : { items: [product], total: 2, total_pages: 2 };
  }
  if (path.endsWith("units/")) return { items: [unit] };
  if (path.endsWith("warehouses/")) return { items: [warehouse] };
  if (path.endsWith("inventory/balances/")) {
    return {
      items: [
        {
          id: "balance-1",
          warehouse_id: warehouse.id,
          product_id: lookupProduct.id,
          quantity_on_hand: "7.000000",
          reserved_quantity: "2.000000",
          available: "5.000000",
        },
      ],
    };
  }
  if (path.includes("inventory/movements/")) return { items: [] };
  return {};
}

describe("CatalogInventoryPanel", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string | URL | Request) => ({
        ok: true,
        json: async () => responseFor(String(input)),
      })),
    );
  });

  it("renders live catalog and derived available inventory", async () => {
    render(<CatalogInventoryPanel />);

    expect((await screen.findAllByText("Black Tea"))[0]).toBeVisible();
    expect(screen.getAllByText("Green Tea")[0]).toBeVisible();
    expect(screen.queryByText("Unknown product")).not.toBeInTheDocument();
    expect(screen.getByText("TEA-1")).toBeVisible();
    expect(screen.getByText("7.000000")).toBeVisible();
    expect(screen.getByText("5.000000")).toBeVisible();
  });

  it("posts quantities as strings with an idempotency key", async () => {
    const fetchMock = vi.mocked(fetch);
    render(<CatalogInventoryPanel />);

    await screen.findAllByText("Black Tea");
    fireEvent.change(screen.getByLabelText("Warehouse"), {
      target: { value: warehouse.id },
    });
    fireEvent.change(screen.getByLabelText("Product"), {
      target: { value: product.id },
    });
    fireEvent.change(screen.getByLabelText("Quantity"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Unit cost for receipts"), {
      target: { value: "2.750000" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Post movement" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/bff/inventory/receipts/",
        expect.objectContaining({
          method: "POST",
          headers: expect.objectContaining({ "Idempotency-Key": expect.any(String) }),
          body: JSON.stringify({
            warehouse_id: warehouse.id,
            product_id: product.id,
            quantity: "3",
            unit_cost: "2.750000",
          }),
        }),
      ),
    );
  });

  it("deletes an unused product without trying to parse the empty 204 response", async () => {
    const fetchMock = vi.fn(async (input: string | URL | Request, init?: RequestInit) => {
      if (init?.method === "DELETE") return { ok: true, status: 204, json: async () => { throw new Error("204 has no body"); } };
      return { ok: true, status: 200, json: async () => responseFor(String(input)) };
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<CatalogInventoryPanel />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete Black Tea" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(
      "/api/bff/products/product-1",
      expect.objectContaining({ method: "DELETE" }),
    ));
  });
});
