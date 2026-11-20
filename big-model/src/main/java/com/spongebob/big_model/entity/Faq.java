package com.spongebob.big_model.entity;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 高频问题库实体类
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@TableName("faq")
public class Faq {

    /** 主键ID */
    @TableId
    private Long id;

    /** 问题 */
    private String question;

    /** 标准答案 */
    private String answer;

    /** 排序（高频优先，数字越小越靠前） */
    private Integer sort;

    /** 创建时间 */
    private LocalDateTime createTime;
}
