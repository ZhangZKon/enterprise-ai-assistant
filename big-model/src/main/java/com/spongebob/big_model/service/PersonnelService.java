package com.spongebob.big_model.service;

import java.util.List;
import java.util.Map;

public interface PersonnelService {

    /**
     * 按姓名/手机号/邮箱查询人员，并按角色权限过滤返回字段（旧接口，兼容 validate_name_and_fallback）。
     */
    List<Map<String, Object>> search(String name, String phone, String email,
                                     String role, List<String> requestedFields);

    /**
     * 执行 PersonnelQueryDSL，支持 detail/list/count/distinct 四种 operation。
     * Java 层做 Validator 校验，MyBatis-Plus 安全构造 SQL。
     *
     * @param dsl  Python 生成的 PersonelQueryDSL
     *              {operation, filters:{name,phone,email,department,title},
     *               distinct_field, select_fields, limit, offset, role}
     * @return {success, data, operation, ...}
     */
    Map<String, Object> query(Map<String, Object> dsl);
}
