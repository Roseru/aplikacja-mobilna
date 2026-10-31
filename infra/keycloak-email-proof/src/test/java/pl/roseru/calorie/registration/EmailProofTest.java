package pl.roseru.calorie.registration;

import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.Signature;
import java.util.Base64;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import jakarta.ws.rs.core.MultivaluedHashMap;
import jakarta.ws.rs.core.MultivaluedMap;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.core.UriInfo;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.keycloak.authentication.AuthenticationFlowContext;
import org.keycloak.authentication.ValidationContext;
import org.keycloak.common.util.Time;
import org.keycloak.crypto.SignatureProvider;
import org.keycloak.crypto.SignatureVerifierContext;
import org.keycloak.email.EmailException;
import org.keycloak.email.EmailSenderProvider;
import org.keycloak.forms.login.LoginFormsProvider;
import org.keycloak.http.HttpRequest;
import org.keycloak.models.AuthenticationExecutionModel;
import org.keycloak.models.ClientModel;
import org.keycloak.models.KeycloakContext;
import org.keycloak.models.KeycloakSession;
import org.keycloak.models.RealmModel;
import org.keycloak.models.SingleUseObjectProvider;
import org.keycloak.models.TokenManager;
import org.keycloak.models.KeycloakUriInfo;
import org.keycloak.sessions.AuthenticationSessionCompoundId;
import org.keycloak.sessions.AuthenticationSessionModel;
import org.keycloak.sessions.RootAuthenticationSessionModel;
import org.keycloak.util.JsonSerialization;
import org.keycloak.events.EventBuilder;
import org.keycloak.events.Errors;
import org.keycloak.services.messages.Messages;
import org.keycloak.userprofile.UserProfile;
import org.keycloak.userprofile.Attributes;
import org.keycloak.userprofile.ValidationException;
import org.keycloak.validate.ValidationError;
import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class EmailProofTest {
    @BeforeAll static void configureKeycloakFeatures() { org.keycloak.common.Profile.configure(); }
    KeycloakSession session;
    RealmModel realm;
    AuthenticationSessionModel auth;
    AuthenticationFlowContext context;
    SingleUseObjectProvider store;
    EmailSenderProvider sender;
    LoginFormsProvider forms;
    HttpRequest request;
    KeycloakUriInfo uri;
    Map<String,String> notes;
    ConcurrentHashMap<String,Map<String,String>> singleUse;
    KeyPair keys;
    String emailed;

    @BeforeEach void setup() throws Exception {
        session=mock(KeycloakSession.class);realm=mock(RealmModel.class);auth=mock(AuthenticationSessionModel.class);
        context=mock(AuthenticationFlowContext.class);store=mock(SingleUseObjectProvider.class);
        sender=mock(EmailSenderProvider.class);forms=mock(LoginFormsProvider.class,RETURNS_SELF);
        request=mock(HttpRequest.class);uri=mock(KeycloakUriInfo.class);
        notes=new HashMap<>();singleUse=new ConcurrentHashMap<>();
        keys=KeyPairGenerator.getInstance("RSA").generateKeyPair();
        when(realm.getId()).thenReturn("realm-one");when(realm.getName()).thenReturn("calorie-dev");
        when(realm.isRegistrationEmailAsUsername()).thenReturn(true);
        when(realm.isLoginWithEmailAllowed()).thenReturn(true);
        when(realm.getSmtpConfig()).thenReturn(Map.of("host","test"));
        ClientModel client=mock(ClientModel.class);when(client.getId()).thenReturn("client-internal");
        when(client.getClientId()).thenReturn("calorie-android");when(auth.getClient()).thenReturn(client);
        RootAuthenticationSessionModel root=mock(RootAuthenticationSessionModel.class);when(root.getId()).thenReturn("root-one");
        when(auth.getParentSession()).thenReturn(root);when(auth.getTabId()).thenReturn("tab-one");
        when(auth.getAuthNote(anyString())).thenAnswer(a->notes.get(a.getArgument(0)));
        doAnswer(a->{notes.put(a.getArgument(0),a.getArgument(1));return null;}).when(auth).setAuthNote(anyString(),anyString());
        doAnswer(a->{notes.remove(a.getArgument(0));return null;}).when(auth).removeAuthNote(anyString());
        when(session.singleUseObjects()).thenReturn(store);
        when(store.putIfAbsent(anyString(),anyLong())).thenAnswer(a->singleUse.putIfAbsent(a.getArgument(0),Map.of())==null);
        doAnswer(a->{singleUse.put(a.getArgument(0),a.getArgument(2));return null;}).when(store).put(anyString(),anyLong(),anyMap());
        when(store.remove(anyString())).thenAnswer(a->singleUse.remove(a.getArgument(0)));
        KeycloakContext kc=mock(KeycloakContext.class);when(session.getContext()).thenReturn(kc);when(kc.getUri()).thenReturn(uri);
        when(uri.getBaseUri()).thenReturn(URI.create("https://provider.test/"));
        when(uri.getQueryParameters()).thenReturn(new MultivaluedHashMap<>());
        when(context.getSession()).thenReturn(session);when(context.getRealm()).thenReturn(realm);
        when(context.getAuthenticationSession()).thenReturn(auth);when(context.getHttpRequest()).thenReturn(request);
        when(context.getUriInfo()).thenReturn(uri);when(context.form()).thenReturn(forms);
        when(context.generateAccessCode()).thenReturn("csrf");
        when(context.getActionUrl("csrf")).thenReturn(URI.create("https://provider.test/realms/calorie-dev/login-actions/registration?session_code=csrf&execution=exec-one&tab_id=tab-one"));
        AuthenticationExecutionModel execution=new AuthenticationExecutionModel();execution.setId("exec-one");
        when(context.getExecution()).thenReturn(execution);
        when(forms.createForm(anyString())).thenReturn(Response.ok().build());
        when(session.getProvider(EmailSenderProvider.class)).thenReturn(sender);
        TokenManager tokens=mock(TokenManager.class);when(session.tokens()).thenReturn(tokens);
        when(tokens.encode(any())).thenAnswer(a->sign(a.getArgument(0),keys));
        SignatureProvider provider=mock(SignatureProvider.class);SignatureVerifierContext verifier=mock(SignatureVerifierContext.class);
        when(session.getProvider(SignatureProvider.class,"RS256")).thenReturn(provider);when(provider.verifier("test")).thenReturn(verifier);
        when(verifier.verify(any(),any())).thenAnswer(a->{Signature sig=Signature.getInstance("SHA256withRSA");sig.initVerify(keys.getPublic());sig.update((byte[])a.getArgument(0));return sig.verify(a.getArgument(1));});
        doAnswer(a->{emailed=a.getArgument(3);return null;}).when(sender).send(anyMap(),anyString(),anyString(),anyString(),isNull());
        // A production change that adds even a lookup before proof will fail the initiation tests.
        when(session.users()).thenThrow(new AssertionError("User store accessed before mailbox proof"));
    }

    String sign(Object token,KeyPair pair) throws Exception {
        Base64.Encoder b64=Base64.getUrlEncoder().withoutPadding();
        String data=b64.encodeToString("{\"alg\":\"RS256\",\"typ\":\"JWT\",\"kid\":\"test\"}".getBytes(StandardCharsets.UTF_8))+"."
                +b64.encodeToString(JsonSerialization.writeValueAsBytes(token));
        Signature sig=Signature.getInstance("SHA256withRSA");sig.initSign(pair.getPrivate());sig.update(data.getBytes(StandardCharsets.US_ASCII));
        return data+"."+b64.encodeToString(sig.sign());
    }
    EmailProofToken issued(int expiry) {
        EmailProofToken token=new EmailProofToken("person@example.test",expiry,
                AuthenticationSessionCompoundId.fromAuthSession(auth).getEncodedId(),"calorie-android","exec-one");
        token.serialize(session,realm,uri);notes.put(Proof.PENDING_ID,token.getId());notes.put(Proof.PENDING_EMAIL,token.getEmail());
        singleUse.put(Proof.singleUseKey(realm,token),Map.of());return token;
    }
    @Test void initiationSendsWithoutReadingOrCreatingAnyUser() throws Exception {
        new EmailProofAuthenticator().requestProof(context,"Person@Example.test");
        verify(sender).send(anyMap(),eq("person@example.test"),anyString(),contains("email_proof="),isNull());
        verify(session,never()).users();verify(context,never()).setUser(any());verify(context,never()).success();
        assertNotNull(notes.get(Proof.PENDING_ID));assertNull(Proof.verified(auth));
    }
    @Test void accountExistenceCannotInfluenceInitialResponseOrDispatch() throws Exception {
        // There is no dependency on an existing/missing user. Both paths use only the address and SMTP.
        new EmailProofAuthenticator().requestProof(context,"existing@example.test");
        new EmailProofAuthenticator().requestProof(context,"missing@example.test");
        verify(sender,times(2)).send(anyMap(),anyString(),eq("Potwierdź adres e-mail / Confirm your email"),anyString(),isNull());
        verify(forms,times(2)).setAttribute("emailProofSent",true);verify(session,never()).users();
    }
    @Test void resendCooldownDoesNotReadUsersOrReplaceTheValidChallenge() {
        EmailProofAuthenticator authenticator=new EmailProofAuthenticator();
        authenticator.requestProof(context,"person@example.test");String original=notes.get(Proof.PENDING_ID);
        authenticator.requestProof(context,"person@example.test");assertEquals(original,notes.get(Proof.PENDING_ID));
        verify(session,never()).users();
    }
    @Test void deliveryFailureDoesNotCreateUserOrLeaveUsableProof() throws Exception {
        doThrow(new EmailException("private transport detail")).when(sender).send(anyMap(),anyString(),anyString(),anyString(),isNull());
        new EmailProofAuthenticator().requestProof(context,"person@example.test");
        assertNull(notes.get(Proof.PENDING_ID));verify(forms).setError("calorieEmailDeliveryFailed");verify(session,never()).users();
        assertTrue(singleUse.keySet().stream().allMatch(k->k.contains(":cooldown:")));
    }
    @Test void signedProofIsBoundToRealmClientSessionTabExecutionAndCurrentChallenge() throws Exception {
        EmailProofToken token=issued(Time.currentTime()+300);String encoded=token.serialize(session,realm,uri);
        assertEquals(token.getId(),Proof.verify(session,realm,auth,"exec-one",encoded).getId());
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-other",encoded));
        when(auth.getTabId()).thenReturn("tab-other");assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",encoded));
        when(auth.getTabId()).thenReturn("tab-one");when(auth.getClient().getClientId()).thenReturn("other-client");
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",encoded));
        when(auth.getClient().getClientId()).thenReturn("calorie-android");notes.put(Proof.PENDING_ID,"replacement");
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",encoded));
    }
    @Test void wrongSignatureExpiredWrongIssuerAudienceAndAlgorithmAreRejected() throws Exception {
        EmailProofToken expired=issued(Time.currentTime()-1);
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",expired.serialize(session,realm,uri)));
        EmailProofToken token=issued(Time.currentTime()+300);
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",sign(token,KeyPairGenerator.getInstance("RSA").generateKeyPair())));
        token.issuer("https://other.test/realms/calorie-dev");assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",sign(token,keys)));
        token.issuer("https://provider.test/realms/calorie-dev").audience("other");
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",sign(token,keys)));
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one","eyJhbGciOiJub25lIn0.e30."));
    }
    @Test void consumptionIsSingleUseAndCannotBeReplayed() throws Exception {
        EmailProofToken token=issued(Time.currentTime()+300);
        assertTrue(Proof.consume(session,realm,auth,token));assertEquals(token.getEmail(),Proof.verified(auth));
        assertFalse(Proof.consume(session,realm,auth,token));
        assertThrows(Exception.class,()->Proof.verify(session,realm,auth,"exec-one",token.serialize(session,realm,uri)));
    }
    @Test void linkGetDoesNotConsumeTokenOrRunRegistration() {
        EmailProofToken token=issued(Time.currentTime()+300);MultivaluedMap<String,String> query=new MultivaluedHashMap<>();
        query.putSingle("email_proof",token.serialize(session,realm,uri));when(uri.getQueryParameters()).thenReturn(query);
        when(request.getDecodedFormParameters()).thenReturn(new MultivaluedHashMap<>());
        new EmailProofAuthenticator().action(context);verify(forms).createForm("calorie-email-proof-confirm.ftl");
        assertTrue(singleUse.containsKey(Proof.singleUseKey(realm,token)));assertNull(Proof.verified(auth));verify(context,never()).success();
    }
    @Test void directFormPostWithoutProofDoesNotReachStockUniquenessLookup() {
        ValidationContext validation=mock(ValidationContext.class);when(validation.getAuthenticationSession()).thenReturn(auth);
        when(validation.getHttpRequest()).thenReturn(request);when(request.getDecodedFormParameters()).thenReturn(new MultivaluedHashMap<>());
        new ProvenEmailUserCreation().validate(validation);verify(validation).validationError(any(),anyList());
        verify(validation,never()).getSession();verify(validation,never()).success();
    }
    @Test void changedAddressOrExpiredProofCannotReachUserCreation() {
        notes.put(Proof.VERIFIED_EMAIL,"person@example.test");notes.put(Proof.VERIFIED_UNTIL,Integer.toString(Time.currentTime()+300));
        ValidationContext validation=mock(ValidationContext.class);when(validation.getAuthenticationSession()).thenReturn(auth);
        when(validation.getRealm()).thenReturn(realm);when(validation.getHttpRequest()).thenReturn(request);
        MultivaluedMap<String,String> data=new MultivaluedHashMap<>();data.putSingle("email","other@example.test");
        when(request.getDecodedFormParameters()).thenReturn(data);
        new ProvenEmailUserCreation().validate(validation);verify(validation).validationError(any(),anyList());verify(validation,never()).getSession();
        notes.put(Proof.VERIFIED_UNTIL,Integer.toString(Time.currentTime()-1));assertNull(Proof.verified(auth));
        assertThrows(Exception.class,()->new ProvenEmailUserCreation().success(validation));
    }
    @Test void provenAddressDoesNotPermitEnumeratingOtherUsernamesOrMultipleEmails() {
        notes.put(Proof.VERIFIED_EMAIL,"person@example.test");notes.put(Proof.VERIFIED_UNTIL,Integer.toString(Time.currentTime()+300));
        ValidationContext validation=mock(ValidationContext.class);when(validation.getAuthenticationSession()).thenReturn(auth);
        when(validation.getRealm()).thenReturn(realm);when(validation.getHttpRequest()).thenReturn(request);
        MultivaluedMap<String,String> data=new MultivaluedHashMap<>();data.putSingle("email","person@example.test");data.putSingle("username","victim@example.test");
        when(request.getDecodedFormParameters()).thenReturn(data);
        new ProvenEmailUserCreation().validate(validation);verify(validation).validationError(any(),anyList());verify(validation,never()).getSession();
        reset(validation);when(validation.getAuthenticationSession()).thenReturn(auth);when(validation.getRealm()).thenReturn(realm);when(validation.getHttpRequest()).thenReturn(request);
        data.remove("username");data.add("email","victim@example.test");
        new ProvenEmailUserCreation().validate(validation);verify(validation).validationError(any(),anyList());verify(validation,never()).getSession();
    }
    @Test void stockEmailUniquenessValidationStillRunsAfterProof() {
        notes.put(Proof.VERIFIED_EMAIL,"person@example.test");notes.put(Proof.VERIFIED_UNTIL,Integer.toString(Time.currentTime()+300));
        ValidationContext validation=mock(ValidationContext.class);when(validation.getAuthenticationSession()).thenReturn(auth);
        when(validation.getRealm()).thenReturn(realm);when(validation.getHttpRequest()).thenReturn(request);when(validation.getSession()).thenReturn(session);
        EventBuilder event=mock(EventBuilder.class,RETURNS_SELF);when(validation.getEvent()).thenReturn(event);
        MultivaluedMap<String,String> data=new MultivaluedHashMap<>();data.putSingle("email","Person@Example.test");
        when(request.getDecodedFormParameters()).thenReturn(data);
        UserProfile profile=mock(UserProfile.class);Attributes attrs=mock(Attributes.class);when(profile.getAttributes()).thenReturn(attrs);
        when(attrs.getFirst("email")).thenReturn("person@example.test");when(attrs.getFirst("username")).thenReturn("person@example.test");
        when(session.getAttribute("UP_REGISTER")).thenReturn(profile);
        doThrow(new ValidationException(new ValidationError("email-exists","email",Messages.EMAIL_EXISTS))).when(profile).validate();
        new ProvenEmailUserCreation().validate(validation);
        verify(profile).validate();verify(validation).error(Errors.EMAIL_IN_USE);verify(validation).validationError(any(),anyList());
        verify(profile,never()).create();assertEquals("person@example.test",data.getFirst("username"));assertEquals("person@example.test",data.getFirst("email"));
    }
    @Test void emailSyntaxUsesTheProviderValidatorAndRejectsMultipleRecipientsOrHeaders() {
        assertEquals("person+tag@example.test",Proof.email(" Person+tag@Example.test "));
        for(String bad:java.util.List.of("person@example.test,other@example.test","person@example.test\r\nBcc: other@example.test","not-an-email","<person@example.test>"))
            assertThrows(IllegalArgumentException.class,()->Proof.email(bad));
    }
    @Test void configurationMakesBothGuardsMandatoryWithoutGrantingRolesOrChangingLoginResetFlows() throws Exception {
        @SuppressWarnings("unchecked") Map<String,Object> config=JsonSerialization.readValue(java.nio.file.Files.readAllBytes(java.nio.file.Path.of("realm-flow.json")),Map.class);
        assertEquals(true,config.get("registrationEmailAsUsername"));assertEquals(true,config.get("loginWithEmailAllowed"));
        assertEquals(false,config.get("duplicateEmailsAllowed"));
        for(String forbidden:java.util.List.of("roles","defaultRole","defaultRoles","users","clients","browserFlow","resetCredentialsFlow"))assertFalse(config.containsKey(forbidden));
        @SuppressWarnings("unchecked") java.util.List<Map<String,Object>> flows=(java.util.List<Map<String,Object>>)config.get("authenticationFlows");
        assertEquals(2,flows.size());assertEquals("calorie-email-proof-v1",config.get("registrationFlow"));
        @SuppressWarnings("unchecked") java.util.List<Map<String,Object>> top=(java.util.List<Map<String,Object>>)flows.get(0).get("authenticationExecutions");
        @SuppressWarnings("unchecked") java.util.List<Map<String,Object>> form=(java.util.List<Map<String,Object>>)flows.get(1).get("authenticationExecutions");
        assertEquals(EmailProofAuthenticator.ID,top.get(0).get("authenticator"));assertEquals("registration-page-form",top.get(1).get("authenticator"));
        assertEquals(ProvenEmailUserCreation.ID,form.get(0).get("authenticator"));assertEquals("registration-password-action",form.get(1).get("authenticator"));
        java.util.stream.Stream.concat(top.stream(),form.stream()).forEach(e->assertEquals("REQUIRED",e.get("requirement")));
    }
}
