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
  if (session?.state === "unclaimed") {
    return <SetupScreen onDone={onAuthed} />;
  }
  if (session?.state !== "owner") {
    return <LoginScreen onDone={onAuthed} />;
  }
  return <>{children}</>;
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
