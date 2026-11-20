package com.spongebob.big_model.controller.chat;

import com.alibaba.fastjson.JSON;
import com.spongebob.big_model.common.enums.ResultCode;
import com.spongebob.big_model.common.vo.PromptData;
import com.spongebob.big_model.common.vo.Result;
import com.spongebob.big_model.service.ChatService;
import io.micrometer.common.util.StringUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.*;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.CacheControl;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.io.UncheckedIOException;
import java.util.Map;
import java.util.concurrent.Executor;
import java.util.concurrent.atomic.AtomicBoolean;

@RestController
@RequestMapping(value = "/chat")
public class ChatController {

    private static final Logger log = LoggerFactory.getLogger(ChatController.class);
    @Autowired
    private ChatService chatService;

    @Autowired
    @Qualifier("chatStreamTaskExecutor")
    private Executor chatStreamTaskExecutor;

    @RequestMapping("/generate")
    @ResponseBody
    public Result generate(@RequestParam String prompt) {
        Result result = Result.success();
        if(StringUtils.isBlank(prompt)) {
            return Result.error(ResultCode.PARAM_INVALID,"prompt不能为空");
        }
        try {
            String res = chatService.callAiForOneReply(prompt);
            result.setData(res);
        } catch (Exception e) {
            result = Result.error();
        }
        return result;

    }


    @RequestMapping("/getInfo")
    @ResponseBody
    public Result getInfo(@RequestBody PromptData promptData) {
        Result result = Result.success();
        if (promptData == null) {
            return Result.error(ResultCode.PARAM_INVALID, "参数不能为空");
        }
        if(StringUtils.isBlank(promptData.getPrompt())){
            return Result.error(ResultCode.PARAM_INVALID,"参数不能为空");
        }

        log.info("新接口222被调用");
        try{
            String res = chatService.callAiForOneReply(promptData.getPrompt());
            result.setData(res);
        }catch (Exception e){
            result = Result.error();
        }
        log.info("新接口222返回数据:[{}]",JSON.toJSON(result));
        return result;

    }

    @PostMapping(value = "/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<SseEmitter> stream(@RequestBody PromptData promptData) {
        SseEmitter emitter = new SseEmitter(120_000L);
        AtomicBoolean cancelled = new AtomicBoolean(false);

        emitter.onCompletion(() -> cancelled.set(true));
        emitter.onTimeout(() -> {
            cancelled.set(true);
            emitter.complete();
        });
        emitter.onError(error -> cancelled.set(true));

        if (promptData == null || StringUtils.isBlank(promptData.getPrompt())) {
            sendErrorAndComplete(emitter, "参数不能为空");
            return sseResponse(emitter);
        }

        try {
            chatStreamTaskExecutor.execute(() -> {
                try {
                    chatService.streamAiReply(
                            promptData.getPrompt(),
                            promptData.getConversationId(),
                            promptData.getRole(),
                            cancelled,
                            payload -> {
                                try {
                                    // payload 已是 Python 的 JSON，不再二次 JSON 序列化。
                                    emitter.send(SseEmitter.event().data(payload));
                                } catch (IOException exception) {
                                    throw new UncheckedIOException(exception);
                                }
                            }
                    );

                    if (!cancelled.get()) {
                        emitter.complete();
                    }
                } catch (Exception exception) {
                    if (!cancelled.get()) {
                        log.error("流式问答失败", exception);
                        sendErrorAndComplete(emitter, "生成回答失败");
                    }
                }
            });
        } catch (Exception exception) {
            log.error("流式任务提交失败", exception);
            sendErrorAndComplete(emitter, "服务器繁忙，请稍后重试");
        }

        return sseResponse(emitter);
    }

    private ResponseEntity<SseEmitter> sseResponse(SseEmitter emitter) {
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .cacheControl(CacheControl.noCache())
                .header("X-Accel-Buffering", "no")
                .body(emitter);
    }

    private void sendErrorAndComplete(SseEmitter emitter, String message) {
        try {
            String errorPayload = JSON.toJSONString(
                    Map.of("type", "error", "data", Map.of("message", message))
            );
            emitter.send(SseEmitter.event().data(errorPayload));
        } catch (IOException ignored) {
            // 客户端已断开时无法继续写入。
        } finally {
            emitter.complete();
        }
    }

}
