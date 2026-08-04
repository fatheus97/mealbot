import { useState } from "react";
import { useAuth } from "../contexts/AuthContext";
import { useIsMobile } from "../hooks/useIsMobile";
import { AutoLoginAfterRegisterError } from "../contexts/authErrors";
import { SettingsPopup } from "./SettingsPopup";
import { ForgotPasswordModal } from "./ForgotPasswordModal";
import { TermsConsent } from "./auth/TermsConsent";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { useI18n, type TranslationKey } from "../i18n";
import { Trans } from "../i18n/Trans";

const SUPPORT_EMAIL = "info@trymealbot.com";

export function AuthBar() {
  const { userId, email, login, logout, loginDemo, demoEnabled, register, registrationEnabled } = useAuth();
  const isMobile = useIsMobile();
  const { t } = useI18n();
  const [inputEmail, setInputEmail] = useState(email);
  const [inputPassword, setInputPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showSettings, setShowSettings] = useState(false);
  const [showForgot, setShowForgot] = useState(false);
  // The KEY, not the sentence. Storing `t(...)` output would freeze the message
  // in whatever language it was raised in: switching to Czech re-renders every
  // other label here but cannot reach a string that was already translated, and
  // this one persists until a keystroke clears it. Translate at render instead —
  // the same store-intent-not-output shape EmailVerificationBanner uses.
  const [authError, setAuthError] = useState<TranslationKey | null>(null);
  const [acceptTerms, setAcceptTerms] = useState(false);

  const handleLogin = async () => {
    setLoading(true);
    setAuthError(null);
    try {
      await login(inputEmail, inputPassword);
      setInputPassword("");
    } catch (error) {
      console.error(error);
      setAuthError("auth.error.login");
    } finally {
      setLoading(false);
    }
  };

  const handleRegister = async () => {
    // Surface a client-side guard before hitting the backend so the user
    // doesn't have to wait for a 422 to see "password too short".
    if (inputPassword.length < 8) {
      setAuthError("auth.error.passwordTooShort");
      return;
    }
    // Checked here rather than by disabling Register: the same two fields also
    // drive Sign In, and disabling the button would leave a user who has not
    // ticked the box guessing which of the three controls they broke.
    if (!acceptTerms) {
      setAuthError("auth.error.acceptTerms");
      return;
    }
    setLoading(true);
    setAuthError(null);
    try {
      await register(inputEmail, inputPassword, acceptTerms);
      setInputPassword("");
    } catch (error) {
      console.error(error);
      if (error instanceof AutoLoginAfterRegisterError) {
        // Crucial distinction: the account was created. Telling the user
        // "registration failed" here would get them to submit again and
        // hit a 409 on the duplicate email.
        setAuthError("auth.error.accountCreated");
      } else {
        // Neutral copy covers 403 (flag flipped), 409 (duplicate), 422
        // (weak password that passed the client guard), 5xx, etc.
        setAuthError("auth.error.register");
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <section style={{ marginBottom: "1.5rem", padding: "1rem", backgroundColor: "#f0f8ff", color: "#111", borderRadius: "8px" }}>
      {/* The switcher rides on the heading's own row rather than adding one, so
          it costs no vertical space and cannot shift the form below it. */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.5rem" }}>
        <h2 style={{ margin: 0 }}>{userId ? t("auth.welcome") : t("auth.login")}</h2>
        <LanguageSwitcher />
      </div>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: isMobile ? "stretch" : "center", flexDirection: isMobile ? "column" : "row", flexWrap: "wrap", marginTop: "0.75rem" }}>
        {!userId && (
          // A real <form> so pressing Enter in either field submits (implicit
          // submission only works inside a form). display:contents keeps the
          // inputs/buttons participating directly in the parent flex row, so the
          // layout is unchanged. Sign In is the submit button; Register/Demo are
          // type="button" so Enter (or an accidental submit) can't trigger them.
          <form
            onSubmit={e => { e.preventDefault(); handleLogin(); }}
            style={{ display: "contents" }}
          >
            <input
              value={inputEmail}
              onChange={e => { setInputEmail(e.target.value); setAuthError(null); }}
              placeholder={t("auth.email")}
              style={{ padding: "0.5rem" }}
            />
            <input
              type="password"
              value={inputPassword}
              onChange={e => { setInputPassword(e.target.value); setAuthError(null); }}
              placeholder={t("auth.password")}
              style={{ padding: "0.5rem" }}
            />
            <button type="submit" disabled={loading} style={{ padding: "0.5rem 1rem" }}>
              {loading ? t("auth.busy") : t("auth.signIn")}
            </button>
            {registrationEnabled && (
              <button
                type="button"
                onClick={handleRegister}
                disabled={loading}
                style={{ padding: "0.5rem 1rem", backgroundColor: "#2563eb", color: "white", border: "none", borderRadius: "4px" }}
              >
                {loading ? t("auth.busy") : t("auth.register")}
              </button>
            )}
            {demoEnabled && (
              <button
                type="button"
                onClick={async () => {
                  setLoading(true);
                  setAuthError(null);
                  try {
                    await loginDemo();
                  } catch {
                    setAuthError("auth.error.demo");
                  } finally {
                    setLoading(false);
                  }
                }}
                disabled={loading}
                title={t("auth.demoTitle")}
                style={{ padding: "0.5rem 1rem", backgroundColor: "#2e7d32", color: "white", border: "none", borderRadius: "4px" }}
              >
                {loading ? t("auth.busy") : t("auth.tryDemo")}
              </button>
            )}
          </form>
        )}
        {userId && (
          <div style={{ display: "flex", gap: "1rem", alignItems: "center", position: "relative", flexWrap: "wrap" }}>
             <span style={{ minWidth: 0, overflowWrap: "anywhere" }}>✅ {email}</span>
             <button
               onClick={() => setShowSettings(!showSettings)}
               style={{ background: "none", border: "none", fontSize: "1.3rem", cursor: "pointer", padding: "0.25rem" }}
               aria-label={t("auth.settings")}
               title={t("auth.settings")}
             >
               ⚙️
             </button>
             <button onClick={logout} style={{ padding: "0.5rem 1rem", backgroundColor: "#dc2626", color: "white", border: "none", borderRadius: "4px" }}>{t("auth.logout")}</button>
             {showSettings && <SettingsPopup onClose={() => setShowSettings(false)} />}
          </div>
        )}
      </div>
      {/* Only where an account can actually be created — the Register button is
          gated on the same flag, and a consent checkbox with nothing to consent
          to would just be clutter on a login form. */}
      {!userId && registrationEnabled && (
        <div style={{ marginTop: "0.75rem" }}>
          <TermsConsent
            checked={acceptTerms}
            onChange={(next) => { setAcceptTerms(next); setAuthError(null); }}
            disabled={loading}
          />
        </div>
      )}
      {!userId && authError && (
        <p role="alert" style={{ marginTop: "0.75rem", marginBottom: 0, color: "#b91c1c", fontSize: "0.85rem" }}>
          {/* supportEmail passed unconditionally — interpolate() leaves the
              messages that have no such placeholder untouched. */}
          {t(authError, { supportEmail: SUPPORT_EMAIL })}
        </p>
      )}
      {!userId && (
        <p style={{ marginTop: "0.75rem", marginBottom: 0, fontSize: "0.85rem" }}>
          <button
            type="button"
            onClick={() => setShowForgot(true)}
            style={{
              background: "none",
              border: "none",
              padding: 0,
              color: "#007bff",
              cursor: "pointer",
              fontSize: "0.85rem",
              textDecoration: "underline",
            }}
          >
            {t("auth.forgotPassword")}
          </button>
        </p>
      )}
      {showForgot && (
        <ForgotPasswordModal
          onClose={() => setShowForgot(false)}
          initialEmail={inputEmail}
        />
      )}
      {!userId && registrationEnabled === false && (
        <p style={{ marginTop: "0.75rem", fontSize: "0.85rem", color: "#555" }}>
          <Trans
            k="auth.closedAlpha"
            nodes={{
              supportEmail: (
                <a href={`mailto:${SUPPORT_EMAIL}`} style={{ color: "#007bff" }}>
                  {SUPPORT_EMAIL}
                </a>
              ),
            }}
          />
        </p>
      )}
    </section>
  );
}
