package com.spongebob.big_model.entity;

//import jakarta.persistence.*;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 用户问答记录表实体类
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@TableName("qa_record")
public class QaRecord {

    /** 主键ID */
    @TableId
    private Long id;
    /** 关联用户ID（外键） */
    private Long userId;

    /** 提问内容 */
    private String question;

    /** 回答内容 */
    private String answer;

    /** 创建时间 */
    private LocalDateTime createTime;

    /**
     * 可选：多对一关联到 SysUser
     * 如果需要在查询问答记录时直接获取用户信息，可以添加这个关联
     */
//    @ManyToOne(fetch = FetchType.LAZY)
//    @JoinColumn(name = "user_id", insertable = false, updatable = false)
    private SysUser sysUser;
}
