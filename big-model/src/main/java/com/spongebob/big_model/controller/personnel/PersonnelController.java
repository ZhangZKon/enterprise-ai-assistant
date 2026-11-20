package com.spongebob.big_model.controller.personnel;

import com.spongebob.big_model.service.PersonnelService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.ResponseBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("/personnel")
public class PersonnelController {

    private static final Logger log = LoggerFactory.getLogger(PersonnelController.class);

    @Autowired
    private PersonnelService personnelService;

    @SuppressWarnings("unchecked")
    @PostMapping("/search")
    @ResponseBody
    public Map<String, Object> search(@RequestBody Map<String, Object> request) {
        String name = (String) request.get("name");
        String phone = (String) request.get("phone");
        String email = (String) request.get("email");
        String role = (String) request.getOrDefault("role", "user");
        List<String> requestedFields = (List<String>) request.get("requested_fields");

        // 角色校验
        if (!"admin".equals(role) && !"user".equals(role)) {
            return Map.of(
                    "success", false,
                    "message", "无效的角色参数，仅接受 admin 或 user",
                    "data", List.of()
            );
        }

        try {
            List<Map<String, Object>> results =
                    personnelService.search(name, phone, email, role, requestedFields);
            return Map.of(
                    "success", true,
                    "data", results,
                    "masked_fields", "admin".equals(role) ? List.of() : List.of("phone", "email")
            );
        } catch (Exception e) {
            log.error("人员查询失败", e);
            return Map.of(
                    "success", false,
                    "message", "查询失败：" + e.getMessage(),
                    "data", List.of()
            );
        }
    }

    /** DSL 查询端点：接收完整的 PersonnelQueryDSL，支持 detail/list/count/distinct */
    @SuppressWarnings("unchecked")
    @PostMapping("/query")
    @ResponseBody
    public Map<String, Object> query(@RequestBody Map<String, Object> request) {
        String role = request.get("role") instanceof String s ? s : "user";
        if (!"admin".equals(role) && !"user".equals(role)) {
            return Map.of(
                    "success", false,
                    "message", "无效的角色参数，仅接受 admin 或 user",
                    "data", List.of()
            );
        }

        try {
            return personnelService.query(request);
        } catch (Exception e) {
            log.error("人员 DSL 查询失败", e);
            return Map.of(
                    "success", false,
                    "message", "查询失败：" + e.getMessage(),
                    "data", List.of()
            );
        }
    }
}
