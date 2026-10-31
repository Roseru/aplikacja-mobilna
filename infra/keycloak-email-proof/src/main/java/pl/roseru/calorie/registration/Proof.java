package pl.roseru.calorie.registration;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.HexFormat;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import org.keycloak.TokenVerifier;
import org.keycloak.common.util.Time;
import org.keycloak.crypto.SignatureProvider;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.services.Urls;
import org.keycloak.sessions.AuthenticationSessionCompoundId;
import org.keycloak.sessions.AuthenticationSessionModel;

final class Proof {
    static final int LIFETIME = 300;
    static final String PREFIX = "calorie.registration.proof.";
    static final String PENDING_ID = PREFIX + "pending-id";
    static final String PENDING_EMAIL = PREFIX + "pending-email";
    static final String VERIFIED_EMAIL = PREFIX + "verified-email";
    static final String VERIFIED_UNTIL = PREFIX + "verified-until";
    static final String KEY_PREFIX = "calorie-registration-proof-v1:";
    private Proof() {}

    static String email(String value) {
        if (value == null) throw new IllegalArgumentException("Email required");
        String result = value.strip().toLowerCase(Locale.ROOT);
        // Deliberately validate syntax without consulting the user store.
        if (result.length() > 254 || !org.keycloak.services.validation.Validation.isEmailValid(result))
            throw new IllegalArgumentException("Invalid email");
        return result;
    }

    static String verified(AuthenticationSessionModel auth) {
        if (auth == null) return null;
        try {
            String value = auth.getAuthNote(VERIFIED_EMAIL);
            long until = Long.parseLong(auth.getAuthNote(VERIFIED_UNTIL));
            return until > Time.currentTime() ? email(value) : null;
        } catch (RuntimeException ignored) { return null; }
    }

    static String singleUseKey(RealmModel realm, EmailProofToken token) {
        return KEY_PREFIX + realm.getId() + ":" + token.getId();
    }

    static String cooldownKey(RealmModel realm, String email) {
        try {
            return KEY_PREFIX + "cooldown:" + HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest((realm.getId() + "\n" + email).getBytes(StandardCharsets.UTF_8)));
        } catch (java.security.NoSuchAlgorithmException impossible) { throw new IllegalStateException(impossible); }
    }

    static EmailProofToken verify(KeycloakSession session, RealmModel realm, AuthenticationSessionModel auth,
                                  String execution, String encoded) throws Exception {
        if (encoded == null || encoded.length() > 8192) throw new IllegalArgumentException("Invalid proof");
        TokenVerifier<EmailProofToken> verifier = TokenVerifier.create(encoded, EmailProofToken.class);
        // Fix the algorithm; do not let the incoming JWT select another key family.
        if (!"RS256".equals(verifier.getHeader().getAlgorithm().name())) throw new IllegalArgumentException("Invalid proof");
        String issuer = Urls.realmIssuer(session.getContext().getUri().getBaseUri(), realm.getName());
        verifier.verifierContext(session.getProvider(SignatureProvider.class, "RS256").verifier(verifier.getHeader().getKeyId()))
                .withChecks(TokenVerifier.IS_ACTIVE, new TokenVerifier.RealmUrlCheck(issuer),
                        new TokenVerifier.AudienceCheck(issuer)).verify();
        EmailProofToken token = verifier.getToken();
        if (!EmailProofToken.TYPE.equals(token.getType()) || token.getSubject() != null
                || token.getActionVerificationNonce() == null || token.getId() == null
                || !Objects.equals(token.getIssuedFor(), auth.getClient().getClientId())
                || !Objects.equals(token.getCompoundAuthenticationSessionId(), AuthenticationSessionCompoundId.fromAuthSession(auth).getEncodedId())
                || !Objects.equals(token.getNote("execution"), execution)
                || !Objects.equals(token.getId(), auth.getAuthNote(PENDING_ID))
                || !Objects.equals(email(token.getEmail()), auth.getAuthNote(PENDING_EMAIL)))
            throw new IllegalArgumentException("Invalid proof");
        return token;
    }

    static boolean consume(KeycloakSession session, RealmModel realm, AuthenticationSessionModel auth, EmailProofToken token) {
        // remove is documented atomic, including across cluster/multi-site nodes.
        Map<String, String> removed = session.singleUseObjects().remove(singleUseKey(realm, token));
        if (removed == null) return false;
        auth.setAuthNote(VERIFIED_EMAIL, email(token.getEmail()));
        auth.setAuthNote(VERIFIED_UNTIL, Long.toString(token.getExpiration()));
        auth.removeAuthNote(PENDING_ID);
        auth.removeAuthNote(PENDING_EMAIL);
        return true;
    }
}
