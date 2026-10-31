package pl.roseru.calorie.registration;

import java.net.URI;
import java.util.List;
import java.util.Map;
import jakarta.ws.rs.core.MultivaluedMap;
import jakarta.ws.rs.core.UriBuilder;
import org.keycloak.Config;
import org.keycloak.authentication.Authenticator;
import org.keycloak.authentication.AuthenticatorFactory;
import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.common.util.Time;
import org.keycloak.email.EmailException;
import org.keycloak.email.EmailSenderProvider;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.KeycloakSessionFactory;
import org.keycloak.models.RealmModel;
import org.keycloak.models.UserModel;
import org.keycloak.provider.ProviderConfigProperty;
import org.keycloak.sessions.AuthenticationSessionCompoundId;
import org.keycloak.sessions.AuthenticationSessionModel;

/** Standard registration-flow execution. No user lookup or account mutation before proof. */
public final class EmailProofAuthenticator implements Authenticator, AuthenticatorFactory {
    public static final String ID = "calorie-registration-email-proof";
    @Override public void authenticate(AuthenticationFlowContext context) {
        String linkToken = context.getUriInfo().getQueryParameters().getFirst("email_proof");
        if (linkToken != null) showLinkConfirmation(context, linkToken);
        else if (Proof.verified(context.getAuthenticationSession()) != null) context.success();
        else context.challenge(context.form().createForm("calorie-email-proof.ftl"));
    }

    @Override public void action(AuthenticationFlowContext context) {
        MultivaluedMap<String, String> query = context.getUriInfo().getQueryParameters();
        MultivaluedMap<String, String> form = context.getHttpRequest().getDecodedFormParameters();
        String proof = form.getFirst("email_proof");
        if (proof != null) {
            try {
                EmailProofToken token = Proof.verify(context.getSession(), context.getRealm(), context.getAuthenticationSession(),
                        context.getExecution().getId(), proof);
                if (!Proof.consume(context.getSession(), context.getRealm(), context.getAuthenticationSession(), token))
                    throw new IllegalArgumentException("Used proof");
                context.success();
            } catch (Exception ignored) {
                // No token, address, exception or existence detail reaches logging or the public page.
                context.challenge(context.form().setError("calorieEmailProofExpired").createForm("calorie-email-proof.ftl"));
            }
            return;
        }
        String linkToken = query.getFirst("email_proof");
        if (linkToken != null) {
            showLinkConfirmation(context, linkToken);
            return;
        }
        requestProof(context, form.getFirst("email"));
    }

    private void showLinkConfirmation(AuthenticationFlowContext context, String token) {
        // Registration GET re-enters authenticate(), not action(). Both paths remain read-only.
        if (token.length() > 8192) {
            context.challenge(context.form().setError("calorieEmailProofExpired").createForm("calorie-email-proof.ftl"));
            return;
        }
        context.challenge(context.form().setAttribute("emailProofToken", token)
                .createForm("calorie-email-proof-confirm.ftl"));
    }

    void requestProof(AuthenticationFlowContext context, String input) {
        final String email;
        try { email = Proof.email(input); }
        catch (IllegalArgumentException ignored) {
            context.challenge(context.form().setError("invalidEmailMessage").createForm("calorie-email-proof.ftl"));
            return;
        }
        AuthenticationSessionModel auth = context.getAuthenticationSession();
        KeycloakSession session = context.getSession();
        RealmModel realm = context.getRealm();
        // Rate limiting is independent of account existence, including across authentication sessions.
        if (session.singleUseObjects().putIfAbsent(Proof.cooldownKey(realm, email), 60)) {
            String oldId = auth.getAuthNote(Proof.PENDING_ID);
            if (oldId != null) session.singleUseObjects().remove(Proof.KEY_PREFIX + realm.getId() + ":" + oldId);
            auth.removeAuthNote(Proof.VERIFIED_EMAIL);
            auth.removeAuthNote(Proof.VERIFIED_UNTIL);
            EmailProofToken token = new EmailProofToken(email, Time.currentTime() + Proof.LIFETIME,
                    AuthenticationSessionCompoundId.fromAuthSession(auth).getEncodedId(), auth.getClient().getClientId(),
                    context.getExecution().getId());
            String encoded = token.serialize(session, realm, context.getUriInfo());
            auth.setAuthNote(Proof.PENDING_ID, token.getId());
            auth.setAuthNote(Proof.PENDING_EMAIL, email);
            session.singleUseObjects().put(Proof.singleUseKey(realm, token), Proof.LIFETIME, Map.of());
            // A GET link must not carry a one-use form session_code: a mail scanner/refresh
            // would otherwise invalidate it before the user confirms. The confirmation page
            // itself receives the ordinary CSRF-protected POST action from context.form().
            URI link = UriBuilder.fromUri(context.getRefreshExecutionUrl())
                    .queryParam("email_proof", encoded).build();
            try {
                session.getProvider(EmailSenderProvider.class).send(realm.getSmtpConfig(), email,
                        "Potwierdź adres e-mail / Confirm your email",
                        "Aby kontynuować rejestrację, otwórz poniższy link w tej samej przeglądarce i potwierdź. "
                        + "Link jest ważny przez 5 minut. Jeśli masz już konto, skorzystaj z logowania lub resetu hasła.\n\n"
                        + "To continue registration, open this link in the same browser and confirm. "
                        + "It expires in 5 minutes. If you already have an account, use login or password reset.\n\n" + link,
                        null);
            } catch (EmailException ignored) {
                session.singleUseObjects().remove(Proof.singleUseKey(realm, token));
                auth.removeAuthNote(Proof.PENDING_ID);
                auth.removeAuthNote(Proof.PENDING_EMAIL);
                // Delivery failure is observable by its real owner, never a username-existence signal.
                context.challenge(context.form().setError("calorieEmailDeliveryFailed").createForm("calorie-email-proof.ftl"));
                return;
            }
        }
        context.challenge(context.form().setAttribute("emailProofSent", true).createForm("calorie-email-proof.ftl"));
    }

    @Override public String getId() { return ID; }
    @Override public Authenticator create(KeycloakSession session) { return this; }
    @Override public String getDisplayType() { return "Calorie: prove email before registration"; }
    @Override public String getHelpText() { return "Required before the guarded registration form; never searches for a user."; }
    @Override public String getReferenceCategory() { return null; }
    @Override public boolean isConfigurable() { return false; }
    @Override public boolean isUserSetupAllowed() { return false; }
    @Override public List<ProviderConfigProperty> getConfigProperties() { return List.of(); }
    @Override public AuthenticationExecutionModel.Requirement[] getRequirementChoices() {
        return new AuthenticationExecutionModel.Requirement[] { AuthenticationExecutionModel.Requirement.REQUIRED };
    }
    @Override public boolean requiresUser() { return false; }
    @Override public boolean configuredFor(KeycloakSession s, RealmModel r, UserModel u) { return true; }
    @Override public void setRequiredActions(KeycloakSession s, RealmModel r, UserModel u) {}
    @Override public void init(Config.Scope scope) {}
    @Override public void postInit(KeycloakSessionFactory factory) {}
    @Override public void close() {}
}
