package pl.roseru.calorie.registration;

import java.util.List;
import jakarta.ws.rs.core.MultivaluedHashMap;
import jakarta.ws.rs.core.MultivaluedMap;
import org.keycloak.authentication.AuthenticationFlowError;
import org.keycloak.authentication.AuthenticationFlowException;
import org.keycloak.authentication.FormContext;
import org.keycloak.authentication.ValidationContext;
import org.keycloak.authentication.forms.RegistrationUserCreation;
import org.keycloak.forms.login.LoginFormsProvider;
import org.keycloak.models.UserModel;
import org.keycloak.models.utils.FormMessage;

/** Replaces stock user creation; preserves its profile validation, uniqueness and default roles. */
public final class ProvenEmailUserCreation extends RegistrationUserCreation {
    public static final String ID = "calorie-proven-email-user-creation";
    @Override public String getId() { return ID; }
    @Override public String getDisplayType() { return "Calorie: create only for the proven email"; }
    @Override public void validate(ValidationContext context) {
        if (!matches(context)) {
            // No call to stock validation: its EMAIL_EXISTS check is itself the public oracle.
            context.validationError(context.getHttpRequest().getDecodedFormParameters(),
                    List.of(new FormMessage(UserModel.EMAIL, "calorieEmailProofRequired")));
            return;
        }
        // Do not pass arbitrary usernames or a second email value to stock profile validators.
        bindFields(context);
        super.validate(context);
    }
    @Override public void buildPage(FormContext context, LoginFormsProvider form) {
        String email = Proof.verified(context.getAuthenticationSession());
        if (email == null) throw new AuthenticationFlowException(AuthenticationFlowError.EXPIRED_CODE);
        MultivaluedMap<String, String> data = new MultivaluedHashMap<>(context.getHttpRequest().getDecodedFormParameters());
        data.putSingle(UserModel.EMAIL, email);
        data.putSingle(UserModel.USERNAME, email);
        form.setFormData(data);
        super.buildPage(context, form);
    }
    @Override public void success(FormContext context) {
        if (!matches(context)) throw new AuthenticationFlowException(AuthenticationFlowError.EXPIRED_CODE);
        bindFields(context);
        super.success(context);
        // Set only after the stock provider created the exact proven address.
        context.getUser().setEmailVerified(true);
        context.getAuthenticationSession().removeAuthNote(Proof.VERIFIED_EMAIL);
        context.getAuthenticationSession().removeAuthNote(Proof.VERIFIED_UNTIL);
    }
    private boolean matches(FormContext context) {
        String email = Proof.verified(context.getAuthenticationSession());
        if (email == null || !context.getRealm().isRegistrationEmailAsUsername()
                || !context.getRealm().isLoginWithEmailAllowed()
                || context.getRealm().isDuplicateEmailsAllowed()) return false;
        try {
            MultivaluedMap<String, String> data = context.getHttpRequest().getDecodedFormParameters();
            List<String> emails = data.get(UserModel.EMAIL);
            List<String> usernames = data.get(UserModel.USERNAME);
            return emails != null && emails.size() == 1 && email.equals(Proof.email(emails.get(0)))
                    && (usernames == null || (usernames.size() == 1 && email.equals(Proof.email(usernames.get(0)))));
        } catch (IllegalArgumentException ignored) { return false; }
    }
    private void bindFields(FormContext context) {
        String email = Proof.verified(context.getAuthenticationSession());
        MultivaluedMap<String, String> data = context.getHttpRequest().getDecodedFormParameters();
        data.putSingle(UserModel.EMAIL, email);
        data.putSingle(UserModel.USERNAME, email);
    }
}
