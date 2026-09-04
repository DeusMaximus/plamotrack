import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { api, ApiError, tokensQuery } from "../../api/client";
import type { AccessToken, AccessTokenMinted, TokenScope } from "../../api/types";
import { Button, Card, EmptyState, ErrorBanner, Field, Input, Select } from "../../components/ui";
import { formatDateTime, formatNumber } from "../../lib/format";
import { SectionHeader } from "./SectionHeader";

/** Settings → Access tokens (§5.5 family 6; #189): mint, list and revoke the
 *  owner's personal access tokens. The secret is shown exactly once, in the
 *  mint response, and never again — the list carries the public prefix so a
 *  row can be matched to whichever client holds it. Every route here wants the
 *  owner's session (a token cannot manage tokens), which the AuthGate has
 *  already established by the time this renders. */
export function AccessTokensSection() {
  const { t } = useTranslation();
  const [minted, setMinted] = useState<AccessTokenMinted | null>(null);

  return (
    <div className="space-y-6">
      <SectionHeader
        title={t("settings.sections.tokens")}
        description={t("settings.tokens.description")}
      />
      {minted ? (
        <MintedCard minted={minted} onDone={() => setMinted(null)} />
      ) : (
        <CreateCard onMinted={setMinted} />
      )}
      <TokenList />
    </div>
  );
}

type Access = "read" | "write";
const SCOPES: Record<Access, TokenScope[]> = {
  read: ["collection:read"],
  write: ["collection:read", "collection:write"],
};

/** Expiry choices, in days; "" is never. The instant is computed here at submit
 *  time so the server receives an offset-bearing ISO 8601 value. */
const EXPIRY_DAYS = [30, 90, 365] as const;

function CreateCard({ onMinted }: { onMinted: (minted: AccessTokenMinted) => void }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<{ name: string; access: Access; expiry: string }>({
    defaultValues: { name: "", access: "read", expiry: "" },
  });

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      const days = values.expiry ? Number(values.expiry) : null;
      const minted = await api.createToken({
        name: values.name.trim(),
        scopes: SCOPES[values.access],
        ...(days ? { expires_at: new Date(Date.now() + days * 86_400_000).toISOString() } : {}),
      });
      await queryClient.invalidateQueries({ queryKey: tokensQuery.queryKey });
      reset();
      onMinted(minted);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t("common.requestFailed"));
    }
  });

  return (
    <Card title={t("settings.tokens.createTitle")} description={t("settings.tokens.createDescription")}>
      <form onSubmit={onSubmit} className="space-y-3">
        <ErrorBanner message={error} />
        <Field label={t("settings.tokens.nameLabel")} required error={errors.name?.message}>
          <Input
            maxLength={100}
            placeholder={t("settings.tokens.namePlaceholder")}
            autoComplete="off"
            {...register("name", {
              required: t("validation.nameRequired"),
              validate: (value) => value.trim().length > 0 || t("validation.nameRequired"),
            })}
          />
        </Field>
        <Field label={t("settings.tokens.scopeLabel")} required>
          <Select {...register("access")}>
            <option value="read">{t("settings.tokens.scopeRead")}</option>
            <option value="write">{t("settings.tokens.scopeWrite")}</option>
          </Select>
        </Field>
        <p className="text-xs text-zinc-500">{t("settings.tokens.scopeNote")}</p>
        <Field label={t("settings.tokens.expiryLabel")} className="max-w-48">
          <Select {...register("expiry")}>
            <option value="">{t("settings.tokens.expiryNever")}</option>
            {EXPIRY_DAYS.map((days) => (
              <option key={days} value={String(days)}>
                {t("settings.tokens.expiryDays", { count: days, countDisplay: formatNumber(days) })}
              </option>
            ))}
          </Select>
        </Field>
        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? t("settings.tokens.creating") : t("settings.tokens.createButton")}
        </Button>
      </form>
    </Card>
  );
}

function MintedCard({ minted, onDone }: { minted: AccessTokenMinted; onDone: () => void }) {
  const { t } = useTranslation();
  const [copied, setCopied] = useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(minted.token);
      setCopied(true);
    } catch {
      // No clipboard (insecure context, permissions): the token is selectable
      // below, so the fallback is a manual copy.
      setCopied(false);
    }
  }

  return (
    <Card title={t("settings.tokens.mintedTitle")} description={t("settings.tokens.mintedDescription")}>
      <div className="space-y-3">
        <p className="text-sm text-zinc-700">{minted.name}</p>
        <div className="flex items-start gap-2">
          <code
            data-testid="minted-token"
            className="min-w-0 flex-1 select-all break-all rounded-md border border-zinc-200 bg-zinc-50 px-2.5 py-1.5 font-mono text-sm"
          >
            {minted.token}
          </code>
          <Button type="button" variant="secondary" onClick={copy}>
            {copied ? t("settings.tokens.copied") : t("settings.tokens.copy")}
          </Button>
        </div>
        <p className="text-xs text-zinc-500">{t("settings.tokens.usageHint")}</p>
        <Button type="button" onClick={onDone}>
          {t("settings.tokens.done")}
        </Button>
      </div>
    </Card>
  );
}

function TokenList() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: tokens, error } = useQuery(tokensQuery);
  const [actionError, setActionError] = useState<string | null>(null);

  const revoke = useMutation({
    mutationFn: (token: AccessToken) => api.revokeToken(token.id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tokensQuery.queryKey }),
    onError: (err) => setActionError(err instanceof ApiError ? err.message : t("common.requestFailed")),
  });

  function onRevoke(token: AccessToken) {
    setActionError(null);
    if (!window.confirm(t("settings.tokens.confirmRevoke", { name: token.name }))) return;
    revoke.mutate(token);
  }

  return (
    <Card title={t("settings.tokens.listTitle")} description={t("settings.tokens.listDescription")}>
      <ErrorBanner
        message={
          actionError ?? (error ? (error instanceof ApiError ? error.message : t("common.requestFailed")) : null)
        }
      />
      {tokens === undefined ? (
        <p className="text-sm text-zinc-500">{t("common.loading")}</p>
      ) : tokens.length === 0 ? (
        <EmptyState>{t("settings.tokens.empty")}</EmptyState>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs font-medium text-zinc-500">
              <tr>
                <th className="pb-2 pr-3">{t("settings.tokens.colName")}</th>
                <th className="pb-2 pr-3">{t("settings.tokens.colPrefix")}</th>
                <th className="pb-2 pr-3">{t("settings.tokens.colAccess")}</th>
                <th className="pb-2 pr-3">{t("settings.tokens.colCreated")}</th>
                <th className="pb-2 pr-3">{t("settings.tokens.colLastUsed")}</th>
                <th className="pb-2 pr-3">{t("settings.tokens.colExpires")}</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-100">
              {tokens.map((token) => (
                <TokenRow
                  key={token.id}
                  token={token}
                  busy={revoke.isPending && revoke.variables?.id === token.id}
                  onRevoke={() => onRevoke(token)}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function TokenRow({
  token,
  busy,
  onRevoke,
}: {
  token: AccessToken;
  busy: boolean;
  onRevoke: () => void;
}) {
  const { t } = useTranslation();
  const revoked = token.revoked_at !== null;
  const expired =
    !revoked && token.expires_at !== null && new Date(token.expires_at).getTime() <= Date.now();
  const inactive = revoked || expired;
  const writes = token.scopes.includes("collection:write");
  return (
    <tr data-testid="token-row" className={inactive ? "text-zinc-400" : ""}>
      <td className="py-2 pr-3 font-medium">{token.name}</td>
      <td className="py-2 pr-3 font-mono text-xs">ptk_{token.token_prefix}_…</td>
      <td className="py-2 pr-3">
        {writes ? t("settings.tokens.accessWrite") : t("settings.tokens.accessRead")}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">{formatDateTime(token.created_at)}</td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {token.last_used_at ? formatDateTime(token.last_used_at) : t("settings.tokens.neverUsed")}
      </td>
      <td className="py-2 pr-3 whitespace-nowrap">
        {expired
          ? t("settings.tokens.expired")
          : token.expires_at
            ? formatDateTime(token.expires_at)
            : t("settings.tokens.noExpiry")}
      </td>
      <td className="py-2 text-right whitespace-nowrap">
        {revoked ? (
          <span className="text-xs">
            {t("settings.tokens.revoked", { when: formatDateTime(token.revoked_at as string) })}
          </span>
        ) : (
          <Button type="button" variant="danger" disabled={busy} onClick={onRevoke}>
            {busy ? t("settings.tokens.revoking") : t("settings.tokens.revoke")}
          </Button>
        )}
      </td>
    </tr>
  );
}
