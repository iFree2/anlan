import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Duration;
import java.util.List;
import java.util.Set;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CompletionStage;
import java.util.concurrent.Executors;
import java.util.concurrent.Flow;
import java.io.ByteArrayOutputStream;

/** Two loopback read-only APIs. Python FactTools remains the sole business authority. */
public final class AnlanFactApi {
    private static final Set<String> PATHS = Set.of("/api/worker-qualification", "/api/area-status");
    private static final HttpClient CLIENT = HttpClient.newBuilder()
        .connectTimeout(Duration.ofSeconds(2)).followRedirects(HttpClient.Redirect.NEVER).build();

    private static final class BoundedBody implements HttpResponse.BodySubscriber<byte[]> {
        private final CompletableFuture<byte[]> future = new CompletableFuture<>();
        private final ByteArrayOutputStream body = new ByteArrayOutputStream();
        private Flow.Subscription subscription;
        public CompletionStage<byte[]> getBody() { return future; }
        public void onSubscribe(Flow.Subscription value) { subscription = value; value.request(1); }
        public void onNext(List<ByteBuffer> buffers) {
            for (ByteBuffer buffer : buffers) {
                if (body.size() + buffer.remaining() > 65536) {
                    subscription.cancel();
                    future.completeExceptionally(new IllegalArgumentException("oversize"));
                    return;
                }
                byte[] bytes = new byte[buffer.remaining()];
                buffer.get(bytes);
                body.writeBytes(bytes);
            }
            subscription.request(1);
        }
        public void onError(Throwable error) { future.completeExceptionally(error); }
        public void onComplete() { future.complete(body.toByteArray()); }
    }

    private static void reply(HttpExchange exchange, int status, byte[] body) throws Exception {
        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(status, body.length);
        exchange.getResponseBody().write(body);
    }
    private static byte[] error(String category) {
        return ("{\"error\":\"" + category + "\"}").getBytes(StandardCharsets.UTF_8);
    }
    private static String env(String name) {
        String value = System.getenv(name);
        if (value == null || value.length() < 16) throw new IllegalArgumentException("Missing config");
        return value;
    }
    public static void main(String[] args) throws Exception {
        String apiToken = env("ANLAN_API_TOKEN");
        String backendToken = env("ANLAN_BACKEND_TOKEN");
        URI backend = URI.create(System.getenv("ANLAN_BACKEND_URL"));
        if (!"http".equals(backend.getScheme()) || !"127.0.0.1".equals(backend.getHost())
            || backend.getPort() <= 0 || backend.getUserInfo() != null || backend.getQuery() != null
            || backend.getFragment() != null || !backend.getPath().isEmpty()) {
            throw new IllegalArgumentException("Only a private loopback origin is permitted");
        }
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1",
            Integer.parseInt(args[0])), 8);
        server.setExecutor(Executors.newFixedThreadPool(4));
        server.createContext("/", exchange -> {
            try {
                String path = exchange.getRequestURI().getPath();
                if ("/health".equals(path) && "GET".equals(exchange.getRequestMethod())) {
                    reply(exchange, 200, "{\"status\":\"ok\"}".getBytes(StandardCharsets.UTF_8));
                    return;
                }
                List<String> auth = exchange.getRequestHeaders().get("Authorization");
                if (auth == null || auth.size() != 1 || !MessageDigest.isEqual(
                    auth.get(0).getBytes(StandardCharsets.UTF_8),
                    ("Bearer " + apiToken).getBytes(StandardCharsets.UTF_8))) {
                    reply(exchange, 401, error("unauthorized")); return;
                }
                if (!PATHS.contains(path) || exchange.getRequestURI().getRawQuery() != null) {
                    reply(exchange, 404, error("not_found")); return;
                }
                if (!"POST".equals(exchange.getRequestMethod())) {
                    reply(exchange, 405, error("method_not_allowed")); return;
                }
                byte[] body = exchange.getRequestBody().readNBytes(4097);
                if (body.length > 4096) { reply(exchange, 413, error("body_too_large")); return; }
                HttpRequest.Builder builder = HttpRequest.newBuilder(backend.resolve(path))
                    .timeout(Duration.ofSeconds(2)).header("Authorization", "Bearer " + backendToken)
                    .header("Content-Type", "application/json");
                for (String key : List.of("X-Anlan-Tenant", "X-Anlan-User", "X-Anlan-As-Of")) {
                    List<String> values = exchange.getRequestHeaders().get(key);
                    if (values != null && values.size() == 1) builder.header(key, values.get(0));
                }
                HttpRequest request = builder.POST(HttpRequest.BodyPublishers.ofByteArray(body)).build();
                HttpResponse<byte[]> result = CLIENT.send(request, ignored -> new BoundedBody());
                reply(exchange, result.statusCode(), result.body());
            } catch (java.net.http.HttpTimeoutException e) {
                try { reply(exchange, 504, error("backend_timeout")); } catch (Exception ignored) { }
            } catch (Exception e) {
                try { reply(exchange, 502, error("backend_unavailable")); } catch (Exception ignored) { }
            } finally { exchange.close(); }
        });
        Runtime.getRuntime().addShutdownHook(new Thread(() -> server.stop(0)));
        server.start();
    }
}
