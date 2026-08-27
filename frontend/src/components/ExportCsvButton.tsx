import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, downloadFile } from "../api/client";
import { Button } from "./ui";

/** Per-page "get this table out as CSV". The full archive lives on the Data page. */
export function ExportCsvButton({ table, label }: { table: string; label?: string }) {
  const { t } = useTranslation();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      await downloadFile(`/export/${table}.csv`, `${table}.csv`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Button variant="secondary" onClick={run} disabled={busy} title={error ?? undefined}>
      {busy
        ? t("common.exporting")
        : error
          ? t("common.exportFailedShort")
          : (label ?? t("common.exportCsv"))}
    </Button>
  );
}
