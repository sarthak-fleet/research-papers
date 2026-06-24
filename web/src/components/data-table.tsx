import * as React from "react";
import {
  type ColumnDef,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronLeft, ChevronRight, ChevronsLeft, ChevronsRight } from "lucide-react";

import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fmt } from "@/lib/utils";

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[];
  data: TData[];
  searchPlaceholder?: string;
  pageSize?: number;
  initialSort?: { id: string; desc: boolean }[];
}

export function DataTable<TData, TValue>({
  columns,
  data,
  searchPlaceholder,
  pageSize = 25,
  initialSort = [],
}: DataTableProps<TData, TValue>) {
  const [sorting, setSorting] = React.useState<SortingState>(initialSort);
  const [filter, setFilter] = React.useState("");

  const table = useReactTable({
    data,
    columns,
    state: { sorting, globalFilter: filter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
  });

  const totalRows = table.getFilteredRowModel().rows.length;
  const pageIdx = table.getState().pagination.pageIndex;
  const pageCount = table.getPageCount();
  const tableId = React.useId().replace(/:/g, "");

  return (
    <div className="space-y-3">
      {searchPlaceholder !== undefined && (
        <Input
          placeholder={searchPlaceholder}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="max-w-sm h-9"
        />
      )}
      <div className="rounded-xl border bg-card overflow-hidden">
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((hg) => (
              <TableRow key={hg.id} className="hover:bg-transparent border-b">
                {hg.headers.map((h) => {
                  const sort = h.column.getIsSorted();
                  const canSort = h.column.getCanSort();
                  return (
                    <TableHead
                      key={h.id}
                      id={`${tableId}-${h.id}`}
                      scope="col"
                      className="text-[11px] uppercase tracking-wider text-muted-foreground font-semibold h-10"
                    >
                      {h.isPlaceholder ? null : canSort ? (
                        <button
                          onClick={h.column.getToggleSortingHandler()}
                          className="flex items-center gap-1.5 hover:text-foreground transition-colors"
                        >
                          {flexRender(h.column.columnDef.header, h.getContext())}
                          {sort === "asc" ? <ArrowUp className="h-3 w-3" /> : sort === "desc" ? <ArrowDown className="h-3 w-3" /> : <ArrowUpDown className="h-3 w-3 opacity-40" />}
                        </button>
                      ) : (
                        flexRender(h.column.columnDef.header, h.getContext())
                      )}
                    </TableHead>
                  );
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id} className="border-b border-border/40 hover:bg-muted/30">
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id} headers={`${tableId}-${cell.column.id}`} className="py-2.5">
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={columns.length} className="h-24 text-center text-muted-foreground">
                  No results.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
      {pageCount > 1 && (
        <div className="flex items-center justify-between text-sm text-muted-foreground">
          <div>{fmt.format(totalRows)} rows</div>
          <div className="flex items-center gap-2">
            <span>Page {pageIdx + 1} of {pageCount}</span>
            <div className="flex gap-1">
              <Button variant="outline" size="icon" className="h-7 w-7" aria-label="First page" onClick={() => table.firstPage()} disabled={!table.getCanPreviousPage()}>
                <ChevronsLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="icon" className="h-7 w-7" aria-label="Previous page" onClick={() => table.previousPage()} disabled={!table.getCanPreviousPage()}>
                <ChevronLeft className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="icon" className="h-7 w-7" aria-label="Next page" onClick={() => table.nextPage()} disabled={!table.getCanNextPage()}>
                <ChevronRight className="h-3.5 w-3.5" />
              </Button>
              <Button variant="outline" size="icon" className="h-7 w-7" aria-label="Last page" onClick={() => table.lastPage()} disabled={!table.getCanNextPage()}>
                <ChevronsRight className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
