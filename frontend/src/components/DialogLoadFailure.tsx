import { useTranslation } from "react-i18next";

import type { DialogLoadFailureState } from "../lib/dialogLoadFailure";
import { Modal } from "./Modal";
import { ErrorBanner } from "./ui";

/** The dialog in its failure state: what could not be loaded, Retry, Cancel. */
export function DialogLoadFailure({
  title,
  onClose,
  wide,
  failure,
}: {
  title: string;
  onClose: () => void;
  wide?: boolean;
  failure: DialogLoadFailureState;
}) {
  const { t } = useTranslation();
  return (
    <Modal
      title={title}
      onClose={onClose}
      wide={wide}
      actions={{
        secondary: { label: t("common.cancel"), onClick: onClose },
        primary: {
          label: failure.retrying ? t("dialogLoad.retrying") : t("dialogLoad.retry"),
          onClick: failure.retry,
          pending: failure.retrying,
        },
      }}
    >
      <div className="space-y-2">
        {failure.messages.map((message) => (
          <ErrorBanner key={message} message={message} />
        ))}
        <p className="text-sm text-muted">{t("dialogLoad.note")}</p>
      </div>
    </Modal>
  );
}
