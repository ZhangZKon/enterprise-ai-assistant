package com.spongebob.big_model.service;

import java.util.concurrent.atomic.AtomicBoolean;
import java.util.function.Consumer;

public interface ChatService {

    String callAiForOneReply(String prompt);

    void streamAiReply(
            String prompt,
            String conversationId,
            String role,
            AtomicBoolean cancelled,
            Consumer<String> onSseData
    );
}
