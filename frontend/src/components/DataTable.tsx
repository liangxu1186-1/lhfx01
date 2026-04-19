import { useEffect, useState } from 'react';
import { Button, Empty, Pagination, Select, Space, Typography } from 'antd';
import {
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
  type ColumnDef,
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
}

export function DataTable<T extends object>({
  columns,
  data,
  initialPageSize = 10,
  pageSizeOptions = [10, 20, 50],
  initialSorting = [],
}: DataTableProps<T>) {
  const [pagination, setPagination] = useState<PaginationState>({
    pageIndex: 0,
    pageSize: initialPageSize,
  });
  const [sorting, setSorting] = useState<SortingState>(initialSorting);

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

  if (!data.length) {
    return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无数据" />;
  }

  return (
    <div className="cbw-table-panel">
      <div className="cbw-table-shell">
        <table className="cbw-data-table">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id}>
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
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id}>
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
