package com.spongebob.big_model.service.impl.personnel;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.spongebob.big_model.entity.SysUser;
import com.spongebob.big_model.repository.SysUserRepository;
import com.spongebob.big_model.service.PersonnelService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.*;
import java.util.stream.Collectors;

@Service
public class PersonnelServiceImpl implements PersonnelService {

    private static final Logger log = LoggerFactory.getLogger(PersonnelServiceImpl.class);

    /** 公开字段：无论角色，始终返回 */
    private static final Set<String> PUBLIC_FIELDS = Set.of(
            "employee_id", "username", "nickname", "department", "title"
    );

    /** 敏感字段：仅 admin 可看 */
    private static final Set<String> SENSITIVE_FIELDS = Set.of(
            "phone", "email", "supervisor", "hire_date"
    );

    @Autowired
    private SysUserRepository sysUserRepository;

    @Override
    public List<Map<String, Object>> search(String name, String phone, String email,
                                            String role, List<String> requestedFields) {
        // 1. 参数校验
        if ((name == null || name.isBlank())
                && (phone == null || phone.isBlank())
                && (email == null || email.isBlank())) {
            return Collections.emptyList();
        }

        // 2. 构建查询条件
        QueryWrapper<SysUser> wrapper = new QueryWrapper<>();
        wrapper.eq("status", 1);
        if (name != null && !name.isBlank()) {
            wrapper.and(w -> w
                    .like("nickname", name)
                    .or()
                    .like("username", name)
            );
        }
        if (phone != null && !phone.isBlank()) {
            wrapper.eq("phone", phone);
        }
        if (email != null && !email.isBlank()) {
            wrapper.eq("email", email);
        }

        List<SysUser> users = sysUserRepository.list(wrapper);

        log.info("Personnel query: role={} type={} -> hits={}",
                role, (name != null ? "name" : phone != null ? "phone" : "email"),
                users.size());

        // 3. 角色权限过滤 + 字段白名单
        boolean isAdmin = "admin".equalsIgnoreCase(role);
        Set<String> allowedFields = new LinkedHashSet<>(PUBLIC_FIELDS);
        if (isAdmin) {
            allowedFields.addAll(SENSITIVE_FIELDS);
        }
        // 如果调用方指定了 requested_fields，做交集白名单
        boolean hasWhitelist = requestedFields != null && !requestedFields.isEmpty();
        if (hasWhitelist) {
            allowedFields.retainAll(requestedFields);
            // 始终保留 nickname，避免回答里没有姓名
            allowedFields.add("nickname");
        }

        final Set<String> finalFields = allowedFields;

        return users.stream().map(user -> toMap(user, finalFields)).collect(Collectors.toList());
    }

    // ═══════════════════════════════════════════════════════════
    // DSL /query（第二阶段新增）
    // ═══════════════════════════════════════════════════════════

    private static final Set<String> ALLOWED_OPERATIONS = Set.of(
            "detail", "list", "count", "distinct", "rag", "clarify"
    );
    private static final Set<String> ALLOWED_DISTINCT_FIELDS = Set.of("department", "title");
    private static final int DEFAULT_LIMIT = 20;
    private static final int MAX_LIMIT = 50;

    /** DSL 字段名 → 实体字段名映射（name → nickname） */
    private static final Map<String, String> DSL_TO_ENTITY = Map.of("name", "nickname");

    @Override
    public Map<String, Object> query(Map<String, Object> dsl) {
        // 1. operation 校验
        String operation = strVal(dsl.get("operation"), "clarify");
        if ("rag".equals(operation) || "clarify".equals(operation)) {
            return Map.of("success", true, "data", List.of(), "operation", operation);
        }
        if (!ALLOWED_OPERATIONS.contains(operation)) {
            return Map.of("success", false, "message", "无效 operation: " + operation, "data", List.of());
        }

        // 2. filters 提取（直接传 Map，由各 operation 方法统一处理）
        Map<String, Object> rawFilters = (Map<String, Object>) dsl.getOrDefault("filters", Map.of());
        if (rawFilters == null) rawFilters = Map.of();

        // 3. role + select_fields
        String role = strVal(dsl.get("role"), "user");
        List<String> rawSelectFields = (List<String>) dsl.get("select_fields");
        Set<String> selectFields = resolveSelectFields(rawSelectFields, role);

        // 4. distinct_field 白名单校验
        String distinctField = strVal(dsl.get("distinct_field"), null);
        if (distinctField != null && !ALLOWED_DISTINCT_FIELDS.contains(distinctField)) {
            distinctField = null;
        }

        // 5. limit 截断
        int limit = toInt(dsl.get("limit"), DEFAULT_LIMIT);
        limit = Math.max(1, Math.min(limit, MAX_LIMIT));
        int offset = Math.max(0, toInt(dsl.get("offset"), 0));

        // 6. 按 operation 分发执行（filters 以 Map 传递，由各方法统一处理全部字段）
        switch (operation) {
            case "detail":
                return doDetail(rawFilters, selectFields);
            case "list":
                return doList(rawFilters, selectFields, limit, offset);
            case "count":
                return doCount(rawFilters);
            case "distinct":
                return doDistinct(distinctField, strVal(rawFilters.get("department"), null));
            default:
                return Map.of("success", false, "message", "不支持的操作", "data", List.of());
        }
    }

    // ── operation 执行 ──

    private Map<String, Object> doDetail(Map<String, Object> f, Set<String> selectFields) {
        boolean hasLocator = !isBlankMap(f, "name") || !isBlankMap(f, "phone") || !isBlankMap(f, "email")
                || !isBlankMap(f, "username") || !isBlankMap(f, "employee_id");
        if (!hasLocator) {
            return Map.of("success", true, "data", List.of(), "operation", "detail");
        }
        // 构造SQL命令
        QueryWrapper<SysUser> wrapper = buildBaseWrapper(f);
        // 查询数据库
        List<SysUser> users = sysUserRepository.list(wrapper);

        log.info("[DSL] op=detail -> hits={}", users.size());
        return Map.of("success", true, "data",
                users.stream().map(u -> toMap(u, selectFields)).collect(Collectors.toList()),
                "operation", "detail");
    }

    private Map<String, Object> doList(Map<String, Object> f, Set<String> selectFields, int limit, int offset) {
        QueryWrapper<SysUser> wrapper = buildBaseWrapper(f);
        wrapper.last("LIMIT " + offset + ", " + limit);

        List<SysUser> users = sysUserRepository.list(wrapper);

        log.info("[DSL] op=list dept={} title={} -> hits={}", f.get("department"), f.get("title"), users.size());
        return Map.of("success", true, "data",
                users.stream().map(u -> toMap(u, selectFields)).collect(Collectors.toList()),
                "operation", "list");
    }

    private Map<String, Object> doCount(Map<String, Object> f) {
        QueryWrapper<SysUser> wrapper = buildBaseWrapper(f);

        long cnt = sysUserRepository.count(wrapper);

        log.info("[DSL] op=count dept={} title={} -> {}", f.get("department"), f.get("title"), cnt);
        return Map.of("success", true, "data", List.of(), "operation", "count", "count", cnt);
    }

    private Map<String, Object> doDistinct(String distinctField, String department) {
        if (distinctField == null) {
            return Map.of("success", false, "message", "distinct 缺少 distinct_field", "data", List.of());
        }

        QueryWrapper<SysUser> wrapper = new QueryWrapper<>();
        wrapper.select("DISTINCT " + distinctField);  // distinctField 已过白名单，安全
        wrapper.eq("status", 1);
        if (department != null && !department.isBlank()) {
            wrapper.like("department", department);
        }
        wrapper.orderByAsc(distinctField);

        List<Map<String, Object>> maps = sysUserRepository.listMaps(wrapper);
        log.info("[DSL] op=distinct field={} -> {} values", distinctField, maps.size());
        return Map.of("success", true, "data", maps, "operation", "distinct");
    }

    // ── 工具方法 ──

    /**
     * 构建基础查询条件：status=1 + 全部字段过滤（与 personnel_semantic.yaml 字段一一对应）。
     * name → LIKE nickname/username；username/employee_id/phone/email → EQ；
     * department/title/supervisor/hire_date → LIKE。
     */
    private QueryWrapper<SysUser> buildBaseWrapper(Map<String, Object> f) {
        QueryWrapper<SysUser> wrapper = new QueryWrapper<>();
        wrapper.eq("status", 1);

        String name = strVal(f.get("name"), null);
        if (name != null) {
            wrapper.and(w -> w.like("nickname", name).or().like("username", name));
        }
        if (isNotBlankMap(f, "username")) wrapper.eq("username", f.get("username").toString().strip());
        if (isNotBlankMap(f, "employee_id")) wrapper.eq("employee_id", f.get("employee_id").toString().strip());
        if (isNotBlankMap(f, "phone")) wrapper.eq("phone", f.get("phone").toString().strip());
        if (isNotBlankMap(f, "email")) wrapper.eq("email", f.get("email").toString().strip());
        if (isNotBlankMap(f, "department")) wrapper.like("department", f.get("department").toString().strip());
        if (isNotBlankMap(f, "title")) wrapper.like("title", f.get("title").toString().strip());
        if (isNotBlankMap(f, "supervisor")) wrapper.like("supervisor", f.get("supervisor").toString().strip());
        if (isNotBlankMap(f, "hire_date")) wrapper.like("hire_date", f.get("hire_date").toString().strip());

        return wrapper;
    }

    /** 角色权限 + select_fields 白名单求交 */
    private Set<String> resolveSelectFields(List<String> raw, String role) {
        Set<String> allowed = new LinkedHashSet<>(PUBLIC_FIELDS);
        if ("admin".equalsIgnoreCase(role)) {
            allowed.addAll(SENSITIVE_FIELDS);
        }
        if (raw != null && !raw.isEmpty()) {
            // 将 DSL 字段名归一化为实体字段名
            Set<String> normalized = new LinkedHashSet<>();
            for (String f : raw) {
                String entityField = DSL_TO_ENTITY.getOrDefault(f, f);
                normalized.add(entityField);
            }
            allowed.retainAll(normalized);
            allowed.add("nickname");  // 始终保留姓名
        }
        return allowed;
    }

    /** SysUser → Map（按 selectFields 过滤字段） */
    private Map<String, Object> toMap(SysUser user, Set<String> fields) {
        Map<String, Object> result = new LinkedHashMap<>();
        if (fields.contains("employee_id")) result.put("employee_id", user.getEmployeeId());
        if (fields.contains("username")) result.put("username", user.getUsername());
        if (fields.contains("nickname")) result.put("nickname", user.getNickname());
        if (fields.contains("department")) result.put("department", user.getDepartment());
        if (fields.contains("title")) result.put("title", user.getTitle());
        if (fields.contains("phone")) result.put("phone", user.getPhone());
        if (fields.contains("email")) result.put("email", user.getEmail());
        if (fields.contains("supervisor")) result.put("supervisor", user.getSupervisor());
        if (fields.contains("hire_date")) result.put("hire_date", user.getHireDate());
        return result;
    }

    private static String strVal(Object obj, String defaultVal) {
        if (obj instanceof String s && !s.isBlank()) {
            return s.strip();
        }
        return defaultVal;
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    /** Map 中某字段是否有非空值 */
    private static boolean isNotBlankMap(Map<String, Object> f, String key) {
        Object v = f.get(key);
        return v != null && (!(v instanceof String s) || !s.isBlank());
    }

    /** Map 中某字段是否为 null 或空白 */
    private static boolean isBlankMap(Map<String, Object> f, String key) {
        return !isNotBlankMap(f, key);
    }

    private static int toInt(Object obj, int defaultVal) {
        if (obj instanceof Number n) {
            return n.intValue();
        }
        return defaultVal;
    }
}
