// Read-only preflight in the Android VM, separate from APK/browser acceptance.
import java.io.FileInputStream;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import java.security.cert.CertificateFactory;
import javax.net.ssl.HttpsURLConnection;
import javax.net.ssl.SSLContext;
import javax.net.ssl.TrustManagerFactory;
import org.json.JSONObject;

public final class AndroidHttpsProbe {
    private static JSONObject get(String origin, String path, SSLContext trust) throws Exception {
        HttpsURLConnection connection = (HttpsURLConnection) new URL(origin + path).openConnection();
        connection.setSSLSocketFactory(trust.getSocketFactory());
        // Keep the platform hostname verifier. Never trust all or bypass TLS errors.
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(10000);
        connection.setInstanceFollowRedirects(false);
        connection.setRequestProperty("Accept", "application/json");
        try {
            if (connection.getResponseCode() != 200) throw new IllegalStateException("HTTP preflight failed");
            try (var body = connection.getInputStream()) {
                byte[] bytes = body.readNBytes(131073);
                if (bytes.length > 131072) throw new IllegalStateException("Oversized response");
                return new JSONObject(new String(bytes, StandardCharsets.UTF_8));
            }
        } finally {
            connection.disconnect();
        }
    }

    public static void main(String[] args) {
        try {
            run(args);
        } catch (Exception error) {
            System.out.println("{\"android_https\":\"FAIL\",\"error_type\":\""
                    + error.getClass().getSimpleName() + "\"}");
            System.exit(2);
        }
    }

    private static void run(String[] args) throws Exception {
        if (args.length != 2 || !args[1].matches("https://[0-9.]+:[0-9]+")) {
            throw new IllegalArgumentException("Expected public CA path and existing IPv4 HTTPS origin");
        }
        KeyStore store = KeyStore.getInstance(KeyStore.getDefaultType());
        store.load(null, null);
        try (var input = new FileInputStream(args[0])) {
            store.setCertificateEntry("existing-integration-ca",
                    CertificateFactory.getInstance("X.509").generateCertificate(input));
        }
        TrustManagerFactory managers = TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());
        managers.init(store);
        SSLContext trust = SSLContext.getInstance("TLS");
        trust.init(null, managers.getTrustManagers(), null);
        String issuer = args[1] + "/realms/calorie-dev";
        JSONObject discovery = get(args[1], "/realms/calorie-dev/.well-known/openid-configuration", trust);
        if (!issuer.equals(discovery.getString("issuer"))) throw new IllegalStateException("Issuer changed");
        if (!"ok".equals(get(args[1], "/health/ready", trust).getString("status"))) {
            throw new IllegalStateException("API is not ready");
        }
        System.out.println(new JSONObject().put("android_https", "PASS").put("discovery", 200)
                .put("readiness", 200).put("issuer", issuer)
                .put("browser_apk_login", "NOT_TESTED").toString());
    }
}
