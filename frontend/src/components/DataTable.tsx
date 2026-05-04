import { useEffect, useState } from 'react';
import { Button, Checkbox, Empty, Pagination, Select, Space, Typography } from 'antd';
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
  type OnChangeFn,
  type PaginationState,
  type SortingState,
} from '@tanstack/react-table';

const { Text } = Typography;

interface DataTableProps<T extends object> {
  columns: ColumnDef<T>[];
  data: T[];
  initialPageSize?: number;
  pageSizeOptions?: number[];
  initialSorting?: SortingState;
  sorting?: SortingState;
  onSortingChange?: OnChangeFn<SortingState>;
  tableClassName?: string;
  getRowId?: (row: T) => string;
  selectedRowIds?: string[];
  onSelectedRowIdsChange?: (rowIds: string[]) => void;
}

export function DataTable<T extends object>({
  columns,
  data,
  initialPageSize = 10,
  pageSizeOptions = [10, 20, 50],
  initialSorting = [],
  sorting: controlledSorting,
  onSortingChange,
  tableClassName,
  getRowId,
  selectedRowIds,
  onSelectedRowIdsChange,
}: DataTableProps<T>) {
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: initialPageSize,
  });
  const [internalSorting, setInternalSorting] = useState<SortingState>(initialSorting);
  const sorting = controlledSorting ?? internalSorting;
  const setSorting = onSortingChange ?? setInternalSorting;
  const selectionEnabled = Boolean(getRowId && selectedRowIds && onSelectedRowIdsChange);

  const table = useReactTable({
    data,
    columns,
    state: { pagination, sorting },
    onPaginationChange: setPagination,
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    getSortedRowModel: getSortedRowModel(),
  });

  useEffect(() => {
    const totalPages = Math.max(1, Math.ceil(data.length / pagination.pageSize));
    if (pagination.pageIndex >= totalPages) {
      setPagination((current) => ({ ...current, pageIndex: 0 }));
    }
  }, [data.length, pagination.pageIndex, pagination.pageSize]);

  const selectedRowIdSet = new Set(selectedRowIds ?? []);
  const allSelectableRowIds = selectionEnabled ? data.map((row) => getRowId!(row)) : [];
  const allRowsSelected = selectionEnabled && allSelectableRowIds.length > 0 && allSelectableRowIds.every((rowId) => selectedRowIdSet.has(rowId));
  const someRowsSelected = selectionEnabled && allSelectableRowIds.some((rowId) => selectedRowIdSet.has(rowId));

  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />;
  }

  return (
    <div className="cbw-table-panel">
      <div className="cbw-table-shell">
        <table className={tableClassName ? `cbw-data-table ${tableClassName}` : 'cbw-data-table'}>
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {selectionEnabled ? (
                  <th style={{ width: 48, minWidth: 48 }}>
                    <div className="cbw-th-checkbox">
                      <Checkbox
                        checked={allRowsSelected}
                        indeterminate={!allRowsSelected && someRowsSelected}
                        onChange={(event) => {
                          if (event.target.checked) {
                            onSelectedRowIdsChange!(allSelectableRowIds);
                            return;
                          }
                          onSelectedRowIdsChange!([]);
                        }}
                      />
                    </div>
                  </th>
                ) : null}
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    style={{
                      width: header.column.columnDef.size,
                      minWidth: header.column.columnDef.minSize,
                    }}
                  >
                    {header.isPlaceholder ? null : (
                      <div className="cbw-th-content">
                        <span>{flexRender(header.column.columnDef.header, header.getContext())}</span>
                        {header.column.getCanSort() ? (
                          <span className="cbw-th-sorter">
                            <Button
                              type="text"
                              size="small"
                              className={header.column.getIsSorted() ? 'is-active' : ''}
                              onClick={() => header.column.toggleSorting(header.column.getIsSorted() === 'asc')}
                            >
                              {header.column.getIsSorted() === 'asc'
                                ? '↑'
                                : header.column.getIsSorted() === 'desc'
                                  ? '↓'
                                  : '↕'}
                            </Button>
                          </span>
                        ) : null}
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id}>
                {selectionEnabled ? (
                  <td style={{ width: 48, minWidth: 48 }}>
                    <div className="cbw-td-checkbox">
                      <Checkbox
                        checked={selectedRowIdSet.has(getRowId!(row.original))}
                        onChange={(event) => {
                          const rowId = getRowId!(row.original);
                          if (event.target.checked) {
                            onSelectedRowIdsChange!([...selectedRowIdSet, rowId]);
                            return;
                          }
                          onSelectedRowIdsChange!(selectedRowIds!.filter((value) => value !== rowId));
                        }}
                      />
                    </div>
                  </td>
                ) : null}
                {row.getVisibleCells().map((cell) => (
                  <td
                    key={cell.id}
                    style={{
                      width: cell.column.columnDef.size,
                      minWidth: cell.column.columnDef.minSize,
                    }}
                  >
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="cbw-table-footer">
        <Space size={12} wrap>
          <Text type="secondary">{`共 ${data.length} 条`}</Text>
          <Space size={6}>
            <Text type="secondary">每页</Text>
            <Select
              size="small"
              value={pagination.pageSize}
              onChange={(value) => table.setPageSize(value)}
              options={pageSizeOptions.map((value) => ({ label: `${value}`, value }))}
              style={{ width: 84 }}
            />
          </Space>
        </Space>

        <Pagination
          current={pagination.pageIndex + 1}
          pageSize={pagination.pageSize}
          total={data.length}
          showSizeChanger={false}
          onChange={(page) => table.setPageIndex(page - 1)}
        />
      </div>
    </div>
  );
}
