package com.spongebob.big_model.service.impl.chat;

import com.spongebob.big_model.config.AiServiceConfig;
import com.spongebob.big_model.service.ChatService;
import com.spongebob.big_model.service.impl.chat.model.GenerateResponse;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.client.RestTemplate;
import java.util.HashMap;
import java.util.Map;

import com.alibaba.fastjson.JSON;
import org.apache.hc.client5.http.classic.methods.HttpPost;
import org.apache.hc.client5.http.impl.classic.CloseableHttpClient;
import org.apache.hc.core5.http.ContentType;
import org.apache.hc.core5.http.io.entity.StringEntity;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

@Service
public class ChatServiceImpl implements ChatService {

    @Autowired
    private RestTemplate restTemplate;

    @Autowired
    private CloseableHttpClient streamingHttpClient;


    @Autowired
    private AiServiceConfig aiServiceConfig;

    @Override
    public String callAiForOneReply(String prompt) {
        // 获取基础URL http://localhost:8000
        String baseUrl = aiServiceConfig.getBaseUrl();
        // 构建完整的请求URL http://localhost:8000/chat/
        String url = baseUrl + "/chat/";
        // 构造JSON体
        Map<String, String> request = new HashMap<>();
        // {"query": "用户输入的问题"}
        request.put("query", prompt);
        try {
            // 发送POST请求并获取响应
            GenerateResponse response = restTemplate.postForObject(url, request, GenerateResponse.class);
            // 从响应中取出 answer 字段值返回
            return response != null ? response.getAnswer() : "";
        } catch (Exception e) {
            System.err.println("===== 调用 Python 失败 =====");
            System.err.println("URL: " + url);
            System.err.println("异常类型: " + e.getClass().getName());
            System.err.println("异常信息: " + e.getMessage());
            e.printStackTrace();
            throw e;
        }
    }

    @Override
    public void streamAiReply(
            String prompt,
            String conversationId,
            String role,
            AtomicBoolean cancelled,
            Consumer<String> onSseData
    ) {
        String url = aiServiceConfig.getBaseUrl() + "/chat/stream";

        Map<String, Object> requestBody = new HashMap<>();
        requestBody.put("query", prompt);
        if (conversationId != null && !conversationId.isBlank()) {
            requestBody.put("conversation_id", conversationId);
        }
        if (role != null && !role.isBlank()) {
            requestBody.put("role", role);
        }

        HttpPost request = new HttpPost(url);
        request.setHeader("Accept", "text/event-stream");
        request.setEntity(new StringEntity(
                JSON.toJSONString(requestBody),
                ContentType.APPLICATION_JSON
        ));

        try (var response = streamingHttpClient.execute(request)) {
            int status = response.getCode();
            if (status < 200 || status >= 300) {
                throw new IllegalStateException("Python 流式接口响应异常，HTTP 状态码：" + status);
            }

            try (BufferedReader reader = new BufferedReader(
                    new InputStreamReader(response.getEntity().getContent(), StandardCharsets.UTF_8)
            )) {
                String line;
                while (!cancelled.get() && (line = reader.readLine()) != null) {
                    // Python 端采用 data: <json>\n\n 格式；空行是事件边界。
                    if (!line.startsWith("data:")) {
                        continue;
                    }

                    String payload = line.substring("data:".length()).stripLeading();
                    if (!payload.isEmpty()) {
                        onSseData.accept(payload);
                    }
                }
            }
        } catch (Exception e) {
            if (!cancelled.get()) {
                throw new RuntimeException("调用 Python 流式接口失败", e);
            }
        }
    }
}
