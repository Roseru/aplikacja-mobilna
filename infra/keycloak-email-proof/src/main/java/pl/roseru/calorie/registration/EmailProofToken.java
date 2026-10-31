package pl.roseru.calorie.registration;

import java.util.UUID;
import java.net.URI;
import jakarta.ws.rs.core.UriInfo;
import org.keycloak.authentication.actiontoken.DefaultActionToken;
import org.keycloak.crypto.SignatureProvider;
import org.keycloak.crypto.SignatureSignerContext;
import org.keycloak.jose.jws.JWSBuilder;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.services.Urls;

/** No subject: an identity must not be created before mailbox possession is proved. */
public final class EmailProofToken extends DefaultActionToken {
    public static final String TYPE = "calorie-registration-email-proof-v1";
    public EmailProofToken() { super(); }
    EmailProofToken(String email, int expires, String authenticationSession, String client, String execution) {
        super(null, TYPE, expires, UUID.randomUUID(), authenticationSession);
        setEmail(email);
        issuedFor(client);
        setNote("execution", execution);
    }
    @Override public String serialize(KeycloakSession session, RealmModel realm, UriInfo uri) {
        return serialize(session, realm, uri.getBaseUri());
    }
    @Override public String serialize(KeycloakSession session, RealmModel realm, URI baseUri) {
        String issuer = Urls.realmIssuer(baseUri, realm.getName());
        issuedNow().id(getId() == null ? UUID.randomUUID().toString() : getId()).issuer(issuer).audience(issuer);
        // INTERNAL action tokens default to HS512 in Keycloak 26.8.1. Select RSA explicitly
        // rather than broadening the verifier's fixed RS256 algorithm/key-family contract.
        SignatureSignerContext signer = session.getProvider(SignatureProvider.class, "RS256").signer();
        if (!"RS256".equals(signer.getAlgorithm())) throw new IllegalStateException("RSA signing unavailable");
        return new JWSBuilder().type("JWT").kid(signer.getKid()).jsonContent(this).sign(signer);
    }
}
