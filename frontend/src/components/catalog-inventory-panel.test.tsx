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
const unit = { id: "unit-1", code: "EACH", name: "Each", precision: 0 };
const warehouse = { id: "warehouse-1", code: "MAIN", name: "Main Store" };

function responseFor(path: string) {
  if (path.endsWith("products/")) return { items: [product] };
  if (path.endsWith("units/")) return { items: [unit] };
  if (path.endsWith("warehouses/")) return { items: [warehouse] };
  if (path.endsWith("inventory/balances/")) {
    return {
      items: [
        {
          id: "balance-1",
          warehouse_id: warehouse.id,
          product_id: product.id,
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
});
