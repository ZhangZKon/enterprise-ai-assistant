package com.spongebob.big_model.common.vo;

import com.fasterxml.jackson.annotation.JsonProperty;

import java.io.Serializable;

public class PromptData implements Serializable {
    private static final long serialVersionUID = 1L;

    private String prompt;

    @JsonProperty("conversation_id")
    private String conversationId;

    @JsonProperty("role")
    private String role;

    public PromptData() {
    }

    public PromptData(String prompt) {
        this.prompt = prompt;
    }

    public String getPrompt() {
        return this.prompt;
    }

    public String getConversationId() {
        return conversationId;
    }

    public void setConversationId(String conversationId) {
        this.conversationId = conversationId;
    }

    public void setPrompt(String prompt) {
        this.prompt = prompt;
    }

    public String getRole() {
        return role;
    }

    public void setRole(String role) {
        this.role = role;
    }

}
