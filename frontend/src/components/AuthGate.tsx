import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { useForm } from "react-hook-form";
import { useTranslation } from "react-i18next";

import { ApiError, api, authSessionQuery, setCsrfToken } from "../api/client";
import { Button, Card, ErrorBanner, Field, Input } from "./ui";

/** The authentication boundary (§5.5 families 2–3; #188). Every render of the app
 *  passes through here: an unclaimed instance shows the setup screen, an
 *  anonymous browser the login screen, and only the owner reaches the app. It
 *  keeps `setCsrfToken` in step with the session so cookie-borne writes carry the
 *  token, and clears the React Query cache on a state change so no other user's
 *  data lingers after logout. */
export function AuthGate({ children }: { children: ReactNode }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data: session, isPending, refetch } = useQuery(authSessionQuery);

  useEffect(() => {
    setCsrfToken(session?.csrf_token ?? null);
  }, [session?.csrf_token]);

  const onAuthed = async () => {
    // A fresh identity: drop every cached query so nothing from before the
    // login (or from a prior owner) is shown, then re-read the session.
    queryClient.clear();
    await refetch();
  };

  if (isPending) {
    return <Centered>{t("auth.checking")}</Centered>;
  }
  if (session?.auth_mode === "oidc") {
    // OIDC mode (#191): no password anywhere. `unclaimed` is also a claimed
    // owner with no binding yet, which the same screen handles — the setup
    // token plus a sign-in at the provider binds whoever completes it.
    if (session.state === "unclaimed") {
      return <OidcSetupScreen issuer={session.oidc_issuer} />;
    }
    if (session.state !== "owner") {
      return <OidcLoginScreen issuer={session.oidc_issuer} />;
    }
    return <>{children}</>;
  }
  if (session?.state === "unclaimed") {
    return <SetupScreen onDone={onAuthed} />;
  }
  if (session?.state !== "owner") {
    return <LoginScreen onDone={onAuthed} />;
  }
  return <>{children}</>;
}

/** The `auth_error` code the OIDC callback sends the browser back with (#191),
 *  read once from the query string and then removed from the address bar so a
 *  reload does not show it again. */
function useOidcCallbackError(): string | null {
  const [code] = useState<string | null>(() => {
    const params = new URLSearchParams(window.location.search);
    const value = params.get("auth_error");
    if (value !== null) {
      params.delete("auth_error");
      const query = params.toString();
      window.history.replaceState(
        null,
        "",
        `${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`,
      );
    }
    return value;
  });
  return code;
}

const OIDC_ERROR_KEYS = {
  oidc_denied: "auth.oidcError_denied",
  oidc_expired: "auth.oidcError_expired",
  oidc_failed: "auth.oidcError_failed",
  oidc_setup_required: "auth.oidcError_setupRequired",
  oidc_identity_refused: "auth.oidcError_identityRefused",
} as const;
type OidcErrorKey = (typeof OIDC_ERROR_KEYS)[keyof typeof OIDC_ERROR_KEYS];

/** The catalogue key for a callback error code; an unknown code (a newer API)
 *  reads as the generic failure rather than as nothing. */
function oidcErrorKey(code: string): OidcErrorKey {
  return (OIDC_ERROR_KEYS as Record<string, OidcErrorKey | undefined>)[code] ?? "auth.oidcError_failed";
}

function providerName(issuer: string | null): string {
  if (!issuer) return "your identity provider";
  try {
    return new URL(issuer).host;
  } catch {
    return issuer;
  }
}

/** Ask the API for the provider's authorization URL and go there. The response
 *  sets the login-binding cookie, so the navigation happens in this tab; the
 *  callback brings the browser back to `/` with the session cookie, or with
 *  `?auth_error=…`. */
async function startOidcLogin(setupToken?: string): Promise<void> {
  const { authorization_url } = await api.oidcStart(setupToken);
  window.location.assign(authorization_url);
}

function OidcSetupScreen({ issuer }: { issuer: string | null }) {
  const { t } = useTranslation();
  const callbackError = useOidcCallbackError();
  const [error, setError] = useState<string | null>(
    callbackError ? t(oidcErrorKey(callbackError)) : null,
  );
  const [redirecting, setRedirecting] = useState(false);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<{ token: string }>();
  const provider = providerName(issuer);

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      setRedirecting(true);
      await startOidcLogin(values.token.trim());
    } catch (err) {
      setRedirecting(false);
      setError(messageFor(err, t("common.requestFailed")));
    }
  });

  return (
    <Centered>
      <Wordmark />
      <Card title={t("auth.setupTitle")} description={t("auth.oidcSetupIntro")}>
        <form onSubmit={onSubmit} className="space-y-3">
          <ErrorBanner message={error} />
          <Field label={t("auth.setupTokenLabel")} required error={errors.token?.message}>
            <Input autoFocus autoComplete="off" {...register("token", { required: true })} />
            <p className="mt-1 text-xs text-zinc-400">{t("auth.setupTokenHint")}</p>
          </Field>
          <Button
            type="submit"
            disabled={isSubmitting || redirecting || !watch("token")}
            className="w-full"
          >
            {redirecting
              ? t("auth.redirecting", { provider })
              : t("auth.continueWithProvider", { provider })}
          </Button>
        </form>
      </Card>
    </Centered>
  );
}

function OidcLoginScreen({ issuer }: { issuer: string | null }) {
  const { t } = useTranslation();
  const callbackError = useOidcCallbackError();
  const [error, setError] = useState<string | null>(
    callbackError ? t(oidcErrorKey(callbackError)) : null,
  );
  const [redirecting, setRedirecting] = useState(false);
  const provider = providerName(issuer);

  const onClick = async () => {
    setError(null);
    try {
      setRedirecting(true);
      await startOidcLogin();
    } catch (err) {
      setRedirecting(false);
      setError(messageFor(err, t("common.requestFailed")));
    }
  };

  return (
    <Centered>
      <Wordmark />
      <Card title={t("auth.loginTitle")} description={t("auth.oidcLoginIntro")}>
        <div className="space-y-3">
          <ErrorBanner message={error} />
          <Button type="button" onClick={onClick} disabled={redirecting} className="w-full">
            {redirecting
              ? t("auth.redirecting", { provider })
              : t("auth.continueWithProvider", { provider })}
          </Button>
        </div>
      </Card>
    </Centered>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-50 p-6">
      <div className="w-full max-w-sm">{children}</div>
    </div>
  );
}

function Wordmark() {
  const { t } = useTranslation();
  return (
    <div className="mb-6 text-center">
      <h1 className="text-2xl font-bold tracking-tight text-indigo-600">plamotrack</h1>
      <p className="mt-0.5 text-xs text-zinc-400">{t("layout.tagline")}</p>
    </div>
  );
}

function messageFor(err: unknown, fallback: string): string {
  return err instanceof ApiError ? err.message : fallback;
}

function SetupScreen({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<{ token: string; password: string; confirm: string }>();

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    if (values.password !== values.confirm) {
      setError(t("auth.passwordMismatch"));
      return;
    }
    try {
      await api.setupOwner(values.token.trim(), values.password);
      await onDone();
    } catch (err) {
      setError(messageFor(err, t("common.requestFailed")));
    }
  });

  return (
    <Centered>
      <Wordmark />
      <Card title={t("auth.setupTitle")} description={t("auth.setupIntro")}>
        <form onSubmit={onSubmit} className="space-y-3">
          <ErrorBanner message={error} />
          <Field label={t("auth.setupTokenLabel")} required error={errors.token?.message}>
            <Input autoFocus autoComplete="off" {...register("token", { required: true })} />
            <p className="mt-1 text-xs text-zinc-400">{t("auth.setupTokenHint")}</p>
          </Field>
          <Field label={t("auth.passwordLabel")} required error={errors.password?.message}>
            <Input
              type="password"
              autoComplete="new-password"
              {...register("password", { required: true, minLength: 12 })}
            />
            <p className="mt-1 text-xs text-zinc-400">{t("auth.passwordHint")}</p>
          </Field>
          <Field label={t("auth.confirmPasswordLabel")} required error={errors.confirm?.message}>
            <Input
              type="password"
              autoComplete="new-password"
              {...register("confirm", { required: true })}
            />
          </Field>
          <Button type="submit" disabled={isSubmitting || !watch("token")} className="w-full">
            {t("auth.createButton")}
          </Button>
        </form>
      </Card>
    </Centered>
  );
}

function LoginScreen({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<{ password: string }>();

  const onSubmit = handleSubmit(async (values) => {
    setError(null);
    try {
      await api.login(values.password);
      await onDone();
    } catch (err) {
      setError(messageFor(err, t("common.requestFailed")));
    }
  });

  return (
    <Centered>
      <Wordmark />
      <Card title={t("auth.loginTitle")} description={t("auth.loginIntro")}>
        <form onSubmit={onSubmit} className="space-y-3">
          <ErrorBanner message={error} />
          <Field label={t("auth.passwordLabel")} required error={errors.password?.message}>
            <Input
              type="password"
              autoFocus
              autoComplete="current-password"
              {...register("password", { required: true })}
            />
          </Field>
          <Button type="submit" disabled={isSubmitting} className="w-full">
            {t("auth.signInButton")}
          </Button>
        </form>
      </Card>
    </Centered>
  );
}
