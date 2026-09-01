# training_modules/excel_handler.py
"""
Compatibility shim. Classes now come from the database — see class_catalog.py.

This module used to read the roster workbook with openpyxl on every page render and was
the source of classes, dates and assignments. That reading has moved to
`ClassCatalog`, which stores the same information in `training_classes` and its three
companion tables and answers the same questions. A workbook is opened in one place only
now: `class_catalog.import_workbook`, behind Training Admin's "Import roster workbook".

`ExcelHandler` survives as a name because it is spelled out in app.py, in
admin_access.py and in scripts/, and because renaming it everywhere in the same change
that swapped its insides would have made the swap impossible to review. It takes the
path it always took, resolves which training year that file belongs to, and hands back a
catalog. New code should ask for a `ClassCatalog` by name and pass it a year.
"""

import os
import sqlite3

from training_modules.class_catalog import (  # noqa: F401 - re-exported for callers
    DEFAULT_CLASS_DETAILS,
    ClassCatalog,
    import_workbook,
)
from training_modules.config import NON_CLASS_COLUMNS  # noqa: F401 - re-exported

DEFAULT_DB_PATH = os.path.join('data', 'medflight_tracks.db')


def year_for_roster(roster_path, db_path=DEFAULT_DB_PATH):
    """
    Which training year a roster filename belongs to.

    The workbook is no longer read, but its name is still how the older call sites say
    which year they mean — `training_years.roster_filename` is the link. A file nothing
    is registered against falls back to the active year, and then to the file's own stem,
    so a caller gets a catalog scoped to something sensible rather than an exception.
    """
    filename = os.path.basename(str(roster_path or ''))
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT year_label FROM training_years WHERE roster_filename = ?",
            (filename,)).fetchone()
        if not row:
            row = cursor.execute(
                "SELECT year_label FROM training_years WHERE is_active = 1 "
                "LIMIT 1").fetchone()
        conn.close()
        if row:
            return row['year_label']
    except sqlite3.OperationalError:
        # No training_years table yet — a database that has never run the module.
        pass

    stem = os.path.splitext(filename)[0]
    return stem.split(' ')[0] if stem else 'FY26'


class ExcelHandler(ClassCatalog):
    """A `ClassCatalog` for the year a roster filename belongs to."""

    def __init__(self, excel_path, db_path=DEFAULT_DB_PATH):
        self.excel_path = excel_path
        super().__init__(year_for_roster(excel_path, db_path=db_path), db_path=db_path)
