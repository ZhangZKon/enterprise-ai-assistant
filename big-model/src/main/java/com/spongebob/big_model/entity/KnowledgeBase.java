package com.spongebob.big_model.entity;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Data;
import lombok.NoArgsConstructor;

import java.time.LocalDateTime;

/**
 * 企业知识库实体类
 */
@Data
@NoArgsConstructor
@AllArgsConstructor
@Builder
@TableName("knowledge_base")
public class KnowledgeBase {

    /** 主键ID */
    @TableId
    private Long id;

    /** 标题 */
    private String title;

    /** 内容（可能较长，用 TEXT 存储） */
    private String content;

    /** 分类（如流程 / 基础信息） */
    private String category;

    /** 创建时间 */
    private LocalDateTime createTime;
}
