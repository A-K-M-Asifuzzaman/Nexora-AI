import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Brand } from "./brand";

describe("Brand", () => {
  it("has an accessible product label", () => {
    render(<Brand />);
    expect(screen.getByLabelText("Nexora AI")).toBeInTheDocument();
  });
});
