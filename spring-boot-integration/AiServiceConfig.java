package com.artistplatform.integration;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.ExchangeStrategies;
import java.time.Duration;
import io.netty.channel.ChannelOption;
import reactor.netty.http.client.HttpClient;
import org.springframework.http.client.reactive.ReactorClientHttpConnector;

/**
 * AiServiceConfig
 * ──────────────────────────────────────────────────────────────────────────────
 * Configures the WebClient used to call the Python AI service.
 *
 * Setup in application.properties / application.yml:
 *   ai.service.base-url=http://localhost:8000
 *   ai.service.timeout.connect-ms=5000
 *   ai.service.timeout.read-ms=60000
 *
 * Or in .env / environment variables:
 *   AI_SERVICE_BASE_URL=http://localhost:8000
 *
 * The long read timeout (60s) is necessary because:
 *   - First request after cold start may take 10–15s for model loading
 *   - Image moderation with CLIP can take 3–8s
 *   - Tagging with CLIP can take 3–8s
 * ──────────────────────────────────────────────────────────────────────────────
 */
@Configuration
public class AiServiceConfig {

    @Value("${ai.service.base-url:http://localhost:8000}")
    private String aiServiceBaseUrl;

    @Value("${ai.service.timeout.connect-ms:5000}")
    private int connectTimeoutMs;

    @Value("${ai.service.timeout.read-ms:60000}")
    private int readTimeoutMs;

    /**
     * WebClient bean configured for the Python AI service.
     * Inject this into AiServiceClient.
     *
     * Handles large JSON responses (increased codec buffer to 10MB).
     */
    @Bean("aiServiceWebClient")
    public WebClient aiServiceWebClient() {
        // Allow larger response buffers (default 256KB is too small for image responses)
        ExchangeStrategies strategies = ExchangeStrategies.builder()
            .codecs(config -> config.defaultCodecs().maxInMemorySize(10 * 1024 * 1024))
            .build();

        HttpClient httpClient = HttpClient.create()
            .option(ChannelOption.CONNECT_TIMEOUT_MILLIS, connectTimeoutMs)
            .responseTimeout(Duration.ofMillis(readTimeoutMs));

        return WebClient.builder()
            .baseUrl(aiServiceBaseUrl)
            .clientConnector(new ReactorClientHttpConnector(httpClient))
            .exchangeStrategies(strategies)
            .defaultHeader("Content-Type", "application/json")
            .build();
    }
}
