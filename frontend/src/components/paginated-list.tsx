"use client";

import { ChevronLeft, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import type { ReactNode } from "react";

type PaginatedListProps<T> = {
  items: T[];
  pageSize?: number;
  label: string;
  className: string;
  keyFor: (item: T) => string;
  renderItem: (item: T) => ReactNode;
  header?: ReactNode;
  empty?: ReactNode;
  scrollable?: boolean;
};

export function PaginatedList<T>({
  items,
  pageSize = 6,
  label,
  className,
  keyFor,
  renderItem,
  header,
  empty,
  scrollable = false,
}: PaginatedListProps<T>) {
  const [page, setPage] = useState(1);
  const totalPages = Math.max(1, Math.ceil(items.length / pageSize));
  const activePage = Math.min(page, totalPages);
  const start = (activePage - 1) * pageSize;
  const visible = items.slice(start, start + pageSize);

  return (
    <>
      <div
        className={className}
        {...(scrollable ? { role: "region", "aria-label": label, tabIndex: 0 } : {})}
      >
        {header}
        {visible.map((item) => <Fragment key={keyFor(item)}>{renderItem(item)}</Fragment>)}
        {items.length === 0 && empty}
      </div>
      {totalPages > 1 && (
        <nav className="pagination-controls" aria-label={`${label} pagination`}>
          <button
            type="button"
            disabled={activePage === 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            <ChevronLeft /> Previous
          </button>
          <span>Page {activePage} of {totalPages} · {items.length} records</span>
          <button
            type="button"
            disabled={activePage === totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
          >
            Next <ChevronRight />
          </button>
        </nav>
      )}
    </>
  );
}
