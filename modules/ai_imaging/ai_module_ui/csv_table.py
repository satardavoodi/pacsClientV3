import csv
from pathlib import Path


class CsvColumn(list):
    @property
    def iloc(self):
        return self

    @property
    def dtype(self):
        return object

    def astype(self, _dtype):
        return CsvColumn("" if item is None else str(item) for item in self)

    def __eq__(self, other):
        return [item == other for item in self]


class CsvIndex(list):
    def __getitem__(self, item):
        if isinstance(item, list):
            return CsvIndex(value for value, keep in zip(self, item) if keep)
        return super().__getitem__(item)

    def tolist(self):
        return list(self)


class _AtAccessor:
    def __init__(self, table):
        self._table = table

    def __getitem__(self, key):
        row_idx, column = key
        return self._table.rows[row_idx].get(column, "")

    def __setitem__(self, key, value):
        row_idx, column = key
        self._table.ensure_column(column)
        self._table.rows[row_idx][column] = "" if value is None else str(value)


class _LocAccessor:
    def __init__(self, table):
        self._table = table

    def __getitem__(self, key):
        row_indexes, columns = key
        rows = [{column: self._table.rows[idx].get(column, "") for column in columns} for idx in row_indexes]
        return CsvTable(rows, columns)


class CsvTable:
    """Small pandas-like CSV table used to keep pandas out of the compiled core."""

    def __init__(self, rows=None, columns=None):
        self.rows = list(rows or [])
        self.columns = list(columns or [])
        for row in self.rows:
            for column in row:
                if column not in self.columns:
                    self.columns.append(column)
        self.index = CsvIndex(range(len(self.rows)))
        self.at = _AtAccessor(self)
        self.loc = _LocAccessor(self)

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, key):
        if isinstance(key, str):
            return CsvColumn(row.get(key, "") for row in self.rows)
        if isinstance(key, list):
            rows = [row.copy() for row, keep in zip(self.rows, key) if keep]
            return CsvTable(rows, self.columns)
        raise TypeError(f"Unsupported CsvTable key: {type(key)!r}")

    def __setitem__(self, column, value):
        self.ensure_column(column)
        if isinstance(value, (list, tuple)):
            values = list(value)
            for idx, row in enumerate(self.rows):
                row[column] = "" if idx >= len(values) or values[idx] is None else str(values[idx])
            return
        for row in self.rows:
            row[column] = "" if value is None else str(value)

    def ensure_column(self, column):
        if column not in self.columns:
            self.columns.append(column)
            for row in self.rows:
                row[column] = ""

    def to_dict(self):
        return {
            column: {idx: row.get(column, "") for idx, row in enumerate(self.rows)}
            for column in self.columns
        }

    def to_csv(self, csv_path, index=False):
        del index
        write_csv_table(csv_path, self)


def read_csv_table(csv_path):
    path = Path(csv_path)
    with path.open("r", newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        columns = list(reader.fieldnames or [])
        rows = [{column: row.get(column, "") for column in columns} for row in reader]
    return CsvTable(rows, columns)


def write_csv_table(csv_path, table):
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=table.columns)
        writer.writeheader()
        for row in table.rows:
            writer.writerow({column: row.get(column, "") for column in table.columns})


def concat_tables(tables):
    columns = []
    rows = []
    for table in tables:
        for column in table.columns:
            if column not in columns:
                columns.append(column)
        rows.extend(row.copy() for row in table.rows)
    return CsvTable(rows, columns)
