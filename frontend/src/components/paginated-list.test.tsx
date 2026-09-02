import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { PaginatedList } from "./paginated-list";

describe("PaginatedList", () => {
  afterEach(cleanup);

  it("keeps a large collection compact and navigable", () => {
    const items = Array.from({ length: 13 }, (_, index) => ({
      id: String(index + 1),
      name: `Record ${index + 1}`,
    }));
    render(
      <PaginatedList
        items={items}
        pageSize={5}
        label="Demo records"
        className="records"
        keyFor={(item) => item.id}
        renderItem={(item) => <p>{item.name}</p>}
      />,
    );

    expect(screen.getByText("Record 1")).toBeVisible();
    expect(screen.queryByText("Record 6")).not.toBeInTheDocument();
    expect(screen.getByText("Page 1 of 3 · 13 records")).toBeVisible();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Record 6")).toBeVisible();
    expect(screen.queryByText("Record 1")).not.toBeInTheDocument();
  });
});
