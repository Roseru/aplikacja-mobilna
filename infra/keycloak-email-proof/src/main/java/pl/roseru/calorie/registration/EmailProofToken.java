package pl.roseru.calorie.registration;

import java.util.UUID;
import org.keycloak.authentication.actiontoken.DefaultActionToken;

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
}
