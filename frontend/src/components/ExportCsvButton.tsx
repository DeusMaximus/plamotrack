import { Download } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, downloadFile } from "../api/client";
import { Button, PAGE_ACTION_FOCUS } from "./ui";

/** Per-page "get this table out as CSV". The full archive lives in
 *  Settings → Data management. */
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
    <Button
      variant="secondary"
      icon={Download}
      onClick={run}
      disabled={busy}
      title={error ?? undefined}
      // A phone's page head has no room for it (`PageHeader`): the keyboard goes
      // to the action it stood beside.
      data-focus-stand-in={PAGE_ACTION_FOCUS}
    >
      {busy
        ? t("common.exporting")
        : error
          ? t("common.exportFailedShort")
          : (label ?? t("common.exportCsv"))}
    </Button>
  );
}
