package com.spongebob.big_model.entity;

import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDate;
import java.time.LocalDateTime;

@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@TableName("sys_user")
public class SysUser {
    @TableId
    private Long id;
    private String employeeId;
    private String username;
    private String password;

    /** 用户昵称（如真实姓名） */
    private String nickname;
    private String department;
    private String title;

    /** 角色：user-普通用户，admin-系统管理员 */
    private String role;

    /** 手机号（可选） */
    private String phone;

    /** 邮箱（可选） */
    private String email;
    private String officePhone;
    private String address;
    private LocalDate hireDate;
    private String supervisor;

    /** 状态：1-启用，0-禁用（禁用后无法登录） */
    private Integer status;

    /** 密码盐值（用于加密） */
    private String salt;

    /** 创建时间 */
    private LocalDateTime createTime;

    /** 更新时间 */
    private LocalDateTime updateTime;
}
